"""Daily candle chart with SMA5/20/60 and the system's own price levels."""
import plotly.graph_objects as go
from plotly.subplots import make_subplots

_SMA_STYLE = ((5, "#5eead4"), (20, "#fbbf24"), (60, "#c084fc"))


def price_chart(frame, title, levels=None, bars=120):
    """``frame`` must already carry sma5/sma20/sma60 columns. ``levels`` is a
    list of ``(price, label, color)``; entries with a missing price are skipped
    (unmeasured is not drawn as zero)."""
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.8, 0.2], vertical_spacing=0.03)
    if frame.empty:
        return fig
    x = frame["date"]
    fig.add_trace(
        go.Candlestick(
            x=x, open=frame["open"], high=frame["high"], low=frame["low"], close=frame["close"],
            name="일봉", increasing_line_color="#ff6577", decreasing_line_color="#619fff",
        ),
        row=1, col=1,
    )
    fig.add_trace(go.Bar(x=x, y=frame["volume"], name="거래량", marker_color="#435d80"), row=2, col=1)
    for window, color in _SMA_STYLE:
        column = f"sma{window}"
        if column in frame:
            fig.add_trace(
                go.Scatter(x=x, y=frame[column], name=f"{window}일선", line=dict(color=color, width=1.4)),
                row=1, col=1,
            )
    for price, label, color in levels or []:
        if price is not None:
            fig.add_hline(y=price, line_dash="dot", line_color=color, annotation_text=label, row=1, col=1)
    fig.update_layout(
        template="plotly_dark", height=470, margin=dict(l=5, r=10, t=30, b=5),
        paper_bgcolor="#101c30", plot_bgcolor="#101c30", font=dict(color="#dce7f6"),
        legend=dict(orientation="h", y=1.09), xaxis_rangeslider_visible=False,
        title=dict(text=title, font=dict(size=14)),
        uirevision=title,
    )
    fig.update_xaxes(type="category", nticks=7, gridcolor="#233047")
    fig.update_xaxes(range=[max(0, len(frame) - bars) - 0.5, len(frame) - 0.5])
    fig.update_yaxes(gridcolor="#233047", side="right")
    return fig
