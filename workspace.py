"""Read-only browsing of the Jarvis workspace for the VPS Monitor dashboard.
Writing happens only through the workspace-fs MCP tool (see tools.py /
mcp_client.py) — this module never creates, edits, or deletes anything.
"""
import os

WORKSPACE_ROOT = os.environ.get(
    "JARVIS_WORKSPACE_ROOT", os.path.join(os.path.dirname(__file__), "workspace")
)
MAX_PREVIEW_BYTES = 200_000


def _resolve(rel_path):
    """Returns the real absolute path for rel_path if it's inside
    WORKSPACE_ROOT, else None (blocks .. traversal and symlink escapes)."""
    root = os.path.realpath(WORKSPACE_ROOT)
    os.makedirs(root, exist_ok=True)
    target = os.path.realpath(os.path.join(root, (rel_path or "").lstrip("/\\")))
    if target != root and not target.startswith(root + os.sep):
        return None
    return target


def list_dir(rel_path=""):
    target = _resolve(rel_path)
    if target is None:
        return {"error": "Invalid path."}
    if not os.path.isdir(target):
        return {"error": f"'{rel_path}' is not a directory."}

    entries = []
    try:
        for name in sorted(os.listdir(target)):
            full = os.path.join(target, name)
            is_dir = os.path.isdir(full)
            entries.append({
                "name": name,
                "is_dir": is_dir,
                "size": None if is_dir else os.path.getsize(full),
                "modified": os.path.getmtime(full),
            })
    except OSError as exc:
        return {"error": str(exc)}

    return {"path": rel_path.strip("/"), "entries": entries}


def read_file(rel_path):
    target = _resolve(rel_path)
    if target is None or not os.path.isfile(target):
        return {"error": "Invalid file."}
    size = os.path.getsize(target)
    if size > MAX_PREVIEW_BYTES:
        return {"error": f"File is {size} bytes — too large to preview here."}
    try:
        with open(target, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError as exc:
        return {"error": str(exc)}
    return {"path": rel_path.strip("/"), "size": size, "content": content}


def resolve_for_download(rel_path):
    """Returns the real path if it's a valid file inside the workspace, else None."""
    target = _resolve(rel_path)
    if target is None or not os.path.isfile(target):
        return None
    return target
