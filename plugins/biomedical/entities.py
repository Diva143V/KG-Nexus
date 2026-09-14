"""Biomedical Domain Entities."""

from __future__ import annotations

from core.entities.entity import Entity, EntityKind


class Gene(Entity):
    """Biomedical Gene entity."""

    kind: EntityKind = EntityKind.CONCEPT
    symbol: str | None = None
    tax_id: str | None = None


class Protein(Entity):
    """Biomedical Protein entity."""

    kind: EntityKind = EntityKind.CONCEPT
    uniprot_id: str | None = None
    sequence: str | None = None
    tax_id: str | None = None


class ChemicalEntity(Entity):
    """Biomedical ChemicalEntity."""

    kind: EntityKind = EntityKind.OBJECT
    chebi_id: str | None = None
    smiles: str | None = None


class Drug(Entity):
    """Biomedical Drug entity."""

    kind: EntityKind = EntityKind.OBJECT
    chembl_id: str | None = None
    inn: str | None = None


class DrugProduct(Entity):
    """Biomedical DrugProduct formulation."""

    kind: EntityKind = EntityKind.OBJECT
    ndc: str | None = None
    formulation: str | None = None


class ActiveMoiety(Entity):
    """Biomedical ActiveMoiety entity."""

    kind: EntityKind = EntityKind.OBJECT
    chebi_id: str | None = None


class Disease(Entity):
    """Biomedical Disease entity."""

    kind: EntityKind = EntityKind.CONCEPT
    mondo_id: str | None = None


class Pathway(Entity):
    """Biomedical Pathway entity."""

    kind: EntityKind = EntityKind.PROCESS
    reactome_id: str | None = None
