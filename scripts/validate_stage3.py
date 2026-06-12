"""Stage 3 검증: 제정안·개정안 두 모드 동시 테스트.

제정안: '청년 1인가구 사회적 고립 예방' 정책 의도 → 새 조례
개정안: 의용소방대 조례 본문 + '재난피해 복구 지원 활동 경비 신설' 의도
        → 일부개정조례안 + 신·구조문대비표
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from core.pipeline.stage3_drafting import draft_amend, draft_new
from core.review_only.utils.hwpx_reader import read_hwpx


DEFAULT_MATERIALS_DIR = Path(
    r"C:\Users\Usery\.art work(2)\제388회 임시회(2026.2) 안건 및 검토보고서"
)


async def test_new() -> None:
    print("\n" + "=" * 60)
    print("[Test 1] 제정안 모드")
    print("=" * 60)
    intent = (
        "경기도에 거주하는 청년 1인가구의 사회적 고립을 예방하고 "
        "사회관계망을 강화하기 위한 지원 정책의 법적 근거를 마련하고자 한다. "
        "지원사업·시설·예산 근거를 모두 포함."
    )
    report = await draft_new(
        policy_intent=intent,
        title="경기도 청년 1인가구 사회적 고립 예방 및 지원 조례",
        delegation_law="「지방자치법」 제28조",
    )
    print(f"[요약] {report.summary}")
    print(f"[오류] {report.errors or '없음'}")

    if not report.draft:
        print("(draft 생성 실패)")
        return

    d = report.draft
    print(f"\n--- 제목: {d.title}")
    print(f"--- 위임 근거: {d.delegation_law}")
    print(f"\n--- 1. 제안이유 ---")
    print(d.proposal_reason[:800])
    print(f"\n--- 2. 주요내용 ---")
    for c in d.main_contents:
        print(f"  {c}")
    print(f"\n--- 3. 조문 ({len(d.articles)}개) ---")
    for a in d.articles[:6]:
        print(f"\n  {a.get('label', '?')}({a.get('title', '')})")
        body_preview = a.get("body", "")[:300]
        print(f"    {body_preview}")
    print(f"\n--- 부칙 ---")
    print(d.addendum)


async def test_amend() -> None:
    print("\n\n" + "=" * 60)
    print("[Test 2] 개정안 모드 — 의용소방대 조례 가상 개정")
    print("=" * 60)

    materials_dir = Path(os.environ.get("COUNCIL_MATERIALS_DIR", DEFAULT_MATERIALS_DIR))
    existing_fp = materials_dir / "2614. 경기도 의용소방대 설치 및 운영 조례 일부개정조례안.hwpx"
    existing_doc = read_hwpx(existing_fp)
    # 일부개정조례안에는 신·구조문대비표가 있어 대표 조문이 포함됨 → 그대로 입력
    intent = (
        "의용소방대원의 처우 개선을 위해 화재 등 재난 출동 시 위험수당을 "
        "월정액으로 지급할 수 있는 근거를 신설하고, 정기 건강검진 지원 항목을 추가하자."
    )

    report = await draft_amend(
        existing_ordinance=existing_doc.body[:5000],
        amendment_intent=intent,
        title="경기도 의용소방대 설치 및 운영 조례 일부개정조례안",
    )
    print(f"[요약] {report.summary}")
    print(f"[오류] {report.errors or '없음'}")

    if not report.draft:
        print("(draft 생성 실패)")
        return

    d = report.draft
    print(f"\n--- 제목: {d.title}")
    print(f"\n--- 1. 제안이유 ---")
    print(d.proposal_reason[:600])
    print(f"\n--- 2. 주요내용 ---")
    for c in d.main_contents:
        print(f"  {c}")

    print(f"\n--- 3. 신·구조문대비표 ({len(report.diffs)}행) ---")
    print(f"{'조항':<20} {'유형':<10} 비고")
    print("-" * 60)
    for diff in report.diffs:
        print(f"{diff.article_label:<20} {diff.change_type:<10} {diff.note[:60]}")
        print(f"  현 행: {diff.current_text[:200]}")
        print(f"  개정안: {diff.revised_text[:200]}")
        print()


async def main() -> int:
    await test_new()
    await test_amend()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
