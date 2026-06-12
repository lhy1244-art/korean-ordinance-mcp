"""정책 의도 vs PolicyCard 관련성 사후 필터.

Stage 1 어댑터 검색이 너무 일반적인 키워드 fallback으로 빠지면 무관한 결과가 들어온다
(예: '高齢者'만으로 e-Gov를 치면 '보통교부세 성령' 같은 무관 법령까지 잡힘). 이 모듈은
정책 의도와 카드의 의미적 관련성을 1회 LLM 호출로 일괄 판정해 무관 카드를 제거한다.

설계 원칙:
- LLM 비용을 줄이기 위해 한 번의 호출에 카드들을 batch로 묶어 판정.
- 보수적(strict): 애매하면 제외 — false positive(무관한데 포함)가 사용자 신뢰를
  더 해친다는 판단.
- 실패해도 파이프라인을 막지 않는다 — LLM 응답이 깨지면 원본 리스트를 그대로 반환
  (필터 안 한 것과 동일). 데이터 손실 방지.
"""

from __future__ import annotations

import json

from core.cache import get as cache_get, set as cache_set
from core.llm.client import get_client, model_for
from core.llm.prompts import RELEVANCE_FILTER_SYSTEM
from core.models import PolicyCard


async def filter_relevant_cards(
    policy_idea: str,
    cards: list[PolicyCard],
) -> tuple[list[PolicyCard], list[str]]:
    """무관 카드를 제거한 리스트 + 제거 사유(로깅용)를 반환.

    Args:
        policy_idea: 한국어 정책 의도.
        cards: 필터링 대상 카드 리스트. 빈 리스트면 그대로 반환.

    Returns:
        (kept_cards, removed_notes). removed_notes는 '제목 — 사유' 형식 문자열 리스트.
    """
    if not cards:
        return [], []

    # 캐시 키: 정책 의도 + 각 카드의 식별자(url 또는 title) 묶음.
    card_ids = [(c.url or c.title) for c in cards]
    cache_key = {
        "task": "relevance_filter",
        "idea": policy_idea,
        "cards": card_ids,
    }
    cached = cache_get("llm", cache_key)
    if cached is not None:
        decisions = cached
    else:
        try:
            decisions = await _judge(policy_idea, cards)
            cache_set("llm", cache_key, decisions)
        except Exception:
            # LLM 실패 시 보수적으로 전부 통과 — 차라리 노이즈가 누락보다 낫다.
            return list(cards), []

    kept: list[PolicyCard] = []
    removed: list[str] = []
    decision_by_index = {d.get("index"): d for d in decisions if isinstance(d, dict)}
    for i, card in enumerate(cards):
        d = decision_by_index.get(i)
        if d is None:
            # 판정 누락 카드는 보수적으로 유지.
            kept.append(card)
            continue
        if d.get("relevant"):
            kept.append(card)
        else:
            reason = (d.get("reason") or "").strip() or "무관 판정"
            removed.append(f"{card.title} — {reason}")
    return kept, removed


async def _judge(policy_idea: str, cards: list[PolicyCard]) -> list[dict]:
    """LLM 1회 호출로 batch 관련성 판정."""
    client = get_client()
    user_payload = {
        "policy_intent": policy_idea,
        "cards": [
            {
                "index": i,
                "title": c.title,
                "title_translated": c.title_translated,
                "country": c.country,
                "summary": c.summary,
                "key_points": c.key_points,
            }
            for i, c in enumerate(cards)
        ],
    }
    msg = await client.messages.create(
        model=model_for("reasoning"),
        max_tokens=1500,
        system=RELEVANCE_FILTER_SYSTEM,
        messages=[
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)}
        ],
    )
    text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
    text = _strip_code_fences(text)
    data = json.loads(text)
    decisions = data.get("decisions") or []
    if not isinstance(decisions, list):
        raise ValueError("relevance_filter: 'decisions' must be a list")
    return decisions


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
