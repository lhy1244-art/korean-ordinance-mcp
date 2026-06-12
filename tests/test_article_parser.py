"""Tests for the Korean ordinance article parser."""

from __future__ import annotations

from core.utils.article_parser import parse_articles


def test_empty_input_returns_empty_list() -> None:
    assert parse_articles("") == []
    assert parse_articles("   \n  ") == []


def test_single_article_with_title() -> None:
    text = "제1조(목적) 이 조례는 청년 1인가구의 사회적 고립 예방을 목적으로 한다."
    arts = parse_articles(text)
    assert len(arts) == 1
    a = arts[0]
    assert a.label == "제1조"
    assert a.number == 1
    assert a.branch is None
    assert a.title == "목적"
    assert "청년 1인가구" in a.body
    assert a.section == "main"


def test_multiple_articles() -> None:
    text = (
        "제1조(목적) 이 조례는 ... 목적으로 한다.\n"
        "\n"
        "제2조(정의) 이 조례에서 사용하는 용어의 뜻은 다음과 같다.\n"
        '1. "청년"이란 19세 이상 39세 이하인 사람을 말한다.\n'
        "\n"
        "제3조(적용범위) 이 조례는 경기도 내에 거주하는 ..."
    )
    arts = parse_articles(text)
    assert [a.label for a in arts] == ["제1조", "제2조", "제3조"]
    assert arts[1].title == "정의"
    # Item line should be captured inside article 2's body, not parsed as its own header
    assert '"청년"이란' in arts[1].body


def test_inserted_article_branch_number() -> None:
    text = (
        "제2조(정의) 정의 내용.\n"
        "제2조의2(추가정의) 추가 정의 내용.\n"
        "제3조(적용) 적용 내용."
    )
    arts = parse_articles(text)
    assert [a.label for a in arts] == ["제2조", "제2조의2", "제3조"]
    assert arts[1].branch == 2
    assert arts[1].title == "추가정의"


def test_article_without_title_parens() -> None:
    text = "제1조 이 조례는 ... 한다.\n제2조(정의) 정의 내용."
    arts = parse_articles(text)
    assert len(arts) == 2
    assert arts[0].label == "제1조"
    assert arts[0].title == ""
    assert "이 조례는" in arts[0].body


def test_addendum_section_flagged() -> None:
    text = (
        "제1조(목적) 본칙 1조 내용.\n"
        "제2조(정의) 본칙 2조 내용.\n"
        "\n"
        "부칙\n"
        "제1조(시행일) 이 조례는 공포한 날부터 시행한다.\n"
        "제2조(경과조치) 경과조치 내용."
    )
    arts = parse_articles(text)
    main = [a for a in arts if a.section == "main"]
    add = [a for a in arts if a.section == "addendum"]
    assert [a.label for a in main] == ["제1조", "제2조"]
    assert [a.label for a in add] == ["제1조", "제2조"]
    assert add[0].title == "시행일"


def test_full_text_round_trip() -> None:
    text = "제1조(목적) 본문 내용이다."
    arts = parse_articles(text)
    assert arts[0].full_text == "제1조(목적) 본문 내용이다."


def test_full_text_without_title() -> None:
    text = "제1조 본문 내용이다."
    arts = parse_articles(text)
    assert arts[0].full_text == "제1조 본문 내용이다."


def test_indented_header_tolerated() -> None:
    text = "   제1조(목적) 들여쓰기된 조항.\n  제2조(정의) 정의."
    arts = parse_articles(text)
    assert [a.label for a in arts] == ["제1조", "제2조"]


def test_text_with_no_article_headers_returns_empty() -> None:
    text = "이 문서는 조례가 아닙니다. 그냥 평범한 메모입니다."
    assert parse_articles(text) == []


def test_body_does_not_include_next_header() -> None:
    text = "제1조(목적) 첫 조문.\n제2조(정의) 두 번째."
    arts = parse_articles(text)
    assert "제2조" not in arts[0].body
    assert "제1조" not in arts[1].body
