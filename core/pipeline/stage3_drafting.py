"""Stage 3: 조례안 자동 작성 파이프라인.

두 진입점:
  - draft_new(policy_intent, ...) — 제정안
  - draft_amend(existing_text, intent, ...) — 개정안 + 신·구조문대비표

Stage 1/2의 결과를 references로 받아 풍부한 컨텍스트로 작성 가능.

`output_dir` 지정 시 LLM 결과를 즉시 .docx로도 렌더링해 파일 경로를
DraftOrdinance.docx_path에 기록한다. 한글 오피스에서 그대로 열린다.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from core.config import DATA_DIR
from core.llm.diff_table import polish_diff_table
from core.llm.draft_ordinance import draft_amendment, draft_new_ordinance
from core.llm.self_check import SelfCheckResult, run_self_check
from core.models import AmendmentDiff, DraftOrdinance, RawHit, StageReport
from core.templates.render import render_amendment, render_new_ordinance


DEFAULT_OUTPUT_DIR = DATA_DIR / "outputs"


DISCLAIMER = (
    "⚠️ 본 조례안 초안은 LLM이 자동 생성한 결과입니다. 입법조사관·법제관의 "
    "검토를 반드시 거쳐야 하며, 인용된 상위법령·통계의 정확성도 별도 확인 필요."
)


async def draft_new(
    policy_intent: str,
    title: str = "",
    delegation_law: str = "",
    references: list[RawHit] | None = None,
    decisions_text: str = "",
    output_dir: str | Path | None = "default",
) -> StageReport:
    """제정조례안 자동 작성 + 자동 셀프 점검 첨부.

    Args:
        decisions_text: (선택) 결정 카드에서 사용자가 답변한 결정값 자유서술.
                        셀프 점검의 *결정값 반영* 항목에 활용된다.
        output_dir: ".docx 출력 폴더. None이면 파일 생성 안 함. 'default'면 data/outputs/.
    """
    if not policy_intent or not policy_intent.strip():
        return StageReport(
            stage="3",
            summary="정책 의도가 비어 있습니다.",
            errors=["empty policy_intent"],
            disclaimer=DISCLAIMER,
        )

    draft = await draft_new_ordinance(
        policy_intent=policy_intent,
        title=title,
        delegation_law=delegation_law,
        references=references,
    )

    # 자동 셀프 점검 — 작성자가 빠뜨린 것을 환기하는 sanity check.
    # 실패해도 파이프라인을 막지 않는다 (조용히 errors에 기록).
    self_check, self_check_errs = await run_self_check(
        draft=draft, decisions_text=decisions_text, policy_intent=policy_intent
    )

    docx_path = _maybe_render_new(draft, output_dir)
    if docx_path:
        draft = draft.model_copy(update={"docx_path": str(docx_path)})

    file_note = f" → {docx_path}" if docx_path else ""
    self_check_note = ""
    if self_check is not None:
        n_issues = (
            len(self_check.decision_reflection.issues)
            + len(self_check.higher_law_conflicts)
            + len(self_check.citation_hallucination_suspects)
            + len(self_check.missing_standard_components)
        )
        self_check_note = f" / 셀프 점검 {n_issues}건 환기"
    summary = (
        f"제정조례안 '{draft.title}' 초안 생성 완료. "
        f"조문 {len(draft.articles)}개, 주요내용 {len(draft.main_contents)}개{self_check_note}.{file_note}"
    )
    return StageReport(
        stage="3",
        summary=summary,
        draft=draft,
        errors=self_check_errs,
        disclaimer=DISCLAIMER,
    )


async def draft_amend(
    existing_ordinance: str,
    amendment_intent: str,
    title: str = "",
    output_dir: str | Path | None = "default",
) -> StageReport:
    """일부개정조례안 + 신·구조문대비표 생성."""
    if not existing_ordinance or not existing_ordinance.strip():
        return StageReport(
            stage="3",
            summary="기존 조례 본문이 비어 있습니다.",
            errors=["empty existing_ordinance"],
            disclaimer=DISCLAIMER,
        )
    if not amendment_intent or not amendment_intent.strip():
        return StageReport(
            stage="3",
            summary="개정 의도가 비어 있습니다.",
            errors=["empty amendment_intent"],
            disclaimer=DISCLAIMER,
        )

    draft, raw_diffs = await draft_amendment(
        existing_ordinance=existing_ordinance,
        amendment_intent=amendment_intent,
        title=title,
    )

    polished_diffs: list[AmendmentDiff] = await polish_diff_table(raw_diffs)

    # 개정안에도 자동 셀프 점검 적용 — 오탈자 + 개정안 정합성 점검(지시문 ↔ 대비표 ↔ 본문)까지.
    from core.templates.render import _build_amendment_directives  # 지연 import (순환 회피)
    directives = _build_amendment_directives(polished_diffs)
    diffs_payload = [d.model_dump(mode="json") for d in polished_diffs]
    self_check, self_check_errs = await run_self_check(
        draft=draft,
        decisions_text="",
        policy_intent=amendment_intent,
        mode="amendment",
        directives=directives,
        diffs=diffs_payload,
        existing_ordinance=existing_ordinance,
    )

    docx_path = _maybe_render_amend(draft, polished_diffs, output_dir)
    if docx_path:
        draft = draft.model_copy(update={"docx_path": str(docx_path)})

    file_note = f" → {docx_path}" if docx_path else ""
    self_check_note = ""
    if self_check is not None:
        n_issues = (
            len(self_check.decision_reflection.issues)
            + len(self_check.higher_law_conflicts)
            + len(self_check.citation_hallucination_suspects)
            + len(self_check.missing_standard_components)
            + len(self_check.typo_suspects)
            + (len(self_check.amendment_consistency.issues) if self_check.amendment_consistency else 0)
        )
        self_check_note = f" / 셀프 점검 {n_issues}건 환기"
    summary = (
        f"개정조례안 '{draft.title}' 초안 생성 완료. "
        f"변경 사항 {len(polished_diffs)}건, 신·구조문대비표 {len(polished_diffs)}행{self_check_note}.{file_note}"
    )
    return StageReport(
        stage="3",
        summary=summary,
        draft=draft,
        diffs=polished_diffs,
        disclaimer=DISCLAIMER,
    )


# ---------------- file output helpers ----------------


def _resolve_output_dir(output_dir: str | Path | None) -> Path | None:
    if output_dir is None:
        return None
    if output_dir == "default":
        return DEFAULT_OUTPUT_DIR
    return Path(output_dir)


def _build_filename(title: str, suffix: str = "") -> str:
    """제목 + 타임스탬프로 충돌 없는 파일명 생성. 파일시스템 금지문자는 _ 로 치환."""
    safe = re.sub(r'[<>:"/\\|?*\n\r\t]', "_", title).strip().rstrip(".")
    safe = safe[:60] or "조례안"
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = f"{safe}_{ts}{suffix}"
    return f"{stem}.docx"


def _maybe_render_new(
    draft: DraftOrdinance,
    output_dir: str | Path | None,
) -> Path | None:
    dest = _resolve_output_dir(output_dir)
    if dest is None:
        return None
    return render_new_ordinance(draft, dest / _build_filename(draft.title, "_제정안"))


def _maybe_render_amend(
    draft: DraftOrdinance,
    diffs: list[AmendmentDiff],
    output_dir: str | Path | None,
) -> Path | None:
    dest = _resolve_output_dir(output_dir)
    if dest is None:
        return None
    return render_amendment(draft, diffs, dest / _build_filename(draft.title, "_개정안"))
