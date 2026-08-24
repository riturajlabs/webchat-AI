"""Per-provider circuit breaker (Phase 4 provider resilience).

Prevents repeated calls to unhealthy AI providers. Each ``(role, provider)``
pair gets an independent circuit with the classic three states:

- ``CLOSED``: normal operation; consecutive failures are counted.
- ``OPEN``: after ``AI_CIRCUIT_FAILURE_THRESHOLD`` consecutive failures the
  provider is skipped entirely for ``AI_CIRCUIT_COOLDOWN_SECONDS``.
- ``HALF_OPEN``: after the cooldown exactly one probe request is allowed;
  success closes the circuit, failure reopens it with a fresh cooldown.

State is **process-global by design**: fallback chains are rebuilt per
request (`deps.get_rag_service` is an uncached dependency), so any state
attached to a chain instance would be lost between requests.

Isolation rules:
- Generation and embedding circuits are tracked separately (``role``), so a
  failing generation endpoint never blocks embeddings of the same vendor
  (retrieval must keep working while generation degrades).
- Only normalized provider errors (``GenerationError``/``EmbeddingError``)
  count as failures; unexpected exceptions are programming bugs and
  propagate unchanged without touching circuit state.
- When ``AI_CIRCUIT_BREAKER_ENABLED=false`` every operation is a no-op that
  allows all traffic - byte-for-byte the pre-Phase-4 behaviour.

Observation is log-based ("ai_circuit_*" structured messages on the shared
``webchat_ai`` logger): opened / half-open / closed transitions and skips are
alertable without coupling this module to the metrics registry.

A stalled HALF_OPEN probe cannot deadlock the circuit: if no result was ever
recorded (e.g. the probing request died mid-flight), a new probe is re-armed
once another cooldown window has passed.
"""

import logging
import threading
import time

from backend.core.config import get_settings

logger = logging.getLogger("webchat_ai")

ROLE_GENERATION = "generation"
ROLE_EMBEDDING = "embedding"

__all__ = [
    "CircuitState",
    "ROLE_EMBEDDING",
    "ROLE_GENERATION",
    "allow_provider",
    "circuit_snapshot",
    "record_provider_failure",
    "record_provider_success",
    "reset_circuit_breakers",
]


class CircuitState:
    """Circuit states (plain string constants for cheap logging)."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class _Circuit:
    """Mutable state for one (role, provider) pair."""

    __slots__ = ("consecutive_failures", "opened_at", "probe_at", "state")

    def __init__(self) -> None:
        self.state: str = CircuitState.CLOSED
        self.consecutive_failures: int = 0
        self.opened_at: float = 0.0
        self.probe_at: float = 0.0


_LOCK = threading.Lock()
_CIRCUITS: dict[tuple[str, str], _Circuit] = {}


def _monotonic() -> float:
    """Indirection so tests can freeze time via monkeypatch."""
    return time.monotonic()


def _read_settings() -> tuple[bool, int, float]:
    """Resolve (enabled, threshold, cooldown) from settings at call time.

    Reading on every operation keeps the breaker honest across env reloads
    and tests; `get_settings` is cached so this is a dict lookup in practice.
    """
    settings = get_settings()
    enabled = bool(settings.ai_circuit_breaker_enabled)
    threshold = settings.ai_circuit_failure_threshold
    cooldown = float(settings.ai_circuit_cooldown_seconds)
    # Degenerate config values degrade to "trip immediately / instant retry"
    # rather than raising inside a request path.
    threshold = threshold if threshold >= 1 else 1
    cooldown = cooldown if cooldown > 0 else 0.0
    return enabled, threshold, cooldown


def allow_provider(role: str, name: str) -> bool:
    """Whether a request to this provider may be attempted now."""
    enabled, _, cooldown = _read_settings()
    if not enabled:
        return True
    now = _monotonic()
    with _LOCK:
        circuit = _CIRCUITS.setdefault((role, name), _Circuit())
        if circuit.state is CircuitState.CLOSED:
            return True
        if circuit.state is CircuitState.OPEN:
            if now - circuit.opened_at < cooldown:
                return False
            # Cooldown elapsed: allow exactly one probe (HALF_OPEN).
            circuit.state = CircuitState.HALF_OPEN
            circuit.probe_at = now
            logger.info(
                "ai_circuit_half_open role=%s provider=%s cooldown_seconds=%s probe_allowed=true",
                role,
                name,
                cooldown,
            )
            return True
        # HALF_OPEN: a probe is already allowed once per cooldown window. If
        # it never resolved (request died without recording), re-arm after
        # another full cooldown instead of skipping forever.
        if now - circuit.probe_at >= cooldown:
            circuit.probe_at = now
            return True
        return False


def record_provider_success(role: str, name: str) -> None:
    """Close the circuit and reset the failure counter after a success."""
    enabled, _, _ = _read_settings()
    if not enabled:
        return
    with _LOCK:
        circuit = _CIRCUITS.get((role, name))
        if circuit is None:
            return
        circuit.consecutive_failures = 0
        if circuit.state is not CircuitState.CLOSED:
            logger.info("ai_circuit_closed role=%s provider=%s", role, name)
            circuit.state = CircuitState.CLOSED


def record_provider_failure(role: str, name: str) -> None:
    """Count one provider failure; open the circuit at the threshold."""
    enabled, threshold, cooldown = _read_settings()
    if not enabled:
        return
    now = _monotonic()
    with _LOCK:
        circuit = _CIRCUITS.setdefault((role, name), _Circuit())
        circuit.consecutive_failures += 1
        if circuit.consecutive_failures >= threshold or (circuit.state is CircuitState.HALF_OPEN):
            circuit.state = CircuitState.OPEN
            circuit.opened_at = now
            logger.warning(
                "ai_circuit_opened role=%s provider=%s "
                "consecutive_failures=%d threshold=%d cooldown_seconds=%s",
                role,
                name,
                circuit.consecutive_failures,
                threshold,
                cooldown,
            )


def circuit_snapshot() -> dict[str, dict[str, object]]:
    """Read-only view of all circuits (diagnostics/tests; not a hot path)."""
    with _LOCK:
        return {
            f"{role}:{name}": {
                "state": circuit.state,
                "consecutive_failures": circuit.consecutive_failures,
            }
            for (role, name), circuit in sorted(_CIRCUITS.items())
        }


def reset_circuit_breakers() -> None:
    """Clear all circuit state (tests only)."""
    with _LOCK:
        _CIRCUITS.clear()
