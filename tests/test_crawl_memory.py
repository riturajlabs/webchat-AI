"""FIND-01: worker-memory measurement behaviour tests.

Focused on observable behaviour (source chosen, current/limit bytes, fail-open
fallthrough, process-tree summation, robustness against vanishing/unreadable
procs) rather than private implementation details. Every scenario is built on
``tmp_path`` fake cgroup/proc trees injected via ``cgroup_root``/``proc_root``/
``self_pid``, so measurements never depend on the host's real ``/proc``.
"""

from pathlib import Path

from backend.services.ingestion.crawl_memory import current_rss_mb, measure_memory

_MIB = 1024 * 1024


def _write_proc(
    root: Path,
    pid: int,
    *,
    ppid: int | None = None,
    rss_kb: int | None = None,
) -> None:
    """Create a fake ``/proc/<pid>`` entry (``stat`` + ``status`` files)."""
    d = root / str(pid)
    d.mkdir(parents=True, exist_ok=True)
    if ppid is not None:
        stat = (
            f"{pid} (demo proc) S {ppid} {pid} {pid} 34816 {pid} 1 0 0 0 "
            f"4194304 2147483648 140737488355328 0 0 0 0 0 0 0 20 0 4 0 0 0 0 0 "
            f"0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0\n"
        )
        (d / "stat").write_text(stat)
    if rss_kb is not None:
        (d / "status").write_text(
            f"Name:\tdemo\nVmPeak:\t 1000 kB\nVmRSS:\t   {rss_kb} kB\nVmSize:\t 2000 kB\n"
        )


def _proc_root(tmp_path: Path) -> Path:
    return tmp_path / "proc"


def _cgroup_root(tmp_path: Path) -> Path:
    return tmp_path / "sys" / "fs" / "cgroup"


def _assert_unavailable(measurement) -> None:
    assert measurement.source == "unavailable"
    assert measurement.current_bytes is None
    assert measurement.limit_bytes is None


def test_cgroup_v2_current_and_limit(tmp_path) -> None:
    """cgroup v2 mount yields usage and limit with python-rss attribution."""
    cg = _cgroup_root(tmp_path)
    cg.mkdir(parents=True)
    (cg / "memory.current").write_text(f"{50 * _MIB}\n")
    (cg / "memory.max").write_text(f"{256 * _MIB}\n")

    measurement = measure_memory(cgroup_root=cg, proc_root=_proc_root(tmp_path), self_pid=100)

    assert measurement.source == "cgroup_v2"
    assert measurement.current_bytes == 50 * _MIB
    assert measurement.limit_bytes == 256 * _MIB


def test_cgroup_v2_max_limit_is_none(tmp_path) -> None:
    """cgroup v2 ``memory.max = max`` means an unbounded (unknown) limit."""
    cg = _cgroup_root(tmp_path)
    cg.mkdir(parents=True)
    (cg / "memory.current").write_text(f"{10 * _MIB}\n")
    (cg / "memory.max").write_text("max\n")

    measurement = measure_memory(cgroup_root=cg, proc_root=_proc_root(tmp_path), self_pid=100)

    assert measurement.source == "cgroup_v2"
    assert measurement.current_bytes == 10 * _MIB
    assert measurement.limit_bytes is None


def test_cgroup_v2_delegated_path_from_proc_self_cgroup(tmp_path) -> None:
    """A delegated v2 cgroup (e.g. k8s) is resolved from /proc/self/cgroup."""
    cg = _cgroup_root(tmp_path)
    proc = _proc_root(tmp_path)
    delegated = cg / "kubepods" / "burstable" / "podabc" / "cri-xyz"
    delegated.mkdir(parents=True)
    (delegated / "memory.current").write_text(f"{5 * _MIB}\n")
    (delegated / "memory.max").write_text(f"{64 * _MIB}\n")
    (proc / "self").mkdir(parents=True)
    (proc / "self" / "cgroup").write_text("0::/kubepods/burstable/podabc/cri-xyz\n")

    measurement = measure_memory(cgroup_root=cg, proc_root=proc, self_pid=100)

    assert measurement.source == "cgroup_v2"
    assert measurement.current_bytes == 5 * _MIB
    assert measurement.limit_bytes == 64 * _MIB


def test_cgroup_v1_current_and_limit(tmp_path) -> None:
    """cgroup v1 mount yields usage and limit bytes."""
    cg = _cgroup_root(tmp_path)
    v1 = cg / "memory"
    v1.mkdir(parents=True)
    (v1 / "memory.usage_in_bytes").write_text(f"{80 * _MIB}\n")
    (v1 / "memory.limit_in_bytes").write_text(f"{512 * _MIB}\n")

    measurement = measure_memory(cgroup_root=cg, proc_root=_proc_root(tmp_path), self_pid=100)

    assert measurement.source == "cgroup_v1"
    assert measurement.current_bytes == 80 * _MIB
    assert measurement.limit_bytes == 512 * _MIB


def test_cgroup_v1_controller_path_from_proc_self_cgroup(tmp_path) -> None:
    """v1 memory controller is located via /proc/self/cgroup (docker-style)."""
    cg = _cgroup_root(tmp_path)
    proc = _proc_root(tmp_path)
    delegated = cg / "memory" / "docker" / "deadbeef"
    delegated.mkdir(parents=True)
    (delegated / "memory.usage_in_bytes").write_text(f"{20 * _MIB}\n")
    (delegated / "memory.limit_in_bytes").write_text(f"{1000 * _MIB}\n")
    (proc / "self").mkdir(parents=True)
    (proc / "self" / "cgroup").write_text("2:memory:/docker/deadbeef\n")

    measurement = measure_memory(cgroup_root=cg, proc_root=proc, self_pid=100)

    assert measurement.source == "cgroup_v1"
    assert measurement.current_bytes == 20 * _MIB
    assert measurement.limit_bytes == 1000 * _MIB


def test_v2_unreadable_falls_back_to_v1(tmp_path) -> None:
    """A v2 mount whose current file is unreadable degrades to v1, not death."""
    cg = _cgroup_root(tmp_path)
    v1 = cg / "memory"
    v1.mkdir(parents=True)
    # A directory where memory.current should live -> IsADirectoryError on read.
    (cg / "memory.current").mkdir()
    (v1 / "memory.usage_in_bytes").write_text(f"{30 * _MIB}\n")
    (v1 / "memory.limit_in_bytes").write_text(f"{100 * _MIB}\n")

    measurement = measure_memory(cgroup_root=cg, proc_root=_proc_root(tmp_path), self_pid=100)

    assert measurement.source == "cgroup_v1"
    assert measurement.current_bytes == 30 * _MIB


def test_v1_root_present_uses_nested_membership(tmp_path) -> None:
    """FIND-01 (P2): membership wins even when the v1 mount root is also present.

    The bare mount root of a v1 host accounts the WHOLE node (here 60 GiB);
    the process's own ``2:memory:/docker/deadbeef`` cgroup holds the true
    300 MiB. The per-process membership path must be measured, never the root.
    """
    cg = _cgroup_root(tmp_path)
    v1 = cg / "memory"
    v1.mkdir(parents=True)
    (v1 / "memory.usage_in_bytes").write_text(f"{60 * 1024 * _MIB}\n")  # whole node
    (v1 / "memory.limit_in_bytes").write_text(f"{128 * 1024 * _MIB}\n")
    proc = _proc_root(tmp_path)
    (proc / "self").mkdir(parents=True)
    (proc / "self" / "cgroup").write_text("2:memory:/docker/deadbeef\n")
    container = v1 / "docker" / "deadbeef"
    container.mkdir(parents=True)
    (container / "memory.usage_in_bytes").write_text(f"{300 * _MIB}\n")
    (container / "memory.limit_in_bytes").write_text(f"{1024 * _MIB}\n")

    measurement = measure_memory(cgroup_root=cg, proc_root=proc, self_pid=100)

    assert measurement.source == "cgroup_v1"
    assert measurement.current_bytes == 300 * _MIB
    assert measurement.limit_bytes == 1024 * _MIB


def test_v2_root_present_uses_nested_membership(tmp_path) -> None:
    """FIND-01 (P2): membership wins even when the v2 mount root is also present."""
    cg = _cgroup_root(tmp_path)
    cg.mkdir(parents=True)
    (cg / "memory.current").write_text(f"{40 * 1024 * _MIB}\n")  # broader scope
    (cg / "memory.max").write_text("max\n")
    proc = _proc_root(tmp_path)
    (proc / "self").mkdir(parents=True)
    (proc / "self" / "cgroup").write_text("0::/container/deadbeef\n")
    container = cg / "container" / "deadbeef"
    container.mkdir(parents=True)
    (container / "memory.current").write_text(f"{300 * _MIB}\n")
    (container / "memory.max").write_text(f"{1024 * _MIB}\n")

    measurement = measure_memory(cgroup_root=cg, proc_root=proc, self_pid=100)

    assert measurement.source == "cgroup_v2"
    assert measurement.current_bytes == 300 * _MIB
    assert measurement.limit_bytes == 1024 * _MIB


def test_malformed_cgroup_values_fail_open(tmp_path) -> None:
    """Garbage bytes in the counters degrade to the next measurement layer."""
    cg = _cgroup_root(tmp_path)
    cg.mkdir(parents=True)
    (cg / "memory.current").write_text("not-a-number\n")
    (cg / "memory.max").write_text("also-not-a-number\n")
    proc = _proc_root(tmp_path)
    proc.mkdir(parents=True)
    _write_proc(proc, 100, ppid=1, rss_kb=100)

    measurement = measure_memory(cgroup_root=cg, proc_root=proc, self_pid=100)

    assert measurement.source == "process_tree"
    assert measurement.current_bytes == 100 * 1024


def test_missing_cgroup_files_fail_open(tmp_path) -> None:
    """No cgroup files and no process tree -> unavailable, never a raise."""
    cg = _cgroup_root(tmp_path)
    cg.mkdir(parents=True)
    proc = _proc_root(tmp_path)
    proc.mkdir(parents=True)

    measurement = measure_memory(cgroup_root=cg, proc_root=proc, self_pid=100)

    _assert_unavailable(measurement)


def test_unreadable_cgroup_file_fails_open(tmp_path) -> None:
    """An unreadable memory.current (dir, chmod, bad mount) is not fatal."""
    cg = _cgroup_root(tmp_path)
    cg.mkdir(parents=True)
    (cg / "memory.current").mkdir()
    (cg / "memory.max").write_text(f"{64 * _MIB}\n")

    measurement = measure_memory(cgroup_root=cg, proc_root=_proc_root(tmp_path), self_pid=100)

    _assert_unavailable(measurement)


def test_process_tree_sums_python_and_chromium_children(tmp_path) -> None:
    """Fallback sums the worker plus every descendant (Chromium + renderers)."""
    proc = _proc_root(tmp_path)
    proc.mkdir(parents=True)
    _write_proc(proc, 100, ppid=1, rss_kb=10_000)  # python worker
    _write_proc(proc, 101, ppid=100, rss_kb=20_000)  # chromium browser
    _write_proc(proc, 102, ppid=101, rss_kb=15_000)  # renderer
    _write_proc(proc, 103, ppid=102, rss_kb=3_000)  # gpu helper

    measurement = measure_memory(cgroup_root=_cgroup_root(tmp_path), proc_root=proc, self_pid=100)

    assert measurement.source == "process_tree"
    assert measurement.current_bytes == (10_000 + 20_000 + 15_000 + 3_000) * 1024
    assert measurement.python_rss_bytes == 10_000 * 1024
    assert measurement.processes == 4


def test_process_tree_covers_descendants_beyond_one_level(tmp_path) -> None:
    """Grandchildren of the worker are included (not just direct children)."""
    proc = _proc_root(tmp_path)
    proc.mkdir(parents=True)
    _write_proc(proc, 50, ppid=1, rss_kb=1_000)
    _write_proc(proc, 200, ppid=50, rss_kb=2_000)
    _write_proc(proc, 300, ppid=200, rss_kb=4_000)
    _write_proc(proc, 400, ppid=300, rss_kb=8_000)

    measurement = measure_memory(cgroup_root=_cgroup_root(tmp_path), proc_root=proc, self_pid=50)

    assert measurement.current_bytes == (1_000 + 2_000 + 4_000 + 8_000) * 1024
    assert measurement.processes == 4


def test_process_tree_duplicate_pid_protection(tmp_path) -> None:
    """A reparenting race (root reports itself as its own parent) cannot double count."""
    proc = _proc_root(tmp_path)
    proc.mkdir(parents=True)
    _write_proc(proc, 100, ppid=1, rss_kb=10)
    _write_proc(proc, 101, ppid=100, rss_kb=1)
    _write_proc(proc, 102, ppid=101, rss_kb=2)
    # Reparenting race: the root now lists itself as its own child. Without a
    # visited set the scan would revisit (and re-count) the root forever.
    (proc / "100" / "stat").write_text("100 (demo proc) S 100 100 100 34816 ...\n")

    measurement = measure_memory(cgroup_root=_cgroup_root(tmp_path), proc_root=proc, self_pid=100)

    assert measurement.current_bytes == (10 + 1 + 2) * 1024
    assert measurement.processes == 3


def test_process_tree_skips_disappearing_processes(tmp_path) -> None:
    """A pid that vanishes mid-scan is skipped, not fatal, not double-counted."""
    proc = _proc_root(tmp_path)
    proc.mkdir(parents=True)
    _write_proc(proc, 100, ppid=1, rss_kb=10_000)
    _write_proc(proc, 102, ppid=100, rss_kb=5_000)
    # 103 vanished after the pid listing: its stat is present but its status
    # file is gone, so its RSS read fails and it is skipped without crashing.
    vanished = proc / "103"
    vanished.mkdir()
    (vanished / "stat").write_text("103 (demo proc) S 100 103 103 34816 ...\n")

    measurement = measure_memory(cgroup_root=_cgroup_root(tmp_path), proc_root=proc, self_pid=100)

    assert measurement.current_bytes == (10_000 + 5_000) * 1024
    assert measurement.processes == 2


def test_empty_process_tree_is_unavailable(tmp_path) -> None:
    """A readable /proc with no measurable process -> unavailable, no crash."""
    proc = _proc_root(tmp_path)
    proc.mkdir(parents=True)
    proc.joinpath("999").mkdir(parents=True)  # pid dir with no status/stat

    measurement = measure_memory(cgroup_root=_cgroup_root(tmp_path), proc_root=proc, self_pid=999)

    _assert_unavailable(measurement)


def test_cgroup_preferred_over_process_tree(tmp_path) -> None:
    """When a cgroup source is readable it wins over the /proc fallback."""
    cg = _cgroup_root(tmp_path)
    cg.mkdir(parents=True)
    (cg / "memory.current").write_text(f"{7 * _MIB}\n")
    (cg / "memory.max").write_text(f"{128 * _MIB}\n")
    proc = _proc_root(tmp_path)
    proc.mkdir(parents=True)
    _write_proc(proc, 100, ppid=1, rss_kb=999_999)

    measurement = measure_memory(cgroup_root=cg, proc_root=proc, self_pid=100)

    assert measurement.source == "cgroup_v2"
    assert measurement.current_bytes == 7 * _MIB


def test_measure_memory_never_raises(tmp_path) -> None:
    """Even a hostile root layout cannot raise out of the measurement."""
    cg = _cgroup_root(tmp_path)
    cg.mkdir(parents=True)
    (cg / "memory.current").mkdir()  # unreadable
    (cg / "memory.max").write_text("max\n")
    broken_proc = tmp_path / "broken"  # a FILE where a directory is expected

    measurement = measure_memory(cgroup_root=cg, proc_root=broken_proc, self_pid=100)

    _assert_unavailable(measurement)


def test_current_rss_mb_zero_when_unavailable(tmp_path, monkeypatch) -> None:
    """The MiB wrapper reports 0 for an unmeasurable footprint (fail-open)."""
    from backend.services.ingestion import crawl_memory

    cg = _cgroup_root(tmp_path)
    cg.mkdir(parents=True)
    proc = _proc_root(tmp_path)
    proc.mkdir(parents=True)
    monkeypatch.setattr(
        crawl_memory,
        "measure_memory",
        lambda: measure_memory(cgroup_root=cg, proc_root=proc, self_pid=100),
    )

    assert measure_memory(cgroup_root=cg, proc_root=proc, self_pid=100).source == "unavailable"
    assert current_rss_mb() == 0


def test_current_rss_mb_reports_cgroup_megabytes(tmp_path, monkeypatch) -> None:
    """The MiB wrapper surfaces the cgroup footprint, rounded down to MiB."""
    from backend.services.ingestion import crawl_memory

    cg = _cgroup_root(tmp_path)
    cg.mkdir(parents=True)
    (cg / "memory.current").write_text(f"{5 * _MIB + 1_000_000}\n")
    (cg / "memory.max").write_text("max\n")
    monkeypatch.setattr(
        crawl_memory,
        "measure_memory",
        lambda: measure_memory(cgroup_root=cg, proc_root=_proc_root(tmp_path), self_pid=100),
    )

    assert current_rss_mb() == 5
