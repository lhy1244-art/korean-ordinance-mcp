"""Capture real adapter responses once and save under tests/fixtures/.

Re-run only when an adapter endpoint or query changes meaningfully — the
fixtures pin parser tests to known-good payloads, so refreshing them
without updating the corresponding tests can mask regressions.

The kr_local fixture comes from a real API call, so we scrub the OC value
out before persisting — fixtures end up in version control and shouldn't
leak per-user credentials.
"""

from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

import httpx

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from core.config import settings

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = PROJECT_ROOT / "tests" / "fixtures"


MIN_FIXTURE_BYTES = 500  # discard suspiciously small responses


def _save(path: Path, content: bytes, label: str) -> None:
    """Only overwrite a fixture if the new response looks healthy."""
    if len(content) < MIN_FIXTURE_BYTES:
        print(f"  ! {label}: response too small ({len(content)} bytes); keeping existing fixture")
        return
    path.write_bytes(content)


async def main() -> None:
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    headers_common = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,ko;q=0.8",
    }

    async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers=headers_common) as c:
        # jp_egov
        r = await c.get(
            "https://laws.e-gov.go.jp/api/2/keyword",
            params={"keyword": "子ども 家庭", "limit": 3, "response_format": "json", "sentences_limit": 1},
        )
        print(f"jp_egov: {r.status_code}, {len(r.content)} bytes")
        _save(FIXTURES_DIR / "jp_egov_search.json", r.content, "jp_egov")

        # uk_legislation — bilingual case included
        r = await c.get(
            "https://www.legislation.gov.uk/primary/data.feed",
            params={"text": "social", "results-count": 5},
        )
        print(f"uk_legislation: {r.status_code}, {len(r.content)} bytes")
        _save(FIXTURES_DIR / "uk_legislation_search.xml", r.content, "uk_legislation")

        # eu_eurlex
        r = await c.get(
            "https://eur-lex.europa.eu/search.html",
            params={
                "scope": "EURLEX",
                "text": "loneliness youth",
                "lang": "en",
                "type": "quick",
                "qid": "1",
            },
        )
        print(f"eu_eurlex: {r.status_code}, {len(r.content)} bytes")
        _save(FIXTURES_DIR / "eu_eurlex_search.html", r.content, "eu_eurlex")

        # kr_local + kr_law — both need a configured OC. Sanitize before saving.
        if settings.law_go_kr_oc:
            for target, query, name in [
                ("ordin", "청년", "kr_local_search.xml"),
                ("law", "청소년", "kr_law_search.xml"),
            ]:
                r = await c.get(
                    "https://www.law.go.kr/DRF/lawSearch.do",
                    params={
                        "OC": settings.law_go_kr_oc,
                        "target": target,
                        "query": query,
                        "type": "XML",
                        "display": 3,
                    },
                )
                print(f"kr_{target}: {r.status_code}, {len(r.content)} bytes")
                if len(r.content) < MIN_FIXTURE_BYTES:
                    print(f"  ! kr_{target}: response too small; keeping existing fixture")
                    continue
                sanitized = re.sub(
                    rf"OC={re.escape(settings.law_go_kr_oc)}", "OC=REDACTED", r.text
                )
                (FIXTURES_DIR / name).write_text(sanitized, encoding="utf-8")
        else:
            print("kr_local + kr_law: SKIPPED — set LAW_GO_KR_OC to capture")

        # us_govinfo (DEMO_KEY)
        body = {
            "query": '"loneliness" AND collection:(PLAW OR BILLS OR USCODE)',
            "pageSize": 3,
            "offsetMark": "*",
            "sorts": [{"field": "relevancy", "sortOrder": "DESC"}],
            "historical": True,
        }
        govinfo_key = settings.govinfo_api_key or "DEMO_KEY"
        r = await c.post(
            "https://api.govinfo.gov/search",
            json=body,
            headers={"X-Api-Key": govinfo_key, "Accept": "application/json"},
        )
        print(f"us_govinfo: {r.status_code}, {len(r.content)} bytes")
        _save(FIXTURES_DIR / "us_govinfo_search.json", r.content, "us_govinfo")

    print(f"\nFixtures saved under {FIXTURES_DIR}")


if __name__ == "__main__":
    asyncio.run(main())
