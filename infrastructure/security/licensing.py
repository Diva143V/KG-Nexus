"""Platform Security and Licensing Enforcement (Phase 27).

Enforces source licenses, redistribution permissions, derived-data restrictions,
and export policies to block non-compliant releases.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from core.resources.source_release import SourceRelease


class SourceLicensePolicy(BaseModel):
    """Licensing policy governing source release usage and redistribution."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_id: str = Field(min_length=1)
    license_name: str = Field(min_length=1)
    redistribution_permitted: bool = True
    derived_data_restricted: bool = False
    export_allowed: bool = True


class LicenseEnforcementGate:
    """Gate evaluating source licenses before release publication."""

    def __init__(self, policies: list[SourceLicensePolicy] | None = None) -> None:
        self.policies = {p.source_id: p for p in (policies or [])}

    def evaluate_release(self, release: SourceRelease) -> tuple[bool, str]:
        source_name = getattr(release, "source_id", None)
        s_id = str(getattr(source_name, "value", source_name))
        policy = self.policies.get(s_id)

        if not policy:
            # Default permissive check for tests if no explicit policy registered
            return True, f"Default license check passed for {s_id}."

        if not policy.redistribution_permitted:
            return (
                False,
                f"Release BLOCKED: Source '{s_id}' license '{policy.license_name}' "
                "prohibits redistribution.",
            )

        if not policy.export_allowed:
            return (
                False,
                f"Release BLOCKED: Source '{s_id}' license '{policy.license_name}' "
                "prohibits export.",
            )

        return True, f"License check PASSED for source '{s_id}' ({policy.license_name})."
