"""Run web + durable billing worker in the existing container, not web threads.

If either child exits unexpectedly the container exits non-zero, letting the
hosting platform restart it. Workers can overlap during deploys: row locks and
payment identities prevent double application. No extra Railway service needed.
"""

import os
import signal
import subprocess
import sys
import threading


def web_command():
    return [
        sys.executable, "-m", "gunicorn", "config.wsgi:application",
        "--bind", "0.0.0.0:" + os.getenv("PORT", "8000"),
        "--workers", os.getenv("WEB_CONCURRENCY", "2"),
        "--threads", os.getenv("GUNICORN_THREADS", "2"),
        "--timeout", os.getenv("GUNICORN_TIMEOUT", "120"),
        "--access-logfile", "-", "--error-logfile", "-",
    ]


def worker_requested():
    return os.getenv("PAYSTACK_LIVE_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}


def supervise(commands, stopped):
    children = []
    try:
        for command in commands:
            children.append(subprocess.Popen(command))
        while not stopped.is_set():
            if any(child.poll() is not None for child in children):
                print("A required application process stopped; restarting the container.", flush=True)
                return 1
            stopped.wait(0.5)
        return 0
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=25)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


def main():
    migration = subprocess.run([sys.executable, "manage.py", "migrate", "--noinput"])
    if migration.returncode:
        return migration.returncode
    stopped = threading.Event()
    previous = {}
    for sig in (signal.SIGINT, signal.SIGTERM):
        previous[sig] = signal.signal(sig, lambda signum, frame: stopped.set())
    commands = []
    if worker_requested():
        commands.append([sys.executable, "manage.py", "process_paystack_live_events", "--watch"])
    commands.append(web_command())
    try:
        return supervise(commands, stopped)
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


if __name__ == "__main__":
    raise SystemExit(main())
