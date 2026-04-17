"""总览页 — 核心绩效指标 + 净值曲线 + 回撤"""

from __future__ import annotations

import plotly.graph_objects as go
from plotly.subplots import make_subplots
import dash_bootstrap_components as dbc
from dash import html, dcc
import pandas as pd


def layout():
    from qtrade.dashboard.app import get_data

    data = get_data()

    # 无数据或 "准备中" (live 但尚无进度点)
    if data is None:
        return _placeholder()
    if data.result is None:
        if getattr(data, "live", False):
            return _live_placeholder(data)
        return _placeholder()

    is_live = getattr(data, "live", False)
    r = data.result
    m = r.metrics

    # 进度 banner (实时模式时显示)
    live_banner = []
    if is_live:
        bar = getattr(data, "live_bar", 0)
        total = max(getattr(data, "live_total", 0), 1)
        pct = int(100 * bar / total)
        live_banner.append(
            dbc.Alert(
                [
                    dbc.Spinner(size="sm", spinner_class_name="me-2"),
                    f"回测运行中 · 进度 {pct}% ({bar}/{total})"
                    f"  ·  净值 {r.equity_curve.iloc[-1]:,.0f}",
                ],
                color="info",
                className="py-2 px-3 mb-3 d-flex align-items-center",
            )
        )

    # 标题行
    header = html.Div(
        [
            html.H4("策略总览", className="mb-1 d-inline-block"),
            html.Div(
                [
                    dbc.Button(
                        "↓ equity",
                        id={"type": "export-btn", "kind": "equity"},
                        size="sm", color="outline-light", className="me-1",
                    ),
                    dbc.Button(
                        "↓ positions",
                        id={"type": "export-btn", "kind": "positions"},
                        size="sm", color="outline-light", className="me-1",
                    ),
                    dbc.Button(
                        "↓ trades",
                        id={"type": "export-btn", "kind": "trades"},
                        size="sm", color="outline-light", className="me-1",
                    ),
                    dbc.Button(
                        "↓ fills",
                        id={"type": "export-btn", "kind": "fills"},
                        size="sm", color="outline-light",
                    ),
                ],
                className="float-end",
            ) if not is_live else None,
        ],
    )

    info_parts = [data.strategy_name or ""]
    if data.backtest_start and data.backtest_end:
        info_parts.append(f"{data.backtest_start} ~ {data.backtest_end}")
    if data.symbols_count:
        info_parts.append(f"{data.symbols_count} 只股票")
    if data.factor_name:
        info_parts.append(f"因子: {data.factor_name}")

    children: list = [
        *live_banner,
        header,
        html.Small("  ·  ".join(info_parts), className="text-muted"),
        html.Hr(className="mt-2 mb-3"),
        # KPI 卡片
        _kpi_row(m),
        # 净值曲线
        dbc.Card(
            dbc.CardBody(dcc.Graph(figure=_equity_fig(r), config={"displaylogo": False})),
            className="mb-3",
        ),
    ]

    # 月度热力图 / 滚动指标 — 需要足够的日收益数据
    has_enough = len(r.daily_returns.dropna()) > 5
    if has_enough:
        children.append(
            dbc.Card(
                dbc.CardBody(dcc.Graph(
                    figure=_monthly_heatmap(r), config={"displaylogo": False})),
                className="mb-3",
            )
        )
    if len(r.daily_returns.dropna()) > 63:
        children.append(
            dbc.Card(
                dbc.CardBody(dcc.Graph(
                    figure=_rolling_fig(r), config={"displaylogo": False})),
                className="mb-3",
            )
        )

    return html.Div(children)


# ====================================================================
# KPI 卡片行
# ====================================================================

def _metric_card(title: str, value: str, sub: str = "", color: str = "light",
                 delta: str = "", delta_color: str = ""):
    delta_node = None
    if delta:
        delta_node = html.Small(
            delta,
            className="ms-2",
            style={"color": delta_color or "#aaa", "fontWeight": "600"},
        )
    return dbc.Col(
        dbc.Card(
            dbc.CardBody(
                [
                    html.P(title, className="text-muted mb-1", style={"fontSize": "0.78rem"}),
                    html.Div(
                        [
                            html.Span(value, style={"fontWeight": "700", "fontSize": "1.25rem"}),
                            delta_node,
                        ],
                        className="mb-0",
                    ),
                    html.Small(sub, className="text-muted") if sub else None,
                ],
                className="py-2 px-3",
            ),
            color=color,
            outline=True,
            className="h-100",
        ),
        md=2,
        className="mb-2",
    )


def _kpi_row(m: dict) -> dbc.Row:
    total_ret = m.get("total_return", 0) or 0
    ann_ret = m.get("annual_return", 0) or 0
    sharpe = m.get("sharpe_ratio", 0) or 0
    sortino = m.get("sortino_ratio", 0) or 0
    mdd = m.get("max_drawdown", 0) or 0
    calmar = m.get("calmar_ratio", 0) or 0
    win = m.get("daily_win_rate", m.get("win_rate", 0)) or 0
    info_r = m.get("information_ratio", 0) or 0
    excess = m.get("excess_return", 0) or 0
    bench_ret = m.get("benchmark_return", 0) or 0

    ret_color = "success" if total_ret >= 0 else "danger"

    # 相对基准的 Δ
    delta_vs_bench = total_ret - bench_ret
    delta_text = f"Δ {delta_vs_bench:+.2%}"
    delta_color = "#2ed573" if delta_vs_bench > 0 else "#ff4757"

    return dbc.Row(
        [
            _metric_card("总收益", f"{total_ret:+.2%}", f"年化 {ann_ret:+.2%}", ret_color,
                         delta=delta_text, delta_color=delta_color),
            _metric_card("夏普比率", f"{sharpe:.2f}", f"Sortino {sortino:.2f}"),
            _metric_card("最大回撤", f"{mdd:.2%}", f"Calmar {calmar:.2f}",
                         "danger" if mdd < -0.15 else "light"),
            _metric_card("胜率", f"{win:.1%}", "日频"),
            _metric_card("超额收益", f"{excess:+.2%}", f"基准 {bench_ret:+.2%}"),
            _metric_card("信息比率", f"{info_r:.2f}", ""),
        ],
        className="mb-3 g-2",
    )


# ====================================================================
# 净值曲线 + 回撤
# ====================================================================

def _equity_fig(r) -> go.Figure:
    eq = r.equity_curve
    bench = r.benchmark_curve

    # 归一化到 1
    eq_norm = eq / eq.iloc[0]
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, row_heights=[0.7, 0.3],
        vertical_spacing=0.04,
    )

    fig.add_trace(
        go.Scatter(x=eq_norm.index, y=eq_norm.values, name="策略净值",
                   line=dict(color="#00d4ff", width=2)),
        row=1, col=1,
    )
    if bench is not None:
        bench_norm = bench / bench.iloc[0]
        # 对齐到策略的日期范围
        common = eq_norm.index.intersection(bench_norm.index)
        if len(common) > 0:
            bn = bench_norm.loc[common]
            bn = bn / bn.iloc[0]  # 从同一天归一化
            fig.add_trace(
                go.Scatter(x=bn.index, y=bn.values, name="SPY 基准",
                           line=dict(color="#888", width=1, dash="dash")),
                row=1, col=1,
            )

    # 回撤
    running_max = eq.cummax()
    dd = (eq - running_max) / running_max
    fig.add_trace(
        go.Scatter(x=dd.index, y=dd.values, name="回撤",
                   fill="tozeroy", line=dict(color="#ff4757", width=1),
                   fillcolor="rgba(255,71,87,0.25)"),
        row=2, col=1,
    )

    fig.update_layout(
        template="plotly_dark", height=520, margin=dict(l=50, r=20, t=40, b=30),
        title=dict(text="策略净值与回撤", font=dict(size=14)),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="x unified",
    )
    fig.update_yaxes(title_text="净值", row=1, col=1)
    fig.update_yaxes(title_text="回撤", tickformat=".0%", row=2, col=1)
    return fig


# ====================================================================
# 月度收益热力图
# ====================================================================

def _monthly_heatmap(r) -> go.Figure:
    daily_ret = r.daily_returns
    monthly = daily_ret.resample("ME").apply(lambda x: (1 + x).prod() - 1)
    monthly.index = monthly.index.to_period("M")

    years = sorted(set(monthly.index.year))
    months = list(range(1, 13))
    month_labels = ["1月", "2月", "3月", "4月", "5月", "6月",
                    "7月", "8月", "9月", "10月", "11月", "12月"]

    z = []
    text = []
    for y in years:
        row = []
        txt_row = []
        for m in months:
            key = pd.Period(year=y, month=m, freq="M")
            if key in monthly.index:
                v = monthly.loc[key]
                row.append(v)
                txt_row.append(f"{v:+.2%}")
            else:
                row.append(None)
                txt_row.append("")
        z.append(row)
        text.append(txt_row)

    fig = go.Figure(
        go.Heatmap(
            z=z, x=month_labels, y=[str(y) for y in years], text=text,
            texttemplate="%{text}", textfont={"size": 11},
            colorscale=[[0, "#ff4757"], [0.5, "#2f3542"], [1, "#2ed573"]],
            zmid=0, hovertemplate="年: %{y}<br>月: %{x}<br>收益: %{text}<extra></extra>",
        )
    )
    fig.update_layout(
        template="plotly_dark", height=250, margin=dict(l=50, r=20, t=40, b=30),
        title=dict(text="月度收益热力图", font=dict(size=14)),
    )
    return fig


# ====================================================================
# 滚动夏普 & 波动率
# ====================================================================

def _rolling_fig(r) -> go.Figure:
    daily_ret = r.daily_returns
    window = 63  # ~3 个月

    roll_ret = daily_ret.rolling(window).mean() * 252
    roll_vol = daily_ret.rolling(window).std() * (252 ** 0.5)
    roll_sharpe = roll_ret / roll_vol.replace(0, float("nan"))

    fig = make_subplots(rows=1, cols=2, subplot_titles=["滚动夏普比率 (63日)", "滚动年化波动率 (63日)"])

    fig.add_trace(
        go.Scatter(x=roll_sharpe.index, y=roll_sharpe.values, name="滚动 Sharpe",
                   line=dict(color="#00d4ff", width=1.5)),
        row=1, col=1,
    )
    fig.add_hline(y=0, line_dash="dash", line_color="#666", row=1, col=1)

    fig.add_trace(
        go.Scatter(x=roll_vol.index, y=roll_vol.values, name="滚动波动率",
                   line=dict(color="#ffa502", width=1.5)),
        row=1, col=2,
    )

    fig.update_layout(
        template="plotly_dark", height=300, margin=dict(l=50, r=20, t=50, b=30),
        showlegend=False, hovermode="x unified",
    )
    fig.update_yaxes(tickformat=".1%", col=2)
    return fig


# ====================================================================
# 占位页
# ====================================================================

def _placeholder():
    return html.Div(
        [
            html.Div(
                [
                    html.I(className="bi bi-graph-up", style={"fontSize": "3rem"}),
                    html.H4("尚无回测数据", className="mt-3 mb-2"),
                    html.P("请在左侧面板配置参数后点击「运行回测」", className="text-muted"),
                ],
                className="text-center py-5",
            )
        ],
        className="d-flex justify-content-center align-items-center",
        style={"minHeight": "60vh"},
    )


def _live_placeholder(data):
    """回测已启动但尚无进度点 (正在加载数据 / 计算因子)。"""
    status = getattr(data, "live_status", "preparing")
    msg = "正在加载数据与计算因子, 请稍候…" if status == "preparing" else "准备中…"
    return html.Div(
        [
            html.Div(
                [
                    dbc.Spinner(color="primary", spinner_style={"width": "3rem", "height": "3rem"}),
                    html.H4("回测运行中", className="mt-3 mb-2"),
                    html.P(msg, className="text-muted"),
                ],
                className="text-center py-5",
            )
        ],
        className="d-flex justify-content-center align-items-center",
        style={"minHeight": "60vh"},
    )
