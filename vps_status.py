"""Read-only VPS health metrics — no external package, just /proc and
shutil.disk_usage. Nothing here executes or changes anything; it only
reads local system state, which is a different risk category entirely
from the system-connector's remote execution.
"""
import os
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
}
_EXCLUDE_PREFIXES = ("systemd-", "getty@", "serial-getty@", "user@", "hc-net-ifup@")


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


def list_running_services():
    """Every currently-running systemd service on the box, whatever project
    it belongs to — not a fixed list, so it doesn't go stale."""
    try:
        result = subprocess.run(
            ["systemctl", "list-units", "--type=service", "--state=running", "--no-legend", "--plain"],
            capture_output=True, text=True, timeout=5,
        )
    except Exception:
        return []

    services = []
    for line in result.stdout.splitlines():
        parts = line.split(None, 4)
        if len(parts) < 4:
            continue
        unit, _load, active, _sub = parts[:4]
        description = parts[4] if len(parts) > 4 else unit
        if unit in _EXCLUDE_UNITS or unit.startswith(_EXCLUDE_PREFIXES):
            continue
        services.append({"unit": unit, "description": description, "active": active == "active"})
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
        "services": list_running_services(),
        "containers": list_containers(),
        "timestamp": time.time(),
    }
