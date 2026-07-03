# Market Metrics Automation

## 목적
`market_metrics.json`을 사람이 직접 작성하는 구조에서 벗어나, 시계열 데이터 입력값을 기반으로 자동 계산하는 구조로 전환한다.

## 현재 반영 구조

```text
app/data/source_snapshots/market_series_sample.json
        ↓
scripts/build_market_metrics.py
        ↓
app/data/market_metrics.json
        ↓
app/reasoning.html
```

## 계산 지표

축종별로 다음 값을 계산한다.

- 가격 전월 대비
- 공급 전월 대비
- 가격 전년동월 대비
- 공급 전년동월 대비
- 계절 수요 가중치
- 질병 변수 영향도
- 시장신호 점수
- 데이터 신뢰도

## 시장신호 점수 계산 개념

현재는 설명 가능한 휴리스틱 방식이다.

```text
기준점수 50
+ 가격 전월 대비 상승/하락 영향
+ 공급 전년 대비 감소/증가 영향
+ 질병 변수
+ 계절 수요
- 돈육의 경우 재고 부담 감점
```

점수는 0~100 범위로 제한한다.

## GitHub Actions

`.github/workflows/update-market-metrics.yml`이 추가되어 있다.

실행 방식:

- 수동 실행: GitHub Actions > Update Market Metrics > Run workflow
- 자동 실행: 매일 22:00 UTC 기준

## 현재 한계

현재 `market_series_sample.json`은 샘플/수동 스냅샷이다.

다음 단계에서 필요한 작업:

1. KREI OASIS 가격 데이터 다운로드 또는 수집기 연결
2. KREI OASIS 도축·도계량 데이터 다운로드 또는 수집기 연결
3. 대한양계협회 닭 지육가 수집기 연결
4. KAHIS/농식품부 질병 이슈 수집기 연결
5. 수집 성공/실패 상태를 `market_metrics.json`에 기록
6. 화면에서 실제값과 샘플값을 구분 표시

## 운영 원칙

- 내부 매입단가, 재고, 계약물량, 벤더 정보는 자동수집 대상에서 제외한다.
- 공개 출처 데이터만 사용한다.
- 숫자가 없는 뉴스는 가격 판단의 1차 근거가 아니라 보조 근거로만 사용한다.
- 지표 산출 방식은 사용자가 설명할 수 있도록 단순하고 투명해야 한다.
