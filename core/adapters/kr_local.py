"""Korean local ordinance (자치법규) adapter — law.go.kr DRF OPEN API.

Endpoint: https://www.law.go.kr/DRF/lawSearch.do
Target:   ordin (자치법규)
Auth:     ?OC={user_id} — issued at open.law.go.kr (free). The caller's IP/domain
          must be registered with that OC; otherwise the API returns
          "사용자 정보 검증에 실패하였습니다".

Sign-up flow (one-time, ~5 min):
  1. https://open.law.go.kr 가입
  2. OPEN API 신청 → 본인 IP/도메인 등록
  3. 발급된 OC 값을 .env의 LAW_GO_KR_OC에 저장
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


class KrLocalAdapter(SearchAdapter):
    """Korean local government ordinances via the official DRF API."""

    source_id = "kr_local"
    country = "KR"
    level = "local"

    async def search(
        self,
        keywords: list[str],
        topk: int = 5,
        year_from: int | None = None,
    ) -> list[RawHit]:
        if not keywords:
            return []
        if not settings.law_go_kr_oc:
            # No key configured. Return empty so the pipeline degrades gracefully
            # — Stage 1 still works with other adapters.
            return []

        for query in self._candidate_queries(keywords):
            cache_key = {"q": query, "topk": topk, "src": self.source_id}
            cached = cache_get("adapter_search", cache_key)
            if cached:
                return [RawHit.model_validate(h) for h in cached]

            params = {
                "OC": settings.law_go_kr_oc,
                "target": "ordin",
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

        # Auth/validation failure responses use a different envelope:
        #   <Response><result>...</result><msg>...</msg></Response>
        # A successful 자치법규 search returns:
        #   <OrdinSearch>
        #     <resultCode>00</resultCode>
        #     <law id="1"> ... </law>
        #     ...
        #   </OrdinSearch>
        # (Yes, ordinance items are tagged <law> inside <OrdinSearch>.)
        result_code = (root.findtext("resultCode") or "").strip()
        if result_code and result_code != "00":
            return []

        items = root.findall(".//law")

        hits: list[RawHit] = []
        for item in items[:topk]:
            title = self._text(item, "자치법규명")
            if not title:
                continue

            jurisdiction = self._text(item, "지자체기관명")
            promul = self._text(item, "공포일자")
            detail_link = self._text(item, "자치법규상세링크")
            revision_type = self._text(item, "제개정구분명")

            # The response gives a relative link like
            # "/DRF/lawService.do?OC=...&target=ordin&MST=...&type=HTML". Use it as-is.
            url = f"{LAW_GO_KR_ROOT}{detail_link}" if detail_link else ""

            # 공포일자 is YYYYMMDD without separators.
            year_match = re.match(r"(\d{4})", promul)
            year = int(year_match.group(1)) if year_match else None

            snippet_bits = [b for b in [jurisdiction, revision_type, promul] if b]
            snippet = " · ".join(snippet_bits) or title

            hits.append(
                RawHit(
                    source_id=self.source_id,
                    country="KR",
                    level="local",
                    jurisdiction=jurisdiction,
                    title=title,
                    enacted_year=year,
                    url=url,
                    snippet=snippet,
                )
            )
        return hits

    async def fetch_full_text(self, hit: RawHit) -> str | None:
        """`lawService.do?target=ordin&MST=...`로 자치법규 전문(全文)을 가져온다.

        자치법규 응답은 `<조>` 요소 안에 `<조내용>`이 이미 항·호를 포함한 본문을
        담고 있어 별도 항 평탄화가 필요 없다. 조 단위로 줄바꿈만 넣어 합친다.

        실패 시(키 미설정, MST 못 찾음, 네트워크 오류) None.
        """
        if not settings.law_go_kr_oc:
            return None
        m = MST_PARAM_RE.search(hit.url)
        if not m:
            return None
        mst = m.group(1)

        cache_key = {"task": "kr_local_fulltext", "mst": mst}
        cached = cache_get("adapter_fetch", cache_key)
        if cached is not None:
            return cached

        params = {
            "OC": settings.law_go_kr_oc,
            "target": "ordin",
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
        for jo in root.findall(".//조"):
            content = self._text(jo, "조내용")
            if content:
                parts.append(content)
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
        """ConnectError·timeout 3회 재시도 (지수 backoff). kr_law와 동일 정책."""
        return await self.client.get(url, params=params)

    @staticmethod
    def _text(item: etree._Element, tag: str) -> str:
        el = item.find(tag)
        if el is None or el.text is None:
            return ""
        return el.text.strip()
