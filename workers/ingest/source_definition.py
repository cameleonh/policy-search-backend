"""Source registry definitions.

A SourceDefinition describes everything the ingestion orchestrator needs
to know about a source before any network request is made — its identity,
access policy, credential requirements, and allowed hosts.

This is the static metadata that lives in the `sources` table.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class SourceCategory(StrEnum):
    """Which audience a source primarily serves."""

    YOUTH = "youth"
    BUSINESS = "business"
    BOTH = "both"


class ExecutionMode(StrEnum):
    """How a source is collected."""

    API = "api"
    WEB_SCRAPING = "web_scraping"
    RSS = "rss"


class CredentialRequirement(StrEnum):
    """Whether a source needs credentials and what kind."""

    NONE = "none"
    API_KEY = "api_key"
    LOGIN = "login"


class RobotsStatus(StrEnum):
    """robots.txt / ToS collection permission status."""

    ALLOWED = "allowed"
    DISALLOWED = "disallowed"
    UNKNOWN = "unknown"


class SourceDefinition(BaseModel):
    """Static definition of an ingestion source."""

    source_key: str = Field(description="Stable identifier, e.g. 'youthcenter', 'sbiz24'")
    display_name: str = Field(description="Human-readable name")
    base_url: str = Field(description="Root URL of the source")
    category: SourceCategory = Field(description="Primary audience: youth, business, or both")
    execution_mode: ExecutionMode = Field(
        description="How records are collected: api, web_scraping, rss"
    )
    credential_requirement: CredentialRequirement = Field(
        default=CredentialRequirement.NONE,
        description="Whether credentials are needed",
    )
    robots_status: RobotsStatus = Field(
        default=RobotsStatus.UNKNOWN,
        description="robots.txt / ToS permission to collect",
    )
    allowed_hosts: list[str] = Field(
        default_factory=list,
        description="Hosts the adapter is permitted to request",
    )
    request_delay_seconds: float = Field(
        default=0.5,
        description="Minimum delay between requests to this source",
    )
    region_applicable: bool = Field(
        default=True,
        description="Whether source data has region scoping",
    )
    config: dict[str, Any] = Field(
        default_factory=dict,
        description="Source-specific configuration (e.g. API endpoints)",
    )


# ── Registry of known sources from youth-search and sole-search ──

KNOWN_SOURCES: dict[str, SourceDefinition] = {
    # ── youth-search sources ──
    "youthcenter": SourceDefinition(
        source_key="youthcenter",
        display_name="온통청년",
        base_url="https://www.youthcenter.go.kr",
        category=SourceCategory.YOUTH,
        execution_mode=ExecutionMode.API,
        credential_requirement=CredentialRequirement.NONE,
        robots_status=RobotsStatus.ALLOWED,
        allowed_hosts=["www.youthcenter.go.kr", "youthcenter.go.kr"],
        request_delay_seconds=0.4,
    ),
    "bokjiro": SourceDefinition(
        source_key="bokjiro",
        display_name="복지로",
        base_url="https://www.bokjiro.go.kr",
        category=SourceCategory.BOTH,
        execution_mode=ExecutionMode.WEB_SCRAPING,
        credential_requirement=CredentialRequirement.NONE,
        robots_status=RobotsStatus.ALLOWED,
        allowed_hosts=["www.bokjiro.go.kr", "bokjiro.go.kr"],
    ),
    "work24": SourceDefinition(
        source_key="work24",
        display_name="워크넷24",
        base_url="https://www.work24.go.kr",
        category=SourceCategory.YOUTH,
        execution_mode=ExecutionMode.WEB_SCRAPING,
        credential_requirement=CredentialRequirement.NONE,
        robots_status=RobotsStatus.ALLOWED,
        allowed_hosts=["www.work24.go.kr", "work24.go.kr"],
    ),
    "myhome": SourceDefinition(
        source_key="myhome",
        display_name="마이홈",
        base_url="https://www.applyhome.co.kr",
        category=SourceCategory.YOUTH,
        execution_mode=ExecutionMode.WEB_SCRAPING,
        credential_requirement=CredentialRequirement.NONE,
        robots_status=RobotsStatus.ALLOWED,
        allowed_hosts=["www.applyhome.co.kr", "applyhome.co.kr"],
    ),
    "yw": SourceDefinition(
        source_key="yw",
        display_name="청년일경험",
        base_url="https://www.youthwork.go.kr",
        category=SourceCategory.YOUTH,
        execution_mode=ExecutionMode.WEB_SCRAPING,
        credential_requirement=CredentialRequirement.NONE,
        robots_status=RobotsStatus.ALLOWED,
        allowed_hosts=["www.youthwork.go.kr", "youthwork.go.kr"],
    ),
    # ── sole-search sources ──
    "sbiz24": SourceDefinition(
        source_key="sbiz24",
        display_name="소상공인24",
        base_url="https://www.sbiz24.kr",
        category=SourceCategory.BUSINESS,
        execution_mode=ExecutionMode.API,
        credential_requirement=CredentialRequirement.NONE,
        robots_status=RobotsStatus.ALLOWED,
        allowed_hosts=["www.sbiz24.kr", "sbiz24.kr"],
    ),
    "sbiz24_combine": SourceDefinition(
        source_key="sbiz24_combine",
        display_name="소상공인24 통합조회",
        base_url="https://www.sbiz24.kr",
        category=SourceCategory.BUSINESS,
        execution_mode=ExecutionMode.API,
        credential_requirement=CredentialRequirement.NONE,
        robots_status=RobotsStatus.ALLOWED,
        allowed_hosts=["www.sbiz24.kr", "sbiz24.kr"],
    ),
    "bizinfo": SourceDefinition(
        source_key="bizinfo",
        display_name="기업마당",
        base_url="https://www.bizinfo.go.kr",
        category=SourceCategory.BUSINESS,
        execution_mode=ExecutionMode.WEB_SCRAPING,
        credential_requirement=CredentialRequirement.NONE,
        robots_status=RobotsStatus.ALLOWED,
        allowed_hosts=["www.bizinfo.go.kr", "bizinfo.go.kr"],
    ),
    "gov24": SourceDefinition(
        source_key="gov24",
        display_name="정부24",
        base_url="https://www.gov.kr",
        category=SourceCategory.BOTH,
        execution_mode=ExecutionMode.WEB_SCRAPING,
        credential_requirement=CredentialRequirement.NONE,
        robots_status=RobotsStatus.ALLOWED,
        allowed_hosts=["www.gov.kr", "gov.kr"],
    ),
}
