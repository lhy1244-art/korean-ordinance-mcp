"""일부개정조례안 *개정 지시문* 생성 LLM 모듈.

기존 휴리스틱(`_build_amendment_directives` in templates/render.py)이 "제N조를
다음과 같이 한다 + 전체 본문" 식으로 비표준이었다. 이를 표준 패턴
(`제N조 중 "AAA"를 "BBB"로 한다.` 등 — 매뉴얼 p.195, p.199)으로 교체.

학습 자산:
  data/reference/diff_table_samples/공식매뉴얼_2면대비표.md
"""

from __future__ import annotations

import json

from pydantic import BaseModel, Field

from core.cache import get as cache_get, set as cache_set
from core.llm.client import get_client, model_for
from core.llm.prompts import AMENDMENT_DIRECTIVES_SYSTEM
from core.models import AmendmentDiff


class Directive(BaseModel):
    label: str = ""
    text: str
    body: str = ""


async def generate_amendment_directives(
    diffs: list[AmendmentDiff],
    existing_ordinance: str = "",
    title: str = "",
) -> list[Directive]:
    """diffs + 기존 조례 본문 → 표준 양식의 개정 지시문 목록.

    실패 시 빈 리스트를 반환하지 않고 fallback 휴리스틱으로 만든 지시문을 줘서
    파이프라인이 막히지 않게 한다.
    """
    if not diffs:
        return []

    cache_key = {
        "task": "amendment_directives",
        "prompt_version": "v6_strict_combine_2026_06_09",
        "title": title,
        "n": len(diffs),
        "labels": [d.article_label for d in diffs],
        "existing_hash": f"{len(existing_ordinance)}:{existing_ordinance[:120]}",
    }
    cached = cache_get("llm", cache_key)
    if cached is not None:
        try:
            return [Directive.model_validate(d) for d in cached]
        except Exception:
            pass

    try:
        directives = await _ask(diffs, existing_ordinance, title)
    except Exception:
        return _fallback(diffs)

    if not directives:
        return _fallback(diffs)

    # 후처리: LLM이 조 번호 이동 지시문을 빠뜨렸으면 자동 주입 (결합 형태).
    directives = _ensure_renumber_directives(directives, diffs)

    cache_set("llm", cache_key, [d.model_dump(mode="json") for d in directives])
    return directives


def _ensure_renumber_directives(
    directives: list[Directive],
    diffs: list[AmendmentDiff],
) -> list[Directive]:
    """입력 diffs에 *조 번호 이동* 변경이 있는데 LLM이 그 지시문을 빠뜨렸으면 자동 주입.

    조 번호 이동은 diff에서 `current_text` 첫 줄의 조 라벨과 `revised_text` 첫 줄의
    조 라벨이 *다른* 경우 (조 본문은 같음). 예: "제8조(...)" → "제9조(...)".

    빠진 이동들을 *결합 한 문장*으로 만들어 directives 맨 앞에 끼워 넣는다.
    """
    import re

    renumber_pairs: list[tuple[str, str]] = []
    pat = re.compile(r"^(제\d+조(?:의\d+)?)")
    for d in diffs:
        if d.change_type != "modified":
            continue
        cur_first = (d.current_text or "").strip().splitlines()
        rev_first = (d.revised_text or "").strip().splitlines()
        if not cur_first or not rev_first:
            continue
        cm = pat.search(cur_first[0])
        rm = pat.search(rev_first[0])
        if not (cm and rm):
            continue
        if cm.group(1) != rm.group(1):
            renumber_pairs.append((cm.group(1), rm.group(1)))

    if not renumber_pairs:
        return directives

    # LLM 결과에 이미 포함된 이동 (예: `제8조를 제9조로 한다.`)을 빼고 남은 것만 주입.
    existing = " ".join(d.text for d in directives)
    missing = [
        (old, new)
        for old, new in renumber_pairs
        if f"{old}를 {new}로" not in existing
    ]
    if not missing:
        return directives

    # 결합 형태: "제8조 및 제9조를 각각 제9조 및 제10조로 한다."
    if len(missing) == 1:
        old, new = missing[0]
        combined = f"{old}를 {new}로 한다."
    else:
        olds = " 및 ".join(o for o, _ in missing)
        news = " 및 ".join(n for _, n in missing)
        combined = f"{olds}를 각각 {news}로 한다."

    injected = Directive(label="(조번호이동)", text=combined, body="")
    # 신설 지시문보다 앞에 두는 게 자연스러움 (조 번호 정비 → 본문 변경 순)
    return [injected] + directives


async def _ask(
    diffs: list[AmendmentDiff], existing_ordinance: str, title: str
) -> list[Directive]:
    client = get_client()
    payload = {
        "ordinance_title": title,
        "existing_ordinance_head": existing_ordinance[:5000],
        "changes": [d.model_dump(mode="json") for d in diffs],
    }
    msg = await client.messages.create(
        model=model_for("reasoning"),
        max_tokens=4000,
        system=AMENDMENT_DIRECTIVES_SYSTEM,
        messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
    )
    text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
    text = _strip_code_fences(text)
    data = json.loads(text)
    raw = data.get("directives") or []
    if not isinstance(raw, list):
        return []
    out: list[Directive] = []
    for d in raw:
        if isinstance(d, dict):
            try:
                out.append(Directive.model_validate(d))
            except Exception:
                pass
    return out


def _fallback(diffs: list[AmendmentDiff]) -> list[Directive]:
    """LLM 실패 시 단순 휴리스틱 fallback (옛 _build_amendment_directives 패턴)."""
    out: list[Directive] = []
    for d in diffs:
        label = (d.article_label or "").strip()
        ct = d.change_type
        rev = (d.revised_text or "").strip()
        cur = (d.current_text or "").strip()
        if ct == "deleted":
            out.append(Directive(label=label, text=f"{label}을 삭제한다."))
        elif ct == "new":
            out.append(Directive(
                label=label,
                text=f"{label}을 다음과 같이 신설한다.",
                body=rev,
            ))
        else:
            # modified — 휴리스틱으로는 "부분 치환"을 만들 수 없으므로
            # 안전한 fallback: 본문 전체 교체 지시
            out.append(Directive(
                label=label,
                text=f"{label}을 다음과 같이 한다.",
                body=rev or cur,
            ))
    return out


def render_directives_for_docx(directives: list[Directive]) -> list[str]:
    """워드 본문 단락 리스트로 변환 — body 가 있으면 별도 단락으로 분리."""
    paragraphs: list[str] = []
    for d in directives:
        if d.text:
            paragraphs.append(d.text)
        if d.body:
            # body는 한 단락 또는 여러 줄. 줄 단위 분리해서 단락마다 하나.
            for line in d.body.split("\n"):
                line = line.rstrip()
                if line.strip():
                    paragraphs.append(line)
    return paragraphs


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        rows = text.splitlines()
        if rows[0].startswith("```"):
            rows = rows[1:]
        if rows and rows[-1].startswith("```"):
            rows = rows[:-1]
        text = "\n".join(rows)
    return text.strip()
