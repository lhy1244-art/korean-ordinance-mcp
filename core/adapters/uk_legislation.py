"""UK legislation.gov.uk adapter.

API docs: https://www.legislation.gov.uk/developer
Atom feed search: https://www.legislation.gov.uk/{scope}/data.feed?text=...
No API key required.

Scope selection: /all/ mixes UK-origin Acts with retained EU law
(EU directives/regulations adopted post-Brexit), which produced misleading
hits like "Commission Implementing Decision (EU) ..." for UK searches.
We restrict to UK-origin scopes — primary legislation (Acts) first, then
statutory instruments — so the user sees UK Parliament/regulator output,
not EU instruments that happen to remain in force in the UK.
"""

from __future__ import annotations

import re

from lxml import etree

from core.adapters.base import SearchAdapter
from core.cache import get as cache_get, set as cache_set
from core.models import RawHit


BASE_URL = "https://www.legislation.gov.uk"
ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}

# Scope paths under legislation.gov.uk that contain only UK-origin instruments.
# /primary covers UK Acts (ukpga, ukla, nia, asp, anaw, etc.).
# /uksi covers UK Statutory Instruments (regulator-level rules).
UK_ORIGIN_SCOPES = ["primary", "uksi"]


class UkLegislationAdapter(SearchAdapter):
    source_id = "uk_legislation"
    country = "UK"
    level = "national"

    async def search(
        self,
        keywords: list[str],
        topk: int = 5,
        year_from: int | None = None,
    ) -> list[RawHit]:
        if not keywords:
            return []
        joined = " ".join(keywords[:3])

        cache_key = {"q": joined, "topk": topk, "src": self.source_id}
        cached = cache_get("adapter_search", cache_key)
        if cached:
            return [RawHit.model_validate(h) for h in cached]

        for scope in UK_ORIGIN_SCOPES:
            for params in self._param_variants(joined, keywords, topk):
                resp = await self.client.get(
                    f"{BASE_URL}/{scope}/data.feed", params=params
                )
                if resp.status_code != 200:
                    continue
                hits = self._parse_atom(resp.content, topk)
                if hits:
                    cache_set(
                        "adapter_search",
                        cache_key,
                        [h.model_dump(mode="json") for h in hits],
                    )
                    return hits

        return []

    @staticmethod
    def _param_variants(joined: str, keywords: list[str], topk: int) -> list[dict]:
        """Try the most relevant single keyword in titles first (precision),
        then expand to body text, then fall back to joined queries (recall)."""
        variants: list[dict] = []
        for k in keywords[:3]:
            variants.append({"title": k, "results-count": topk})
        for k in keywords[:3]:
            variants.append({"text": k, "results-count": topk})
        variants.append({"text": joined, "results-count": topk})
        return variants

    def _parse_atom(self, body: bytes, topk: int) -> list[RawHit]:
        try:
            root = etree.fromstring(body)
        except etree.XMLSyntaxError:
            return []

        hits: list[RawHit] = []
        for entry in root.findall("atom:entry", ATOM_NS)[:topk]:
            title_el = entry.find("atom:title", ATOM_NS)
            title = self._element_text(title_el)
            summary = self._element_text(entry.find("atom:summary", ATOM_NS))
            link_el = entry.find("atom:link", ATOM_NS)
            href = link_el.get("href") if link_el is not None else ""
            updated = entry.findtext("atom:updated", default="", namespaces=ATOM_NS) or ""

            year_match = re.search(r"\((\d{4})\)", title) or re.search(r"(\d{4})", title)
            if not year_match:
                year_match = re.search(r"(\d{4})", updated)
            year = int(year_match.group(1)) if year_match else None

            hits.append(
                RawHit(
                    source_id=self.source_id,
                    country="UK",
                    level="national",
                    jurisdiction="United Kingdom",
                    title=title,
                    enacted_year=year,
                    url=href,
                    snippet=summary or title,
                )
            )
        return hits

    @staticmethod
    def _element_text(el) -> str:
        """Extract clean text from an Atom element, handling xhtml-typed titles.

        Welsh/devolved Acts use <title type="xhtml"> with bilingual nested spans
        (English + Welsh). findtext() returns empty for those; itertext()
        flattens the nested text. We keep only the first language segment
        (English) where bilingual content is separated by ' / '.
        """
        if el is None:
            return ""
        text = "".join(el.itertext()).strip()
        # Collapse whitespace runs created by nested xhtml.
        text = re.sub(r"\s+", " ", text)
        # Bilingual UK-Welsh titles look like "English title / Welsh title".
        # Prefer the English half if the separator looks unambiguous.
        if " / " in text:
            text = text.split(" / ", 1)[0].strip()
        return text
