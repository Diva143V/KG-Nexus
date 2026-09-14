"""Biomedical Relation Definitions and Relation Contracts."""

from __future__ import annotations

from pydantic import BaseModel

from core.relations.relation import Relation


class BiomedicalRelationContract(BaseModel):
    """Relation contract for biomedical predicates."""

    predicate: str
    domain: list[str]
    range: list[str]
    inverse: str | None = None
    symmetry: bool = False
    transitivity: bool = False
    evidence_policy: str | None = None
    temporal_behavior: str | None = None
    projection_behavior: str | None = None
    is_derived: bool = False


RELATION_CONTRACTS: dict[str, BiomedicalRelationContract] = {
    "encodes": BiomedicalRelationContract(
        predicate="encodes",
        domain=["Gene"],
        range=["Protein"],
        inverse="encoded_by",
        symmetry=False,
        transitivity=False,
        evidence_policy="expert_curated",
        temporal_behavior="static",
        projection_behavior="direct_edge",
    ),
    "participates_in": BiomedicalRelationContract(
        predicate="participates_in",
        domain=["Protein", "Gene"],
        range=["Pathway"],
        inverse="has_participant",
        symmetry=False,
        transitivity=False,
        evidence_policy="experimental",
        temporal_behavior="contextual",
        projection_behavior="direct_edge",
    ),
    "targets": BiomedicalRelationContract(
        predicate="targets",
        domain=["Drug", "ChemicalEntity"],
        range=["Protein"],
        inverse="targeted_by",
        symmetry=False,
        transitivity=False,
        evidence_policy="experimental",
        temporal_behavior="static",
        projection_behavior="direct_edge",
    ),
    "treats": BiomedicalRelationContract(
        predicate="treats",
        domain=["Drug"],
        range=["Disease"],
        inverse="treated_by",
        symmetry=False,
        transitivity=False,
        evidence_policy="clinical_trial",
        temporal_behavior="static",
        projection_behavior="direct_edge",
    ),
    "treated_by": BiomedicalRelationContract(
        predicate="treated_by",
        domain=["Disease"],
        range=["Drug"],
        inverse="treats",
        symmetry=False,
        transitivity=False,
        evidence_policy="clinical_trial",
        temporal_behavior="static",
        projection_behavior="derived_inverse",
        is_derived=True,
    ),
    "associated_with": BiomedicalRelationContract(
        predicate="associated_with",
        domain=["Gene", "Protein", "Disease"],
        range=["Gene", "Protein", "Disease"],
        inverse="associated_with",
        symmetry=True,
        transitivity=False,
        evidence_policy="observational",
        temporal_behavior="static",
        projection_behavior="bidirectional_edge",
    ),
    "orthologous_to": BiomedicalRelationContract(
        predicate="orthologous_to",
        domain=["Gene", "Protein"],
        range=["Gene", "Protein"],
        inverse="orthologous_to",
        symmetry=True,
        transitivity=True,
        evidence_policy="computational",
        temporal_behavior="static",
        projection_behavior="bidirectional_edge",
    ),
    "isoform_of": BiomedicalRelationContract(
        predicate="isoform_of",
        domain=["Protein"],
        range=["Gene", "Protein"],
        inverse="has_isoform",
        symmetry=False,
        transitivity=False,
        evidence_policy="expert_curated",
        temporal_behavior="static",
        projection_behavior="direct_edge",
    ),
    "salt_of": BiomedicalRelationContract(
        predicate="salt_of",
        domain=["ChemicalEntity", "Drug"],
        range=["ActiveMoiety", "ChemicalEntity"],
        inverse="has_salt",
        symmetry=False,
        transitivity=False,
        evidence_policy="expert_curated",
        temporal_behavior="static",
        projection_behavior="direct_edge",
    ),
    "has_active_moiety": BiomedicalRelationContract(
        predicate="has_active_moiety",
        domain=["Drug", "ChemicalEntity"],
        range=["ActiveMoiety"],
        inverse="active_moiety_of",
        symmetry=False,
        transitivity=False,
        evidence_policy="expert_curated",
        temporal_behavior="static",
        projection_behavior="direct_edge",
    ),
}


class BiomedicalRelation(Relation):
    """Generic relation instance for biomedical predicates."""

    pass


def derive_inverse_relation(relation: Relation) -> Relation | None:
    """Derive inverse relation (e.g. treated_by from treats) dynamically."""
    contract = RELATION_CONTRACTS.get(relation.predicate)
    if not contract or not contract.inverse:
        return None

    # Do not re-derive if already derived
    if contract.is_derived:
        return None

    return Relation(
        id=relation.id,
        subject=relation.object,
        predicate=contract.inverse,
        object=relation.subject,
        context=relation.context,
    )
