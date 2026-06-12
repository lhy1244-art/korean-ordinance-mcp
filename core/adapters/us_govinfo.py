"""US federal legislation adapter — GovInfo Search API.

Endpoint: POST https://api.govinfo.gov/search
Docs:     https://api.govinfo.gov/docs/

We filter to legislation-relevant collections:
  - PLAW   Public and Private Laws (enacted laws)
  - BILLS  Congressional Bills
  - USCODE US Code

Auth: ?api_key=... or X-Api-Key header. The shared DEMO_KEY works but is
rate-limited (~30 req/hr globally). For real use, set GOVINFO_API_KEY in .env
after signing up at https://api.data.gov/signup/.
"""

from __future__ import annotations

import re

from core.adapters.base import SearchAdapter
from core.cache import get as cache_get, set as cache_set
from core.config import settings
from core.models import RawHit


SEARCH_URL = "https://api.govinfo.gov/search"
PUBLIC_DETAILS_URL = "https://www.govinfo.gov/app/details"

LEGISLATION_COLLECTIONS = ["PLAW", "BILLS", "USCODE"]
COLLECTION_FILTER = "collection:(" + " OR ".join(LEGISLATION_COLLECTIONS) + ")"


class UsGovInfoAdapter(SearchAdapter):
    source_id = "us_govinfo"
    country = "US"
    level = "national"

    async def search(
        self,
        keywords: list[str],
        topk: int = 5,
        year_from: int | None = None,
    ) -> list[RawHit]:
        if not keywords:
            return []

        # Fall back to DEMO_KEY so the adapter is testable out of the box.
        # Rate-limited; sets should override with their own key in production.
        api_key = settings.govinfo_api_key or "DEMO_KEY"

        for query in self._candidate_queries(keywords, year_from):
            cache_key = {"q": query, "topk": topk, "src": self.source_id}
            cached = cache_get("adapter_search", cache_key)
            if cached:
                return [RawHit.model_validate(h) for h in cached]

            body = {
                "query": query,
                "pageSize": topk,
                "offsetMark": "*",
                "sorts": [{"field": "relevancy", "sortOrder": "DESC"}],
                "historical": True,
            }
            resp = await self.client.post(
                SEARCH_URL,
                json=body,
                headers={"X-Api-Key": api_key, "Accept": "application/json"},
            )
            if resp.status_code != 200:
                continue

            try:
                data = resp.json()
            except ValueError:
                continue

            hits = self._parse(data, topk)
            if hits:
                cache_set(
                    "adapter_search", cache_key, [h.model_dump(mode="json") for h in hits]
                )
                return hits

        return []

    @staticmethod
    def _candidate_queries(keywords: list[str], year_from: int | None) -> list[str]:
        date_filter = f" AND publishdate:range({year_from}-01-01,2099-12-31)" if year_from else ""
        joined = " ".join(keywords[:3])
        seen: set[str] = set()
        out: list[str] = []
        for kw in [joined] + keywords[:5]:
            if not kw or kw in seen:
                continue
            seen.add(kw)
            out.append(f'"{kw}" AND {COLLECTION_FILTER}{date_filter}')
        return out

    def _parse(self, data: dict, topk: int) -> list[RawHit]:
        results = data.get("results") or []
        hits: list[RawHit] = []
        for item in results[:topk]:
            title = (item.get("title") or "").strip()
            package_id = item.get("packageId") or ""
            date_issued = item.get("dateIssued") or ""
            collection = item.get("collectionCode") or ""

            if not title or not package_id:
                continue

            year_match = re.match(r"(\d{4})", date_issued)
            year = int(year_match.group(1)) if year_match else None

            # Canonical public URL — packageId works directly in /app/details/.
            url = f"{PUBLIC_DETAILS_URL}/{package_id}"

            jurisdiction_parts = ["US Federal"]
            if collection:
                jurisdiction_parts.append(collection)
            jurisdiction = " · ".join(jurisdiction_parts)

            snippet_bits = [b for b in [date_issued, collection] if b]
            snippet = " · ".join(snippet_bits) or title

            hits.append(
                RawHit(
                    source_id=self.source_id,
                    country="US",
                    level="national",
                    jurisdiction=jurisdiction,
                    title=title,
                    enacted_year=year,
                    url=url,
                    snippet=snippet,
                )
            )
        return hits
