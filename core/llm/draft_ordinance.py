"""Stage 3 — 조례안 자동 작성.

두 모드 지원:
  - 제정안(new): 정책 의도 + (선택) 위임 근거 → 새 조례 전체
  - 개정안(amendment): 기존 조례 + 개정 의도 → 변경 사항 리스트

LLM 응답은 strict JSON으로 받아 DraftOrdinance / AmendmentDiff 리스트로 변환.
양식 .docx 출력은 core/templates/ 모듈이 별도로 담당 (이번 라운드 범위 밖).
"""

from __future__ import annotations

import json

from core.cache import get as cache_get, set as cache_set
from core.llm.client import get_client, model_for
from core.llm.prompts import (
    DRAFT_AMENDMENT_SYSTEM,
    DRAFT_NEW_ORDINANCE_SYSTEM,
)
from core.models import AmendmentDiff, DraftOrdinance, RawHit


async def draft_new_ordinance(
    policy_intent: str,
    title: str = "",
    delegation_law: str = "",
    references: list[RawHit] | None = None,
) -> DraftOrdinance:
    """제정조례안 작성.

    Args:
        policy_intent: 한국어 정책 의도 자연어.
        title: 조례명 (없으면 LLM이 정책 의도에서 추출).
        delegation_law: 위임 근거 상위법 (예: "「지방자치법」 제28조").
        references: Stage 1/2에서 모은 해외·국내 참고 자료 (선택).
    """
    cache_key = {
        "task": "draft_new",
        "intent": policy_intent[:300],
        "title": title,
        "delegation": delegation_law,
        "ref_urls": [r.url for r in references or []][:5],
    }
    cached = cache_get("llm", cache_key)
    if cached:
        return DraftOrdinance.model_validate(cached)

    ref_block = ""
    if references:
        ref_lines = [
            f"- [{r.country}/{r.jurisdiction}] {r.title}: {(r.snippet or r.raw_text)[:200]}"
            for r in references[:5]
        ]
        ref_block = "\n[참고 자료]\n" + "\n".join(ref_lines)

    user_msg = (
        f"[정책 의도]\n{policy_intent}\n\n"
        f"[조례명 후보] {title or '(미지정 — 직접 정해)'}\n"
        f"[위임 근거 상위법] {delegation_law or '(미지정)'}\n"
        f"{ref_block}\n\n"
        "위 정보로 경기도의회 표준 양식의 제정조례안을 작성하라."
    )

    client = get_client()
    msg = await client.messages.create(
        model=model_for("reasoning"),
        max_tokens=8000,  # 제정안은 조문 8~15개 + 본문 한국어라 토큰 많이 씀
        system=DRAFT_NEW_ORDINANCE_SYSTEM,
        messages=[{"role": "user", "content": user_msg}],
    )
    text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
    text = _strip_code_fences(text)

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = {}

    draft = DraftOrdinance(
        mode="new",
        title=(parsed.get("title") or title or "(제목 생성 실패)").strip(),
        proposal_reason=(parsed.get("proposal_reason") or "").strip(),
        main_contents=_listify(parsed.get("main_contents")),
        articles=_normalize_articles(parsed.get("articles")),
        addendum=(parsed.get("addendum") or "이 조례는 공포한 날부터 시행한다.").strip(),
        delegation_law=(parsed.get("delegation_law") or delegation_law or "").strip(),
    )
    cache_set("llm", cache_key, draft.model_dump(mode="json"))
    return draft


async def draft_amendment(
    existing_ordinance: str,
    amendment_intent: str,
    title: str = "",
) -> tuple[DraftOrdinance, list[AmendmentDiff]]:
    """일부개정조례안 작성.

    Returns:
        (DraftOrdinance, AmendmentDiff list). diff 리스트는 신·구조문대비표
        diff_table 모듈의 입력으로 그대로 쓸 수 있다.
    """
    cache_key = {
        "task": "draft_amendment",
        "intent": amendment_intent[:300],
        "existing_hash": f"{len(existing_ordinance)}:{existing_ordinance[:200]}",
        "title": title,
    }
    cached = cache_get("llm", cache_key)
    if cached:
        draft = DraftOrdinance.model_validate(cached["draft"])
        diffs = [AmendmentDiff.model_validate(d) for d in cached["diffs"]]
        return draft, diffs

    user_msg = (
        f"[기존 조례 본문]\n{existing_ordinance[:6000]}\n\n"
        f"[개정 의도]\n{amendment_intent}\n\n"
        f"[조례명 후보] {title or '(미지정)'}\n\n"
        "위 정보로 일부개정조례안을 작성하라."
    )

    client = get_client()
    msg = await client.messages.create(
        model=model_for("reasoning"),
        max_tokens=8000,  # 제정안은 조문 8~15개 + 본문 한국어라 토큰 많이 씀
        system=DRAFT_AMENDMENT_SYSTEM,
        messages=[{"role": "user", "content": user_msg}],
    )
    text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
    text = _strip_code_fences(text)

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = {}

    changes = parsed.get("changes") or []
    if not isinstance(changes, list):
        changes = []

    diffs: list[AmendmentDiff] = []
    for ch in changes:
        if not isinstance(ch, dict):
            continue
        ct = ch.get("change_type") or "modified"
        if ct not in {"new", "modified", "deleted"}:
            ct = "modified"
        diffs.append(
            AmendmentDiff(
                article_label=(ch.get("article_label") or "").strip(),
                current_text=(ch.get("current_text") or "").strip(),
                revised_text=(ch.get("revised_text") or "").strip(),
                change_type=ct,  # type: ignore[arg-type]
                note=(ch.get("note") or "").strip(),
            )
        )

    draft = DraftOrdinance(
        mode="amendment",
        title=(parsed.get("title") or title or "(제목 생성 실패)").strip(),
        proposal_reason=(parsed.get("proposal_reason") or "").strip(),
        main_contents=_listify(parsed.get("main_contents")),
        articles=[],  # 개정안은 articles 대신 diffs로 표현
        addendum=(parsed.get("addendum") or "이 조례는 공포한 날부터 시행한다.").strip(),
        delegation_law="",
    )
    cache_set(
        "llm",
        cache_key,
        {
            "draft": draft.model_dump(mode="json"),
            "diffs": [d.model_dump(mode="json") for d in diffs],
        },
    )
    return draft, diffs


def _listify(v) -> list[str]:
    if not v:
        return []
    if isinstance(v, list):
        return [str(x).strip() for x in v if x]
    return [str(v).strip()]


def _normalize_articles(arts) -> list[dict]:
    """LLM이 articles에 dict 리스트로 보냈는지 검증, 누락 필드 채움."""
    if not isinstance(arts, list):
        return []
    out: list[dict] = []
    for a in arts:
        if not isinstance(a, dict):
            continue
        out.append({
            "label": str(a.get("label") or "").strip(),
            "title": str(a.get("title") or "").strip(),
            "body": str(a.get("body") or "").strip(),
        })
    return out


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines)
    return text.strip()
