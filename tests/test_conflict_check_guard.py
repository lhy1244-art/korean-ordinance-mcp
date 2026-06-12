"""Hallucination guard 단위 테스트.

_quote_present는 LLM이 인용한 evidence_quote가 실제 후보 본문에 들어있는지
확인한다. 한국 법령 텍스트는 동등한 의미의 다른 유니코드 문장부호(예: ㆍ vs ·)가
자주 등장해, 단순 substring 검사는 false-positive 환각 의심을 낸다.
이 테스트가 그런 정규화 케이스를 잠근다.
"""

from __future__ import annotations

from core.review_only.llm.conflict_check import _quote_present


def test_short_quote_always_present() -> None:
    assert _quote_present("a", "anything")
    assert _quote_present("법", "")


def test_exact_substring_present() -> None:
    src = "제14조(경비의 부담) 의용소방대의 운영과 활동에 필요한 경비는 시도지사가 부담한다."
    assert _quote_present("의용소방대의 운영과 활동", src)


def test_whitespace_differences_normalized() -> None:
    src = "의용소방대의\n운영과   활동에 필요한 경비"
    assert _quote_present("의용소방대의 운영과 활동에 필요한 경비", src)


def test_korean_araea_middle_dot_treated_as_ascii_middle_dot() -> None:
    """원문은 'ㆍ' (U+318D), LLM은 '·' (U+00B7)으로 인용하는 경우가 잦음."""
    src = "시ㆍ도지사 또는 시ㆍ군의 장은 부담한다"
    assert _quote_present("시·도지사 또는 시·군의 장은 부담한다", src)


def test_japanese_katakana_middle_dot_normalized() -> None:
    src = "市・町・村が負担する"
    # ・ (U+30FB) vs · (U+00B7) — 같은 의미로 봐서 통과
    assert _quote_present("市·町·村が負担する", src)


def test_smart_quotes_normalized() -> None:
    src = '법령은 "필요한 경비"를 부담한다'
    assert _quote_present("법령은 “필요한 경비”를 부담한다", src)


def test_legal_brackets_normalized() -> None:
    """한국 법령은 「」, 일본 법령은 『』를 자주 사용. LLM이 직접 인용 시 큰따옴표로
    바꿔쓰는 일이 흔해 일치 검사가 깨진다. 둘 다 표준 따옴표로 통일."""
    src = "「의용소방대 설치 및 운영에 관한 법률」 제14조"
    assert _quote_present('"의용소방대 설치 및 운영에 관한 법률" 제14조', src)


def test_truly_absent_quote_returns_false() -> None:
    src = "이 조례는 청년 1인가구 지원에 관한 사항을 규정한다."
    assert not _quote_present("이 조례는 화재진압 의무를 규정한다", src)


def test_dash_variants_normalized() -> None:
    src = "2014-11-19 개정"
    assert _quote_present("2014–11–19 개정", src)  # en dash → hyphen
