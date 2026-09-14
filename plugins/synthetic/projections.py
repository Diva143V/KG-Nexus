"""Synthetic Domain Projection Profiles."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SyntheticProjectionProfile(BaseModel):
    """Projection configuration profile for synthetic domain entities and relations."""

    profile_id: str = "synthetic_projection_profile_v1"
    entity_label_mapping: dict[str, str] = Field(
        default_factory=lambda: {
            "Person": "PersonNode",
            "Organization": "OrganizationNode",
        }
    )
    relation_mapping: dict[str, str] = Field(
        default_factory=lambda: {
            "located_in": "LOCATED_IN",
        }
    )

    def map_entity_label(self, entity_type: str) -> str:
        return self.entity_label_mapping.get(entity_type, entity_type)

    def map_relation_type(self, predicate: str) -> str:
        return self.relation_mapping.get(predicate, predicate.upper())
