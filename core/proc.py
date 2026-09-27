"""subprocess.run with a timeout that actually returns on Windows.

subprocess.run(..., timeout=N) kills only the direct child when time runs out,
then waits for its output pipes to close. If that child started processes of
its own — any `a | b` under shell=True, or a script that spawns a helper —
they still hold the pipes, and run() blocks forever. In Freya that wedged the
live tool executor, so every later tool call queued behind it.
"""

import subprocess


def run(cmd, timeout: float, **kwargs) -> subprocess.CompletedProcess:
    """Like subprocess.run(cmd, capture_output=True, text=True, timeout=...),
    but on timeout the whole process tree is killed before re-raising
    TimeoutExpired. Extra kwargs go to Popen (cwd, shell, ...)."""
    kwargs.setdefault("encoding", "utf-8")
    kwargs.setdefault("errors", "replace")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, **kwargs)
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        raise
    return subprocess.CompletedProcess(cmd, proc.returncode, out or "", err or "")
