from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


Country = Literal["KR", "JP", "US", "EU", "UK"]
Level = Literal["national", "supranational", "state", "local"]

# Stage 1 참고 분류:
#   "direct"   — 법체계·문화·언어 근접으로 조문 차용·번안이 현실적인 그룹 (KR 타지자체 + JP).
#   "indirect" — 정책 시각·구조만 참고 가능, 직접 이식은 어려운 그룹 (UK/EU/US).
# 보고서에서 그룹별 깊이(원문 포함 여부)와 배치 순서가 달라진다.
ReferenceTier = Literal["direct", "indirect"]


class RawHit(BaseModel):
    """Raw search result returned by an adapter, before LLM processing."""

    source_id: str
    country: Country
    level: Level
    jurisdiction: str = ""
    title: str
    enacted_year: int | None = None
    url: str = ""
    snippet: str = ""
    raw_text: str = ""
    fetched_at: datetime = Field(default_factory=datetime.now)


class PolicyCard(BaseModel):
    """LLM-summarized policy card shown to the user in Stage 1.

    tier 필드로 직접 참고(direct) / 간접 참고(indirect)를 구분한다 — 한국 입법 실무상
    국내 타지자체·일본 조례는 조문 차용이 현실적이라 raw_excerpt에 원문 발췌까지 함께
    실어 보낸다. 영미권은 정책 시각만 참고하므로 raw_excerpt는 비어 있다.
    """

    source_id: str
    country: Country
    jurisdiction: str
    title: str
    title_translated: str = ""
    enacted_year: int | None = None
    summary: str
    key_points: list[str] = Field(default_factory=list)
    relevance_note: str = ""
    url: str
    raw_hit_id: str = ""
    tier: ReferenceTier = "indirect"
    raw_excerpt: str = ""


class ComparisonRow(BaseModel):
    """One row of a Stage 2 article-by-article comparison table."""

    article_label: str
    draft_text: str
    reference_text: str
    common_points: list[str] = Field(default_factory=list)
    differences: list[str] = Field(default_factory=list)
    note: str = ""


class ConflictCandidate(BaseModel):
    """Stage 2-a: a candidate higher-law conflict (NOT an automated determination)."""

    draft_article: str
    suspected_higher_law: str
    suspected_higher_article: str = ""
    concern: str
    evidence_quote: str
    confidence: Literal["low", "medium", "high"]
    additional_review_needed: list[str] = Field(default_factory=list)


class DraftOrdinance(BaseModel):
    """Stage 3 output: a generated ordinance draft."""

    mode: Literal["new", "amendment"]
    title: str
    proposal_reason: str
    main_contents: list[str]
    articles: list[dict]
    addendum: str
    delegation_law: str = ""
    docx_path: str = ""


class AmendmentDiff(BaseModel):
    """One row of the 신·구조문대비표 table."""

    article_label: str
    current_text: str
    revised_text: str
    change_type: Literal["new", "modified", "deleted"]
    note: str = ""


class ReviewSummary(BaseModel):
    """Stage 2: 검토보고서 스타일의 통합 요약.

    실제 경기도의회 검토보고서의 'Ⅰ. 제안이유 / Ⅱ. 주요내용 / Ⅲ. 검토의견'
    구조를 모방한다. conflict/comparison 같은 세부 결과 위에 얹는 요약 층.
    """

    purpose_summary: str = ""
    main_contents: list[str] = Field(default_factory=list)
    legislative_purpose: str = ""
    procedural_notes: str = ""
    overall_recommendation: Literal["타당함", "조건부 타당", "재검토 필요", ""] = ""


class StageReport(BaseModel):
    """Top-level report returned by a pipeline stage."""

    stage: Literal["1", "2", "3"]
    summary: str
    cards: list[PolicyCard] = Field(default_factory=list)
    comparisons: list[ComparisonRow] = Field(default_factory=list)
    conflicts: list[ConflictCandidate] = Field(default_factory=list)
    diffs: list[AmendmentDiff] = Field(default_factory=list)
    review_summary: ReviewSummary | None = None
    draft: DraftOrdinance | None = None
    errors: list[str] = Field(default_factory=list)
    disclaimer: str = ""
