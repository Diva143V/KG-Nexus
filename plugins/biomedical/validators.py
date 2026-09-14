"""Biomedical Validators enforcing specification rules BIO-TYPE-001 through BIO-ID-001."""

from __future__ import annotations

from core.identifiers.identifier import Identifier
from core.validation.context import ValidationContext
from core.validation.result import ValidationResult, ValidationSeverity, ValidationStatus
from sdk.validation import ApplicationValidator, EvidenceValidator


class BioTypeValidator(ApplicationValidator):
    """BIO-TYPE-001: Gene and Protein cannot be automatically merged."""

    @property
    def name(self) -> str:
        return "BIO-TYPE-001"

    @property
    def version(self) -> str:
        return "1.0.0"

    def validate(
        self,
        *,
        context: ValidationContext,
        activity_id: Identifier,
    ) -> tuple[ValidationResult, ...]:
        target_data = context.data
        src_type = target_data.get("source_type")
        cand_type = target_data.get("candidate_type")

        val_id = Identifier(namespace="VAL", value=f"{self.name}_1")
        if (src_type == "Gene" and cand_type == "Protein") or (
            src_type == "Protein" and cand_type == "Gene"
        ):
            res = ValidationResult(
                validation_id=val_id,
                validator=self.name,
                validator_version=self.version,
                target=context.target,
                severity=ValidationSeverity.BLOCKER,
                code="BIO-TYPE-001",
                message="Gene and Protein entities cannot be automatically merged.",
                status=ValidationStatus.FAIL,
                activity_id=activity_id,
            )
        else:
            res = ValidationResult(
                validation_id=val_id,
                validator=self.name,
                validator_version=self.version,
                target=context.target,
                severity=ValidationSeverity.INFO,
                code="BIO-TYPE-001",
                message="Entity types compatible.",
                status=ValidationStatus.PASS,
                activity_id=activity_id,
            )
        return (res,)


class BioTaxonValidator(ApplicationValidator):
    """BIO-TAXON-001: Cross-species assertions require explicit taxonomic semantics."""

    @property
    def name(self) -> str:
        return "BIO-TAXON-001"

    @property
    def version(self) -> str:
        return "1.0.0"

    def validate(
        self,
        *,
        context: ValidationContext,
        activity_id: Identifier,
    ) -> tuple[ValidationResult, ...]:
        target_data = context.data
        src_tax = target_data.get("source_tax_id")
        cand_tax = target_data.get("candidate_tax_id")
        predicate = target_data.get("predicate")

        val_id = Identifier(namespace="VAL", value=f"{self.name}_1")
        if src_tax and cand_tax and src_tax != cand_tax and predicate != "orthologous_to":
            res = ValidationResult(
                validation_id=val_id,
                validator=self.name,
                validator_version=self.version,
                target=context.target,
                severity=ValidationSeverity.ERROR,
                code="BIO-TAXON-001",
                message="Cross-species assertion missing explicit orthologous_to semantics.",
                status=ValidationStatus.FAIL,
                activity_id=activity_id,
            )
        else:
            res = ValidationResult(
                validation_id=val_id,
                validator=self.name,
                validator_version=self.version,
                target=context.target,
                severity=ValidationSeverity.INFO,
                code="BIO-TAXON-001",
                message="Taxonomic compatibility valid.",
                status=ValidationStatus.PASS,
                activity_id=activity_id,
            )
        return (res,)


class BioDrugValidator(ApplicationValidator):
    """BIO-DRUG-001: Salt and active moiety remain distinct."""

    @property
    def name(self) -> str:
        return "BIO-DRUG-001"

    @property
    def version(self) -> str:
        return "1.0.0"

    def validate(
        self,
        *,
        context: ValidationContext,
        activity_id: Identifier,
    ) -> tuple[ValidationResult, ...]:
        target_data = context.data
        is_salt = target_data.get("is_salt", False)
        is_moiety = target_data.get("is_active_moiety", False)
        action = target_data.get("action")

        val_id = Identifier(namespace="VAL", value=f"{self.name}_1")
        if is_salt and is_moiety and action == "merge":
            res = ValidationResult(
                validation_id=val_id,
                validator=self.name,
                validator_version=self.version,
                target=context.target,
                severity=ValidationSeverity.BLOCKER,
                code="BIO-DRUG-001",
                message="Salt and active moiety cannot be merged.",
                status=ValidationStatus.FAIL,
                activity_id=activity_id,
            )
        else:
            res = ValidationResult(
                validation_id=val_id,
                validator=self.name,
                validator_version=self.version,
                target=context.target,
                severity=ValidationSeverity.INFO,
                code="BIO-DRUG-001",
                message="Salt and active moiety distinction preserved.",
                status=ValidationStatus.PASS,
                activity_id=activity_id,
            )
        return (res,)


class BioIsoformValidator(ApplicationValidator):
    """BIO-ISOFORM-001: Protein isoforms remain distinct from gene loci."""

    @property
    def name(self) -> str:
        return "BIO-ISOFORM-001"

    @property
    def version(self) -> str:
        return "1.0.0"

    def validate(
        self,
        *,
        context: ValidationContext,
        activity_id: Identifier,
    ) -> tuple[ValidationResult, ...]:
        target_data = context.data
        is_isoform = target_data.get("is_isoform", False)
        is_gene_locus = target_data.get("is_gene_locus", False)

        val_id = Identifier(namespace="VAL", value=f"{self.name}_1")
        if is_isoform and is_gene_locus:
            res = ValidationResult(
                validation_id=val_id,
                validator=self.name,
                validator_version=self.version,
                target=context.target,
                severity=ValidationSeverity.ERROR,
                code="BIO-ISOFORM-001",
                message="Protein isoform cannot be equated directly with gene locus.",
                status=ValidationStatus.FAIL,
                activity_id=activity_id,
            )
        else:
            res = ValidationResult(
                validation_id=val_id,
                validator=self.name,
                validator_version=self.version,
                target=context.target,
                severity=ValidationSeverity.INFO,
                code="BIO-ISOFORM-001",
                message="Isoform vs gene locus distinction valid.",
                status=ValidationStatus.PASS,
                activity_id=activity_id,
            )
        return (res,)


class BioGranularityValidator(ApplicationValidator):
    """BIO-GRANULARITY-001: Drug classes and clinical formulations cannot be silently merged."""

    @property
    def name(self) -> str:
        return "BIO-GRANULARITY-001"

    @property
    def version(self) -> str:
        return "1.0.0"

    def validate(
        self,
        *,
        context: ValidationContext,
        activity_id: Identifier,
    ) -> tuple[ValidationResult, ...]:
        target_data = context.data
        src_granularity = target_data.get("source_granularity")
        cand_granularity = target_data.get("candidate_granularity")

        val_id = Identifier(namespace="VAL", value=f"{self.name}_1")
        if src_granularity and cand_granularity and src_granularity != cand_granularity:
            res = ValidationResult(
                validation_id=val_id,
                validator=self.name,
                validator_version=self.version,
                target=context.target,
                severity=ValidationSeverity.BLOCKER,
                code="BIO-GRANULARITY-001",
                message=f"Granularity mismatch ({src_granularity} vs {cand_granularity}) prevents merging.",
                status=ValidationStatus.FAIL,
                activity_id=activity_id,
            )
        else:
            res = ValidationResult(
                validation_id=val_id,
                validator=self.name,
                validator_version=self.version,
                target=context.target,
                severity=ValidationSeverity.INFO,
                code="BIO-GRANULARITY-001",
                message="Granularity levels match.",
                status=ValidationStatus.PASS,
                activity_id=activity_id,
            )
        return (res,)


class BioEvidenceValidator(EvidenceValidator):
    """BIO-EVIDENCE-001: Required evidence must exist before promotion."""

    @property
    def name(self) -> str:
        return "BIO-EVIDENCE-001"

    @property
    def version(self) -> str:
        return "1.0.0"

    def validate(
        self,
        *,
        context: ValidationContext,
        activity_id: Identifier,
    ) -> tuple[ValidationResult, ...]:
        target_data = context.data
        has_evidence = target_data.get("has_required_evidence", False)

        val_id = Identifier(namespace="VAL", value=f"{self.name}_1")
        if not has_evidence:
            res = ValidationResult(
                validation_id=val_id,
                validator=self.name,
                validator_version=self.version,
                target=context.target,
                severity=ValidationSeverity.BLOCKER,
                code="BIO-EVIDENCE-001",
                message="Required evidence missing for promotion.",
                status=ValidationStatus.FAIL,
                activity_id=activity_id,
            )
        else:
            res = ValidationResult(
                validation_id=val_id,
                validator=self.name,
                validator_version=self.version,
                target=context.target,
                severity=ValidationSeverity.INFO,
                code="BIO-EVIDENCE-001",
                message="Evidence sufficiency validated.",
                status=ValidationStatus.PASS,
                activity_id=activity_id,
            )
        return (res,)


class BioIdentifierValidator(ApplicationValidator):
    """BIO-ID-001: Deprecated identifiers require replacement validation."""

    @property
    def name(self) -> str:
        return "BIO-ID-001"

    @property
    def version(self) -> str:
        return "1.0.0"

    def validate(
        self,
        *,
        context: ValidationContext,
        activity_id: Identifier,
    ) -> tuple[ValidationResult, ...]:
        target_data = context.data
        is_deprecated = target_data.get("is_deprecated", False)
        has_replacement = target_data.get("has_replacement", False)

        val_id = Identifier(namespace="VAL", value=f"{self.name}_1")
        if is_deprecated and not has_replacement:
            res = ValidationResult(
                validation_id=val_id,
                validator=self.name,
                validator_version=self.version,
                target=context.target,
                severity=ValidationSeverity.ERROR,
                code="BIO-ID-001",
                message="Deprecated identifier used without valid replacement.",
                status=ValidationStatus.FAIL,
                activity_id=activity_id,
            )
        else:
            res = ValidationResult(
                validation_id=val_id,
                validator=self.name,
                validator_version=self.version,
                target=context.target,
                severity=ValidationSeverity.INFO,
                code="BIO-ID-001",
                message="Identifier status valid.",
                status=ValidationStatus.PASS,
                activity_id=activity_id,
            )
        return (res,)
