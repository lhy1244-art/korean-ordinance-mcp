"""Parse Korean ordinance text into 조(article) units.

Used by Stage 2 (article-by-article comparison) and Stage 3 (신·구조문대비표).

Korean ordinance structure:
  제1조(목적) 이 조례는 ... 함을 목적으로 한다.
  제2조의2(정의) 이 조례에서 사용하는 ...
  부칙
  제1조(시행일) 이 조례는 공포한 날부터 시행한다.

Parser scope: article-level slicing only. Paragraph(항)/item(호) parsing
is left to consumers — keeping this layer deterministic and small.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal


# Anchored at line start (re.MULTILINE). Captures:
#   (1) article number
#   (2) optional "의N" suffix for inserted articles (제2조의3)
#   (3) optional parenthesized title (제목)
# Tolerates leading whitespace and either ASCII '(' or fullwidth '（'.
# The whole "(title)" group is optional but, when present, must contain
# at least one non-paren character — otherwise a lazy match would pick
# the empty string and leave the literal ')' in the body.
ARTICLE_HEADER = re.compile(
    r"^[ \t]*제\s*(\d+)\s*조(?:\s*의\s*(\d+))?(?:\s*[(（]\s*([^)）\n]+?)\s*[)）])?",
    re.MULTILINE,
)

# Detect the 부칙 section divider. May appear as bare "부칙" or "부 칙" on its own line.
ADDENDUM_DIVIDER = re.compile(r"^[ \t]*부\s*칙[ \t]*$", re.MULTILINE)


Section = Literal["main", "addendum"]


@dataclass(frozen=True)
class Article:
    """One 조 (article) extracted from ordinance text."""

    label: str          # canonical label: "제1조" or "제2조의3"
    number: int         # 1, 2, ...
    branch: int | None  # None, or N for "제2조의N" inserts
    title: str          # parenthesized title text; "" if missing
    body: str           # text between this article header and the next one
    section: Section    # "main" (본칙) or "addendum" (부칙)

    @property
    def full_text(self) -> str:
        """Re-render the article in canonical form, including header."""
        head = self.label
        if self.title:
            head = f"{head}({self.title})"
        body = self.body.strip()
        return f"{head} {body}".rstrip() if body else head


def parse_articles(text: str) -> list[Article]:
    """Slice ordinance text into Article records.

    Returns articles in the order they appear, including 부칙 articles
    flagged with section="addendum". An empty input or text with no
    recognizable 조 headers returns an empty list.
    """
    if not text or not text.strip():
        return []

    # Split into pre-부칙 (본칙) and post-부칙 segments.
    segments: list[tuple[Section, str]] = []
    divider = ADDENDUM_DIVIDER.search(text)
    if divider:
        segments.append(("main", text[: divider.start()]))
        # Skip past the entire matched 부칙 line (including any trailing newline).
        tail_start = divider.end()
        if tail_start < len(text) and text[tail_start] == "\n":
            tail_start += 1
        segments.append(("addendum", text[tail_start:]))
    else:
        segments.append(("main", text))

    articles: list[Article] = []
    for section, segment in segments:
        articles.extend(_parse_section(segment, section))
    return articles


def _parse_section(segment: str, section: Section) -> list[Article]:
    headers = list(ARTICLE_HEADER.finditer(segment))
    if not headers:
        return []

    out: list[Article] = []
    for i, match in enumerate(headers):
        number = int(match.group(1))
        branch_str = match.group(2)
        branch = int(branch_str) if branch_str else None
        title = (match.group(3) or "").strip()

        body_start = match.end()
        body_end = headers[i + 1].start() if i + 1 < len(headers) else len(segment)
        body = segment[body_start:body_end].strip()

        label = f"제{number}조" + (f"의{branch}" if branch is not None else "")

        out.append(
            Article(
                label=label,
                number=number,
                branch=branch,
                title=title,
                body=body,
                section=section,
            )
        )
    return out
