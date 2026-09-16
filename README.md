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

## 현재 운영 경로 (Phase 10.5)
- **주 운영 파이프라인:** `.github/workflows/update-market-data.yml`
  - KOSIS 사전점검 → 목록 후보 → 메타/상세 후보 검증 → 후보 점수·P1/P2/P3 검수 상태 → 승인 JSON 사전점검 → 승인 매핑 생성 → Dry Run → 운영 수집 → 이상치 검수 → DSS 재생성 → Phase 10 최종상태를 한 실행에서 갱신합니다.
- **보조 자동화:** `update-events.yml`, `disease-alert-watch.yml`
- **수동 보조 Workflow:** KOSIS 사전점검·승인 검증·매핑 비교·Dry Run·최종검증 화면용 Workflow
- **레거시 수동 전용:** `update-data.yml`, `update-market-metrics.yml`

KOSIS 상세코드 조사는 `statisticsData.do?method=getMeta&type=ITM` 메타데이터를 사용하고, 후보 조합은 `Param/statisticsParameterData.do` 실제 응답으로 확인합니다. KOSIS 응답의 공식 분류값 필드 `C1`은 내부 승인·운영 계약의 `C1_ID`로 정규화합니다.

승인 매핑은 `kosis_approval_precheck.json`의 `mapping_generation_allowed=true`일 때만 메인 Workflow에서 재생성합니다. 운영 매핑 승격은 별도의 명시적 승인 절차를 유지합니다.

## Actions (레거시 기록)
- Update Events: RSS 수집하여 `app/data/events/*.json` 갱신
- Update Data: 초기 MVP용 집계 경로였으며 Phase 10.5부터 자동 스케줄을 중지하고 수동 호환 점검용으로 유지

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
- GitHub Actions Secrets에 다음을 등록하면 초기 MVP 경로를 수동 검증할 수 있습니다:
  - DATA_GO_KR_SERVICE_KEY
  - KAMIS_CERT_KEY
  - KAMIS_CERT_ID
  - EXIM_AUTHKEY
- `scripts/update_data.mjs`는 JSON/XML 응답을 감지하고, 수집 상태를 `fetch_status`로 기록합니다.
- 현재 운영 DSS는 위 레거시 경로보다 `update-market-data.yml`의 Data First 공식데이터 파이프라인을 우선합니다.
