from __future__ import annotations

import pytest
from contracts_py.models import (
    ApplicationWindowContract,
    BenefitContract,
    DocumentExtractionContract,
    DocumentStatus,
    EligibilityRuleContract,
    ExecutionStatus,
    ExtractMethod,
    IngestionRunContract,
    PolicyVersionContract,
    RegionContract,
    RegionLevel,
    SourceContract,
    TargetType,
)
from pydantic import ValidationError


def test_source_contract() -> None:
    s = SourceContract(source_key="youth", name="Youth", url="https://example.com")
    assert s.source_key == "youth"
    assert s.config == {}


def test_ingestion_run_contract_defaults() -> None:
    r = IngestionRunContract(source_id=1, status=ExecutionStatus.PENDING)
    assert r.total_items is None
    assert r.started_at is None


def test_policy_version_contract() -> None:
    pv = PolicyVersionContract(
        program_id=1,
        version_number=1,
        title="Test",
        content_sha256="abc123",
        target_type=TargetType.INDIVIDUAL,
        announcement_url="https://example.com",
    )
    assert pv.is_valid is True


def test_document_extraction_contract() -> None:
    de = DocumentExtractionContract(
        attachment_id=1,
        file_sha256="abc123",
        parser_name="kordoc",
        parser_version="4.6.0",
        options_hash="opt-hash",
        status=DocumentStatus.PARSED,
    )
    assert de.error_code is None


def test_eligibility_rule_confidence_range() -> None:
    rule = EligibilityRuleContract(
        policy_version_id=1,
        field_name="age",
        operator=">=",
        value="19",
        extract_method=ExtractMethod.RULE_BASED,
        confidence=0.95,
    )
    assert rule.confidence == 0.95

    with pytest.raises(ValidationError):
        EligibilityRuleContract(
            policy_version_id=1,
            field_name="age",
            operator=">=",
            value="19",
            extract_method=ExtractMethod.RULE_BASED,
            confidence=1.5,
        )


def test_region_contract() -> None:
    r = RegionContract(name="Seoul", level=RegionLevel.METROPOLITAN)
    assert r.code is None
    assert r.parent_id is None


def test_benefit_contract() -> None:
    b = BenefitContract(policy_version_id=1, amount=50000, unit="KRW/month")
    assert b.amount == 50000


def test_application_window_contract() -> None:
    aw = ApplicationWindowContract(policy_version_id=1, is_always_open=True)
    assert aw.is_always_open is True
    assert aw.start_date is None
