# 정적 갤러리 (Vercel 배포 대상)

바이브코딩 실습 과제 제출용 — 성안 트랙(공개)의 케이스 스터디·산출물 다운로드 페이지.

## 구조

```
public_demo/
├── index.html              ← 단일 페이지 (Tailwind CDN, 외부 빌드 불필요)
├── vercel.json             ← 캐시·다운로드 헤더 설정
├── downloads/              ← 실제 산출물 .docx / .md
│   ├── stage1_입법례_스크리닝.docx + .md
│   ├── stage2_결정카드.md
│   └── stage3_제정안_셀프점검포함.docx
└── README.md               ← 이 파일
```

## 로컬 미리보기

```bash
cd public_demo
python -m http.server 8000
# 브라우저에서 http://localhost:8000
```

## Vercel 배포

옵션 A — CLI:
```bash
cd public_demo
npx vercel              # 첫 배포 — 프로젝트 생성
npx vercel --prod        # 프로덕션 배포
```

옵션 B — GitHub 연동:
1. 공개 저장소에 `public_demo/` 폴더가 푸시되어 있을 때
2. Vercel 대시보드 → Add New Project → Import Git Repository
3. **Root Directory** 를 `public_demo` 로 지정
4. Framework Preset = "Other" (정적 파일)
5. Deploy

## 멘토 피드백 반영

| 피드백 | 본 페이지 적용 |
|---|---|
| Claude Code 사용 | 페이지 상단 명시 |
| 파일 분리 (단일 HTML 지양) | 코드는 `core/` 모듈 분리 + 본 페이지 자체는 정적 single-page (배포 단순화 우선) |
| AI PDF 추출 지양 | pdfplumber/PyMuPDF/kordoc 명시 |
| **검증 에이전트 도입** | `relevance_filter` + `self_check` 두 모듈 강조 — 실제 발견 사례 인용 |

## 폰트·색감

- 메인 컬러: `#3A2266` (보고서 .docx와 동일 GRI 보라)
- 폰트: Noto Sans KR
- 외부 의존성: Tailwind CDN, Google Fonts CDN뿐 (빌드 단계 없음)
