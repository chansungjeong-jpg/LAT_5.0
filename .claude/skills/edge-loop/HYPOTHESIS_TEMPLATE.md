# 가설 등록 양식

```
## H-NNN: <한 줄 제목>

- 등록일: YYYY-MM-DD
- 근거: (왜 이게 될 것 같은지, 1~3문장)
- 변경 범위: (edge_validation.py에 추가할 함수/필드 1개. "기존 함수 수정"이면 반려)
- 예상 부호: (이 가설이 맞다면 어느 방향으로 수치가 움직여야 하는지, 결과 보기 전에 적을 것)
- 채택 기준: SKILL.md 규칙4 그대로 — train·holdout 부호 일관 + 독립블록≥2 + net 개선. 이 가설만의 특별 기준을 추가하려면 여기 등록 시점에 적고 이후 변경 금지.
- train 구간: YYYY-MM-DD ~ YYYY-MM-DD (holdout 시작 전날까지)
- holdout 구간: YYYY-MM-DD ~ YYYY-MM-DD (세션 캘린더 최근 5거래일)
- 상태: REGISTERED | FAILED_TRAIN | PENDING_HOLDOUT | RESOLVED
```

상태 전이는 SKILL.md "절차" 3~5단계 참고. `RESOLVED`가 되면 `adopted.md` 또는 `failures.md`로 옮기고 여기서는 상태만 남긴다(중복 기록 안 함).
