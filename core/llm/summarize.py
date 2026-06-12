import json

from core.cache import get as cache_get, set as cache_set
from core.llm.client import get_client, model_for
from core.llm.prompts import SUMMARIZE_CARD_SYSTEM, UNTRUSTED_BLOCK_NOTE
from core.models import PolicyCard, RawHit


async def summarize_to_card(hit: RawHit) -> PolicyCard:
    """RawHit -> PolicyCard via LLM. Cached by source+url."""
    cache_key = {
        "task": "summarize_card",
        "src": hit.source_id,
        "url": hit.url,
        "title": hit.title,
    }
    cached = cache_get("llm", cache_key)
    if cached:
        return PolicyCard.model_validate(cached)

    body = hit.raw_text or hit.snippet or hit.title
    user_msg = (
        f"국가/관할: {hit.country} / {hit.jurisdiction}\n"
        f"법령명: {hit.title}\n"
        f"제정연도(추정): {hit.enacted_year or '미상'}\n"
        f"출처 URL: {hit.url}\n\n"
        f"{UNTRUSTED_BLOCK_NOTE}\n"
        f"<untrusted_source>\n{body}\n</untrusted_source>"
    )

    client = get_client()
    msg = await client.messages.create(
        model=model_for("summary"),
        max_tokens=800,
        system=SUMMARIZE_CARD_SYSTEM,
        messages=[{"role": "user", "content": user_msg}],
    )
    text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
    text = _strip_code_fences(text)

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = {
            "title_translated": hit.title,
            "summary": "(요약 생성 실패 — 원문 링크를 확인하세요)",
            "key_points": [],
            "relevance_note": "",
        }

    card = PolicyCard(
        source_id=hit.source_id,
        country=hit.country,  # type: ignore[arg-type]
        jurisdiction=hit.jurisdiction,
        title=hit.title,
        title_translated=parsed.get("title_translated", "") or "",
        enacted_year=hit.enacted_year,
        summary=parsed.get("summary", "") or "",
        key_points=list(parsed.get("key_points", []) or []),
        relevance_note=parsed.get("relevance_note", "") or "",
        url=hit.url,
    )
    cache_set("llm", cache_key, card.model_dump(mode="json"))
    return card


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
