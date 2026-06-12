"""MCP server entry point.

Exposes legislative-research tools to Claude Desktop via stdio transport.

Tools currently exposed:
  - screen_overseas_examples_tool — Stage 1 full pipeline (해외 4개국 스크리닝).
                                    Requires ANTHROPIC_API_KEY for keyword
                                    extraction + LLM card summarization.
  - search_domestic_ordinances    — Stage 2 Track B 후보 검색 (kr_local 직접 호출).
                                    LLM 불필요, OC 키만 있으면 작동.
  - search_higher_korean_laws     — Stage 2 Track A 후보 검색 (kr_law 직접 호출).
                                    LLM 불필요.

The 'overseas' tool depends on the LLM; the two 'search_*' tools are
adapter-only thin wrappers and stay usable even when LLM access is offline.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

import os
from datetime import datetime
from pathlib import Path

from core.adapters.kr_law import KrLawAdapter
from core.adapters.kr_local import KrLocalAdapter
from core.config import DATA_DIR
from core.pipeline.stage1_screening import screen_overseas_examples
from core.pipeline.stage3_drafting import draft_amend, draft_new
from core.templates.report_stage1 import render_stage1_docx, render_stage1_markdown

# 검토 트랙(비공개)은 ENABLE_REVIEW_TOOLS=1 일 때만 노출.
# 공개 빌드(성안만)에서는 core/review_only/ 폴더와 그 모듈들이 함께 빠지므로
# import 자체가 조건부여야 한다.
_REVIEW_ENABLED = os.environ.get("ENABLE_REVIEW_TOOLS", "").lower() in ("1", "true", "yes")
if _REVIEW_ENABLED:
    from core.review_only.pipeline.review_track import (
        ReviewMeta,
        review_from_hwpx,
        run_review_pipeline,
    )
    from core.review_only.pipeline.stage2_review import review_draft  # 옛 도구 호환
    from core.review_only.templates.render_review_report import render_review_report


mcp = FastMCP("gg-council-legislation")


@mcp.tool()
async def screen_overseas_examples_tool(
    policy_idea: str,
    countries: list[str] | None = None,
    topk_per_country: int = 3,
    output_dir: str = "",
) -> dict:
    """Stage 1: 정책 아이디어로 참고 입법례를 2-Tier 구조로 스크리닝합니다.

    한국 지방의회 입법 실무 관점에서 참고 입법례는 두 그룹으로 다룹니다:

      • Tier A — 직접 참고 (원문 포함):
          - 한국 자치법규(KR · kr_local) — *경기도 기존 조례 우선 표시*
          - 일본 법령(JP · e-Gov)
      • Tier B — 간접 참고 (요약만):
          - 영국(UK) · EU · 미국(US)

    경기도 기존 조례가 검색되면 보고서가 *개정* 검토를 유도하고,
    없으면 *신규 제정*을 유도합니다.

    Args:
        policy_idea: 한국어 정책 아이디어 (자연어 1~3 문장).
        countries: 검색할 관할 ISO 코드 리스트. 기본값은 ["KR", "JP", "UK", "EU", "US"].
        topk_per_country: 관할별 최대 결과 개수.
        output_dir: 비워두면 파일 저장 없이 마크다운만 반환. 값이 있으면 해당 폴더에
                    {타임스탬프}_stage1_report.md / .docx 두 파일을 저장하고 경로를 반환.
                    'default' 지정 시 프로젝트의 data/outputs/.

    Returns:
        StageReport dict + 다음 키:
          - 'report_markdown': 사용자에게 곧바로 보여줄 마크다운 보고서.
          - 'markdown_path', 'docx_path': output_dir 지정 시에만 채워진다.
    """
    report = await screen_overseas_examples(
        policy_idea=policy_idea,
        countries=countries,
        topk_per_country=topk_per_country,
    )
    md = render_stage1_markdown(report, policy_idea=policy_idea)
    result = report.model_dump(mode="json")
    result["report_markdown"] = md

    if output_dir:
        out_dir = DATA_DIR / "outputs" if output_dir == "default" else Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        md_path = out_dir / f"{stamp}_stage1_report.md"
        docx_path = out_dir / f"{stamp}_stage1_report.docx"
        md_path.write_text(md, encoding="utf-8")
        render_stage1_docx(report, docx_path, policy_idea=policy_idea)
        result["markdown_path"] = str(md_path)
        result["docx_path"] = str(docx_path)

    return result


@mcp.tool()
async def search_domestic_ordinances(topic: str, topk: int = 5) -> dict:
    """국내 타지자체 자치법규(조례·규칙)를 검색합니다.

    국가법령정보센터 OPEN API를 통해 검색합니다. Stage 2 Track B에서
    초안과 비교할 다른 지자체 조례를 찾을 때 유용합니다.

    Args:
        topic: 검색 키워드 (예: "청년 1인가구", "사회적 고립").
        topk: 최대 결과 개수.

    Returns:
        {source, topic, count, hits} 형식의 dict. hits는 RawHit 목록.
    """
    async with KrLocalAdapter() as adapter:
        hits = await adapter.search([topic], topk=topk)
    return {
        "source": "kr_local",
        "topic": topic,
        "count": len(hits),
        "hits": [h.model_dump(mode="json") for h in hits],
    }


@mcp.tool()
async def search_higher_korean_laws(topic: str, topk: int = 5) -> dict:
    """한국 상위법령(법률·대통령령·부령 등)을 검색합니다.

    국가법령정보센터 OPEN API를 통해 검색합니다. Stage 2 Track A의
    상위법령 저촉 검토에 사용할 후보를 찾을 때 활용합니다. 결과의
    jurisdiction에 법령구분(법률/대통령령/부령 등)이 포함됩니다.

    Args:
        topic: 검색 키워드 (예: "청소년 기본법", "지방자치").
        topk: 최대 결과 개수.

    Returns:
        {source, topic, count, hits} 형식의 dict.
    """
    async with KrLawAdapter() as adapter:
        hits = await adapter.search([topic], topk=topk)
    return {
        "source": "kr_law",
        "topic": topic,
        "count": len(hits),
        "hits": [h.model_dump(mode="json") for h in hits],
    }


if _REVIEW_ENABLED:

    @mcp.tool()
    async def review_ordinance_draft(
        draft_text: str,
        ordinance_title: str = "",
        session_name: str = "",
        committee_name: str = "",
        proposer_info: str = "",
        bill_no: str = "",
        propose_date: str = "",
        referral_date: str = "",
        report_date: str = "",
        reviewer: str = "",
        max_articles: int = 8,
        max_candidates_per_track: int = 3,
        output_dir: str = "",
    ) -> dict:
        """검토 트랙 (비공개): 조례안 초안을 받아 검토보고서 데이터 + .docx를 생성합니다.

        본격 검토 — 안건 분석 + 상위법 저촉(조문별 통합) + 타지자체 비교 + 영향분석지표
        10항목 자동 평가. 어제(2026-06-08) 분석한 경기도의회 안행위 검토보고서 양식 그대로.

        Args:
            draft_text: 조례안 본문 (한국어).
            ordinance_title ~ reviewer: 검토보고서 표지·회부경위 메타.
            output_dir: 비우면 파일 저장 없이 데이터만 반환. 'default'면 data/outputs/.

        Returns:
            ReviewBundle dict + (저장 시) docx_path.
        """
        meta = ReviewMeta(
            session_name=session_name,
            committee_name=committee_name,
            ordinance_title=ordinance_title,
            proposer_info=proposer_info,
            bill_no=bill_no,
            propose_date=propose_date,
            referral_date=referral_date,
            report_date=report_date,
            reviewer=reviewer,
        )
        bundle = await run_review_pipeline(
            draft_text=draft_text,
            meta=meta,
            max_articles=max_articles,
            max_candidates_per_track=max_candidates_per_track,
        )

        result = _bundle_to_dict(bundle)
        if output_dir:
            out_dir = DATA_DIR / "outputs" if output_dir == "default" else Path(output_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            docx_path = out_dir / f"{stamp}_검토보고서.docx"
            render_review_report(bundle, docx_path)
            result["docx_path"] = str(docx_path)
        return result

    @mcp.tool()
    async def review_external_hwpx(
        hwpx_path: str,
        ordinance_title: str = "",
        session_name: str = "",
        committee_name: str = "",
        proposer_info: str = "",
        bill_no: str = "",
        propose_date: str = "",
        referral_date: str = "",
        report_date: str = "",
        reviewer: str = "",
        max_articles: int = 8,
        max_candidates_per_track: int = 3,
        output_dir: str = "",
    ) -> dict:
        """검토 트랙 (비공개): 외부 .hwpx 조례안을 읽어 검토보고서 .docx까지 한 번에.

        의원 발의안·행정부 송부안 등 *외부에서 받은* .hwpx 파일을 직접 입력으로 받아
        kordoc·hwpx_reader로 본문을 추출하고 검토 파이프라인을 실행.
        """
        meta_overrides = dict(
            session_name=session_name, committee_name=committee_name,
            ordinance_title=ordinance_title, proposer_info=proposer_info,
            bill_no=bill_no, propose_date=propose_date,
            referral_date=referral_date, report_date=report_date,
            reviewer=reviewer,
        )
        bundle = await review_from_hwpx(
            hwpx_path=hwpx_path,
            meta_overrides=meta_overrides,
            max_articles=max_articles,
            max_candidates_per_track=max_candidates_per_track,
        )

        result = _bundle_to_dict(bundle)
        if output_dir:
            out_dir = DATA_DIR / "outputs" if output_dir == "default" else Path(output_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            docx_path = out_dir / f"{stamp}_검토보고서_외부hwpx.docx"
            render_review_report(bundle, docx_path)
            result["docx_path"] = str(docx_path)
        return result

    def _bundle_to_dict(bundle) -> dict:
        """ReviewBundle (dataclass) → MCP 반환용 JSON-serializable dict."""
        return {
            "meta": bundle.meta.model_dump(mode="json"),
            "conflicts": [c.model_dump(mode="json") for c in bundle.conflicts],
            "comparisons": [c.model_dump(mode="json") for c in bundle.comparisons],
            "agenda": bundle.agenda.model_dump(mode="json") if bundle.agenda else None,
            "kr_law_hits": [h.model_dump(mode="json") for h in bundle.kr_law_hits],
            "kr_local_hits": [h.model_dump(mode="json") for h in bundle.kr_local_hits],
            "errors": list(bundle.errors),
        }


@mcp.tool()
async def draft_new_ordinance_tool(
    policy_intent: str,
    title: str = "",
    delegation_law: str = "",
    output_dir: str = "",
) -> dict:
    """Stage 3 (제정안): 정책 의도를 받아 새 조례 초안을 작성하고 .docx로 저장합니다.

    경기도 표준 양식 — 제안이유 / 주요내용 / 조문 / 부칙 구조. 결과는 .docx로
    저장되어 한글 오피스에서 그대로 열립니다.

    Args:
        policy_intent: 정책 목적·필요성을 한국어로 자유 서술.
        title: 조례명 (비우면 LLM이 정함).
        delegation_law: 위임 근거 상위법 (예: "「지방자치법」 제28조").
        output_dir: .docx 저장 폴더. 비우면 프로젝트의 data/outputs/.

    Returns:
        StageReport dict — draft.docx_path에 저장된 파일 경로 포함.
    """
    report = await draft_new(
        policy_intent=policy_intent,
        title=title,
        delegation_law=delegation_law,
        output_dir=output_dir or "default",
    )
    return report.model_dump(mode="json")


@mcp.tool()
async def draft_amendment_tool(
    existing_ordinance: str,
    amendment_intent: str,
    title: str = "",
    output_dir: str = "",
) -> dict:
    """Stage 3 (개정안): 기존 조례 본문 + 개정 의도 → 일부개정조례안 + 신·구조문대비표.

    결과는 .docx로 저장 — 신·구조문대비표가 표 형식으로 들어갑니다.

    Args:
        existing_ordinance: 현행 조례 본문 전체.
        amendment_intent: 어떻게 바꿀지 한국어 자유 서술.
        title: 개정안 명 (비우면 LLM이 정함).
        output_dir: .docx 저장 폴더. 비우면 프로젝트의 data/outputs/.

    Returns:
        StageReport dict — draft.docx_path 포함.
    """
    report = await draft_amend(
        existing_ordinance=existing_ordinance,
        amendment_intent=amendment_intent,
        title=title,
        output_dir=output_dir or "default",
    )
    return report.model_dump(mode="json")


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
