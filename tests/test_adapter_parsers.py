"""Tests for adapter parse methods using captured fixtures.

Fixtures are real responses captured by scripts/capture_fixtures.py.
Tests exercise the parser only (no network) — they verify each adapter
turns its source's wire format into RawHit records correctly.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.adapters.eu_eurlex import EuEurLexAdapter
from core.adapters.jp_egov import JpEgovAdapter
from core.adapters.kr_law import KrLawAdapter
from core.adapters.kr_local import KrLocalAdapter
from core.adapters.uk_legislation import UkLegislationAdapter
from core.adapters.us_govinfo import UsGovInfoAdapter

FIXTURES = Path(__file__).parent / "fixtures"


def _load_json(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _load_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _load_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


# ---------------- jp_egov ----------------

def test_jp_egov_parses_hits_with_expected_fields() -> None:
    data = _load_json("jp_egov_search.json")
    adapter = JpEgovAdapter()
    try:
        hits = adapter._parse(data, topk=3)
    finally:
        pass  # adapter owns its http client only when used as context manager
    assert len(hits) > 0
    for h in hits:
        assert h.source_id == "jp_egov"
        assert h.country == "JP"
        assert h.level == "national"
        assert h.title
        assert h.url.startswith("https://laws.e-gov.go.jp/law/")


# ---------------- uk_legislation ----------------

def test_uk_legislation_parses_atom_feed() -> None:
    body = _load_bytes("uk_legislation_search.xml")
    adapter = UkLegislationAdapter()
    hits = adapter._parse_atom(body, topk=5)
    assert len(hits) > 0
    for h in hits:
        assert h.source_id == "uk_legislation"
        assert h.country == "UK"
        assert h.title, f"empty title for url={h.url}"
        assert h.url
        # Year may be None for very old/undated entries, so don't assert presence.


def test_uk_legislation_excludes_retained_eu_law() -> None:
    """The /primary/ scope should not surface EU-origin instruments."""
    body = _load_bytes("uk_legislation_search.xml")
    adapter = UkLegislationAdapter()
    hits = adapter._parse_atom(body, topk=10)
    for h in hits:
        assert "/eur/" not in h.url, f"EU regulation leaked: {h.url}"
        assert "/eudn/" not in h.url, f"EU decision leaked: {h.url}"
        assert "/eudr/" not in h.url, f"EU directive leaked: {h.url}"


def test_uk_legislation_handles_bilingual_welsh_titles() -> None:
    """Welsh Acts (asc) use <title type='xhtml'> with English + Welsh spans —
    the parser should pull the English half, not return an empty title."""
    body = _load_bytes("uk_legislation_search.xml")
    adapter = UkLegislationAdapter()
    hits = adapter._parse_atom(body, topk=10)
    welsh_hits = [h for h in hits if "/asc/" in h.url or "/anaw/" in h.url]
    if welsh_hits:
        for h in welsh_hits:
            assert h.title.strip(), f"empty title on bilingual entry: {h.url}"


# ---------------- eu_eurlex ----------------

def test_eu_eurlex_parses_search_html() -> None:
    html = _load_text("eu_eurlex_search.html")
    adapter = EuEurLexAdapter()
    hits = adapter._parse(html, topk=5)
    assert len(hits) > 0
    for h in hits:
        assert h.source_id == "eu_eurlex"
        assert h.country == "EU"
        assert h.level == "supranational"
        assert h.title and h.title != "pdf"  # the old bug: PDF download anchors had title 'pdf'
        assert "CELEX" in h.url
        assert h.enacted_year is None or 1950 <= h.enacted_year <= 2099


def test_eu_eurlex_picks_main_title_not_format_link() -> None:
    """Regression guard: a previous version of the parser grabbed PDF/HTML
    download anchors and ended up with titles like '&nbsp;pdf'."""
    html = _load_text("eu_eurlex_search.html")
    adapter = EuEurLexAdapter()
    hits = adapter._parse(html, topk=10)
    for h in hits:
        assert "pdf" != h.title.lower().strip()
        assert "html" != h.title.lower().strip()
        # PDF anchor URLs include /TXT/PDF/ — main title links don't.
        assert "/TXT/PDF/" not in h.url
        assert "/TXT/HTML/" not in h.url


# ---------------- us_govinfo ----------------

def test_us_govinfo_parses_search_results() -> None:
    data = _load_json("us_govinfo_search.json")
    adapter = UsGovInfoAdapter()
    hits = adapter._parse(data, topk=3)
    assert len(hits) > 0
    for h in hits:
        assert h.source_id == "us_govinfo"
        assert h.country == "US"
        assert h.level == "national"
        assert h.title
        assert h.url.startswith("https://www.govinfo.gov/app/details/")


def test_us_govinfo_filters_to_legislation_collections() -> None:
    """The query filter restricts to PLAW/BILLS/USCODE — verify we don't
    surface unrelated collections like CHRG (Congressional Hearings)."""
    data = _load_json("us_govinfo_search.json")
    adapter = UsGovInfoAdapter()
    hits = adapter._parse(data, topk=10)
    for h in hits:
        # collectionCode is rendered into jurisdiction
        assert "CHRG" not in h.jurisdiction, f"hearing leaked: {h.title}"
        assert "CREC" not in h.jurisdiction, f"Cong. Record leaked: {h.title}"


# ---------------- kr_local ----------------

def test_kr_local_parses_drf_xml_response() -> None:
    body = _load_bytes("kr_local_search.xml")
    adapter = KrLocalAdapter()
    hits = adapter._parse(body, topk=5)
    assert len(hits) > 0
    for h in hits:
        assert h.source_id == "kr_local"
        assert h.country == "KR"
        assert h.level == "local"
        assert h.title
        # 자치법규상세링크 is a relative path under law.go.kr.
        assert h.url.startswith("https://www.law.go.kr/DRF/lawService.do")
        # 지자체기관명 (e.g. "경기도 가평군") should populate jurisdiction.
        assert h.jurisdiction


# ---------------- kr_law ----------------

def test_kr_law_parses_drf_xml_response() -> None:
    body = _load_bytes("kr_law_search.xml")
    adapter = KrLawAdapter()
    hits = adapter._parse(body, topk=5)
    assert len(hits) > 0
    for h in hits:
        assert h.source_id == "kr_law"
        assert h.country == "KR"
        assert h.level == "national"  # national law, not local
        assert h.title
        assert h.url.startswith("https://www.law.go.kr/DRF/lawService.do")
        # 법령구분명 + 소관부처명 are joined into jurisdiction (e.g. "법률 · 성평등가족부")
        assert h.jurisdiction
        assert "·" in h.jurisdiction or h.jurisdiction  # at minimum non-empty


def test_kr_law_jurisdiction_includes_law_category() -> None:
    """The jurisdiction should let a caller distinguish 법률 from 대통령령/부령 etc."""
    body = _load_bytes("kr_law_search.xml")
    adapter = KrLawAdapter()
    hits = adapter._parse(body, topk=10)
    # The fixture queries '청소년' which surfaces 법률 + 시행령 + 시행규칙.
    categories = {h.jurisdiction.split(" · ")[0] for h in hits if " · " in h.jurisdiction}
    assert categories, "expected at least one categorized hit"


def test_kr_law_returns_empty_on_auth_failure() -> None:
    error_body = (
        b'<?xml version="1.0" encoding="UTF-8"?>'
        b"<Response><result>auth failed</result></Response>"
    )
    adapter = KrLawAdapter()
    assert adapter._parse(error_body, topk=3) == []


def test_kr_law_parser_returns_empty_on_invalid_xml() -> None:
    adapter = KrLawAdapter()
    assert adapter._parse(b"not xml", topk=3) == []
    assert adapter._parse(b"", topk=3) == []


def test_kr_local_returns_empty_on_auth_failure_envelope() -> None:
    """When the OC/IP combination is invalid the API returns a <Response>
    error envelope instead of <OrdinSearch>. The parser must not raise."""
    error_body = (
        b'<?xml version="1.0" encoding="UTF-8"?>'
        b"<Response><result>\xec\x82\xac\xec\x9a\xa9\xec\x9e\x90 \xec\xa0\x95\xeb\xb3\xb4 "
        b"\xea\xb2\x80\xec\xa6\x9d\xec\x97\x90 \xec\x8b\xa4\xed\x8c\xa8\xed\x95\x98\xec\x98\x80"
        b"\xec\x8a\xb5\xeb\x8b\x88\xeb\x8b\xa4.</result><msg>OC missing</msg></Response>"
    )
    adapter = KrLocalAdapter()
    assert adapter._parse(error_body, topk=3) == []


# ---------------- malformed input ----------------

@pytest.mark.parametrize(
    "adapter_cls, parse_call",
    [
        (JpEgovAdapter, lambda a: a._parse({}, topk=3)),
        (JpEgovAdapter, lambda a: a._parse({"items": []}, topk=3)),
        (UsGovInfoAdapter, lambda a: a._parse({}, topk=3)),
        (UsGovInfoAdapter, lambda a: a._parse({"results": []}, topk=3)),
        (EuEurLexAdapter, lambda a: a._parse("", topk=3)),
        (EuEurLexAdapter, lambda a: a._parse("<html></html>", topk=3)),
    ],
)
def test_parser_returns_empty_on_empty_or_malformed(adapter_cls, parse_call) -> None:
    adapter = adapter_cls()
    assert parse_call(adapter) == []


def test_uk_parser_returns_empty_on_invalid_xml() -> None:
    adapter = UkLegislationAdapter()
    assert adapter._parse_atom(b"not xml at all", topk=3) == []
    assert adapter._parse_atom(b"", topk=3) == []


def test_kr_local_parser_returns_empty_on_invalid_xml() -> None:
    adapter = KrLocalAdapter()
    assert adapter._parse(b"not xml", topk=3) == []
    assert adapter._parse(b"", topk=3) == []
