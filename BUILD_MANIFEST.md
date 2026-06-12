# 공개 빌드 매니페스트

이 폴더는 `scripts/build_public.py`로 *비공개 저장소에서 추출*한 결과입니다.

- 복사된 파일: **70건**
- 제외된 파일: **100건**
- 빌드 시각: 2026-06-12 15:29:46

## 제외 규칙 (요약)

- `core/review_only/` 전체 (비공개 검토 트랙)
- `.env`, 자격증명, 캐시 (`data/cache*`, `data/outputs/`)
- 의회 자료 (`*.hwpx`, `*.hwp`, `*.pdf`, `data/council_materials/`)
- 비공개 노트 (`README_PRIVATE.md`, `NEXT_SESSION.md`, `claude_desktop_config.review.example.json`)
- 캐시·임시 파일 (`__pycache__/`, `.venv/`, `.pytest_cache/`)

## 다음 단계

```bash
cd korean-ordinance-mcp
git init
git add .
git commit -m "Initial public release — 바이브코딩 실습 과제 제출"
git remote add origin <공개 저장소 URL>
git push -u origin main
```

Vercel 배포:
1. Vercel 대시보드 → Add New Project → Import Git Repository
2. **Root Directory** = `public_demo`
3. Framework Preset = "Other"
4. Deploy
