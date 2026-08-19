from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "artifacts" / "latest_scoring" / "backtest_diagnostics.json"
OUTPUT = ROOT / "dashboard" / "index.html"


def _text(value: object, default: str = "-") -> str:
    if value is None or value == "":
        return default
    return html.escape(str(value))


def _price(value: object, default: str = "-") -> str:
    if value is None or value == "":
        return default
    return html.escape(f"{float(value):,.0f}")


def _ratio(value: object, default: str = "-") -> str:
    if value is None or value == "":
        return default
    return html.escape(f"{float(value):.2f}")


def build_dashboard(input_path: Path = INPUT, output_path: Path = OUTPUT) -> Path:
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    diagnostics = payload.get("diagnostics", {})
    rows = [row for row in diagnostics.get("location_decisions", []) if isinstance(row, dict)]
    eligible_count = sum(row.get("entry_eligible") is True for row in rows)
    rows.sort(key=lambda row: float(row.get("location_score", -1)), reverse=True)
    rows = rows[:20]

    rendered_rows: list[str] = []
    for rank, row in enumerate(rows, start=1):
        daily = row.get("daily_ma_reaction") or {}
        components = row.get("score_components") or {}
        vetoes = ", ".join(str(value) for value in row.get("vetoes", [])) or "없음"
        eligible = "가능" if row.get("entry_eligible") is True else "불가"
        eligible_class = "yes" if row.get("entry_eligible") is True else "no"
        rendered_rows.append(
            "<tr>"
            f"<td>{rank}</td>"
            f"<td><strong>{_text(row.get('symbol'))}</strong><br><small>{_text(row.get('name'))}</small></td>"
            f"<td class=score>{_text(row.get('location_score'))}</td>"
            f"<td>{_text(row.get('final_state'))}</td>"
            f"<td class=\"{eligible_class}\">{eligible}</td>"
            f"<td>{_text(components.get('volume'))}</td>"
            f"<td>{_text(components.get('daily_sma5_distance'))}</td>"
            f"<td>{_text(daily.get('rsi14'))}</td>"
            f"<td>{_text(row.get('m60_rsi14'))}</td>"
            f"<td>{_text((row.get('rr_breakdown') or {}).get('rr'))}</td>"
            f"<td>{_price(row.get('breakout_entry_price'))}</td>"
            f"<td>{_price(row.get('breakout_stop_price'))}</td>"
            f"<td>{_price(row.get('breakout_target_price'))}</td>"
            f"<td>{_ratio(row.get('breakout_rr'))}</td>"
            f"<td class=veto>{_text(vetoes)}</td>"
            "</tr>"
        )

    summary = payload.get("summary", {})
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        """<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>LAT 5.0 이평선 트레이딩 시스템</title>
<style>
:root{color-scheme:dark;font-family:Inter,Segoe UI,sans-serif;background:#0b1020;color:#e8eefc}
body{margin:0;background:radial-gradient(circle at top right,#17254b,#0b1020 55%);min-height:100vh}
main{max-width:1500px;margin:auto;padding:34px 24px 50px} header{display:flex;justify-content:space-between;gap:20px;align-items:end;margin-bottom:24px}
h1{margin:0;font-size:30px} .sub{color:#91a2c8;margin-top:8px}.stamp{color:#91a2c8;font-size:13px;text-align:right}
.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:22px}.card{background:#121a30;border:1px solid #263557;border-radius:14px;padding:16px}.label{color:#91a2c8;font-size:12px}.value{font-size:25px;font-weight:700;margin-top:6px}
.panel{background:#10182b;border:1px solid #263557;border-radius:16px;overflow:auto}table{border-collapse:collapse;width:100%;min-width:1650px}th,td{padding:12px 10px;border-bottom:1px solid #22304d;text-align:left;font-size:13px}th{background:#182542;color:#b9c8e8;position:sticky;top:0}td.score{font-size:18px;font-weight:700;color:#78d6ff}td.yes{color:#65e6a0;font-weight:700}td.no{color:#ffbd7a}td.veto{color:#ff9d9d;max-width:260px}small{color:#91a2c8}.note{margin-top:14px;color:#91a2c8;font-size:12px}@media(max-width:800px){main{padding:22px 12px}.cards{grid-template-columns:repeat(2,1fr)}header{display:block}.stamp{text-align:left;margin-top:12px}}
</style></head><body><main>
<header><div><h1>LAT 5.0 이평선 트레이딩 시스템</h1><div class="sub">일봉 방향성 + 60분봉 매수 위치 · Top 20</div></div><div class="stamp">생성: __GENERATED__<br>입력: latest_scoring</div></header>
<section class="cards"><div class="card"><div class="label">위치 판정</div><div class="value">__DECISIONS__건</div></div><div class="card"><div class="label">매수 가능</div><div class="value">__ELIGIBLE__건</div></div><div class="card"><div class="label">거래</div><div class="value">__TRADES__건</div></div><div class="card"><div class="label">데이터 상태</div><div class="value">관찰용</div></div></section>
<section class="panel"><table><thead><tr><th>순위</th><th>종목</th><th>위치점수</th><th>상태</th><th>매수</th><th>거래량</th><th>일봉 5선 이격</th><th>일봉 RSI</th><th>60분 RSI</th><th>손익비</th><th>저항돌파 진입가</th><th>손절(지지)</th><th>목표(2차저항)</th><th>RR(저항돌파)</th><th>차단 사유</th></tr></thead><tbody>__ROWS__</tbody></table></section>
<div class="note">점수 순위는 분석용입니다. Hard Block과 매수 가능 여부를 반드시 함께 확인하세요. RSI는 보조 관찰값이며 점수·게이트에 사용하지 않습니다. 저항돌파 진입가/손절/목표/RR은 눌림 구조가 없을 때도 계산되는 별도 참고값(1차 저항대 돌파 기준)이며, 매수가능 여부(entry_eligible) 판정에는 반영되지 않습니다.</div>
</main></body></html>"""
        .replace("__GENERATED__", generated_at)
        .replace("__DECISIONS__", _text(len(diagnostics.get("location_decisions", [])), "0"))
        .replace("__ELIGIBLE__", _text(eligible_count, "0"))
        .replace("__TRADES__", _text(summary.get("trades"), "0"))
        .replace("__ROWS__", "\n".join(rendered_rows) or '<tr><td colspan="15">데이터 없음</td></tr>'),
        encoding="utf-8",
    )
    return output_path


if __name__ == "__main__":
    print(build_dashboard())
