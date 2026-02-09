# 축산 시황 대시보드 MVP v2 (GitHub Pages + WebView 안정 경로)

## 핵심 변경 (404 해결)
- 데이터 폴더를 `repo-root/data`가 아니라 **`/app/data`** 아래로 넣었습니다.
- 브라우저에서 항상 `./data/...` 상대경로로 읽기 때문에,
  - GitHub Pages(/app 배포)
  - 로컬 파일 서버
  - WebView(앱)
  전부 동일하게 동작합니다.

## 폴더
- `/app` : GitHub Pages 루트
- `/app/data` : 정적 JSON (Actions가 갱신)
- `/scripts` : Actions 실행 스크립트
- `/.github/workflows` : 자동 갱신(이벤트 / 데이터)

## GitHub Pages 설정
Settings → Pages → Deploy from branch → (main) /app

## Actions
- Update Events: 매일 RSS 수집하여 `app/data/events/*.json` 갱신
- Update Data: (현재는 샘플 생성) `app/data/aggregated/species_summary.json` 갱신


## v2.3 운영 패치
- 화면 자동 재조회(업계이슈 5분 / 축종요약 10분)
- 갱신시간 KST/UTC 동시 표시
- RSS 소스별 성공/실패/건수(_sources) 기록 및 화면에 소스 성공개수 표시
- Update Events 스케줄: 3시간마다 실행(운영 안정)


## v2.4 추가 패치
- repo 루트에 문지기 index.html 추가: / → /app/ 리다이렉트
- .nojekyll 추가(README 렌더링 영향 최소화)
- Actions push 충돌 방지: push 전에 `git pull --rebase origin main` 적용(update-events/update-data)


## v2.5 (A안 1차: 실데이터 전환 준비)
- 축종요약 데이터는 `/app/data/aggregated/species_summary.json` 에서 로드됩니다.
- `scripts/update_data.mjs` 추가: (1) sources.json의 URL이 비어있으면 샘플 요약 생성 (2) URL을 채우면 수집 상태를 기록(2차에서 파서 연결)
- `app/data/sources/sources.json` 추가: 대표지표 4종(돈/우/계란/계육) + 선택(환율/곡물) 메타
- `Update Data` 워크플로우 추가: 6시간마다 실행(UTC), push 충돌 방지(rebase)


## v2.6 (OpenAPI 연동 템플릿)
- `app/data/sources/sources.json`에 API 엔드포인트(url)와 params 템플릿이 포함됩니다.
- GitHub Actions Secrets에 다음을 등록하면 자동 갱신됩니다:
  - DATA_GO_KR_SERVICE_KEY
  - KAMIS_CERT_KEY
  - KAMIS_CERT_ID
  - EXIM_AUTHKEY
- `scripts/update_data.mjs`는 JSON/XML 응답을 감지하고, 수집 상태를 `fetch_status`로 기록합니다.
- (다음 단계) 소스별 파서를 연결하면 샘플 대신 실데이터가 current/series로 채워집니다.
