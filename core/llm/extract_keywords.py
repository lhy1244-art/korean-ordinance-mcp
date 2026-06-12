import json

from core.cache import get as cache_get, set as cache_set
from core.llm.client import get_client, model_for
from core.llm.prompts import EXTRACT_KEYWORDS_SYSTEM


async def extract_keywords(policy_idea: str) -> dict[str, list[str]]:
    """Korean policy idea -> {ko, ja, en} keyword lists for legal search."""
    cache_key = {"task": "extract_keywords", "idea": policy_idea}
    cached = cache_get("llm", cache_key)
    if cached:
        return cached

    client = get_client()
    msg = await client.messages.create(
        model=model_for("summary"),
        max_tokens=512,
        system=EXTRACT_KEYWORDS_SYSTEM,
        messages=[{"role": "user", "content": policy_idea}],
    )
    text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()

    try:
        result = json.loads(_strip_code_fences(text))
    except json.JSONDecodeError:
        result = {"ko": [policy_idea], "ja": [policy_idea], "en": [policy_idea]}

    for lang in ("ko", "ja", "en"):
        result.setdefault(lang, [])
        if not isinstance(result[lang], list):
            result[lang] = [str(result[lang])]

    cache_set("llm", cache_key, result)
    return result


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
