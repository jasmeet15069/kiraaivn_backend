"""Background task worker — the '24/7, assign it work' half of Jarvis.

Runs as its own process (see kira-task-worker.service), separate from the
gunicorn-served Flask app, so a long-running task never ties up (or times
out inside) an HTTP request. Polls the tasks table for pending rows, runs
each through the same tool-calling loop the chat endpoint uses (so it has
memory, run_code, MCP tools, etc.), then emails the result.
"""
import time
import traceback

import app as app_module
import mailer
import storage
import vps_status

POLL_INTERVAL_SECONDS = 5
TASK_MAX_TOOL_ITERATIONS = 10
VPS_SAMPLE_INTERVAL_SECONDS = 300  # 5 min — feeds the dashboard's day/month KPI rollups
_last_vps_sample = 0


def process_task(task):
    task_id = task["id"]
    description = task["description"]
    print(f"[worker] running task #{task_id}: {description!r}")
    storage.update_task(task_id, status="running")

    try:
        messages = [{"role": "user", "content": description}]
        reply, used_tools = app_module.run_chat_turn(
            task["model"], task["session_id"], messages, max_iterations=TASK_MAX_TOOL_ITERATIONS
        )
        reply = app_module.sanitize_reply(reply)
        storage.update_task(task_id, status="done", result=reply)
        storage.add_message(task["session_id"], "assistant", f"[Task #{task_id} finished] {reply}")
        mailer.send_task_email(description, reply, success=True)
        print(f"[worker] task #{task_id} done (used tools: {used_tools})")
    except Exception:
        err = traceback.format_exc()
        print(f"[worker] task #{task_id} failed:\n{err}")
        storage.update_task(task_id, status="failed", result=err)
        mailer.send_task_email(description, err, success=False)


def maybe_sample_vps():
    """Records a metrics sample every VPS_SAMPLE_INTERVAL_SECONDS, independent
    of whether anyone has the dashboard open — this is what makes the
    day/month KPI rollups real instead of only covering active viewing."""
    global _last_vps_sample
    now = time.time()
    if now - _last_vps_sample < VPS_SAMPLE_INTERVAL_SECONDS:
        return
    _last_vps_sample = now
    try:
        status = vps_status.get_status()
        storage.record_vps_history_sample(
            status["cpu_percent"], status["memory"]["percent"], status["disk"]["percent"]
        )
    except Exception:
        print(f"[worker] vps sampling error:\n{traceback.format_exc()}")


def main():
    print("[worker] started, polling for tasks...")
    while True:
        try:
            for task in storage.get_pending_tasks():
                process_task(task)
        except Exception:
            print(f"[worker] poll loop error:\n{traceback.format_exc()}")
        maybe_sample_vps()
        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
