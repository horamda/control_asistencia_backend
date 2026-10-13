"""Container entrypoint: migrate, run one elected scheduler, supervise Gunicorn."""
import os
import signal
import subprocess
import sys
import time
from dotenv import load_dotenv


def main():
    load_dotenv('/etc/secrets/.env', override=False)
    load_dotenv(override=False)
    # This entrypoint owns a dedicated scheduler; never duplicate it in workers.
    os.environ['SCHEDULER_IN_WEB'] = '0'
    subprocess.run([sys.executable, 'scripts/bootstrap_schema.py'], check=True)
    storage = os.getenv('RATELIMIT_STORAGE_URI', 'memory://')
    workers = int(os.getenv('WEB_CONCURRENCY', '2' if storage.startswith(('redis://', 'rediss://')) else '1'))
    if workers > 1 and storage == 'memory://':
        raise RuntimeError('Multiple web workers require RATELIMIT_STORAGE_URI pointing to a shared backend.')
    children = []
    stopping = False
    def stop(*_):
        nonlocal stopping
        stopping = True
        for child in children:
            if child.poll() is None:
                child.terminate()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, stop)
    try:
        children.append(subprocess.Popen([sys.executable, 'scripts/run_scheduler.py']))
        children.append(subprocess.Popen([sys.executable, '-m', 'gunicorn', 'app:app', '--bind', '0.0.0.0:' + os.getenv('PORT', '8080'), '--workers', str(workers), '--timeout', os.getenv('GUNICORN_TIMEOUT', '120')]))
        while not stopping and all(child.poll() is None for child in children):
            time.sleep(1)
        return 0 if stopping else 1
    finally:
        stop()
        for child in children:
            try:
                child.wait(timeout=30)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


if __name__ == '__main__':
    raise SystemExit(main())
