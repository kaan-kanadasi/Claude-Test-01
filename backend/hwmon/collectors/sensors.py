"""Temperature / fan sensor providers.

Windows exposes no general sensor API (psutil has no temperatures there), so v1
ships only a placeholder. A LibreHardwareMonitor-backed provider can later
implement the same Collector protocol and emit ``sensor.<name>`` metrics.
"""

from __future__ import annotations

from .base import CollectorUnavailable


class NullSensors:
    name = "sensors"
    interval = None

    def __init__(self):
        raise CollectorUnavailable(
            "No temperature/fan sensor provider configured yet "
            "(LibreHardwareMonitor support is planned)"
        )

    def static_info(self) -> dict:  # pragma: no cover - never constructed
        return {}

    def sample(self) -> dict[str, float]:  # pragma: no cover
        return {}
