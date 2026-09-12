"""FIND-06: worker boot-time resource-caps logging tests.

Covers the ``_log_resource_caps`` startup helper: the 1 GiB production target
is reported alongside a fixture-driven cgroup measurement, an environment
without cgroup data fails open (no crash, ``unavailable`` recorded), and the
startup hook wires the helper in. Mirrors the fixture-driven cgroup pattern
from ``test_crawl_memory.py`` (``tmp_path`` fake trees injected through
``measure_memory``'s ``cgroup_root``/``proc_root``/``self_pid``).
"""

import logging
from pathlib import Path

from backend.services.ingestion.crawl_memory import measure_memory
from backend.workers import app as worker_app

_MIB = 1024 * 1024
_GIB = 1024 * _MIB


def _cgroup_root(tmp_path: Path) -> Path:
    return tmp_path / "sys" / "fs" / "cgroup"


def _write_proc(root: Path, pid: int, *, ppid: int, rss_kb: int) -> None:
    """Create a fake ``/proc/<pid>`` entry (``stat`` + ``status`` files)."""
    d = root / str(pid)
    d.mkdir(parents=True, exist_ok=True)
    (d / "stat").write_text(
        f"{pid} (demo proc) S {ppid} {pid} {pid} 34816 {pid} 1 0 0 0 "
        f"4194304 2147483648 140737488355328 0 0 0 0 0 0 0 20 0 4 0 0 0 0 0 "
        f"0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0\n"
    )
    (d / "status").write_text(
        f"Name:\tdemo\nVmPeak:\t 1000 kB\nVmRSS:\t   {rss_kb} kB\nVmSize:\t 2000 kB\n"
    )


def _log_record(caplog) -> logging.LogRecord:
    """The FIND-06 INFO record emitted by ``_log_resource_caps``."""
    matches = [r for r in caplog.records if r.getMessage().startswith("worker_resource_caps")]
    assert matches, "expected a worker_resource_caps INFO record"
    return matches[-1]


def test_log_resource_caps_reports_one_gib_cgroup_limit(tmp_path, caplog, monkeypatch) -> None:
    """A 1 GiB cgroup limit is surfaced next to the correct production target."""
    cg = _cgroup_root(tmp_path)
    cg.mkdir(parents=True)
    (cg / "memory.current").write_text(f"{512 * _MIB}\n")
    (cg / "memory.max").write_text(f"{_GIB}\n")  # 1 GiB detected limit

    monkeypatch.setattr(
        worker_app,
        "measure_memory",
        lambda: measure_memory(cgroup_root=cg, proc_root=tmp_path / "proc", self_pid=100),
    )

    with caplog.at_level(logging.INFO, logger="webchat_ai"):
        worker_app._log_resource_caps()  # noqa: SLF001

    record = _log_record(caplog)
    message = record.getMessage()
    assert "source=cgroup_v2" in message
    assert f"limit_bytes={_GIB}" in message
    assert f"current_bytes={512 * _MIB}" in message
    assert "expected_memory_mib=1024" in message  # 1 GiB production target
    assert "expected_cpus=2" in message  # 2 vCPU production target


def test_log_resource_caps_reports_process_tree_python_rss_and_count(
    tmp_path, caplog, monkeypatch
) -> None:
    """Fallback process-tree measurement logs python RSS and process count."""
    proc = tmp_path / "proc"
    proc.mkdir(parents=True)
    _write_proc(proc, 100, ppid=1, rss_kb=10_000)  # python worker
    _write_proc(proc, 101, ppid=100, rss_kb=20_000)  # chromium
    _write_proc(proc, 102, ppid=101, rss_kb=15_000)  # renderer

    monkeypatch.setattr(
        worker_app,
        "measure_memory",
        lambda: measure_memory(cgroup_root=tmp_path / "cgroup", proc_root=proc, self_pid=100),
    )

    with caplog.at_level(logging.INFO, logger="webchat_ai"):
        worker_app._log_resource_caps()  # noqa: SLF001

    message = _log_record(caplog).getMessage()
    assert "source=process_tree" in message
    assert f"python_rss_bytes={10_000 * 1024}" in message
    assert "processes=3" in message
    assert "expected_memory_mib=1024" in message


def test_log_resource_caps_unavailable_cgroup_does_not_crash(tmp_path, caplog, monkeypatch) -> None:
    """No cgroup/proc data logs ``unavailable`` without raising."""
    cg = _cgroup_root(tmp_path)
    cg.mkdir(parents=True)
    proc = tmp_path / "proc"
    proc.mkdir(parents=True)

    monkeypatch.setattr(
        worker_app,
        "measure_memory",
        lambda: measure_memory(cgroup_root=cg, proc_root=proc, self_pid=100),
    )

    with caplog.at_level(logging.INFO, logger="webchat_ai"):
        worker_app._log_resource_caps()  # noqa: SLF001

    message = _log_record(caplog).getMessage()
    assert "source=unavailable" in message
    assert "current_bytes=None" in message
    assert "limit_bytes=None" in message


async def test_startup_invokes_resource_caps_logging(monkeypatch) -> None:
    """Worker startup logs the resource caps once (wiring test)."""
    calls: list[str] = []

    def spy() -> None:
        calls.append("resource_caps")

    monkeypatch.setattr(worker_app, "_log_resource_caps", spy)
    monkeypatch.setattr(worker_app, "build_ingestion_embedding_client", lambda: None)
    monkeypatch.setattr(worker_app, "ProviderHealthStore", lambda _client: None)
    monkeypatch.setattr(worker_app, "get_redis", lambda: None)

    await worker_app.startup({})

    assert calls == ["resource_caps"]
