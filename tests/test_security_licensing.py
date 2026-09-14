"""Tests for Platform Security and Licensing Enforcement (Phase 27)."""

from core.identifiers.identifier import Identifier
from core.resources.source_release import SourceRelease
from infrastructure.security.audit import PHISafeAuditLogger
from infrastructure.security.licensing import (
    LicenseEnforcementGate,
    SourceLicensePolicy,
)


def test_license_enforcement_blocks_non_redistributable_source():
    policy = SourceLicensePolicy(
        source_id="restricted_db",
        license_name="Proprietary-NC",
        redistribution_permitted=False,
    )
    gate = LicenseEnforcementGate(policies=[policy])
    release = SourceRelease(
        id=Identifier(namespace="SYS", value="rel_1"),
        source_id=Identifier(namespace="SYS", value="restricted_db"),
        version="1.0.0",
    )

    allowed, msg = gate.evaluate_release(release)
    assert allowed is False
    assert "BLOCKED" in msg


def test_license_enforcement_allows_compliant_source():
    policy = SourceLicensePolicy(
        source_id="open_db",
        license_name="CC-BY-4.0",
        redistribution_permitted=True,
    )
    gate = LicenseEnforcementGate(policies=[policy])
    release = SourceRelease(
        id=Identifier(namespace="SYS", value="rel_2"),
        source_id=Identifier(namespace="SYS", value="open_db"),
        version="1.0.0",
    )

    allowed, msg = gate.evaluate_release(release)
    assert allowed is True
    assert "PASSED" in msg


def test_phi_safe_audit_logger_masks_raw_secrets_and_prompts():
    logger = PHISafeAuditLogger()
    secret_text = "Connecting with api_key: 'super_secret_token_123' to db."
    log_rec = logger.log_event("AUTH", secret_text)

    assert "super_secret_token_123" not in log_rec.message
    assert "[REDACTED_SECRET]" in log_rec.message

    long_prompt_text = "PROMPT: " + ("Analyze biological entities " * 20)
    log_rec2 = logger.log_event("LLM_PROMPT", long_prompt_text)
    assert "[REDACTED_PROMPT_CONTEXT]" in log_rec2.message
