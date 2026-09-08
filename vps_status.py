"""Read-only VPS health metrics — no external package, just /proc and
shutil.disk_usage. Nothing here executes or changes anything; it only
reads local system state, which is a different risk category entirely
from the system-connector's remote execution.
"""
import os
import re
import shutil
import subprocess
import time

# Pure OS/plumbing units nobody's dashboarding for — everything else running
# (every project's services: MHMS/Serenentra, hotel/POS, Jarvis, MCP servers,
# etc.) is discovered live and shown, so this list never needs updating when
# a new project's service gets added to the box.
_EXCLUDE_UNITS = {
    "dbus.service", "polkit.service", "multipathd.service", "qemu-guest-agent.service",
    "rsyslog.service", "cron.service", "atd.service", "containerd.service",
    "unattended-upgrades.service", "docker.service",
    # Standard Ubuntu/cloud-init/distro plumbing — present (mostly inactive-by-design,
    # e.g. oneshot boot units) on essentially any Ubuntu VPS, not project-specific.
    "networkmanager.service", "acpid.service", "apparmor.service", "apport-autoreport.service",
    "apport.service", "apt-daily-upgrade.service", "apt-daily.service", "auditd.service",
    "blk-availability.service", "cloud-config.service", "cloud-final.service",
    "cloud-init-hotplugd.service", "cloud-init-local.service", "cloud-init.service",
    "connman.service", "console-screen.service", "console-setup.service",
    "display-manager.service", "dm-event.service", "dmesg.service", "dpkg-db-backup.service",
    "e2scrub_all.service", "e2scrub_reap.service", "emergency.service", "fcoe.service",
    "finalrd.service", "firewalld.service", "fstrim.service", "getty-static.service",
    "grub-common.service", "grub-initrd-fallback.service", "hc-net-scan.service",
    "hv_kvp_daemon.service", "initrd-cleanup.service", "initrd-parse-etc.service",
    "initrd-switch-root.service", "initrd-udevadm-cleanup-db.service", "iscsi-shutdown.service",
    "iscsid.service", "kbd.service", "keyboard-setup.service", "kmod-static-nodes.service",
    "ldconfig.service", "logrotate.service", "lvm2-activation-early.service",
    "lvm2-lvmpolld.service", "lvm2-monitor.service", "man-db.service", "motd-news.service",
    "netplan-ovs-cleanup.service", "networkd-dispatcher.service", "networking.service",
    "open-iscsi.service", "open-vm-tools.service", "ovsdb-server.service", "pollinate.service",
    "rbdmap.service", "rc-local.service", "rescue.service", "secureboot-db.service",
    "setvtrgb.service", "sshd-keygen.service", "sshd.service", "sysstat-collect.service",
    "sysstat-summary.service", "sysstat.service", "tpm-udev.service", "ua-auto-attach.service",
    "ua-reboot-cmds.service", "ua-timer.service", "ubuntu-advantage-cloud-id-shim.service",
    "ubuntu-advantage.service", "ufw.service", "update-notifier-download.service",
    "update-notifier-motd.service", "uuidd.service", "vgauth.service", "zfs-mount.service",
}
_EXCLUDE_PREFIXES = (
    "systemd-", "getty@", "serial-getty@", "user@", "user-runtime-dir@", "hc-net-ifup@",
    "modprobe@", "plymouth-", "snapd.",
)
_UNIT_RE = re.compile(r"^[A-Za-z0-9_.@-]+\.service$")


def _read_cpu_times():
    with open("/proc/stat") as f:
        parts = [int(x) for x in f.readline().split()[1:]]
    idle = parts[3] + parts[4]  # idle + iowait
    return idle, sum(parts)


def get_cpu_percent(sample_seconds=0.2):
    idle1, total1 = _read_cpu_times()
    time.sleep(sample_seconds)
    idle2, total2 = _read_cpu_times()
    total_delta = total2 - total1
    if total_delta <= 0:
        return 0.0
    return round((1 - (idle2 - idle1) / total_delta) * 100, 1)


def get_memory():
    info = {}
    with open("/proc/meminfo") as f:
        for line in f:
            key, _, rest = line.partition(":")
            value = rest.strip().split()
            if value:
                info[key] = int(value[0])  # kB
    total_kb = info.get("MemTotal", 0)
    available_kb = info.get("MemAvailable", total_kb)
    used_kb = max(total_kb - available_kb, 0)
    percent = round(used_kb / total_kb * 100, 1) if total_kb else 0.0
    return {
        "total_mb": round(total_kb / 1024, 1),
        "used_mb": round(used_kb / 1024, 1),
        "percent": percent,
    }


def get_disk(path="/"):
    total, used, _ = shutil.disk_usage(path)
    return {
        "total_gb": round(total / (1024 ** 3), 1),
        "used_gb": round(used / (1024 ** 3), 1),
        "percent": round(used / total * 100, 1) if total else 0.0,
    }


def get_uptime_seconds():
    with open("/proc/uptime") as f:
        return float(f.readline().split()[0])


def get_load_avg():
    one, five, fifteen = os.getloadavg()
    return {"1m": round(one, 2), "5m": round(five, 2), "15m": round(fifteen, 2)}


def list_services():
    """Every systemd service the box knows about — running, stopped,
    failed, whatever project it belongs to — not a fixed list, so it
    never goes stale. Includes inactive/stopped units (via --all) since
    those matter just as much as running ones for a monitoring view."""
    try:
        result = subprocess.run(
            ["systemctl", "list-units", "--type=service", "--all", "--no-legend", "--plain"],
            capture_output=True, text=True, timeout=5,
        )
    except Exception:
        return []

    services = []
    for line in result.stdout.splitlines():
        parts = line.split(None, 4)
        if len(parts) < 4:
            continue
        unit, _load, active, sub = parts[:4]
        description = parts[4] if len(parts) > 4 else unit
        unit_lower = unit.lower()
        if unit_lower in _EXCLUDE_UNITS or unit_lower.startswith(_EXCLUDE_PREFIXES):
            continue
        services.append({
            "unit": unit, "description": description,
            "active": active == "active", "state": active, "sub_state": sub,
        })
    services.sort(key=lambda s: s["unit"])
    return services


def list_containers():
    """Running Docker containers, if Docker is present — separate from
    systemd services since projects like Serenentra run via docker-compose."""
    try:
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}\t{{.Image}}\t{{.Status}}"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return []
    except Exception:
        return []

    containers = []
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) == 3:
            containers.append({"name": parts[0], "image": parts[1], "status": parts[2]})
    return containers


def get_status():
    return {
        "hostname": os.uname().nodename,
        "cpu_count": os.cpu_count(),
        "cpu_percent": get_cpu_percent(),
        "load_avg": get_load_avg(),
        "memory": get_memory(),
        "disk": get_disk(),
        "uptime_seconds": get_uptime_seconds(),
        "services": list_services(),
        "containers": list_containers(),
        "timestamp": time.time(),
    }


def _parse_exec_start(raw):
    """systemctl show's ExecStart is a struct-ish string like
    '{ path=/usr/bin/python3 ; argv[]=/usr/bin/python3 app.py ; ... }' —
    pull out just the argv[] part, which is what a human wants to see."""
    if not raw:
        return None
    match = re.search(r"argv\[\]=([^;]+)", raw)
    return match.group(1).strip() if match else raw


def _listening_ports_for_pid(pid):
    if not pid or pid == "0":
        return []
    try:
        result = subprocess.run(["ss", "-tlnp"], capture_output=True, text=True, timeout=5)
    except Exception:
        return []
    ports = []
    needle = f"pid={pid},"
    for line in result.stdout.splitlines():
        if needle in line:
            parts = line.split()
            if len(parts) >= 4:
                ports.append(parts[3])
    return ports


def get_service_detail(unit):
    if not _UNIT_RE.match(unit or ""):
        return {"error": f"Invalid unit name '{unit}'."}

    props = {}
    try:
        result = subprocess.run(
            [
                "systemctl", "show", unit, "--no-page",
                "--property=Description,ActiveState,SubState,MainPID,ExecStart,"
                "WorkingDirectory,User,ActiveEnterTimestamp,MemoryCurrent,Restart,FragmentPath",
            ],
            capture_output=True, text=True, timeout=5,
        )
        for line in result.stdout.splitlines():
            if "=" in line:
                key, _, value = line.partition("=")
                props[key] = value
    except Exception as exc:
        return {"error": str(exc)}

    if not props or props.get("FragmentPath", "") == "":
        return {"error": f"'{unit}' not found."}

    pid = props.get("MainPID", "0")
    mem_raw = props.get("MemoryCurrent", "")
    mem_mb = round(int(mem_raw) / (1024 * 1024), 1) if mem_raw.isdigit() else None

    logs = []
    try:
        log_result = subprocess.run(
            ["journalctl", "-u", unit, "-n", "25", "--no-pager", "-o", "short-iso"],
            capture_output=True, text=True, timeout=5,
        )
        logs = log_result.stdout.splitlines()
    except Exception:
        pass

    return {
        "unit": unit,
        "description": props.get("Description") or unit,
        "active_state": props.get("ActiveState", "unknown"),
        "sub_state": props.get("SubState", ""),
        "main_pid": pid if pid != "0" else None,
        "exec_start": _parse_exec_start(props.get("ExecStart", "")),
        "working_directory": props.get("WorkingDirectory") or None,
        "user": props.get("User") or "root",
        "active_since": props.get("ActiveEnterTimestamp") or None,
        "memory_mb": mem_mb,
        "restart_policy": props.get("Restart") or None,
        "unit_file": props.get("FragmentPath") or None,
        "ports": _listening_ports_for_pid(pid),
        "recent_logs": logs,
    }
