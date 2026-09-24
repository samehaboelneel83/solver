"""No core dump from a solver process (the one place this is decided).

Under Docker Desktop the kernel pipes each dump to the Windows host's disk
(%TEMP%/wsl-crashes), about a gigabyte a solver; ten filled 13.8 GB of C: on
2026-09-23. A piped dump ignores `RLIMIT_CORE` 0; a process that is not
dumpable (`PR_SET_DUMPABLE` 0) is never dumped at all. The flag does not
survive `exec`, so every solver process sets it for itself: the sandbox's
child (`app.solve.sandbox`) and the HiGHS worker it starts
(`app.solve.highs_worker`), which is a new program.
"""

from __future__ import annotations


def forbid() -> None:
    try:
        import ctypes

        ctypes.CDLL(None, use_errno=True).prctl(4, 0, 0, 0, 0)  # PR_SET_DUMPABLE, 0
    except (OSError, AttributeError):  # not Linux: nothing to forbid
        pass
