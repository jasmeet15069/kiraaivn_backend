"""The only place in this app that changes system state rather than just
reading it — full lifecycle control of systemd services: start, stop,
restart, delete, and create. Deliberately kept separate from
vps_status.py (which stays strictly read-only).

Every caller must go through /api/service-control or /api/service-create
in app.py, both gated by auth.py's token check plus the frontend's
"admin mode" re-confirmation — this module itself does no auth, it trusts
its caller.

ssh.service is a hard floor, not a scope decision: stopping or deleting it
from a web UI could permanently lock out the only way to fix the box
afterward (short of Hetzner's console), so it's refused regardless of who
asks or what mode they're in.
"""
import os
import re
import subprocess

ALLOWED_ACTIONS = {"start", "stop", "restart"}
_UNIT_RE = re.compile(r"^[A-Za-z0-9_.@-]+\.service$")
_PROTECTED_UNITS = {"ssh.service", "sshd.service"}

UNIT_DIR = "/etc/systemd/system"


def _run(argv, timeout=15):
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except Exception as exc:
        return False, str(exc)
    output = (result.stdout + result.stderr).strip()
    return result.returncode == 0, output


def control_service(unit, action):
    if action not in ALLOWED_ACTIONS:
        return False, f"Invalid action '{action}'."
    if not _UNIT_RE.match(unit or ""):
        return False, f"Invalid unit name '{unit}'."
    if unit in _PROTECTED_UNITS and action != "restart":
        return False, f"'{unit}' is protected — stopping it could lock out remote access to this VPS entirely."
    ok, output = _run(["systemctl", action, unit])
    return ok, output or f"{action} {unit}: ok"


def delete_service(unit):
    if not _UNIT_RE.match(unit or ""):
        return False, f"Invalid unit name '{unit}'."
    if unit in _PROTECTED_UNITS:
        return False, f"'{unit}' is protected and cannot be deleted."

    unit_path = os.path.join(UNIT_DIR, unit)
    if not os.path.abspath(unit_path).startswith(UNIT_DIR + os.sep):
        return False, "Invalid unit path."
    if not os.path.isfile(unit_path):
        return False, f"'{unit}' has no unit file under {UNIT_DIR} — nothing to delete (it may belong to a package)."

    _run(["systemctl", "stop", unit])
    _run(["systemctl", "disable", unit])
    try:
        os.remove(unit_path)
    except OSError as exc:
        return False, f"Stopped and disabled, but couldn't remove the unit file: {exc}"
    _run(["systemctl", "daemon-reload"])
    return True, f"{unit} stopped, disabled, and its unit file removed."


def create_service(unit, description, exec_start, working_directory=None, user="root", environment=None, start=True):
    if not _UNIT_RE.match(unit or ""):
        return False, f"Invalid unit name '{unit}'."
    if unit in _PROTECTED_UNITS:
        return False, f"'{unit}' is a protected name."

    unit_path = os.path.join(UNIT_DIR, unit)
    if not os.path.abspath(unit_path).startswith(UNIT_DIR + os.sep):
        return False, "Invalid unit path."
    if os.path.exists(unit_path):
        return False, f"'{unit}' already exists — delete it first or choose a different name."
    if not exec_start or not exec_start.strip():
        return False, "ExecStart command is required."

    lines = [
        "[Unit]",
        f"Description={description or unit}",
        "After=network.target",
        "",
        "[Service]",
        "Type=simple",
    ]
    if working_directory:
        lines.append(f"WorkingDirectory={working_directory}")
    for env_line in (environment or []):
        if "=" in env_line:
            lines.append(f"Environment={env_line}")
    lines.append(f"ExecStart={exec_start}")
    lines.append(f"User={user or 'root'}")
    lines.append("Restart=on-failure")
    lines.append("RestartSec=3")
    lines.append("")
    lines.append("[Install]")
    lines.append("WantedBy=multi-user.target")
    lines.append("")

    try:
        with open(unit_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
    except OSError as exc:
        return False, f"Could not write unit file: {exc}"

    ok, output = _run(["systemctl", "daemon-reload"])
    if not ok:
        return False, f"Wrote unit file but daemon-reload failed: {output}"

    if start:
        ok, output = _run(["systemctl", "enable", "--now", unit])
        return ok, output or f"{unit} created and started."
    return True, f"{unit} created (not started)."
