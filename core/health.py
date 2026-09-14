"""Domain-neutral health checking for the platform."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from . import __version__

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HealthStatus:
    """Immutable health-check result."""

    status: str
    version: str
    component: str


def healthcheck() -> HealthStatus:
    """Report whether the Core is operational.

    Domain-neutral: no plugins, stores, or models are consulted.
    """
    status = HealthStatus(status="ok", version=__version__, component="core")
    logger.info(
        "healthcheck completed",
        extra={"status": status.status, "version": status.version},
    )
    return status
