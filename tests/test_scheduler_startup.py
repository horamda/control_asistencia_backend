import pytest
from scripts import start_server
from utils import trivia_scheduler


def test_container_rejects_multiple_workers_with_memory_storage(monkeypatch):
    monkeypatch.setattr(start_server, 'load_dotenv', lambda *args, **kwargs: None)
    monkeypatch.setattr(start_server.subprocess, 'run', lambda *args, **kwargs: None)
    monkeypatch.setenv('WEB_CONCURRENCY', '2')
    monkeypatch.setenv('RATELIMIT_STORAGE_URI', 'memory://')
    with pytest.raises(RuntimeError, match='shared backend'):
        start_server.main()


def test_dedicated_entrypoint_disables_worker_schedulers(monkeypatch):
    monkeypatch.setattr(start_server, 'load_dotenv', lambda *args, **kwargs: None)
    monkeypatch.setattr(start_server.subprocess, 'run', lambda *args, **kwargs: None)
    monkeypatch.setattr(start_server.signal, 'signal', lambda *args: None)
    monkeypatch.setenv('WEB_CONCURRENCY', '1')
    monkeypatch.setenv('RATELIMIT_STORAGE_URI', 'memory://')
    monkeypatch.setenv('SCHEDULER_IN_WEB', '1')
    launched = []
    class Process:
        def __init__(self, command):
            launched.append((command, start_server.os.environ['SCHEDULER_IN_WEB']))
        def poll(self):
            return 1
        def wait(self, **kwargs):
            return 1
    monkeypatch.setattr(start_server.subprocess, 'Popen', Process)
    assert start_server.main() == 1
    assert len(launched) == 2
    assert all(value == '0' for _, value in launched)


def test_scheduler_waits_for_running_jobs_before_releasing_ownership(monkeypatch):
    calls = []
    class Scheduler:
        running = True
        def shutdown(self, *, wait):
            calls.append(wait)
    monkeypatch.setattr(trivia_scheduler, '_scheduler', Scheduler())
    trivia_scheduler.shutdown_trivia_scheduler(wait=True)
    assert calls == [True]


@pytest.mark.parametrize("env_threads,expected", [(None, "8"), ("4", "4")])
def test_gunicorn_uses_threads_so_slow_requests_do_not_queue_others(monkeypatch, env_threads, expected):
    monkeypatch.setattr(start_server, 'load_dotenv', lambda *args, **kwargs: None)
    monkeypatch.setattr(start_server.subprocess, 'run', lambda *args, **kwargs: None)
    monkeypatch.setattr(start_server.signal, 'signal', lambda *args: None)
    monkeypatch.setenv('WEB_CONCURRENCY', '1')
    monkeypatch.setenv('RATELIMIT_STORAGE_URI', 'memory://')
    if env_threads:
        monkeypatch.setenv('GUNICORN_THREADS', env_threads)
    else:
        monkeypatch.delenv('GUNICORN_THREADS', raising=False)
    commands = []

    class Process:
        def __init__(self, command):
            commands.append(command)

        def poll(self):
            return 1

        def wait(self, **kwargs):
            return 1

    monkeypatch.setattr(start_server.subprocess, 'Popen', Process)
    start_server.main()
    gunicorn = next(c for c in commands if 'gunicorn' in c)
    assert gunicorn[gunicorn.index('--worker-class') + 1] == 'gthread'
    assert gunicorn[gunicorn.index('--threads') + 1] == expected
