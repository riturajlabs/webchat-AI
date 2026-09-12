"""Container-aware worker memory measurement for the crawl guard (FIND-01).

The historical measure was ``resource.getrusage(RUSAGE_SELF).ru_maxrss``,
which reports only the **Python process's peak RSS**. Chromium runs as child
subprocesses sharing the container's cgroup, so the shared headless browser
was invisible to the guard - precisely the component that can exhaust the
1 GiB Railway worker during a JavaScript-heavy crawl.

This module measures the whole worker/container footprint, preferring in order:

1. cgroup v2 - ``<cgroup>/memory.current`` / ``memory.max``
2. cgroup v1 - ``<cgroup>/memory/memory.usage_in_bytes`` /
   ``memory.limit_in_bytes``
3. process tree - sum of ``VmRSS`` over the Python process and every
   descendant (Chromium, its renderers, GPU and helper processes)

Every read fails open: a missing, unreadable or malformed file degrades to the
next source and finally to ``source="unavailable"`` with
``current_bytes=None``. ``measure_memory`` performs only a handful of bounded
file reads and never raises, so it is safe (and cheap enough) to call inline
during crawl operations - no polling tasks, no process kills.
"""

from __future__ import annotations

import logging
import os
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("webchat_ai")

_MIB = 1024 * 1024

_DEFAULT_CGROUP_ROOT = Path("/sys/fs/cgroup")
_DEFAULT_PROC_ROOT = Path("/proc")

__all__ = ["MemoryMeasurement", "current_rss_mb", "measure_memory"]


@dataclass(frozen=True)
class MemoryMeasurement:
    """One instantaneous footprint sample.

    ``current_bytes`` is the worker/container footprint: cgroup usage when a
    memory controller is mounted, else the summed Python + Chromium process
    tree. ``limit_bytes`` is the cgroup limit when one exists (``None`` for a
    v2 ``max`` limit or an unknown limit). ``source`` names the layer that
    produced the sample: ``cgroup_v2`` | ``cgroup_v1`` | ``process_tree`` |
    ``unavailable``.
    """

    source: str
    current_bytes: int | None
    limit_bytes: int | None
    python_rss_bytes: int | None
    processes: int


def current_rss_mb() -> int:
    """The full worker/container footprint in MiB (best effort).

    Returns 0 when no measurement is possible (the guard fails open then);
    callers that need to distinguish "0 bytes measured" from "unavailable"
    should call :func:`measure_memory` directly.
    """
    measurement = measure_memory()
    if measurement.current_bytes is None:
        return 0
    return measurement.current_bytes // _MIB


def measure_memory(
    *,
    cgroup_root: Path | None = None,
    proc_root: Path | None = None,
    self_pid: int | None = None,
) -> MemoryMeasurement:
    """Measure the full worker/container footprint. Never raises.

    ``cgroup_root``/``proc_root``/``self_pid`` exist for tests; production uses
    the Linux defaults (``/sys/fs/cgroup``, ``/proc``, ``os.getpid()``).
    """
    cgroup_root = cgroup_root or _DEFAULT_CGROUP_ROOT
    proc_root = proc_root or _DEFAULT_PROC_ROOT
    self_pid = self_pid if self_pid is not None else os.getpid()

    try:
        v2 = _cgroup_v2_mount(cgroup_root, proc_root)
        if v2 is not None:
            current = _read_bytes(v2 / "memory.current")
            if current is not None:
                limit = _read_bytes(v2 / "memory.max")
                return MemoryMeasurement(
                    source="cgroup_v2",
                    current_bytes=current,
                    limit_bytes=limit,
                    python_rss_bytes=_proc_rss_kb(proc_root, self_pid),
                    processes=0,
                )

        v1 = _cgroup_v1_mount(cgroup_root, proc_root)
        if v1 is not None:
            current = _read_bytes(v1 / "memory.usage_in_bytes")
            if current is not None:
                limit = _read_bytes(v1 / "memory.limit_in_bytes")
                return MemoryMeasurement(
                    source="cgroup_v1",
                    current_bytes=current,
                    limit_bytes=limit,
                    python_rss_bytes=_proc_rss_kb(proc_root, self_pid),
                    processes=0,
                )

        tree = _process_tree_memory(proc_root, self_pid)
        if tree.count > 0:
            return MemoryMeasurement(
                source="process_tree",
                current_bytes=tree.total_bytes,
                limit_bytes=None,
                python_rss_bytes=tree.python_bytes,
                processes=tree.count,
            )
    except Exception as exc:  # pragma: no cover - last-resort fail-open
        logger.debug("Memory measurement failed: %r", exc)
    return MemoryMeasurement(
        source="unavailable",
        current_bytes=None,
        limit_bytes=None,
        python_rss_bytes=None,
        processes=0,
    )


# ---------------------------------------------------------------- cgroup


def _cgroup_v2_mount(cgroup_root: Path, proc_root: Path) -> Path | None:
    """The cgroup v2 directory exposing this process's memory files.

    The process's *own* cgroup membership is resolved from
    ``/proc/self/cgroup`` (``0::/relative/path``) FIRST: that directory holds
    the exact ledger for this process. The plain mount root is probed only
    when no membership path is available, so a process living in a descendant
    cgroup is never measured against the (broader) mount/root scope - e.g. a
    container whose root ``memory.current`` would be the node's 60 GiB instead
    of the container's own 300 MiB.
    """
    membership = _v2_membership(proc_root)
    if membership is not None:
        rel = membership.lstrip("/")
        base = cgroup_root / rel if rel else cgroup_root
        if (base / "memory.current").is_file():
            return base
    if (cgroup_root / "memory.current").is_file():
        return cgroup_root
    return None


def _v2_membership(proc_root: Path) -> str | None:
    """The process's cgroup v2 path (``0::<path>``) or ``None`` when absent."""
    for line in _read_lines(proc_root / "self" / "cgroup"):
        if line.startswith("0::"):
            return line.split(":", 2)[-1]
    return None


def _cgroup_v1_mount(cgroup_root: Path, proc_root: Path) -> Path | None:
    """The cgroup v1 memory-controller directory for this process.

    The process's own membership is resolved from the ``memory`` controller
    entry in ``/proc/self/cgroup`` (``<id>:memory:/relative/path``) FIRST and
    resolved under the controller mount. The plain mount root is probed only
    when no membership path is available, so a container process is never
    measured at the node (root) scope the bare mount would expose - e.g. a
    docker container at ``/docker/<id>`` whose root ``memory.usage_in_bytes``
    accounts the whole host, not the container.
    """
    membership = _v1_membership(proc_root)
    if membership is not None:
        rel = membership.lstrip("/")
        base = (cgroup_root / "memory" / rel) if rel else cgroup_root / "memory"
        if (base / "memory.usage_in_bytes").is_file():
            return base
    if (cgroup_root / "memory" / "memory.usage_in_bytes").is_file():
        return cgroup_root / "memory"
    return None


def _v1_membership(proc_root: Path) -> str | None:
    """The process's cgroup v1 memory path (``<id>:memory:<path>``) or ``None``."""
    for line in _read_lines(proc_root / "self" / "cgroup"):
        parts = line.split(":")
        if len(parts) != 3:
            continue
        if "memory" not in parts[1].split(","):
            continue
        return parts[2]
    return None


def _read_bytes(path: Path) -> int | None:
    """Parse a cgroup byte counter; ``max``/empty/malformed -> ``None``."""
    try:
        raw = path.read_text(encoding="ascii", errors="replace").strip()
    except OSError:
        return None
    if not raw or raw.lower() == "max":
        return None
    try:
        value = int(raw, 10)
    except ValueError:
        return None
    return value if value >= 0 else None


# ------------------------------------------------------- process tree


@dataclass(frozen=True)
class _TreeMemory:
    total_bytes: int
    python_bytes: int
    count: int


def _process_tree_memory(proc_root: Path, self_pid: int) -> _TreeMemory:
    """Sum ``VmRSS`` over ``self_pid`` and its descendants.

    Process-to-parent links come from ``/proc/<pid>/stat`` and RSS from
    ``/proc/<pid>/status``. Processes that vanish between the listing and a
    read are skipped (their ``stat``/``status`` reads simply fail), so a
    Chromium termination race can never crash the scan. A visited set prevents
    double counting even if the parent map ever contained a cycle.
    """
    pids: list[int] = []
    ppid_by_pid: dict[int, int | None] = {}
    try:
        entries = list(proc_root.iterdir())
    except OSError:
        return _TreeMemory(0, 0, 0)
    for entry in entries:
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        pids.append(pid)
        ppid_by_pid[pid] = _proc_ppid(proc_root, pid)

    children: dict[int, list[int]] = defaultdict(list)
    for pid, ppid in ppid_by_pid.items():
        if ppid is not None:
            children[ppid].append(pid)

    seen = {self_pid}
    stack = [self_pid]
    total_kb = 0
    python_kb = 0
    count = 0
    while stack:
        pid = stack.pop()
        rss_kb = _proc_rss_kb(proc_root, pid)
        if rss_kb is not None:
            total_kb += rss_kb
            if pid == self_pid:
                python_kb = rss_kb
            count += 1
        for child in children.get(pid, ()):
            if child not in seen:
                seen.add(child)
                stack.append(child)
    return _TreeMemory(total_kb * 1024, python_kb * 1024, count)


def _proc_ppid(proc_root: Path, pid: int) -> int | None:
    """Parent PID of ``pid`` from ``/proc/<pid>/stat`` (never raises)."""
    try:
        stat = (proc_root / str(pid) / "stat").read_text(encoding="ascii", errors="replace")
    except OSError:
        return None
    close = stat.rfind(")")
    if close == -1:
        return None
    # The field right after the closing paren of comm is the process state;
    # the one after that is the parent PID (comm may contain spaces/parens).
    rest = stat[close + 1 :].split()
    if len(rest) < 2:
        return None
    try:
        return int(rest[1], 10)
    except ValueError:
        return None


def _proc_rss_kb(proc_root: Path, pid: int) -> int | None:
    """Resident set size (KiB) of ``pid`` from ``VmRSS`` (never raises)."""
    try:
        status = (proc_root / str(pid) / "status").read_text(encoding="ascii", errors="replace")
    except OSError:
        return None
    for line in status.splitlines():
        if line.startswith("VmRSS:"):
            parts = line.split()
            if len(parts) >= 2:
                try:
                    return int(parts[1], 10)
                except ValueError:
                    return None
            return None
    return None


def _read_lines(path: Path) -> list[str]:
    """Read text lines from ``path``; missing/unreadable -> empty list."""
    try:
        text = path.read_text(encoding="ascii", errors="replace")
    except OSError:
        return []
    return [line.strip() for line in text.splitlines()]
