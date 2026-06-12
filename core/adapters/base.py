from abc import ABC, abstractmethod

import httpx

from core.config import settings
from core.models import RawHit


class SearchAdapter(ABC):
    """Common interface for all jurisdiction data sources."""

    source_id: str
    country: str
    level: str

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._owns_client = client is None
        # Several sources (EUR-Lex, law.go.kr) return error pages or empty
        # bodies when the request lacks browser-shaped headers. We send a
        # full set as the default so each adapter doesn't have to.
        self.client = client or httpx.AsyncClient(
            timeout=settings.request_timeout_seconds,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0 Safari/537.36"
                ),
                "Accept": (
                    "text/html,application/xhtml+xml,application/xml;q=0.9,"
                    "*/*;q=0.8"
                ),
                "Accept-Language": "en-US,en;q=0.9,ko;q=0.8",
            },
            follow_redirects=True,
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    async def __aenter__(self) -> "SearchAdapter":
        return self

    async def __aexit__(self, *exc) -> None:
        await self.aclose()

    @abstractmethod
    async def search(
        self,
        keywords: list[str],
        topk: int = 5,
        year_from: int | None = None,
    ) -> list[RawHit]:
        """Search this source for keywords. Returns at most topk hits."""

    async def fetch_full_text(self, hit: RawHit) -> str | None:
        """Fetch full text for a hit. Default: return whatever raw_text was already populated."""
        return hit.raw_text or None
