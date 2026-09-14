"""Edge reconciliation and deduplication (backward compatibility)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from core.assertions.assertion import Assertion
from core.fusion.models import ConflictMode


class EdgeReconciler:
    """Reconciles assertion edges across graphs with deduplication and conflict modes."""

    def reconcile_assertions(
        self,
        assertions_a: Sequence[Assertion],
        assertions_b: Sequence[Assertion],
        conflict_mode: ConflictMode = ConflictMode.CONFLICT_PRESERVE,
    ) -> tuple[list[Assertion], int, list[dict[str, Any]]]:
        """Reconcile assertions from two graphs.

        Returns (reconciled_assertions, dedup_count, conflict_records).
        """
        reconciled: list[Assertion] = []
        dedup_count = 0
        conflicts: list[dict[str, Any]] = []

        seen: dict[tuple[str, str, str], Assertion] = {}

        for a in assertions_a:
            key = (str(a.subject.value), str(a.predicate), str(a.object.value))
            seen[key] = a
            reconciled.append(a)

        for b in assertions_b:
            key = (str(b.subject.value), str(b.predicate), str(b.object.value))
            if key in seen:
                dedup_count += 1
                if conflict_mode == ConflictMode.CONFLICT_PRESERVE:
                    reconciled.append(b)
                # In CONFLICT_REJECT / other modes, keep only the authoritative one from assertions_a
            else:
                seen[key] = b
                reconciled.append(b)

        return reconciled, dedup_count, conflicts
