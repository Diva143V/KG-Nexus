"""Tests for Biomedical Validation Rules BIO-TYPE-001 through BIO-ID-001 (Phase 21)."""

import pytest

from core.identifiers.identifier import Identifier
from core.validation.context import ValidationContext
from core.validation.result import ValidationSeverity, ValidationStatus
from plugins.biomedical.validators import (
    BioDrugValidator,
    BioEvidenceValidator,
    BioGranularityValidator,
    BioIdentifierValidator,
    BioIsoformValidator,
    BioTaxonValidator,
    BioTypeValidator,
)


@pytest.fixture
def act_id() -> Identifier:
    return Identifier(namespace="SYS", value="ACT_VAL_1")


def test_bio_type_001_failure_and_success(act_id: Identifier):
    validator = BioTypeValidator()
    ctx_fail = ValidationContext(
        target="Gene_vs_Protein",
        data={"source_type": "Gene", "candidate_type": "Protein"},
    )
    res_fail = validator.validate(context=ctx_fail, activity_id=act_id)[0]
    assert res_fail.status == ValidationStatus.FAIL
    assert res_fail.code == "BIO-TYPE-001"
    assert res_fail.severity == ValidationSeverity.BLOCKER

    ctx_pass = ValidationContext(
        target="Gene_vs_Gene",
        data={"source_type": "Gene", "candidate_type": "Gene"},
    )
    res_pass = validator.validate(context=ctx_pass, activity_id=act_id)[0]
    assert res_pass.status == ValidationStatus.PASS


def test_bio_taxon_001_cross_species_failure(act_id: Identifier):
    validator = BioTaxonValidator()
    ctx = ValidationContext(
        target="Human_vs_Mouse",
        data={"source_tax_id": "9606", "candidate_tax_id": "10090", "predicate": "treats"},
    )
    res = validator.validate(context=ctx, activity_id=act_id)[0]
    assert res.status == ValidationStatus.FAIL
    assert res.code == "BIO-TAXON-001"


def test_bio_drug_001_salt_moiety_distinct(act_id: Identifier):
    validator = BioDrugValidator()
    ctx = ValidationContext(
        target="Salt_Moiety_Merge",
        data={"is_salt": True, "is_active_moiety": True, "action": "merge"},
    )
    res = validator.validate(context=ctx, activity_id=act_id)[0]
    assert res.status == ValidationStatus.FAIL
    assert res.code == "BIO-DRUG-001"


def test_bio_isoform_001_distinct_from_locus(act_id: Identifier):
    validator = BioIsoformValidator()
    ctx = ValidationContext(
        target="Isoform_Locus",
        data={"is_isoform": True, "is_gene_locus": True},
    )
    res = validator.validate(context=ctx, activity_id=act_id)[0]
    assert res.status == ValidationStatus.FAIL
    assert res.code == "BIO-ISOFORM-001"


def test_bio_granularity_001_mismatch(act_id: Identifier):
    validator = BioGranularityValidator()
    ctx = ValidationContext(
        target="Granularity",
        data={"source_granularity": "DrugClass", "candidate_granularity": "Formulation"},
    )
    res = validator.validate(context=ctx, activity_id=act_id)[0]
    assert res.status == ValidationStatus.FAIL
    assert res.code == "BIO-GRANULARITY-001"


def test_bio_evidence_001_missing_evidence(act_id: Identifier):
    validator = BioEvidenceValidator()
    ctx = ValidationContext(
        target="EvidenceCheck",
        data={"has_required_evidence": False},
    )
    res = validator.validate(context=ctx, activity_id=act_id)[0]
    assert res.status == ValidationStatus.FAIL
    assert res.code == "BIO-EVIDENCE-001"


def test_bio_id_001_deprecated_identifier(act_id: Identifier):
    validator = BioIdentifierValidator()
    ctx = ValidationContext(
        target="DeprecatedID",
        data={"is_deprecated": True, "has_replacement": False},
    )
    res = validator.validate(context=ctx, activity_id=act_id)[0]
    assert res.status == ValidationStatus.FAIL
    assert res.code == "BIO-ID-001"
