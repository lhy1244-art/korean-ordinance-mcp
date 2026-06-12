"""Stage 1: 참고 입법례 스크리닝 파이프라인.

한국 지방의회 조례 실무 관점에서 참고 입법례는 두 그룹으로 본질이 다르다:

  Tier A — 직접 참고 (direct): 한국 타지자체 자치법규(KR) + 일본 법령(JP).
           법체계·문화·언어가 가까워 조문 차용·번안이 현실적. 본문(raw_text)까지
           fetch해서 보고서에 함께 싣는다.

  Tier B — 간접 참고 (indirect): 영국(UK) · EU · 미국(US).
           정책 시각·구조만 참고 가능, 직접 이식은 어렵다. 검색 결과 + 한국어
           요약(PolicyCard)까지만 만들고 본문은 가져오지 않는다.

호출자는 이 단계의 결과(PolicyCard 목록의 tier 필드)와 보고서 모듈을 함께 활용해
경기도 기존 조례 유무 → 개정 vs 신규 제정 판단을 내릴 수 있다.
"""

import asyncio

from core.adapters.base import SearchAdapter
from core.adapters.eu_eurlex import EuEurLexAdapter
from core.adapters.jp_egov import JpEgovAdapter
from core.adapters.kr_local import KrLocalAdapter
from core.adapters.uk_legislation import UkLegislationAdapter
from core.adapters.us_govinfo import UsGovInfoAdapter
from core.config import settings
from core.llm.extract_keywords import extract_keywords
from core.llm.relevance_filter import filter_relevant_cards
from core.llm.summarize import summarize_to_card
from core.models import PolicyCard, RawHit, ReferenceTier, StageReport
from core.utils.parallel import gather_limited, run_with_isolation


ALL_ADAPTERS: dict[str, type[SearchAdapter]] = {
    "KR": KrLocalAdapter,
    "JP": JpEgovAdapter,
    "UK": UkLegislationAdapter,
    "EU": EuEurLexAdapter,
    "US": UsGovInfoAdapter,
}

# 직접 참고(direct) — 본문까지 fetch
TIER_A_COUNTRIES: tuple[str, ...] = ("KR", "JP")
# 간접 참고(indirect) — 검색·요약만
TIER_B_COUNTRIES: tuple[str, ...] = ("UK", "EU", "US")

DEFAULT_COUNTRIES: list[str] = list(TIER_A_COUNTRIES) + list(TIER_B_COUNTRIES)

# 보고서용 원문 발췌 한도 — 너무 길면 마크다운 보고서가 무거워지고 LLM 후속 단계에서도
# 토큰 부담이 커진다. raw_text는 어댑터가 잘라둔 길이 그대로 두고, 발췌만 별도로 자른다.
_RAW_EXCERPT_CHARS = 1500


def _keywords_for(country: str, kw: dict[str, list[str]]) -> list[str]:
    if country == "JP":
        return kw.get("ja") or kw.get("en") or []
    if country == "KR":
        return kw.get("ko") or kw.get("en") or []
    return kw.get("en") or []


def _tier_for(country: str) -> ReferenceTier:
    return "direct" if country in TIER_A_COUNTRIES else "indirect"


def _make_excerpt(raw_text: str, max_chars: int = _RAW_EXCERPT_CHARS) -> str:
    text = (raw_text or "").strip()
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "\n…(발췌 — 이하 생략)"


async def _search_with_fulltext(
    country: str, adapter: SearchAdapter, keywords: list[str], topk: int
) -> list[RawHit]:
    """Tier A 전용 — 검색 후 같은 어댑터로 본문(raw_text)까지 채운다."""
    hits = await adapter.search(keywords, topk=topk)
    enriched: list[RawHit] = []
    for h in hits:
        full = await adapter.fetch_full_text(h)
        if full:
            enriched.append(h.model_copy(update={"raw_text": full}))
        else:
            enriched.append(h)
    return enriched


async def screen_overseas_examples(
    policy_idea: str,
    countries: list[str] | None = None,
    topk_per_country: int = 3,
) -> StageReport:
    """정책 아이디어 → 키워드 추출 → 어댑터 병렬 검색 → tier별 PolicyCard 생성.

    Tier A(KR/JP)는 본문 fetch까지, Tier B(UK/EU/US)는 검색·요약까지.
    함수명은 외부 인터페이스 호환성을 위해 유지 — 내부 의미는 "참고 입법례 스크리닝".
    """
    if not policy_idea or not policy_idea.strip():
        return StageReport(stage="1", summary="정책 아이디어가 비어 있습니다.", errors=["empty input"])

    requested = [c.upper() for c in (countries or DEFAULT_COUNTRIES)]
    enabled = [c for c in requested if c in ALL_ADAPTERS]

    # KR(kr_local)은 국가법령정보센터 OC 키 없으면 동작 불가 → enabled에서 제외.
    if "KR" in enabled and not settings.law_go_kr_oc:
        enabled = [c for c in enabled if c != "KR"]

    keywords = await extract_keywords(policy_idea)

    adapters: dict[str, SearchAdapter] = {c: ALL_ADAPTERS[c]() for c in enabled}

    try:
        search_tasks = {}
        for c in enabled:
            kw = _keywords_for(c, keywords)
            if c in TIER_A_COUNTRIES:
                search_tasks[c] = _search_with_fulltext(
                    c, adapters[c], kw, topk_per_country
                )
            else:
                search_tasks[c] = adapters[c].search(kw, topk=topk_per_country)
        search_results, search_errors = await run_with_isolation(
            search_tasks,
            # Tier A는 fetch까지 도므로 검색 타임아웃에 여유.
            timeout=settings.request_timeout_seconds * 4,
        )
    finally:
        await asyncio.gather(*(a.aclose() for a in adapters.values()), return_exceptions=True)

    # 어느 국가에서 온 hit인지 보존해서 후속 tier 라벨링·발췌에 사용.
    hits_with_country: list[tuple[str, RawHit]] = []
    for c, hits in search_results.items():
        for h in hits or []:
            hits_with_country.append((c, h))

    if not hits_with_country:
        return StageReport(
            stage="1",
            summary="검색 결과 없음. 키워드를 더 구체적으로 입력해보세요.",
            errors=[f"{c}: {err}" for c, err in search_errors.items()],
        )

    summarize_results = await gather_limited(
        [summarize_to_card(h) for _, h in hits_with_country],
        limit=settings.adapter_concurrency_limit,
    )

    cards: list[PolicyCard] = []
    summarize_errors: list[str] = []
    for (country, hit), result in zip(hits_with_country, summarize_results):
        if isinstance(result, Exception):
            summarize_errors.append(f"summarize: {type(result).__name__}: {result}")
            continue
        if not isinstance(result, PolicyCard):
            continue
        tier = _tier_for(country)
        raw_excerpt = _make_excerpt(hit.raw_text) if tier == "direct" else ""
        cards.append(result.model_copy(update={"tier": tier, "raw_excerpt": raw_excerpt}))

    # JP 어댑터는 키워드 fallback이 너무 일반적이라 무관 법령이 자주 들어온다
    # (예: '高齢者' 단독 → 보통교부세 성령). LLM 사후 필터로 정리.
    filter_notes: list[str] = []
    jp_cards = [c for c in cards if c.country == "JP"]
    if jp_cards:
        kept_jp, removed_jp = await filter_relevant_cards(policy_idea, jp_cards)
        if len(kept_jp) != len(jp_cards):
            non_jp = [c for c in cards if c.country != "JP"]
            cards = non_jp + kept_jp
            filter_notes = [f"[관련성 필터 제외 · JP] {note}" for note in removed_jp]

    n_direct = sum(1 for c in cards if c.tier == "direct")
    n_indirect = sum(1 for c in cards if c.tier == "indirect")
    summary = (
        f"{len(cards)}건의 참고 입법례를 {len(set(c.country for c in cards))}개 관할에서 수집 "
        f"(직접 참고 {n_direct}건, 간접 참고 {n_indirect}건). "
        f"키워드: ko={keywords.get('ko')}, ja={keywords.get('ja')}, en={keywords.get('en')}."
    )

    errors = (
        [f"{c}: {err}" for c, err in search_errors.items()]
        + summarize_errors
        + filter_notes
    )

    return StageReport(stage="1", summary=summary, cards=cards, errors=errors)
