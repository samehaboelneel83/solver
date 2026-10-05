"""run_python: the assistant's workbench (general_assistant_kit/sandbox.py, hardened for this server).

The model writes Python, a child process runs it in a working folder kept per conversation, and the
model reads what it printed. It reads the attached files (written into the folder as CSV), measures
data, generates records / relationships / data values as files, and checks an answer independently.
Files it writes come back to the conversation as attachments, so a plan loads them with
`entities_from_file`, `relationships_from_file` and `parameter_values_from_file`.

OFF unless AGENT_RUN_PYTHON=1, and then only for people who may publish models. It runs code a
language model wrote, so:

- the child runs as `nobody` when the server is root (the backend image is): it cannot read the
  backend's environment (/proc/1/environ: DATABASE_URL, JWT_SECRET) or write outside its folder;
- with no environment variables, CPU / memory / file-size limits, a wall-clock timeout, its own session;
- no network: its own network namespace where the kernel allows it (CAP_SYS_ADMIN), and in any case Python's socket module is
  disabled inside the child. The second is a guard, not a wall -- code that goes around Python could
  still reach the network (ClickHouse, the LAN). Where that matters, run the backend with a network
  policy, or keep this off.

AGENT_RUN_PYTHON=unsafe also runs it when the server is not root and cannot drop privileges.
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any

MAX_OUT = 12000
NOBODY = 65534
OUTPUT_SUFFIXES = (".csv", ".tsv", ".xlsx", ".json", ".geojson", ".txt")
MAX_OUTPUT_FILE = 10 * 1024 * 1024
LIBS_HINT = "numpy, scipy, pandas, openpyxl, shapely, pyproj, ezdxf, networkx, ortools (whatever is installed)"

# Runs first in the child: no sockets from Python.
_GUARD = '''
import socket as _s, _socket as _ss
def _no_network(*a, **k):
    raise PermissionError("run_python has no network access")
class _NoSocket(_s.socket):
    """Still a class (ssl and others subclass it), but none can be made."""
    def __init__(self, *a, **k):
        _no_network()
_s.socket = _s.SocketType = _NoSocket
_ss.socket = _ss.SocketType = type("socket", (_ss.socket,), {"__init__": lambda self, *a, **k: _no_network()})
for _m in (_s, _ss):
    for _n in ("create_connection", "create_server", "socketpair", "fromfd", "getaddrinfo", "gethostbyname"):
        if hasattr(_m, _n):
            setattr(_m, _n, _no_network)
del _m, _n, _s, _ss
'''


def mode() -> str:
    value = os.environ.get("AGENT_RUN_PYTHON", "0").strip().lower()
    return "unsafe" if value == "unsafe" else "on" if value in ("1", "on", "true", "yes") else "off"


def available() -> tuple[bool, str]:
    m = mode()
    if m == "off":
        return False, "run_python is turned off on this server (AGENT_RUN_PYTHON=0)"
    if m == "on" and os.name == "posix" and os.geteuid() != 0:
        return False, ("run_python needs the server to run as root so the code can run as `nobody`; "
                       "set AGENT_RUN_PYTHON=unsafe to run it as the server's own user")
    return True, ""


def root() -> str:
    return os.environ.get("AGENT_SANDBOX_ROOT", os.path.join(tempfile.gettempdir(), "assistant_sandbox"))


def workdir(user_id: str, conversation_id: str | None) -> str:
    safe = re.sub(r"[^A-Za-z0-9_-]", "", conversation_id or "")[:64] or "default"
    return os.path.join(root(), re.sub(r"[^A-Za-z0-9_-]", "", str(user_id))[:64], safe)


def cleanup(days: float = 1.0) -> None:
    """Working folders not touched for a day go."""
    base = root()
    if not os.path.isdir(base):
        return
    limit = time.time() - days * 86400
    for user in os.listdir(base):
        for conv in os.listdir(os.path.join(base, user)) if os.path.isdir(os.path.join(base, user)) else []:
            path = os.path.join(base, user, conv)
            try:
                if os.path.getmtime(path) < limit:
                    shutil.rmtree(path, ignore_errors=True)
            except OSError:
                pass


def _csv_name(file_name: str, sheet: str, single: bool) -> str:
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", file_name.rsplit(".", 1)[0])
    return f"{stem}.csv" if single else f"{stem}__{re.sub(r'[^A-Za-z0-9_.-]+', '_', sheet)}.csv"


def _ancestors(path: str) -> list[str]:
    out, path = [], os.path.abspath(path)
    while True:
        parent = os.path.dirname(path)
        if parent == path:
            return out
        out.append(parent)
        path = parent


def csv_name(file: str, sheet: str, only: bool) -> str:
    return _csv_name(file, sheet, only)


def write_attachments(folder: str, files: list[dict[str, Any]]) -> list[str]:
    """Each attached sheet as a CSV in the folder (a shape as GeoJSON text)."""
    os.makedirs(folder, exist_ok=True)
    names = []
    for f in files:
        sheets = f.get("sheets") or []
        for s in sheets:
            name = _csv_name(str(f.get("name", "file")), str(s.get("name", "sheet")), len(sheets) == 1)
            if s.get("truncated") and os.path.exists(os.path.join(folder, name)):
                # A file run_python wrote comes back as an attachment cut to 5,000 rows; writing that copy back
                # over the whole file lost the rest (the camp-bed retest: "Valid cells: 5000").
                names.append(name)
                continue
            with open(os.path.join(folder, name), "w", newline="", encoding="utf-8") as out:
                w = csv.writer(out)
                w.writerow(s.get("columns") or [])
                for row in s.get("rows") or []:
                    w.writerow([json.dumps(v) if isinstance(v, (dict, list)) else v for v in row])
            names.append(name)
    return names


_NET_ISOLATION: bool | None = None


def _can_isolate_network() -> bool:
    """Whether a child can be given a network namespace of its own (needs CAP_SYS_ADMIN; Docker's default
    profile usually refuses it). Asked once per process."""
    global _NET_ISOLATION
    if _NET_ISOLATION is None:
        if not hasattr(os, "unshare") or os.name != "posix":
            _NET_ISOLATION = False
        else:
            try:
                probe = subprocess.run([sys.executable, "-c", "pass"], capture_output=True, env={},
                                       preexec_fn=lambda: os.unshare(os.CLONE_NEWNET))
                _NET_ISOLATION = probe.returncode == 0
            except (subprocess.SubprocessError, OSError):
                # Refused in the child (Docker's default profile: no CAP_SYS_ADMIN) surfaces as an exception
                # here, not a return code -- it made every run_python fail on the live platform (camp-bed
                # retest). No namespace then: the Python socket guard applies.
                _NET_ISOLATION = False
    return _NET_ISOLATION


def _drop(cpu_s: int, mem_mb: int, as_nobody: bool, isolate: bool):
    def apply() -> None:
        import resource

        if isolate:
            os.unshare(os.CLONE_NEWNET)  # before giving up root: no network at all, not even loopback

        resource.setrlimit(resource.RLIMIT_CPU, (cpu_s, cpu_s))
        resource.setrlimit(resource.RLIMIT_AS, (mem_mb * 2**20, mem_mb * 2**20))
        resource.setrlimit(resource.RLIMIT_FSIZE, (256 * 2**20, 256 * 2**20))
        resource.setrlimit(resource.RLIMIT_NPROC, (64, 64))
        os.setsid()
        if as_nobody:
            os.setgroups([])
            os.setgid(NOBODY)
            os.setuid(NOBODY)
    return apply


def run(code: str, folder: str, timeout_s: int = 120, cpu_s: int = 300, mem_mb: int = 3072) -> dict[str, Any]:
    ok, why = available()
    if not ok:
        return {"error": why}
    os.makedirs(folder, exist_ok=True)
    as_nobody = os.name == "posix" and os.geteuid() == 0
    if as_nobody:
        blocked = next((p for p in _ancestors(root()) if not os.stat(p).st_mode & 0o001), None)
        if blocked:
            return {"error": f"run_python cannot work under {root()}: {blocked} is closed to other users. "
                             "Set AGENT_SANDBOX_ROOT to a folder under /tmp."}
    before = {f: os.path.getmtime(os.path.join(folder, f)) for f in os.listdir(folder)}
    script = os.path.join(folder, "_run.py")
    with open(script, "w", encoding="utf-8") as fh:
        fh.write(_GUARD + "\n" + code)
    if as_nobody:
        for dirpath, dirnames, filenames in os.walk(folder):
            os.chown(dirpath, NOBODY, NOBODY)
            for n in filenames:
                os.chown(os.path.join(dirpath, n), NOBODY, NOBODY)
        # The folders above it: passable, not readable, so another conversation's folder stays unseen.
        for parent in (os.path.dirname(folder), os.path.dirname(os.path.dirname(folder))):
            os.chmod(parent, 0o711)
    env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": folder, "MPLBACKEND": "Agg", "LANG": "C.UTF-8",
           "PYTHONDONTWRITEBYTECODE": "1", "OMP_NUM_THREADS": "2", "OPENBLAS_NUM_THREADS": "2"}
    cmd = [sys.executable, "-I", "_run.py"]
    isolate = _can_isolate_network()
    timeout_s = max(5, min(int(timeout_s or 120), 900))
    try:
        p = subprocess.run(cmd, cwd=folder, env=env, capture_output=True, text=True, timeout=timeout_s,
                           preexec_fn=_drop(cpu_s, mem_mb, as_nobody, isolate) if os.name == "posix" else None)
        rc, out, err = p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired as e:
        out = e.stdout.decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        rc, err = -9, f"stopped after {timeout_s} s; make the code faster or split the work"
    changed = sorted(f for f in os.listdir(folder)
                     if not f.startswith("_run") and os.path.isfile(os.path.join(folder, f))
                     and (f not in before or os.path.getmtime(os.path.join(folder, f)) != before[f]))

    def tail(s: str) -> str:
        return s if len(s) <= MAX_OUT else f"...[{len(s) - MAX_OUT} chars cut]...\n" + s[-MAX_OUT:]
    return {"exit_code": rc, "stdout": tail(out or ""), "stderr": tail(err or ""), "files_written": changed,
            "isolation": {"user": "nobody" if as_nobody else "server's own user",
                          "network": "none (own namespace)" if isolate else "blocked in Python only"}}


def read_outputs(folder: str, names: list[str]) -> list[tuple[str, bytes]]:
    """The files a run wrote that can become attachments."""
    out = []
    for name in names:
        path = os.path.join(folder, name)
        if name.lower().endswith(OUTPUT_SUFFIXES) and os.path.getsize(path) <= MAX_OUTPUT_FILE:
            with open(path, "rb") as fh:
                out.append((name, fh.read()))
    return out


SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "run_python",
        "description": ("Run Python in this conversation's private working folder (kept between calls; no network). "
                        "Every attached sheet is there as a CSV, named as ATTACHED FILES shows (\"run_python file\"), "
                        "in the folder itself (no sub-folders); a map layer's \"shape_m\" column is its shape in "
                        "metres as WKT (shapely.wkt.loads), \"geometry\" the same in lon/lat. Use it to read "
                        "and check data, compute sizes and bounds, generate CSV files of records, relationships and "
                        "data values, and check an answer independently. CSV/XLSX/JSON files you write come back as "
                        "attachments, to load with *_from_file in a plan. Print only what you need. Available: "
                        + LIBS_HINT + "."),
        "parameters": {"type": "object", "properties": {
            "code": {"type": "string", "description": "Python source to run."},
            "timeout_s": {"type": "integer", "maximum": 900}},
            "required": ["code"]},
    },
}
