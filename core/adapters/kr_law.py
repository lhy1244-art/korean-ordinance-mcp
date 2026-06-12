"""Korean national law/decree/rule (법령) adapter — law.go.kr DRF OPEN API.

Endpoint: https://www.law.go.kr/DRF/lawSearch.do
Target:   law (법령 — 법률·대통령령·부령·감사원규칙 등)
Auth:     same OC as kr_local. One key, two adapters.

Used by Stage 2 Track A (상위법령 저촉 검토) to surface candidate higher
laws that a draft ordinance might conflict with.

The response envelope is <LawSearch>...<law>...</law>... — item tag is
<law> here too, like kr_local, but the field names use 법령* prefix
instead of 자치법규* and the jurisdiction is the responsible 소관부처명
rather than 지자체기관명.
"""

from __future__ import annotations

import re

import httpx
from lxml import etree
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from core.adapters.base import SearchAdapter
from core.cache import get as cache_get, set as cache_set
from core.config import settings
from core.models import RawHit


BASE_URL = "https://www.law.go.kr/DRF/lawSearch.do"
SERVICE_URL = "https://www.law.go.kr/DRF/lawService.do"
LAW_GO_KR_ROOT = "https://www.law.go.kr"
MST_PARAM_RE = re.compile(r"MST=([0-9]+)")


class KrLawAdapter(SearchAdapter):
    """Korean national legislation (법령) via the official DRF API."""

    source_id = "kr_law"
    country = "KR"
    level = "national"

    async def search(
        self,
        keywords: list[str],
        topk: int = 5,
        year_from: int | None = None,
    ) -> list[RawHit]:
        if not keywords or not settings.law_go_kr_oc:
            return []

        for query in self._candidate_queries(keywords):
            cache_key = {"q": query, "topk": topk, "src": self.source_id}
            cached = cache_get("adapter_search", cache_key)
            if cached:
                return [RawHit.model_validate(h) for h in cached]

            params = {
                "OC": settings.law_go_kr_oc,
                "target": "law",
                "query": query,
                "type": "XML",
                "display": topk,
            }
            resp = await self.client.get(BASE_URL, params=params)
            if resp.status_code != 200:
                continue

            hits = self._parse(resp.content, topk)
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

    def _parse(self, body: bytes, topk: int) -> list[RawHit]:
        try:
            root = etree.fromstring(body)
        except etree.XMLSyntaxError:
            return []

        # Auth failures return <Response><result>...</result></Response>.
        # Successful response: <LawSearch><resultCode>00</resultCode><law>...</law>...
        result_code = (root.findtext("resultCode") or "").strip()
        if result_code and result_code != "00":
            return []

        items = root.findall(".//law")

        hits: list[RawHit] = []
        for item in items[:topk]:
            title = self._text(item, "법령명한글")
            if not title:
                continue

            ministry = self._text(item, "소관부처명")
            law_category = self._text(item, "법령구분명")
            promul = self._text(item, "공포일자")
            detail_link = self._text(item, "법령상세링크")
            revision_type = self._text(item, "제개정구분명")

            url = f"{LAW_GO_KR_ROOT}{detail_link}" if detail_link else ""

            year_match = re.match(r"(\d{4})", promul)
            year = int(year_match.group(1)) if year_match else None

            # Compose jurisdiction with category so the caller can see
            # "법률 · 성평등가족부" at a glance — distinguishing primary law
            # from decrees/rules in mixed results.
            jurisdiction_parts = [law_category, ministry]
            jurisdiction = " · ".join(p for p in jurisdiction_parts if p)

            snippet_bits = [b for b in [law_category, revision_type, promul] if b]
            snippet = " · ".join(snippet_bits) or title

            hits.append(
                RawHit(
                    source_id=self.source_id,
                    country="KR",
                    level="national",
                    jurisdiction=jurisdiction,
                    title=title,
                    enacted_year=year,
                    url=url,
                    snippet=snippet,
                )
            )
        return hits

    async def fetch_full_text(self, hit: RawHit) -> str | None:
        """`lawService.do?target=law&MST=...`로 전문(全文) 본문을 가져온다.

        조문 단위로 평탄화: 장(章) 헤더 + (조 번호·제목·본문 + 항 내용) 순서로
        평문 조립. 평탄화된 본문은 conflict_check LLM이 인용·확인하기 좋다.

        실패 시(키 미설정, MST 못 찾음, 네트워크 오류)는 None 반환 — 호출자가
        snippet 대체.
        """
        if not settings.law_go_kr_oc:
            return None
        m = MST_PARAM_RE.search(hit.url)
        if not m:
            return None
        mst = m.group(1)

        cache_key = {"task": "kr_law_fulltext", "mst": mst}
        cached = cache_get("adapter_fetch", cache_key)
        if cached is not None:
            return cached

        params = {
            "OC": settings.law_go_kr_oc,
            "target": "law",
            "MST": mst,
            "type": "XML",
        }
        try:
            resp = await self._get_with_retry(SERVICE_URL, params=params)
        except Exception:
            return None
        if resp.status_code != 200:
            return None

        try:
            root = etree.fromstring(resp.content)
        except etree.XMLSyntaxError:
            return None

        parts: list[str] = []
        for unit in root.findall(".//조문단위"):
            kind = self._text(unit, "조문여부")
            body = self._text(unit, "조문내용")
            title = self._text(unit, "조문제목")
            if kind == "전문":
                # 장·절 헤더 — 그대로 한 줄로
                if body:
                    parts.append(body)
                continue
            head_line = body
            if title and f"({title})" not in head_line:
                head_line = f"{head_line} ({title})" if head_line else f"({title})"
            if head_line:
                parts.append(head_line)
            for hang in unit.findall("항"):
                hang_text = self._text(hang, "항내용")
                if hang_text:
                    parts.append("  " + hang_text)
        full_text = "\n".join(parts).strip()
        if not full_text:
            return None

        cache_set("adapter_fetch", cache_key, full_text)
        return full_text

    @retry(
        retry=retry_if_exception_type((httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        reraise=True,
    )
    async def _get_with_retry(self, url: str, params: dict) -> httpx.Response:
        """Transient ConnectError/Timeout 발생 시 지수 backoff로 최대 3회 재시도.

        law.go.kr DRF가 가끔 연결을 거절하는데 보통 1~2초 후 회복. 영구 실패는
        그대로 재전파해 호출자가 None으로 폴백.
        """
        return await self.client.get(url, params=params)

    @staticmethod
    def _text(item: etree._Element, tag: str) -> str:
        el = item.find(tag)
        if el is None or el.text is None:
            return ""
        return el.text.strip()
