# HESEB Livestock Terminal 운영 구조

## 목표
HESEB Livestock Terminal은 단순 뉴스 모음이 아니라, 공개 데이터를 기반으로 국내 축산시장 흐름을 빠르게 파악하고 보고서 작성까지 이어지는 Market Intelligence Platform을 목표로 한다.

## 전체 구조

```text
GitHub Actions = 데이터 수집 / 지표 계산 / 보고서 생성
JSON = 수집·계산 결과를 화면과 연결하는 데이터 계층
GitHub Pages = 사용자가 보는 Dashboard 화면
```

## 데이터 흐름

```text
정해진 시간에 GitHub Actions 실행
        ↓
KREI / KAPE / 대한양계협회 / KAHIS / 농식품부 등 공개 데이터 수집
        ↓
source_snapshots 생성
        ↓
전주·전월·전년 비교, 증감률, 이상치 탐지
        ↓
market_metrics.json 생성
        ↓
AI 시황 분석용 reasoning JSON 생성
        ↓
GitHub Pages Dashboard 자동 반영
        ↓
보고서 / PPT / 메일 초안 생성으로 확장
```

## 개발 단계

### 1단계: 수기/반자동 JSON
현재 단계.

- `market_dashboard.json`
- `market_metrics.json`
- `market_reasoning.json`
- `source_links.json`
- `score_rules.json`

수기 또는 샘플 데이터 기반으로 화면 구조와 지표 구조를 검증한다.

### 2단계: GitHub Actions 기반 자동 갱신
진행 중.

- `source_registry.json`으로 공식 출처 관리
- `collect_public_sources.py`로 출처별 수집 상태 생성
- `build_market_metrics.py`로 지표 자동 계산
- `update-market-metrics.yml`로 정기 실행

우선순위:

1. 대한양계협회 닭 지육가
2. KREI OASIS 한우/돼지 지육가
3. KREI OASIS 도축·도계량
4. KAHIS / 농식품부 질병 이슈
5. KAPE / 여기고기 등 추가 가격 참고 지표

### 3단계: 지표 계산 자동화
목표:

- 전주 대비
- 전월 대비
- 전년동월 대비
- 증감률
- 이동평균
- 이상치 탐지
- 가격과 공급의 방향성 동조 여부
- 시장신호 점수 산출
- 데이터 신뢰도 산출

현재 반영:

- 전월 대비 계산
- 전년동월 대비 구조
- 시장신호 점수
- 데이터 신뢰도
- 단위 표기
- 점수 산식 페이지

### 4단계: Dashboard 자동 반영
목표:

- GitHub Actions가 생성한 JSON을 GitHub Pages가 자동 표시
- 축종별 핵심지표 카드 자동 갱신
- 점수 구간 표시
- 단위·증감률·해석 표시
- 출처키 표시

현재 반영:

- `terminal.html`에서 `market_metrics.json` 직접 표시
- 한우/돈육/계육 카드에 가격·도축/도계량 표시
- 상세 화면에 점수 산출 근거 표시

### 5단계: 뉴스 연계
목표:

뉴스는 가격 판단의 1차 근거가 아니라, 지표 판단을 보강하는 보조 근거로 사용한다.

뉴스 표시 기준:

- 링크
- 제목
- 날짜
- 출처
- 관련 축종
- 관련 카테고리
- 관련도 점수
- 1~2줄 요약

뉴스 카테고리:

- 가격
- 수급
- 질병
- 정책
- 유통
- 가공
- 소비
- 신제품
- 기업동향

### 6단계: AI 시황 분석 엔진
목표:

지표와 뉴스를 연결해 국내산 시황 문장을 자동 생성한다.

분석 구조:

```text
가격 변화
+
도축/도계량 변화
+
질병·정책 변수
+
계절 수요
+
관련 뉴스
=
시황 요약 / 원인 / 영향 / 전망
```

표현 원칙:

- 확정 표현 금지
- 가능성, 관찰, 요인, 신호, 전망 표현 사용
- 내부 매입가, 재고, 계약물량, 벤더 정보 노출 금지

### 7단계: 보고서 자동 생성
목표:

사용자가 매주 작성하는 시황보고 흐름을 자동화한다.

산출물:

- 팀장님 스타일 시황보고 문장
- 축종별 요약
- 근거 데이터 표
- PPT 초안
- 메일 초안

보고서 구성:

```text
1. 축종별 시장신호
2. 가격/수급 핵심지표
3. 주요 원인
4. 부위별 영향
5. 단기 전망
6. 참고 기사/공식자료
```

## 운영 원칙

- 공개 데이터만 사용한다.
- 내부 매입단가, 재고, 계약물량, 벤더 정보는 표시하지 않는다.
- 뉴스는 보조 근거로 사용한다.
- 가격과 수급 데이터가 1차 판단 기준이다.
- 점수 산식은 설명 가능해야 한다.
- 수집 실패 시 기존 정상 데이터를 유지한다.
- 모든 수집 상태는 `fetch_status.json`에 남긴다.

## 현재 주요 파일

```text
app/terminal.html                     화면 메인
app/metrics.html                      숫자 기반 핵심지표
app/score.html                        시장신호 산식
app/reasoning.html                    AI 판단근거
app/data/market_dashboard.json         시장 요약
app/data/market_metrics.json           핵심지표
app/data/market_reasoning.json         근거 연결 구조
app/data/score_rules.json              점수 산식
app/data/source_registry.json          공식 출처 등록부
app/data/source_links.json             자료출처 허브
app/data/source_snapshots/             수집 스냅샷
scripts/collect_public_sources.py      공식 출처 수집 상태
scripts/build_market_metrics.py        지표 계산 엔진
.github/workflows/update-market-metrics.yml 정기 자동 실행
```
