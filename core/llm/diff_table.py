"""Stage 3 — 신·구조문대비표 정리.

draft_amendment가 만든 AmendmentDiff 리스트를 받아 표 행 형태로 정돈한다.
이미 AmendmentDiff가 잘 구조화돼 있으면 LLM 호출 없이 그대로 변환 가능.
다만 LLM에 '비고(note)' 정제·압축을 한 번 더 시키면 보고서 품질이 올라간다.
"""

from __future__ import annotations

import json

from core.cache import get as cache_get, set as cache_set
from core.llm.client import get_client, model_for
from core.llm.prompts import DIFF_TABLE_SYSTEM
from core.models import AmendmentDiff


async def polish_diff_table(diffs: list[AmendmentDiff]) -> list[AmendmentDiff]:
    """기존 diff 리스트의 본문 표기·비고 표현을 검토보고서 양식으로 다듬는다.

    빈 본문은 "<신설>"/"<삭제>" 마커로 통일. 비고는 한 줄로 압축.
    """
    if not diffs:
        return []

    # 캐시 키에 프롬프트 버전 포함 — 양식 학습 프롬프트로 강화된 새 결과를 받기 위함.
    cache_key = {
        "task": "polish_diff",
        "prompt_version": "v7_split_new_rows",
        "n": len(diffs),
        "first_label": diffs[0].article_label,
        "labels": [d.article_label for d in diffs],
    }
    cached = cache_get("llm", cache_key)
    if cached:
        return [AmendmentDiff.model_validate(d) for d in cached]

    inp_block = json.dumps(
        [d.model_dump(mode="json") for d in diffs],
        ensure_ascii=False,
        indent=2,
    )
    user_msg = (
        f"[입력 diff 목록]\n{inp_block}\n\n"
        "위 입력을 *경기도의회 표준 신·구조문대비표 양식*에 맞춰 정리하라. "
        "특히 항·호 단위 행 분리, 대시 표기, (현행과 같음)·(생 략) 표기, 신설·삭제 마커를 "
        "정확히 적용. 예시의 도메인 어휘는 절대 차용하지 말 것."
    )

    client = get_client()
    msg = await client.messages.create(
        model=model_for("reasoning"),  # 양식 학습은 reasoning 모델이 더 안정적
        max_tokens=5000,  # 항·호 단위로 분리하면 행 수가 늘어남
        system=DIFF_TABLE_SYSTEM,
        messages=[{"role": "user", "content": user_msg}],
    )
    text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
    text = _strip_code_fences(text)

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = {}

    rows = parsed.get("rows") or []
    if not isinstance(rows, list):
        # LLM이 실패하면 원본 diff에 마커만 적용해서 반환
        return [_marker_only(d) for d in diffs]

    polished: list[AmendmentDiff] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        ct = r.get("change_type") or "modified"
        if ct not in {"new", "modified", "deleted"}:
            ct = "modified"
        # 임병수 표준: 신설은 현행란 빈칸, 삭제는 개정안란 빈칸 (마커 X)
        current = (r.get("current_text") or "").strip()
        revised = (r.get("revised_text") or "").strip()
        polished.append(
            AmendmentDiff(
                article_label=(r.get("article_label") or "").strip(),
                current_text=current,
                revised_text=revised,
                change_type=ct,  # type: ignore[arg-type]
                note=(r.get("note") or "").strip(),
            )
        )

    if not polished:
        polished = [_marker_only(d) for d in diffs]

    cache_set("llm", cache_key, [d.model_dump(mode="json") for d in polished])
    return polished


def _marker_only(d: AmendmentDiff) -> AmendmentDiff:
    # 임병수 표준: 빈칸 그대로 두기 (마커 X). 렌더러가 빈칸을 자동 처리.
    return d.model_copy(update={
        "current_text": d.current_text or "",
        "revised_text": d.revised_text or "",
    })


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
