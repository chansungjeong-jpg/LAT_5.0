"""Plotly figures for the LAT 5.0 cockpit. Dark palette shared with short."""
import plotly.graph_objects as go
from plotly.subplots import make_subplots

PANEL = "#101c30"
GRID = "#233047"
TEXT = "#dce7f6"
_SMA_STYLE = ((5, "#5eead4"), (20, "#fbbf24"), (60, "#c084fc"))
_EMA_COLORS = ("#5eead4", "#fbbf24", "#c084fc")


def _layout(fig, height, title=None, legend=True):
    fig.update_layout(
        template="plotly_dark", height=height, margin=dict(l=5, r=10, t=30, b=5),
        paper_bgcolor=PANEL, plot_bgcolor=PANEL, font=dict(color=TEXT),
        legend=dict(orientation="h", y=1.09) if legend else dict(visible=False),
        xaxis_rangeslider_visible=False,
        title=dict(text=title, font=dict(size=14)) if title else None,
        uirevision=title or "chart",
    )
    fig.update_yaxes(gridcolor=GRID)
    return fig


def _add_levels(fig, levels):
    for price, label, color in levels or []:
        if price is not None:  # unmeasured is not drawn as zero
            fig.add_hline(y=price, line_dash="dot", line_color=color, annotation_text=label, row=1, col=1)


def price_chart(frame, title, levels=None, bars=120):
    """Daily candles. ``frame`` must already carry sma5/sma20/sma60."""
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.8, 0.2], vertical_spacing=0.03)
    if frame.empty:
        return fig
    x = frame["date"]
    fig.add_trace(
        go.Candlestick(x=x, open=frame["open"], high=frame["high"], low=frame["low"], close=frame["close"],
                       name="일봉", increasing_line_color="#ff6577", decreasing_line_color="#619fff"),
        row=1, col=1)
    fig.add_trace(go.Bar(x=x, y=frame["volume"], name="거래량", marker_color="#435d80"), row=2, col=1)
    for window, color in _SMA_STYLE:
        column = f"sma{window}"
        if column in frame:
            fig.add_trace(go.Scatter(x=x, y=frame[column], name=f"{window}일선",
                                     line=dict(color=color, width=1.4)), row=1, col=1)
    _add_levels(fig, levels)
    _layout(fig, 470, title)
    fig.update_xaxes(type="category", nticks=7, gridcolor=GRID)
    fig.update_xaxes(range=[max(0, len(frame) - bars) - 0.5, len(frame) - 0.5])
    fig.update_yaxes(side="right")
    return fig


def intraday_chart(frame, title, ema_spans, bars=240, levels=None):
    """60-minute / 5-minute candles with the EMAs the location score uses.
    ``frame`` carries ``datetime`` (str) and ema<span> columns. The x axis is a
    category axis so overnight/weekend gaps do not stretch the chart."""
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.8, 0.2], vertical_spacing=0.03)
    if frame.empty:
        return fig
    x = frame["datetime"].astype(str)
    fig.add_trace(
        go.Candlestick(x=x, open=frame["open"], high=frame["high"], low=frame["low"], close=frame["close"],
                       name="가격", increasing_line_color="#ff6577", decreasing_line_color="#619fff"),
        row=1, col=1)
    fig.add_trace(go.Bar(x=x, y=frame["volume"], name="거래량", marker_color="#435d80"), row=2, col=1)
    for span, color in zip(ema_spans, _EMA_COLORS):
        column = f"ema{span}"
        if column in frame:
            fig.add_trace(go.Scatter(x=x, y=frame[column], name=f"EMA{span}",
                                     line=dict(color=color, width=1.4)), row=1, col=1)
    _add_levels(fig, levels)
    _layout(fig, 470, title)
    fig.update_xaxes(type="category", nticks=7, gridcolor=GRID)
    fig.update_xaxes(range=[max(0, len(frame) - bars) - 0.5, len(frame) - 0.5])
    fig.update_yaxes(side="right")
    return fig


def count_chart(series):
    """Number of recovery-filter survivors per report date."""
    fig = go.Figure()
    if series.empty:
        return fig
    fig.add_trace(go.Bar(x=series["date"], y=series["passed"] - series["provisional"], name="확정",
                         marker_color="#2a6f7f"))
    fig.add_trace(go.Bar(x=series["date"], y=series["provisional"], name="잠정", marker_color="#a78bfa"))
    fig.update_layout(barmode="stack")
    _layout(fig, 280, "일자별 회복 필터 통과 종목 수")
    fig.update_xaxes(type="category", gridcolor=GRID)
    return fig


def sector_chart(rows):
    """Pass count per sector, coloured by the sector's average RS."""
    rows = [r for r in rows if r["passed"] > 0]
    fig = go.Figure()
    if not rows:
        return fig
    rows = sorted(rows, key=lambda r: r["passed"])
    colors = [("#475569" if r["avg_rs"] is None else ("#ef4444" if r["avg_rs"] > 0 else "#3b82f6"))
              for r in rows]
    labels = []
    for r in rows:
        rate = "" if r["pass_rate"] is None else f" · 통과율 {r['pass_rate'] * 100:.0f}%"
        rs = "RS 확인 불가" if r["avg_rs"] is None else f"평균 RS {r['avg_rs'] * 100:+.1f}%p"
        labels.append(f"{r['passed']}종목 · {rs}{rate}")
    fig.add_trace(go.Bar(y=[r["sector"] for r in rows], x=[r["passed"] for r in rows], orientation="h",
                         marker_color=colors, text=labels, textposition="auto"))
    _layout(fig, max(260, 34 * len(rows) + 60), "섹터별 회복 통과 종목 (색: 평균 RS 빨강=시장 상회 / 파랑=하회)", legend=False)
    fig.update_xaxes(gridcolor=GRID)
    return fig


def rank_chart(history_frame, location_frame, title):
    """RS rank over report dates (1 = strongest, axis inverted) with the days
    the symbol passed the recovery filter marked, and location-score events
    on a second panel. Missing rank is a gap, never zero."""
    fig = make_subplots(rows=2, cols=1, shared_xaxes=False, row_heights=[0.62, 0.38], vertical_spacing=0.14,
                        subplot_titles=("RS 순위 (낮을수록 강함)", "위치점수 판정 이력 (60분 눌림 셋업 발생 시점)"))
    if not history_frame.empty:
        x = history_frame["date"]
        fig.add_trace(go.Scatter(x=x, y=history_frame["rank"], mode="lines+markers", name="RS 순위",
                                 line=dict(color="#5eead4", width=2), connectgaps=False), row=1, col=1)
        passed = history_frame[history_frame["passed"]]
        fig.add_trace(go.Scatter(x=passed["date"], y=passed["rank"], mode="markers", name="회복 통과일",
                                 marker=dict(color="#fbbf24", size=11, symbol="star")), row=1, col=1)
        fig.update_yaxes(autorange="reversed", row=1, col=1)
    if location_frame is not None and not location_frame.empty:
        fig.add_trace(go.Scatter(x=location_frame["evaluated_at"], y=location_frame["location_score"],
                                 mode="markers", name="위치점수", marker=dict(color="#c084fc", size=9),
                                 text=location_frame["final_state"]), row=2, col=1)
        fig.update_yaxes(range=[0, 100], row=2, col=1)
    _layout(fig, 520, title)
    fig.update_xaxes(gridcolor=GRID)
    fig.update_xaxes(type="category", row=1, col=1)
    return fig


def runs_chart(frame):
    """Collection duration per run (unfinished runs have no bar)."""
    fig = go.Figure()
    if frame.empty:
        return fig
    ordered = frame.sort_values("run_id")
    colors = ["#22c55e" if s == "COMPLETE" else "#ef4444" if s == "BLOCKED" else "#eab308"
              for s in ordered["status"]]
    fig.add_trace(go.Bar(x=ordered["run_id"].astype(str), y=ordered["minutes"], marker_color=colors,
                         text=ordered["status"], hovertext=ordered["started_at"]))
    _layout(fig, 260, "수집 run 소요시간(분) — 초록 완료 / 빨강 BLOCKED / 노랑 진행·중단", legend=False)
    fig.update_xaxes(type="category", gridcolor=GRID)
    return fig
