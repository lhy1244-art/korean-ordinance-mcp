"""End-to-end smoke test for Week 1.

Run:  uv run python -m scripts.smoke_test
"""

from __future__ import annotations

import asyncio
import sys
import traceback

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from core.adapters.eu_eurlex import EuEurLexAdapter
from core.adapters.jp_egov import JpEgovAdapter
from core.adapters.kr_law import KrLawAdapter
from core.adapters.kr_local import KrLocalAdapter
from core.adapters.uk_legislation import UkLegislationAdapter
from core.adapters.us_govinfo import UsGovInfoAdapter
from core.config import settings


async def _test_adapter(name: str, adapter_cls, keywords: list[str]) -> bool:
    print(f"\n[{name}] keywords={keywords}")
    try:
        async with adapter_cls() as a:
            hits = await a.search(keywords, topk=3)
        if not hits:
            print(f"  ! no hits returned")
            return False
        for h in hits:
            print(f"  - {h.country}/{h.jurisdiction}  {h.title[:60]}  -> {h.url}")
        return True
    except Exception:
        print(f"  ! exception:")
        traceback.print_exc()
        return False


async def _test_pipeline() -> bool:
    if not settings.anthropic_api_key:
        print("\n[pipeline] SKIPPED — set ANTHROPIC_API_KEY to enable")
        return True
    from core.pipeline.stage1_screening import screen_overseas_examples

    print(f"\n[pipeline] running Stage 1 via Anthropic API with policy_idea='청년 1인가구 사회적 고립 예방'")
    try:
        report = await screen_overseas_examples(
            "청년 1인가구 사회적 고립 예방", topk_per_country=2
        )
        print(f"  summary: {report.summary}")
        print(f"  cards: {len(report.cards)}")
        for c in report.cards:
            print(f"    [{c.country}] {c.title}")
            print(f"        요약: {c.summary[:120]}")
        if report.errors:
            print(f"  errors: {report.errors}")
        return len(report.cards) > 0
    except Exception:
        print("  ! exception:")
        traceback.print_exc()
        return False


async def main() -> int:
    results = []
    results.append(("jp_egov", await _test_adapter("jp_egov", JpEgovAdapter, ["子ども", "家庭"])))
    results.append(
        (
            "uk_legislation",
            await _test_adapter("uk_legislation", UkLegislationAdapter, ["loneliness", "youth"]),
        )
    )
    results.append(
        (
            "eu_eurlex",
            await _test_adapter("eu_eurlex", EuEurLexAdapter, ["loneliness", "youth"]),
        )
    )
    results.append(
        (
            "us_govinfo",
            await _test_adapter("us_govinfo", UsGovInfoAdapter, ["loneliness", "youth"]),
        )
    )
    if settings.law_go_kr_oc:
        results.append(
            (
                "kr_local",
                await _test_adapter("kr_local", KrLocalAdapter, ["청년", "1인가구"]),
            )
        )
        results.append(
            (
                "kr_law",
                await _test_adapter("kr_law", KrLawAdapter, ["청소년", "기본법"]),
            )
        )
    else:
        print("\n[kr_local + kr_law] SKIPPED — set LAW_GO_KR_OC to enable")
    results.append(("stage1_pipeline", await _test_pipeline()))

    print("\n=== summary ===")
    for name, ok in results:
        print(f"  {'OK ' if ok else 'FAIL'} {name}")

    return 0 if all(ok for _, ok in results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
