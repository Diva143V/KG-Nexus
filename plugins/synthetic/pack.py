"""Synthetic Domain Pack.

Provides non-biomedical Person and Organization entities, located_in relation,
identity policy, simple evidence policy, and projection profile.
"""

from __future__ import annotations

from typing import Any

from plugins.synthetic.entities import Organization, Person
from plugins.synthetic.policies import SyntheticEvidencePolicy, SyntheticIdentityPolicy
from plugins.synthetic.projections import SyntheticProjectionProfile
from plugins.synthetic.relations import LOCATED_IN_CONTRACT, LocatedInRelation
from sdk.domain_config import DomainFusionConfig, get_synthetic_preset
from sdk.manifest import PluginManifest


class SyntheticDomainPack:
    """Domain pack implementing non-biomedical synthetic domain."""

    @property
    def manifest(self) -> PluginManifest:
        return PluginManifest(
            plugin_id="synthetic_domain_pack",
            name="Synthetic Domain Pack",
            version="1.0.0",
            core_api_version="1.0.0",
            dependencies=[],
            capabilities=["synthetic_entity_resolution", "synthetic_graph_projection"],
            entities=["Person", "Organization"],
            relations=["located_in"],
            identifier_registries=["synthetic_id"],
            identity_policies=["synthetic_identity_policy_v1"],
            validators=["synthetic_evidence_policy"],
            evidence_policies=["synthetic_evidence_policy_v1"],
            projection_profiles=["synthetic_projection_profile_v1"],
            ai_assets=[],
        )

    def pack_components(self) -> dict[str, Any]:
        return {
            "schemas": {
                "Person": Person,
                "Organization": Organization,
                "LocatedInRelation": LocatedInRelation,
            },
            "ontologies": {
                "synth": "http://schema.org/synthetic/",
            },
            "identifiers": {
                "synthetic_id": {"prefix": "SYNTH", "description": "Synthetic identifier registry"},
            },
            "identity_policies": {
                "synthetic_identity_policy_v1": SyntheticIdentityPolicy(),
            },
            "rules": {
                "located_in_contract": LOCATED_IN_CONTRACT,
            },
            "validators": {},
            "evidence_policies": {
                "synthetic_evidence_policy_v1": SyntheticEvidencePolicy(),
            },
            "projections": {
                "synthetic_projection_profile_v1": SyntheticProjectionProfile(),
            },
            "domain_config": get_synthetic_preset(),
        }

    def get_domain_config(self) -> DomainFusionConfig:
        """Return the domain fusion configuration for this plugin."""
        return get_synthetic_preset()

    def get_default_artifacts(self) -> list[dict[str, Any]]:
        """Return authentic sample dataset artifacts for release pipeline execution."""
        content = (
            b"@prefix synth: <urn:synth:> .\n\n"
            b"synth:ORG_001 <urn:synthetic:located_in> synth:LOC_001 ;\n"
            b'    <urn:synthetic:name> "Acme Corp" ;\n'
            b"    a synth:Organization .\n\n"
            b"synth:PER_001 <urn:synthetic:located_in> synth:ORG_001 ;\n"
            b'    <urn:synthetic:name> "Alice Smith" ;\n'
            b"    a synth:Person .\n"
        )
        return [
            {
                "name": "synthetic_domain_pack_seed_data.ttl",
                "content": content,
                "media_type": "turtle",
            }
        ]
