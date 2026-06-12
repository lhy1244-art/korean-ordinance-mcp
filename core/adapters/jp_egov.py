"""Japan e-Gov 法令API v2 adapter.

Endpoint: GET https://laws.e-gov.go.jp/api/2/keyword
Spec: https://laws.e-gov.go.jp/api/2/swagger-ui/lawapi-v2.yaml
No API key required.
"""

from __future__ import annotations

import re

from core.adapters.base import SearchAdapter
from core.cache import get as cache_get, set as cache_set
from core.models import RawHit


BASE_URL = "https://laws.e-gov.go.jp/api/2"


class JpEgovAdapter(SearchAdapter):
    source_id = "jp_egov"
    country = "JP"
    level = "national"

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
                "keyword": query,
                "limit": topk,
                "response_format": "json",
                "sentences_limit": 1,
            }
            if year_from:
                params["promulgation_date_from"] = f"{year_from}-01-01"

            resp = await self.client.get(f"{BASE_URL}/keyword", params=params)
            if resp.status_code != 200:
                continue
            data = resp.json()
            hits = self._parse(data, topk)
            if hits:
                cache_set("adapter_search", cache_key, [h.model_dump(mode="json") for h in hits])
                return hits

        return []

    @staticmethod
    def _candidate_queries(keywords: list[str]) -> list[str]:
        """Try the joined phrase first, then each individual keyword.

        e-Gov keyword search treats the phrase verbatim (no OR-splitting),
        so falling back to single tokens improves recall.
        """
        joined = " ".join(keywords[:3])
        seen = {joined}
        out = [joined]
        for k in keywords[:5]:
            if k not in seen:
                seen.add(k)
                out.append(k)
        return out

    def _parse(self, data: dict, topk: int) -> list[RawHit]:
        items = data.get("items") or []
        hits: list[RawHit] = []
        for item in items[:topk]:
            law_info = item.get("law_info") or {}
            rev = item.get("revision_info") or {}
            law_id = law_info.get("law_id") or ""
            law_num = law_info.get("law_num") or ""
            title = rev.get("law_title") or law_num
            promul = law_info.get("promulgation_date") or ""

            sentences = item.get("sentences") or []
            snippet_parts = []
            for s in sentences[:2]:
                txt = s.get("text") if isinstance(s, dict) else str(s)
                if txt:
                    snippet_parts.append(txt)
            snippet = " ".join(snippet_parts) or title

            hits.append(
                RawHit(
                    source_id=self.source_id,
                    country="JP",
                    level="national",
                    jurisdiction="日本国",
                    title=title,
                    enacted_year=self._extract_year(promul),
                    url=f"https://laws.e-gov.go.jp/law/{law_id}" if law_id else "",
                    snippet=snippet,
                )
            )
        return hits

    @staticmethod
    def _extract_year(date_str: str) -> int | None:
        if not date_str:
            return None
        m = re.search(r"(\d{4})", date_str)
        return int(m.group(1)) if m else None

    # ---------------- full-text fetch ----------------

    # 본문이 매우 긴 법령(예: 地方自治法 > 40만자)을 통째로 들고 다니면 LLM 토큰·메모리
    # 부담이 크다. 한도를 두고 잘라 보낸다 — 발췌 용도로는 충분.
    _FULLTEXT_MAX_CHARS = 50_000

    async def fetch_full_text(self, hit: RawHit) -> str | None:
        """e-Gov v2의 /law_data/{law_id}로 본문(JSON 트리)을 받아 텍스트로 평탄화.

        Stage 1 직접참고(direct) Tier에서 일본 법령 원문을 함께 보여주기 위해 사용한다.
        응답은 {tag, attr, children} 트리 — leaf 문자열을 순서대로 모으면 본문이 된다.
        """
        law_id = self._extract_law_id(hit.url)
        if not law_id:
            return None

        cache_key = {"law_id": law_id, "src": self.source_id, "kind": "fulltext"}
        cached = cache_get("adapter_fulltext", cache_key)
        if cached is not None:
            return cached

        try:
            resp = await self.client.get(
                f"{BASE_URL}/law_data/{law_id}",
                params={"response_format": "json", "law_full_text_format": "json"},
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
        except Exception:
            return None

        text = self._flatten_text(data.get("law_full_text"))
        if not text:
            return None
        if len(text) > self._FULLTEXT_MAX_CHARS:
            text = text[: self._FULLTEXT_MAX_CHARS] + "\n…(이하 생략 — 원문 길이 초과)"

        cache_set("adapter_fulltext", cache_key, text)
        return text

    @staticmethod
    def _extract_law_id(url: str) -> str | None:
        m = re.search(r"/law/([A-Za-z0-9]+)", url or "")
        return m.group(1) if m else None

    @staticmethod
    def _flatten_text(node) -> str:
        """{tag, attr, children} 트리에서 leaf 문자열만 본문 순서대로 모은다."""
        parts: list[str] = []
        # 스택 기반 DFS — 재귀 깊이 폭주 회피.
        stack: list = [node]
        # 자식 순서를 보존하려면 스택에 역순으로 push.
        while stack:
            n = stack.pop()
            if isinstance(n, str):
                s = n.strip()
                if s:
                    parts.append(s)
            elif isinstance(n, dict):
                children = n.get("children") or []
                for ch in reversed(children):
                    stack.append(ch)
            elif isinstance(n, list):
                for ch in reversed(n):
                    stack.append(ch)
        return "\n".join(parts)
