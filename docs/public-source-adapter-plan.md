# Public Source Adapter Plan

## 목적
KREI OASIS, 대한양계협회, 농식품부, KAHIS 등 공개 출처를 향후 자동수집할 수 있도록 출처 등록부와 수집 상태 구조를 만든다.

## 이번 단계에서 추가된 구조

```text
app/data/source_registry.json
        ↓
scripts/collect_public_sources.py
        ↓
app/data/source_snapshots/fetch_status.json
        ↓
scripts/build_market_metrics.py
        ↓
app/data/market_metrics.json
```

## 출처 등록부

`app/data/source_registry.json`에는 다음 정보가 들어간다.

- 출처 ID
- 출처명
- 제공기관
- 축종
- URL
- 수집 방식
- 현재 상태
- 연결될 지표
- 메모

## 수집 상태 파일

`fetch_status.json`은 GitHub Actions 실행 시 자동 생성된다.

표시 항목:

- source_id
- provider
- category
- species
- target_metric
- collection_method
- status
- last_checked_at
- url
- memo

현재 상태값:

```text
manual_snapshot_connected
adapter_required
```

## 다음 구현 대상

### 1. KREI OASIS 어댑터
대상:

- 한우 지육가
- 돼지 지육가
- 한우·돼지 도축량
- 닭·오리 도축량

필요 확인:

- CSV/Excel 다운로드 URL
- 요청 파라미터
- 기간 설정 방식
- CORS/세션 여부

### 2. 대한양계협회 어댑터
대상:

- 닭 지육가 9~10호

필요 확인:

- 연도별 URL 구조
- HTML 테이블 파싱 가능 여부
- 9~10호 컬럼 위치

### 3. 농식품부/KAHIS 질병 어댑터
대상:

- AI 보도자료
- ASF 보도자료
- 국내 질병현황

필요 확인:

- 목록 페이지 파라미터
- 제목/날짜/링크 추출 방식
- 축종별 키워드 매칭

## 운영 원칙

- 공식 출처별 어댑터는 한 번에 구현하지 않고 출처별로 분리한다.
- 수집 실패 시 기존 스냅샷과 기존 market_metrics.json을 유지한다.
- 수집 성공/실패 상태는 반드시 fetch_status.json에 남긴다.
- 내부 데이터는 수집 대상에 포함하지 않는다.
