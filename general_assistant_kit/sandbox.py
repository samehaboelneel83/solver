"""run_python: a general tool. The model writes Python, the server runs it in a locked-down
subprocess, and the model reads the output. Nothing here knows about any particular problem.

The model uses it to: read attached files (CSV, Excel, DXF, GeoJSON ...), compute sizes and
bounds, generate the records / relationships / parameters the platform needs, and check a
solution independently after the platform solves.

Limits: wall-clock timeout, CPU seconds, memory, output size; one working folder per conversation;
no network variables; optional `unshare -n` (no network namespace) when available.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap

LIBS_HINT = "numpy, scipy, pandas, openpyxl, shapely, ezdxf, networkx, ortools (whatever is installed)"
MAX_OUT = 12000


def _limits(cpu_s, mem_mb):
    def apply():
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_s, cpu_s))
        resource.setrlimit(resource.RLIMIT_AS, (mem_mb * 2**20, mem_mb * 2**20))
        resource.setrlimit(resource.RLIMIT_FSIZE, (512 * 2**20, 512 * 2**20))
        os.setsid()
    return apply


def run_python(code, workdir, files=None, timeout_s=120, cpu_s=300, mem_mb=4096):
    """code: Python source. workdir: per-conversation folder (kept between calls).
    files: {name: local_path} copied in before running (e.g. the user's attachments)."""
    os.makedirs(workdir, exist_ok=True)
    for name, src in (files or {}).items():
        dst = os.path.join(workdir, os.path.basename(name))
        if not os.path.exists(dst):
            shutil.copy(src, dst)
    before = {f: os.path.getmtime(os.path.join(workdir, f)) for f in os.listdir(workdir)}
    script = os.path.join(workdir, "_run.py")
    with open(script, "w") as f:
        f.write(textwrap.dedent(code))
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": workdir, "MPLBACKEND": "Agg",
           "PYTHONDONTWRITEBYTECODE": "1", "OMP_NUM_THREADS": "2"}
    cmd = [sys.executable, "-I", script]
    if shutil.which("unshare") and os.environ.get("SANDBOX_UNSHARE", "1") == "1":
        probe = subprocess.run(["unshare", "-rn", "true"], capture_output=True)
        if probe.returncode == 0:
            cmd = ["unshare", "-rn"] + cmd
    try:
        p = subprocess.run(cmd, cwd=workdir, env=env, capture_output=True, text=True, timeout=timeout_s,
                           preexec_fn=_limits(cpu_s, mem_mb) if os.name == "posix" else None)
        rc, out, err = p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired as e:
        rc, out, err = -9, (e.stdout or b"").decode() if isinstance(e.stdout, bytes) else (e.stdout or ""), \
            f"stopped after {timeout_s} s; make the code faster or split the work"
    changed = sorted(f for f in os.listdir(workdir) if not f.startswith("_run")
                     and (f not in before or os.path.getmtime(os.path.join(workdir, f)) != before[f]))

    def tail(s):
        return s if len(s) <= MAX_OUT else f"...[{len(s) - MAX_OUT} chars cut]...\n" + s[-MAX_OUT:]
    return {"exit_code": rc, "stdout": tail(out or ""), "stderr": tail(err or ""), "files_written": changed,
            "workdir": workdir}


SCHEMA = {
    "type": "function",
    "function": {
        "name": "run_python",
        "description": ("Run Python in a private working folder that keeps files between calls. The user's attached "
                        "files are already in the folder. Use it to read data, compute sizes and bounds, generate "
                        "CSV files of records, relationships and parameters for the platform, and to check a solution "
                        "independently. Print what you need to see; keep output short. Available: " + LIBS_HINT + "."),
        "parameters": {"type": "object", "properties": {
            "code": {"type": "string", "description": "Python source to run."},
            "timeout_s": {"type": "integer", "default": 120, "maximum": 900}},
            "required": ["code"]},
    },
}


def new_workdir(conversation_id):
    root = os.environ.get("SANDBOX_ROOT", os.path.join(tempfile.gettempdir(), "assistant_sandbox"))
    return os.path.join(root, str(conversation_id))
