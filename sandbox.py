"""Isolated code execution: firejail + an unprivileged system user.

No network, no access to the real filesystem outside a scratch dir, a hard
CPU/memory/time limit, and truncated output. This is the *only* form of
"system access" Jarvis has — it cannot reach the host, other services on
this VPS, or any external system.
"""
import os
import shutil
import subprocess
import tempfile
import uuid

SANDBOX_ROOT = os.environ.get("JARVIS_SANDBOX_ROOT", "/opt/kira-chat-backend/sandbox")
SANDBOX_USER = os.environ.get("JARVIS_SANDBOX_USER", "kirasandbox")
TIMEOUT_SECONDS = 10
MAX_OUTPUT_CHARS = 4000

_FIREJAIL_FLAGS = [
    "firejail", "--quiet", "--noprofile",
    "--net=none", "--private-tmp", "--nosound", "--no3d",
    "--caps.drop=all", "--rlimit-cpu=5", "--rlimit-as=268435456",
    f"--timeout=00:00:{TIMEOUT_SECONDS:02d}",
]


def run_python(code):
    return _run(["python3", "-c", code], code)


def run_shell(command):
    return _run(["/bin/sh", "-c", command], command)


def _run(argv, raw_input_for_log):
    work_dir = os.path.join(SANDBOX_ROOT, uuid.uuid4().hex)
    try:
        os.makedirs(work_dir, mode=0o700, exist_ok=True)
        shutil.chown(work_dir, user=SANDBOX_USER, group=SANDBOX_USER)
    except (OSError, LookupError) as exc:
        return f"[sandbox setup failed: {exc}]"

    cmd = ["runuser", "-u", SANDBOX_USER, "--"] + _FIREJAIL_FLAGS + ["--"] + argv
    try:
        proc = subprocess.run(
            cmd,
            cwd=work_dir,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS + 3,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        if not out.strip():
            out = f"(no output, exit code {proc.returncode})"
    except subprocess.TimeoutExpired:
        out = "[execution timed out]"
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    if len(out) > MAX_OUTPUT_CHARS:
        out = out[:MAX_OUTPUT_CHARS] + "\n...[truncated]"
    return out
