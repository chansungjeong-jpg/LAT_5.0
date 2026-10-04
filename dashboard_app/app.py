"""LAT 5.0 cockpit (Streamlit). Same layout language as the short dashboard.

Local evidence only: reads saved artifacts and the market DB read-only.
No orders, no notifications, no data collection. Observation tool -- not a
buy recommendation (see final_spec ch.2: no probability / EV claims).
"""
import sys
from datetime import datetime
from html import escape
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from dashboard_app.charts import price_chart  # noqa: E402
from lat5 import dashboard_data as dd  # noqa: E402
from lat5.candidate_board import latest_decision_by_symbol  # noqa: E402

DB_PATH = ROOT / "data" / "lat5_market.db"

st.set_page_config(page_title="LAT 5.0 | 관찰 · 매수", page_icon="📈", layout="wide",
                   initial_sidebar_state="collapsed")
st.html("""<script>
document.documentElement.lang = 'ko';
document.documentElement.setAttribute('translate', 'no');
document.documentElement.classList.add('notranslate');
document.body.classList.add('notranslate');
</script>""", unsafe_allow_javascript=True)
st.markdown("""<style>
.stApp {background:#0b1424;color:#dce7f6}
[data-testid="stHeader"] {background:#0b1424}
[data-testid="stSidebar"] {background:#101c30}
.block-container {padding-top:2rem;max-width:1800px}
[data-testid="stMetric"] {background:#101c30;border:1px solid #26364e;border-radius:12px;padding:12px}
[data-testid="stMetricValue"] {font-size:1.55rem}
[data-baseweb="tab-list"] {gap:24px;border-bottom:1px solid #26364e}
[data-baseweb="tab"] {color:#c1cee0;font-size:17px}
[aria-selected="true"][data-baseweb="tab"] {color:#5eead4}
.lat-header {display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:12px}
.lat-brand {font-size:28px;font-weight:800;letter-spacing:3px}
.lat-badge {background:#162c37;color:#5eead4;border:1px solid #2a5361;border-radius:20px;padding:7px 13px;font-size:13px}
.lat-band {border:1px solid #26364e;border-radius:14px;background:#101c30;padding:14px 18px;margin-bottom:14px}
.lat-band.go {border-left:6px solid #22c55e}
.lat-band.hold {border-left:6px solid #eab308}
.lat-band.stop {border-left:6px solid #ef4444}
.lat-verdict {font-size:22px;font-weight:700;display:flex;align-items:center;gap:10px}
.lat-why {color:#94a3b8;font-size:13px;margin-top:2px}
.lat-funnel {display:flex;flex-direction:column;gap:4px;margin-top:12px}
.lat-step {display:grid;grid-template-columns:132px 1fr 58px;align-items:center;gap:10px;font-size:13px}
.lat-step .label {color:#c1cee0;text-align:right}
.lat-step .track {background:#16243a;border-radius:6px;height:16px;overflow:hidden}
.lat-step .fill {background:#2a6f7f;height:100%;border-radius:6px}
.lat-step.dead .fill {background:#7f2a37}
.lat-step.dead .label {color:#fca5a5;font-weight:700}
.lat-step .count {color:#dce7f6;font-variant-numeric:tabular-nums}
.lat-chips {display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}
.lat-chip {background:#16243a;border:1px solid #26364e;border-radius:18px;padding:4px 12px;font-size:13px;color:#c1cee0}
.lat-chip b {color:#dce7f6;font-size:15px;margin-left:4px}
</style>""", unsafe_allow_html=True)

with st.sidebar:
    st.header("화면 설정")
    refresh_sec = st.slider("자동 갱신(초)", 10, 300, 60, step=10)
    st.caption("화면 갱신은 데이터 수집이 아닙니다. 저장된 산출물과 DB만 읽습니다.")

COMPONENT_LABELS = {
    "volume": "거래량", "m60_location": "60분 위치", "daily_ma_reaction": "일봉 이평 반응",
    "weekly_trend": "주봉 추세", "slope": "기울기", "recent_5d_bullish": "최근 5일 양봉",
    "daily_trend_persistence": "일봉 추세 지속", "daily_sma5_distance": "5선 이격",
    "decline_rebound_slope": "하락 후 반등 기울기",
}


def fmt_price(value):
    return "확인 불가" if value is None else f"{float(value):,.0f}"


def fmt_pct(value, digits=2):
    return "확인 불가" if value is None else f"{float(value) * 100:+.{digits}f}%"


def fmt_volume(ratio):
    if ratio is None:
        return "확인 불가"
    value = float(ratio)
    label = "증가" if value >= 1.2 else "보통" if value >= 0.8 else "감소"
    return f"{value:.2f}배({label})"


def eligible_text(flag):
    return "가능" if flag is True else "불가" if flag is False else "미평가"


def read_text(path):
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError:
        return None


def render_band(band, funnel, as_of, now):
    stages = funnel["stages"]
    peak = max([s["건수"] for s in stages if s["건수"]] or [1])
    bars, chips = "", ""
    for step in stages:
        count = step["건수"]
        width = 0 if not count else max(3, round(count / peak * 100))
        dead = " dead" if count == 0 else ""
        shown = "확인 불가" if count is None else count
        bars += (f'<div class="lat-step{dead}"><span class="label">{escape(step["단계"])}</span>'
                 f'<span class="track"><span class="fill" style="width:{width}%"></span></span>'
                 f'<span class="count">{shown}</span></div>')
        chips += f'<span class="lat-chip">{escape(step["단계"])}<b>{shown}</b></span>'
    st.markdown(
        f'<div class="lat-band {band["level"]} notranslate">'
        f'<div class="lat-verdict">{escape(band["verdict"])}</div>'
        f'<div class="lat-why">{escape(band["why"])} │ 기준일 {escape(str(as_of))} · '
        f'조회 {now:%m-%d %H:%M:%S} KST · 주문/알림 실행 없음</div>'
        f'<div class="lat-funnel">{bars}</div><div class="lat-chips">{chips}</div></div>',
        unsafe_allow_html=True)


def watch_workspace(board, decisions):
    left, center, right = st.columns([1.05, 2.8, 1.15], gap="medium")
    with left:
        st.subheader("관찰 후보", help="월봉10·주봉5 회복 통과 종목. 매수확률 순위가 아니며 RS 순으로 정렬합니다.")
        sectors = sorted({r.sector or "미분류" for r in board})
        sector = st.selectbox("섹터", ["전체"] + sectors, key="watch_sector")
        rows = [r for r in board if sector == "전체" or (r.sector or "미분류") == sector]
        if not rows:
            st.info("해당 조건의 후보가 없습니다.")
            return
        names = {r.ticker: r for r in rows}
        ticker = st.selectbox("종목", list(names), format_func=lambda t: f"{names[t].name or t} · {t}",
                              key="watch_ticker")
        selected = names[ticker]
        st.dataframe(pd.DataFrame([{
            "종목": r.name or r.ticker, "섹터": r.sector or "미분류", "RS": fmt_pct(r.rs),
            "위치점수": "미평가" if r.location_score is None else str(r.location_score),
            "매수": eligible_text(r.entry_eligible), "잠정": "예" if r.provisional else "",
        } for r in rows]), width="stretch", hide_index=True)
    decision = dd.decision_for(selected.ticker, decisions) or {}
    with center:
        st.subheader(f"{selected.name or ticker}  ·  {ticker}")
        frame = dd.with_moving_averages(dd.load_daily_frame(DB_PATH, ticker, limit=200))
        if frame.empty:
            st.caption("확인 불가 · 일봉 데이터를 읽지 못했습니다.")
        else:
            levels = [
                (decision.get("breakout_entry_price"), "저항돌파 진입가", "#22c55e"),
                (decision.get("breakout_stop_price"), "손절(지지)", "#ef4444"),
                (decision.get("breakout_target_price"), "목표(2차저항)", "#fbbf24"),
            ]
            st.plotly_chart(price_chart(frame, f"{selected.name or ticker} 일봉 · 5/20/60일선", levels),
                            width="stretch")
            st.caption(f"마지막 일봉 {frame['date'].iloc[-1]} · 점선은 위치점수 판정이 계산한 가격(없으면 표시 안 함)")
    with right:
        st.subheader("판정 근거")
        score = selected.location_score
        st.metric("위치점수", "미평가" if score is None else f"{score}/100",
                  help="미평가는 0점이 아닙니다. 해당 종목에 60분 눌림 셋업이 아직 없다는 뜻입니다.")
        st.write(f"**상태** {selected.final_state or '미평가'} · **매수** {eligible_text(selected.entry_eligible)}")
        st.write(f"**RS** {fmt_pct(selected.rs)} · **20일 수익률** {fmt_pct(selected.stock_return)}")
        st.write(f"**거래량(7일평균대비)** {fmt_volume(selected.volume_ratio)}")
        st.write(f"**진입가** {fmt_price(selected.breakout_entry_price)} · **RR** "
                 f"{'확인 불가' if selected.breakout_rr is None else f'{selected.breakout_rr:.2f}'}")
        st.write("**차단 사유** " + (", ".join(selected.vetoes) or "없음"))
        components = decision.get("score_components") or {}
        if components:
            st.dataframe(pd.DataFrame([{"항목": COMPONENT_LABELS.get(k, k), "점수": v}
                                       for k, v in components.items()]),
                         width="stretch", hide_index=True)
        reaction = decision.get("daily_ma_reaction") or {}
        if reaction:
            st.caption(f"일봉 이평 반응: {reaction.get('reaction')} · 5일 상태 {reaction.get('five_day_state')} "
                       f"· RSI {fmt_price(reaction.get('rsi14'))}")


def location_tab(decisions, board):
    latest = sorted(latest_decision_by_symbol(decisions).values(),
                    key=lambda d: d.get("location_score") or -1, reverse=True)[:20]
    passed = {r.ticker for r in board}
    st.caption("60분 눌림 셋업이 발생한 종목의 최신 위치점수 Top 20. 매수확률이 아닙니다. "
               "'회복 통과'가 아닌 종목은 1차 필터(월10·주5)를 통과하지 못해 관찰 후보·매수 가능 집계에서 제외됩니다.")
    if not latest:
        st.caption("해당 기록 없음")
        return
    st.dataframe(pd.DataFrame([{
        "순위": i, "종목코드": d.get("symbol"), "종목명": d.get("name"),
        "회복 통과": "✓" if d.get("symbol") in passed else "—",
        "위치점수": "미평가" if d.get("location_score") is None else str(d["location_score"]), "상태": d.get("final_state"),
        "매수": eligible_text(d.get("entry_eligible")),
        "진입가": fmt_price(d.get("breakout_entry_price")), "손절": fmt_price(d.get("breakout_stop_price")),
        "목표": fmt_price(d.get("breakout_target_price")),
        "RR": "확인 불가" if d.get("breakout_rr") is None else f'{d["breakout_rr"]:.2f}',
        "차단 사유": ", ".join(d.get("vetoes") or []) or "없음",
    } for i, d in enumerate(latest, start=1)]), width="stretch", hide_index=True)


def rs_tab(rs_payload):
    rows = (rs_payload or {}).get("rows") or []
    if not rows:
        st.caption("확인 불가 · RS 산출물이 없습니다.")
        return
    market = rs_payload.get("market_return")
    st.caption(f"기준일 {rs_payload.get('as_of')} · {rs_payload.get('days')}거래일 · 시장 대리수익률 {fmt_pct(market)}")
    st.dataframe(pd.DataFrame([{
        "순위": i, "종목코드": r.get("ticker"), "종목명": r.get("name"),
        "종목 수익률": fmt_pct(r.get("stock_return")), "RS(시장대비)": fmt_pct(r.get("rs")),
    } for i, r in enumerate(rows[:30], start=1)]), width="stretch", hide_index=True)


def system_tab(data_date, payloads):
    c1, c2, c3 = st.columns(3)
    c1.metric("DB 최신 일봉", data_date or "확인 불가")
    c2.metric("위치 판정 건수", len(payloads.location_decisions))
    c3.metric("관찰 목록", "확인 불가" if payloads.universe is None else payloads.universe)
    health = read_text(ROOT / "reports" / "data_health_latest.md")
    st.subheader("데이터 건강성")
    st.markdown(health or "확인 불가 · reports/data_health_latest.md 없음")
    reports = sorted((ROOT / "reports" / "pipeline_health").glob("*.md")) if (ROOT / "reports" / "pipeline_health").exists() else []
    st.subheader("파이프라인 아침 점검")
    st.markdown(read_text(reports[-1]) if reports else "점검 리포트 없음")
    if payloads.issues:
        st.warning("산출물 읽기 실패: " + ", ".join(str(i.get("source")) for i in payloads.issues))


@st.fragment(run_every=refresh_sec)
def body():
    now = datetime.now()
    payloads = dd.load_payloads(ROOT)
    data_date = dd.latest_data_date(DB_PATH)
    board = []
    if payloads.filter_payload is not None:
        board = dd.build_board((payloads.filter_payload or {}).get("rows", []),
                               (payloads.rs_payload or {}).get("rows", []), payloads.location_decisions)
    funnel = dd.build_funnel(universe=payloads.universe, board=board)
    band = dd.status_band(funnel, board, data_date=data_date, today=now.date(),
                          issues=payloads.issues, now_time=now.time())
    as_of = (payloads.filter_payload or {}).get("as_of") or "확인 불가"
    st.markdown('<div class="lat-header"><div class="lat-brand">LAT 5.0</div>'
                '<span class="lat-badge">관찰용 · 주문/알림 없음</span></div>', unsafe_allow_html=True)
    render_band(band, funnel, as_of, now)
    watch_tab, location_tab_, rs_tab_, system_tab_ = st.tabs(["관찰 후보", "위치점수 상세", "RS 순위", "시스템 상태"])
    with watch_tab:
        watch_workspace(board, payloads.location_decisions)
    with location_tab_:
        location_tab(payloads.location_decisions, board)
    with rs_tab_:
        rs_tab(payloads.rs_payload)
    with system_tab_:
        system_tab(data_date, payloads)


body()
