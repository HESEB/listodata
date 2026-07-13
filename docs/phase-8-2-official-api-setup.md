# Phase 8-2 공식 API 인증·통계표 URL 설정 가이드

## 목적

Phase 8-1에서 준비한 실제 공식 데이터 연결기에 KOSIS와 공공데이터포털 호출 URL을 안전하게 주입한다.

인증키와 서비스키는 저장소 파일, 이슈, 화면, 커밋에 직접 기록하지 않는다. GitHub Actions Secret에 전체 호출 URL을 저장한다.

## 등록할 Secret

| Secret 이름 | 용도 |
|---|---|
| `KOSIS_LIVESTOCK_INVENTORY_API_URL` | 가축동향조사 사육마릿수 |
| `KOSIS_LIVESTOCK_PRODUCTION_API_URL` | 축산 생산·도축 통계 |
| `DATA_GO_KR_LIVESTOCK_MARKET_API_URL` | 가격·경락·수입 API |

## 1. KOSIS 인증키 신청

1. KOSIS 공유서비스에 로그인한다.
2. `활용신청`에서 OpenAPI 인증키를 신청한다.
3. 승인된 인증키를 확인한다.
4. `개발 가이드 > 통계자료`에서 사용할 통계표를 찾는다.
5. 통계표 ID, 기관 ID, 항목, 분류, 조회기간을 확정한다.

공식 시작 페이지: `https://kosis.kr/openapi/index/index.jsp`

## 2. KOSIS 호출 URL 작성

KOSIS 개발 가이드에서 제공하는 통계자료 API 형식에 맞춰 전체 HTTPS URL을 작성한다.

예시 형식이며 실제 값은 KOSIS 화면에서 확인한 값으로 교체한다.

```text
https://kosis.kr/openapi/Param/statisticsParameterData.do?method=getList&apiKey=<인증키>&itmId=<항목ID>&objL1=<분류값>&format=json&jsonVD=Y&prdSe=<주기>&startPrdDe=<시작기간>&endPrdDe=<종료기간>&orgId=<기관ID>&tblId=<통계표ID>
```

필수 확인 항목:

- URL이 `https://`로 시작하는지
- `apiKey`가 포함됐는지
- `orgId`, `tblId`가 실제 통계표와 일치하는지
- `format=json` 또는 JSON 응답 설정이 있는지
- 조회기간이 너무 길지 않은지
- 브라우저 테스트 결과에 `PRD_DE`, `DT`, `ITM_NM` 또는 분류명이 포함되는지

## 3. 공공데이터포털 활용신청

1. 공공데이터포털에서 필요한 축산 가격·경락·수입 API를 찾는다.
2. `활용신청`을 완료한다.
3. 마이페이지에서 일반 인증키 또는 Encoding 인증키를 확인한다.
4. 해당 데이터의 상세 활용가이드에서 엔드포인트와 요청변수를 확인한다.
5. JSON 응답을 지원하면 `_type=json` 또는 데이터별 JSON 요청 변수를 사용한다.

공식 포털: `https://www.data.go.kr/`

예시 형식:

```text
https://apis.data.go.kr/<기관>/<서비스>/<오퍼레이션>?serviceKey=<서비스키>&pageNo=1&numOfRows=100&_type=json
```

데이터별 요청변수와 응답 필드는 서로 다르므로 상세 활용가이드를 기준으로 작성한다.

## 4. GitHub Actions Secret 등록

저장소에서 다음 경로로 이동한다.

```text
Settings
→ Secrets and variables
→ Actions
→ New repository secret
```

Secret 이름은 대소문자까지 정확히 입력한다. 값에는 인증키만 넣는 것이 아니라 테스트가 끝난 **전체 HTTPS 호출 URL**을 입력한다.

## 5. Actions 실행

```text
Actions
→ Update market data
→ Run workflow
→ Run workflow
```

예상 실행 순서:

```text
Validate official API setup
→ Collect real official source data
→ Collect official metrics
→ Quality·Direction·Recommendation
```

## 6. 결과 확인

- 설정 가이드: `app/official-api-setup-guide.html`
- 실제 연결 상태: `app/real-official-sources.html`
- 수집 상태: `app/official-data-collector.html`
- Admin 2.0: `app/admin2-dashboard.html`

상태 의미:

| 상태 | 의미 |
|---|---|
| `ready` | Secret 존재 및 기본 URL 형식 정상 |
| `credential_required` | Secret 미등록 |
| `invalid_url` | HTTPS 또는 필수 파라미터 부족 |
| `success` | 실제 API 호출 및 매핑 성공 |
| `empty` | 호출 성공, 유효 매핑 0건 |
| `failed` | 호출 또는 파싱 실패 |

## 보안 원칙

- 인증키가 포함된 URL을 저장소 파일에 쓰지 않는다.
- Actions 로그에 전체 URL을 출력하지 않는다.
- 화면에는 Secret 존재 여부와 마스킹된 호스트만 표시한다.
- 인증키가 노출됐으면 즉시 폐기하고 재발급한다.
- Secret 값 변경 후에는 Workflow를 다시 실행한다.
