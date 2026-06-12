"""EU EUR-Lex adapter.

Source: https://eur-lex.europa.eu (the EU's authoritative legal database).
No API key required — we parse the public search results page.

EUR-Lex also offers SOAP and SPARQL endpoints, but both require registration.
The public search HTML is the path that works without setup. CELEX numbers
in result URLs give us the enactment year deterministically.

Search URL pattern:
  https://eur-lex.europa.eu/search.html?scope=EURLEX&text={query}&lang=en
"""

from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from core.adapters.base import SearchAdapter
from core.cache import get as cache_get, set as cache_set
from core.models import RawHit


BASE_URL = "https://eur-lex.europa.eu"
SEARCH_URL = f"{BASE_URL}/search.html"


class EuEurLexAdapter(SearchAdapter):
    source_id = "eu_eurlex"
    country = "EU"
    level = "supranational"

    async def search(
        self,
        keywords: list[str],
        topk: int = 5,
        year_from: int | None = None,
    ) -> list[RawHit]:
        if not keywords:
            return []

        for query in self._candidate_queries(keywords):
            cache_key = {"q": query, "topk": topk, "src": self.source_id}
            cached = cache_get("adapter_search", cache_key)
            if cached:
                return [RawHit.model_validate(h) for h in cached]

            params = {
                "scope": "EURLEX",
                "text": query,
                "lang": "en",
                "type": "quick",
                "qid": "1",
            }
            if year_from:
                params["DD_YEAR"] = str(year_from)

            resp = await self.client.get(SEARCH_URL, params=params)
            if resp.status_code != 200:
                continue

            hits = self._parse(resp.text, topk)
            if hits:
                cache_set(
                    "adapter_search", cache_key, [h.model_dump(mode="json") for h in hits]
                )
                return hits

        return []

    @staticmethod
    def _candidate_queries(keywords: list[str]) -> list[str]:
        joined = " ".join(keywords[:3])
        seen = {joined}
        out = [joined]
        for k in keywords[:5]:
            if k not in seen:
                seen.add(k)
                out.append(k)
        return out

    def _parse(self, html: str, topk: int) -> list[RawHit]:
        soup = BeautifulSoup(html, "lxml")
        hits: list[RawHit] = []

        # Each result is a <div class="SearchResult"> containing
        # <h2><a class="title" href="./legal-content/AUTO/?uri=CELEX:..."> {title} </a></h2>
        # plus <p class="internalNum"> {document number} </p>
        # and  <p class="textUnderTitle"> {publication metadata} </p>.
        for block in soup.select("div.SearchResult")[:topk * 2]:
            title_link = block.select_one("h2 a.title")
            if not title_link:
                continue
            href = title_link.get("href", "")
            celex_match = re.search(r"CELEX(?:[:%]3A|:)([0-9A-Z()]+)", href)
            if not celex_match:
                continue
            celex = celex_match.group(1)
            full_url = urljoin(BASE_URL, href.split("&qid=")[0])

            title = title_link.get_text(" ", strip=True)
            if not title:
                continue

            # CELEX number structure: <sector-digit><4-digit-year><type-letter(s)><doc-num>.
            # e.g. "52024IE3264" -> sector=5, year=2024, type=IE, num=3264.
            # Skipping the sector digit avoids parsing the year as "5202".
            year_match = re.match(r"^\d(\d{4})[A-Z]", celex)
            year = int(year_match.group(1)) if year_match else None

            doc_num = block.select_one("p.internalNum")
            pub_meta = block.select_one("p.textUnderTitle")
            snippet_parts = []
            if doc_num:
                snippet_parts.append(doc_num.get_text(" ", strip=True))
            if pub_meta:
                snippet_parts.append(pub_meta.get_text(" ", strip=True))
            snippet = " — ".join(p for p in snippet_parts if p) or title

            hits.append(
                RawHit(
                    source_id=self.source_id,
                    country="EU",
                    level="supranational",
                    jurisdiction="European Union",
                    title=title,
                    enacted_year=year,
                    url=full_url,
                    snippet=snippet[:300],
                )
            )
            if len(hits) >= topk:
                break

        return hits
