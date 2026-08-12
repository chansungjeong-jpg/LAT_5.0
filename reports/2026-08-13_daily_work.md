# LAT 5.0 일일 업무 — 2026-08-13

## 오늘 구현·검증 — 일봉 SMA 대표반응 Task 6

- SSOT `LAT_SIMPLE_v1_0_final_spec.md`를 최신 승인 설계와 Task 1–5 런타임
  계약에 맞춰 갱신했다.
  - 위치 점수 100점 배점을 거래량 30 / 60분 위치 20 / 일봉 SMA 반응 20 /
    주봉 10 / 일봉 지속성 5 / 기울기 10 / 최근 5일 양봉 5로 확정했다.
  - 완료 일봉만 사용하는 SMA5·SMA20·SMA60 대표반응 우선순위, 20점 상한,
    품질 보너스와 골든크로스 +2, SMA5 종가 이탈 -4 및 다음 완료봉 회복 +6,
    no-lookahead·UNKNOWN 처리 원칙을 기록했다.
  - 이격도·매물대 proxy·RR은 일봉 반응 점수와 독립된 Hard Block이며,
    SMA5 종가 이탈만으로 REJECT하지 않는다는 계약을 유지했다.
- 출력 계약에는 대표반응/기본점수/품질/SMA/5일선 상태, 거래량 점수, 이격 상태,
  매물대 방법·RR 세부값, 최종 상태를 명시했다. 실제 런타임이 제공하지 않는
  Volume Profile 매물대나 보고 필드는 임의 값으로 만들지 않고 `UNKNOWN`/`null`과
  원인으로 남기도록 했다.
- README는 이미 SSOT 링크와 paper-only 경계를 제공하므로 변경하지 않았다.

### 검증

| 명령 | 결과 |
|---|---|
| `python -m pytest tests/test_cli.py -q` | 7 passed |
| `python -m pytest tests/test_daily_ma_reaction.py tests/test_location_score.py tests/test_location_context.py tests/test_location_decision.py tests/test_location_gate_integration.py -q` | 93 passed |
| `python -m pytest -q` | 204 passed |
| `python -m compileall -q src` | exit 0 |
| `git diff --check` | clean |

### 남은 경고와 내일 할 일

1. 현재 위치결정 payload는 `daily_ma_reaction`, `rr_breakdown`, 최종 `state`를
   직렬화하지만, 범용 CLI 기술기준선 보고서는 이 payload를 받지 않는다. 따라서
   이 보고서에 SMA 세부값을 허위로 채우지 않는다.
2. `volume_score`와 `distance_state`의 최종 보고용 직렬화, 실제 Volume Profile
   매물대 값은 아직 별도 구현 대상이다. 현재는 위치 점수 구성요소·raw gap·
   `swing_high_proxy_v1` 방법만 실제로 확인 가능하다.
3. 최신 승인 설계 초안의 `SMA5_HOLD`와 `SMA20_CLOSE_BREAK`는 현재 반응 enum에
   없다. 이 Task 6에서는 문서상 구현 완료로 선언하지 않았으며, 추가 여부는 다음
   설계 승인 후 테스트 우선으로 결정한다.

## 오늘 완료

- 공식 SSOT를 `LAT_SIMPLE_v1_0_final_spec.md`로 정리하고, 기존 ABC를 공식 매수 조건에서 폐기했다.
- 시스템 핵심을 **Watchlist 종목의 차트 위치·거래량·이격도 기반 좋은 매수자리 탐색**으로 확정했다.
- 위치 점수 기반을 구현했다.
  - 주봉·일봉 추세
  - 최근 5일 양봉 수
  - 60분 EMA60·EMA120 위치와 기울기
  - 거래량 최고 비중
  - 이격도·매물대 proxy·손익비 Hard Block
- KOSPI/KOSDAQ 거래대금·상승률 기반 주도주 랭킹 및 Watchlist snapshot 저장 기반을 추가했다.
- 미국 정보는 매수 게이트가 아닌 참고용 특징주 레이더로 축소했다.
  - 미국 특징주 → 섹터 → 국내 대응 Watchlist 후보 매핑
  - 외부 알림·주문·스케줄러 미연결
- 미국 특징주 저장 테이블 `us_featured_stocks`를 추가했다.
- 검증 완료: `python -m pytest -q` 결과 `146 passed`, `python -m compileall -q src` 통과.

## 설계 확정 사항

```text
핵심: Watchlist에서 좋은 매수자리를 점수화해 고른다.
참고: 미국시장·섹터·미국 특징주는 앞단 나침반일 뿐, 매수 확정 근거가 아니다.
```

- 일봉 5일선 이탈은 즉시 제외가 아닌 감점·WATCH다. 다음 날 회복 시 재평가한다.
- 추가 예정: 피봇 저점/고점 연결선, 매물대, 일봉 5·20·60선에서의 상승 반응을 위치 점수에 반영한다.

## 내일 할 일

1. 피봇·이평선 매수자리 점수 설계를 확정한다.
   - 하단 피봇 지지선 반등
   - 상단 피봇 저항/매물대 돌파
   - 20일선 위 반등
   - 60일선 상향 관통 후 장대양봉
   - 5일선 유지 가점, 이탈 감점·회복 재가점
2. 승인된 설계를 SSOT에 반영한 뒤 테스트 우선으로 위치 점수 엔진에 구현한다.
3. 새 위치 점수를 기본 Backtest/CLI 경로에 연결하고, 기존 ABC는 비교용 legacy로만 유지한다.
4. 특징주 외부 알림은 전체 시스템 완료 후 별도 작업으로 진행한다.

## 차단 사항

- 현재 `C:\trading_system\LAT_5.0`은 Git 저장소가 아니며 `.git` 디렉터리와 `gh` CLI가 없다.
- 따라서 이 폴더에서는 커밋·푸시를 수행할 수 없다. Git 원격 저장소 경로 또는 초기화·원격 연결 권한이 필요하다.
