"""Read-only VPS health metrics — no external package, just /proc and
shutil.disk_usage. Nothing here executes or changes anything; it only
reads local system state, which is a different risk category entirely
from the system-connector's remote execution.
"""
import os
import subprocess
import time

SERVICES = [
    "kira-chat-backend",
    "kira-task-worker",
    "kira-agent-gateway",
    "nginx",
    "jazz-local-qwen3b",
    "jazz-local-dolphin",
    "ollama",
]


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
    total, used, _ = __import__("shutil").disk_usage(path)
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


def get_service_status(name):
    try:
        result = subprocess.run(
            ["systemctl", "is-active", name], capture_output=True, text=True, timeout=3
        )
        return result.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def get_status():
    return {
        "hostname": os.uname().nodename,
        "cpu_count": os.cpu_count(),
        "cpu_percent": get_cpu_percent(),
        "load_avg": get_load_avg(),
        "memory": get_memory(),
        "disk": get_disk(),
        "uptime_seconds": get_uptime_seconds(),
        "services": {name: get_service_status(name) for name in SERVICES},
        "timestamp": time.time(),
    }
