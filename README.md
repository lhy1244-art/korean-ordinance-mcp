# 경기도의회 입법 지원 도구 — 성안 트랙 (공개)

> 바이브코딩 실습 과제 제출용. Claude 기반 MCP 도구로 *조례 성안 워크플로우 4단계*를
> 자동화한다. 한 정책 의도에서 시작해 입법례 스크리닝 → 결정 카드 → 초안 작성 →
> 자동 셀프 점검까지.

🌐 **데모 갤러리**: [public_demo/index.html](public_demo/index.html) — 정적 페이지로
*경기도 노인 디지털 격차 해소* 케이스 스터디 + 4단계 산출물 다운로드.

## 4단계 워크플로우

| 단계 | 도구 (MCP) | 산출물 |
|---|---|---|
| 성안1 · 발굴 | `screen_overseas_examples_tool` | 5개 관할(한·일·영·EU·미) 입법례 보고서 (.docx + .md) |
| 성안2 · 결정 | (Python API) `extract_decision_cards` | 결정 카드 (.docx + .md) — *환각 방지* 근거 매핑 |
| 성안3 · 만들기 | `draft_new_ordinance_tool`, `draft_amendment_tool` | 제정안/일부개정안 .docx — *경기도의회 표준 양식*, 신·구조문대비표 자동 |
| 성안4 · 셀프 점검 | (Python API) `run_self_check` | *별도 검증 에이전트*가 결정값 모순·환각 인용·표준 구조 누락·오탈자·개정안 정합성을 자동 환기 |

## 멘토링 피드백 적용 결과

| # | 피드백 | 본 도구 적용 |
|---|---|---|
| 1 | Cowork ❌ → Claude Code ✅ | 전 과정 Claude Code 개발 |
| 2 | 단일 HTML ❌ → 파일 분리 | `core/adapters` `core/llm` `core/pipeline` `core/templates` 모듈 분리, `public_demo/`는 Vercel 정적 배포 |
| 3 | AI PDF 추출 → opendataloader/직접 추출 | pdfplumber·PyMuPDF·kordoc로 직접 추출. LLM 토큰 최소화 |
| 4 | **검증 에이전트** 도입 | ⭐ `core/llm/relevance_filter.py`(1단계 무관 결과 자동 제거) + `core/llm/self_check.py`(초안 모순 자동 적발) |

## 환각 방지 패턴

- **1단계 결과 카드 근거 매핑** — 결정 카드 선택지의 *근거 타지자체*는 실제 검색 결과의 jurisdiction만. 없으면 정직하게 "근거 없음".
- **초안 셀프 점검** — 결정값과 조문 간 모순, 인용된 법령·조례명이 실재하는지(환각 의심 인용), 표준 구조 누락 등을 *별도 LLM 호출*로 검증.
- **개정안 정합성 점검** — 지시문 ↔ 신·구조문대비표 ↔ 본문 사이의 불일치를 자동 적발 (예: 조 번호 재배치 순환참조 위험).
- 모든 산출물 끝에 *AI 보조 결과* 면책 안내 자동 첨부.

## 설치

### 1) 사전 준비
- Python 3.11+
- [`uv`](https://docs.astral.sh/uv/) 권장
- Claude Desktop 또는 Claude Code

### 2) 의존성 설치
```bash
git clone <이 저장소 URL> ./legislation-tool
cd ./legislation-tool
uv sync
```

### 3) `.env` 설정
```bash
cp .env.example .env
```

필수:
- `LAW_GO_KR_OC` — 국가법령정보센터 OPEN API 키 (https://open.law.go.kr — 무료)
- `ANTHROPIC_API_KEY` — https://console.anthropic.com/ 에서 발급

### 4) Claude Desktop에 등록
`%APPDATA%\Claude\claude_desktop_config.json` (macOS는 `~/Library/Application Support/Claude/...`)에 [`claude_desktop_config.example.json`](claude_desktop_config.example.json) 내용을 병합.

Claude Desktop 재시작 후 *성안 도구 5종*이 자연어로 호출 가능.

## 노출 MCP 도구

| 도구 | 단계 |
|---|---|
| `screen_overseas_examples_tool` | 성안1 |
| `search_domestic_ordinances` | 보조 검색 |
| `search_higher_korean_laws` | 보조 검색 |
| `draft_new_ordinance_tool` | 성안3 (제정안 + 자동 셀프 점검) |
| `draft_amendment_tool` | 성안3 (일부개정안 + 신·구조문대비표 + 자동 셀프 점검) |

(*결정 카드 추출*은 현재 Python API 호출만 — 추후 MCP 도구 노출 예정)

## 기술 스택

Python 3.11+ / FastMCP / Claude Sonnet 4.x (Anthropic API) / pydantic v2 / python-docx / diskcache / 국가법령정보센터 OPEN API / e-Gov 法令API v2 / legislation.gov.uk / EUR-Lex / govinfo.gov

## 라이선스

MIT (예정 — 멘토 상의 후 확정)

## 면책 안내

⚠️ 본 도구의 모든 산출물은 LLM 보조 생성 결과입니다. 정식 입법 절차에서 사용 시 *입법조사관·법제관의 검토*를 반드시 거쳐야 합니다.
