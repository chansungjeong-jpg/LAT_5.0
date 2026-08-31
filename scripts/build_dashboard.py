from __future__ import annotations

import html
import json
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

INPUT = ROOT / "artifacts" / "latest_scoring" / "backtest_diagnostics.json"
RS_INPUT = ROOT / "artifacts" / "latest_scoring" / "relative_strength.json"
FILTER_INPUT = ROOT / "artifacts" / "latest_scoring" / "monthly_weekly_filter.json"
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


def _pct(value: object, default: str = "-") -> str:
    if value is None or value == "":
        return default
    return html.escape(f"{float(value) * 100:+.2f}%p")


def _render_candidate_board(
    filter_path: Path, rs_path: Path, location_decisions: list[dict]
) -> str:
    from lat5.candidate_board import build_candidate_board

    if not filter_path.exists():
        return ""
    filter_payload = json.loads(filter_path.read_text(encoding="utf-8"))
    rs_payload = (
        json.loads(rs_path.read_text(encoding="utf-8")) if rs_path.exists() else {}
    )
    board = build_candidate_board(
        filter_rows=filter_payload.get("rows", []),
        rs_rows=rs_payload.get("rows", []),
        location_decisions=location_decisions,
    )

    rendered = []
    for rank, row in enumerate(board, start=1):
        vetoes = ", ".join(row.vetoes) or "없음"
        if row.entry_eligible is True:
            eligible, eligible_class = "가능", "yes"
        elif row.entry_eligible is False:
            eligible, eligible_class = "불가", "no"
        else:
            eligible, eligible_class = "미판정", "no"
        rendered.append(
            "<tr>"
            f"<td>{rank}</td>"
            f"<td><strong>{_text(row.ticker)}</strong><br><small>{_text(row.name)}</small></td>"
            f"<td>{_text(row.sector)}</td>"
            f"<td class=score>{_pct(row.rs)}</td>"
            f"<td>{_text(row.location_score)}</td>"
            f"<td>{_text(row.final_state)}</td>"
            f"<td class=\"{eligible_class}\">{eligible}</td>"
            f"<td>{_price(row.breakout_entry_price)}</td>"
            f"<td>{_ratio(row.breakout_rr)}</td>"
            f"<td class=veto>{_text(vetoes)}</td>"
            "</tr>"
        )

    eligible_total = sum(1 for row in board if row.entry_eligible is True)
    return f"""
<section class="panel board-panel">
<h2>오늘의 관찰 후보 — {_text(filter_payload.get('as_of'))} ({len(board)}종목)</h2>
<table><thead><tr><th>순위</th><th>종목</th><th>섹터</th><th>RS(시장대비)</th><th>위치점수</th>
<th>상태</th><th>매수</th><th>저항돌파 진입가</th><th>RR</th><th>차단 사유</th></tr></thead>
<tbody>{"".join(rendered) or '<tr><td colspan="10">1차 필터 통과 종목 없음</td></tr>'}</tbody></table>
<div class="note">
<strong>이 표는 매수확률 순위가 아니다.</strong> final_spec 2장이 Probability Score·Expected
Value를 검증 전까지 배제하고 있고, 패턴확률 스캐너도 현재 154종목 중 통계적으로
유의한 종목을 0개로 보고한다. 확률 숫자를 붙이는 대신 실제로 계산된 근거만 싣는다.<br>
포함 기준은 <strong>월봉10·주봉5 회복 1차 필터 통과</strong>(final_spec 0장 불변계약) 하나뿐이며,
필터를 통과하지 못한 종목은 RS가 아무리 강해도 여기 오르지 않는다. 정렬은 이 시스템이
전 종목에 대해 실제로 계산하는 유일한 상대강도(RS) 기준이다.<br>
현재 매수 가능(entry_eligible) 종목: <strong>{eligible_total}건</strong>. 0건은 오류가 아니라
60분 셋업이 아직 없다는 정상 결과다.
</div>
</section>
"""


def _render_relative_strength(rs_path: Path) -> str:
    if not rs_path.exists():
        return ""
    rs_payload = json.loads(rs_path.read_text(encoding="utf-8"))
    rs_rows = rs_payload.get("rows", [])
    market_return = rs_payload.get("market_return")
    market_return_text = (
        f"{float(market_return) * 100:.2f}%" if market_return is not None else "계산불가"
    )
    rendered = []
    for rank, row in enumerate(rs_rows[:10], start=1):
        stock_return_text = f"{float(row.get('stock_return', 0)) * 100:.2f}%"
        rs_text = f"{float(row.get('rs', 0)) * 100:+.2f}%p"
        rendered.append(
            "<tr>"
            f"<td>{rank}</td>"
            f"<td><strong>{_text(row.get('ticker'))}</strong><br><small>{_text(row.get('name'))}</small></td>"
            f"<td>{html.escape(stock_return_text)}</td>"
            f"<td class=score>{html.escape(rs_text)}</td>"
            "</tr>"
        )
    return f"""
<section class="panel rs-panel">
<h2>상대강도(RS) Top10 — {_text(rs_payload.get('as_of'))} ({_text(rs_payload.get('days'))}거래일)</h2>
<table><thead><tr><th>순위</th><th>종목</th><th>종목 수익률</th><th>RS</th></tr></thead>
<tbody>{"".join(rendered) or '<tr><td colspan="4">데이터 없음</td></tr>'}</tbody></table>
<div class="note">시장 대리값(Watchlist {_text(rs_payload.get('universe_size'))}종목 동일가중 평균수익률):
{market_return_text}. <strong>진짜 KOSPI/KOSDAQ 지수 아님</strong> — 지수 차트 TR 코드 미확인 상태의
임시 대리값(`market_proxy_method={_text(rs_payload.get('market_proxy_method'))}`).</div>
</section>
"""


def build_dashboard(
    input_path: Path = INPUT,
    output_path: Path = OUTPUT,
    *,
    rs_path: Path = RS_INPUT,
    filter_path: Path = FILTER_INPUT,
) -> Path:
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    diagnostics = payload.get("diagnostics", {})
    rows = [row for row in diagnostics.get("location_decisions", []) if isinstance(row, dict)]
    eligible_count = sum(row.get("entry_eligible") is True for row in rows)
    board_section = _render_candidate_board(filter_path, rs_path, rows)
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
    rs_section = _render_relative_strength(rs_path)
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
.panel{background:#10182b;border:1px solid #263557;border-radius:16px;overflow:auto}table{border-collapse:collapse;width:100%;min-width:1650px}th,td{padding:12px 10px;border-bottom:1px solid #22304d;text-align:left;font-size:13px}th{background:#182542;color:#b9c8e8;position:sticky;top:0}td.score{font-size:18px;font-weight:700;color:#78d6ff}td.yes{color:#65e6a0;font-weight:700}td.no{color:#ffbd7a}td.veto{color:#ff9d9d;max-width:260px}small{color:#91a2c8}.note{margin-top:14px;color:#91a2c8;font-size:12px}.rs-panel{margin-top:22px;padding:18px}.rs-panel table{min-width:0}.rs-panel h2{margin:0 0 12px;font-size:18px}.board-panel{margin-bottom:26px;padding:18px;border-color:#3a6ea5}.board-panel table{min-width:0}.board-panel h2{margin:0 0 12px;font-size:20px;color:#78d6ff}.section-title{font-size:16px;color:#91a2c8;margin:0 0 10px;font-weight:600}@media(max-width:800px){main{padding:22px 12px}.cards{grid-template-columns:repeat(2,1fr)}header{display:block}.stamp{text-align:left;margin-top:12px}}
</style></head><body><main>
<header><div><h1>LAT 5.0 이평선 트레이딩 시스템</h1><div class="sub">일봉 방향성 + 60분봉 매수 위치 · Top 20</div></div><div class="stamp">생성: __GENERATED__<br>입력: latest_scoring</div></header>
<section class="cards"><div class="card"><div class="label">위치 판정</div><div class="value">__DECISIONS__건</div></div><div class="card"><div class="label">매수 가능</div><div class="value">__ELIGIBLE__건</div></div><div class="card"><div class="label">거래</div><div class="value">__TRADES__건</div></div><div class="card"><div class="label">데이터 상태</div><div class="value">관찰용</div></div></section>
__BOARD_SECTION__
<h2 class="section-title">위치 점수 상세 (Top 20)</h2>
<section class="panel"><table><thead><tr><th>순위</th><th>종목</th><th>위치점수</th><th>상태</th><th>매수</th><th>거래량</th><th>일봉 5선 이격</th><th>일봉 RSI</th><th>60분 RSI</th><th>손익비</th><th>저항돌파 진입가</th><th>손절(지지)</th><th>목표(2차저항)</th><th>RR(저항돌파)</th><th>차단 사유</th></tr></thead><tbody>__ROWS__</tbody></table></section>
<div class="note">점수 순위는 분석용입니다. Hard Block과 매수 가능 여부를 반드시 함께 확인하세요. RSI는 보조 관찰값이며 점수·게이트에 사용하지 않습니다. 저항돌파 진입가/손절/목표/RR은 눌림 구조가 없을 때도 계산되는 별도 참고값(1차 저항대 돌파 기준)이며, 매수가능 여부(entry_eligible) 판정에는 반영되지 않습니다.</div>
__RS_SECTION__
</main></body></html>"""
        .replace("__GENERATED__", generated_at)
        .replace("__DECISIONS__", _text(len(diagnostics.get("location_decisions", [])), "0"))
        .replace("__ELIGIBLE__", _text(eligible_count, "0"))
        .replace("__TRADES__", _text(summary.get("trades"), "0"))
        .replace("__ROWS__", "\n".join(rendered_rows) or '<tr><td colspan="15">데이터 없음</td></tr>')
        .replace("__BOARD_SECTION__", board_section)
        .replace("__RS_SECTION__", rs_section),
        encoding="utf-8",
    )
    return output_path


if __name__ == "__main__":
    print(build_dashboard())
