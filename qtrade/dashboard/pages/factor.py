"""因子分析页 — IC 分析 / IC 衰减 / 分组收益 / 多空组合"""

from __future__ import annotations

import plotly.graph_objects as go
from plotly.subplots import make_subplots
import dash_bootstrap_components as dbc
from dash import html, dcc
import numpy as np


def layout():
    from qtrade.dashboard.app import get_data

    data = get_data()
    if data is None or data.result is None:
        return _placeholder()

    # 从数据库加载的历史回测不含因子分析中间结果, 给出占位
    if data.ic_summary is None or data.ic_summary.empty:
        return html.Div(
            [
                html.H4("因子分析", className="mb-1"),
                html.Small(
                    f"因子: {data.factor_name or '—'}  ·  {data.backtest_start} ~ {data.backtest_end}",
                    className="text-muted",
                ),
                html.Hr(className="mt-2 mb-3"),
                dbc.Alert(
                    [
                        html.H6("该回测未附带因子分析明细", className="mb-1"),
                        html.Small(
                            "历史回测只保存了核心结果(净值/持仓/交易/fills)。如需查看因子分析, "
                            "请在左侧面板重新运行此策略。",
                            className="text-muted",
                        ),
                    ],
                    color="secondary",
                ),
            ]
        )

    return html.Div(
        [
            html.H4("因子分析", className="mb-1"),
            html.Small(
                f"因子: {data.factor_name}  ·  {data.backtest_start} ~ {data.backtest_end}",
                className="text-muted",
            ),
            html.Hr(className="mt-2 mb-3"),
            # IC 汇总表
            dbc.Row(
                [
                    dbc.Col(
                        dbc.Card(dbc.CardBody([
                            html.H6("Pearson IC 汇总", className="mb-2 text-muted"),
                            _ic_table(data.ic_summary),
                        ])),
                        md=6,
                    ),
                    dbc.Col(
                        dbc.Card(dbc.CardBody([
                            html.H6("Spearman Rank IC 汇总", className="mb-2 text-muted"),
                            _ic_table(data.rank_ic_summary),
                        ])),
                        md=6,
                    ),
                ],
                className="mb-3 g-3",
            ),
            # IC 时序 + IC 衰减
            dbc.Row(
                [
                    dbc.Col(
                        dbc.Card(dbc.CardBody(
                            dcc.Graph(figure=_ic_series_fig(data), config={"displaylogo": False})
                        )),
                        md=7,
                    ),
                    dbc.Col(
                        dbc.Card(dbc.CardBody(
                            dcc.Graph(figure=_ic_decay_fig(data), config={"displaylogo": False})
                        )),
                        md=5,
                    ),
                ],
                className="mb-3 g-3",
            ),
            # 分组累计收益 + 多空组合
            dbc.Row(
                [
                    dbc.Col(
                        dbc.Card(dbc.CardBody(
                            dcc.Graph(figure=_group_fig(data), config={"displaylogo": False})
                        )),
                        md=7,
                    ),
                    dbc.Col(
                        dbc.Card(dbc.CardBody(
                            dcc.Graph(figure=_long_short_fig(data), config={"displaylogo": False})
                        )),
                        md=5,
                    ),
                ],
                className="mb-3 g-3",
            ),
            # 分组统计
            dbc.Card(
                dbc.CardBody([
                    html.H6("分组年化统计", className="mb-2 text-muted"),
                    _group_summary_table(data.group_summary),
                ]),
                className="mb-3",
            ),
        ]
    )


# ====================================================================
# IC 汇总表
# ====================================================================

def _ic_table(df) -> dbc.Table:
    if df.empty:
        return html.P("无数据", className="text-muted")

    header = html.Thead(html.Tr(
        [html.Th("持有期")] + [html.Th(c) for c in df.columns]
    ))
    rows = []
    for idx, row in df.iterrows():
        cells = [html.Td(str(idx))]
        for col in df.columns:
            v = row[col]
            style = {}
            if col == "IC_mean":
                style["color"] = "#2ed573" if v > 0 else "#ff4757"
                style["fontWeight"] = "600"
            cells.append(html.Td(f"{v:.4f}" if abs(v) < 100 else f"{v:.1f}", style=style))
        rows.append(html.Tr(cells))

    return dbc.Table(
        [header, html.Tbody(rows)],
        bordered=False, hover=True, striped=True,
        size="sm", className="table-dark mb-0",
    )


# ====================================================================
# IC 时序图
# ====================================================================

def _ic_series_fig(data) -> go.Figure:
    ic = data.ic_series_1d.dropna()
    if ic.empty:
        return go.Figure()

    cum_ic = ic.cumsum()
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    colors = ["#2ed573" if v > 0 else "#ff4757" for v in ic.values]
    fig.add_trace(
        go.Bar(x=ic.index, y=ic.values, name="每日 Rank IC",
               marker_color=colors, opacity=0.5),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(x=cum_ic.index, y=cum_ic.values, name="累计 IC",
                   line=dict(color="#00d4ff", width=2)),
        secondary_y=True,
    )
    mean_val = ic.mean()
    fig.add_hline(y=mean_val, line_dash="dot", line_color="#ffa502",
                  annotation_text=f"均值 {mean_val:.4f}", secondary_y=False)

    fig.update_layout(
        template="plotly_dark", height=350, margin=dict(l=50, r=50, t=40, b=30),
        title=dict(text="Rank IC 时序 (1日)", font=dict(size=14)),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="x unified",
    )
    fig.update_yaxes(title_text="IC", secondary_y=False)
    fig.update_yaxes(title_text="累计 IC", secondary_y=True)
    return fig


# ====================================================================
# IC 衰减图
# ====================================================================

def _ic_decay_fig(data) -> go.Figure:
    decay = data.ic_decay
    if decay.empty:
        return go.Figure()

    colors = ["#2ed573" if v > 0 else "#ff4757" for v in decay.values]
    fig = go.Figure(
        go.Bar(x=[f"{p}D" for p in decay.index], y=decay.values,
               marker_color=colors, text=[f"{v:.4f}" for v in decay.values],
               textposition="outside", textfont=dict(size=9))
    )
    fig.update_layout(
        template="plotly_dark", height=350, margin=dict(l=50, r=20, t=40, b=30),
        title=dict(text="Rank IC 衰减曲线", font=dict(size=14)),
        xaxis_title="持有期 (天)", yaxis_title="平均 Rank IC",
    )
    return fig


# ====================================================================
# 分组累计收益
# ====================================================================

_GROUP_COLORS = ["#ff4757", "#ff7f50", "#ffa502", "#7bed9f", "#2ed573"]


def _group_fig(data) -> go.Figure:
    df = data.group_cum_returns
    if df.empty:
        return go.Figure()

    fig = go.Figure()
    n = len(df.columns)
    for i, col in enumerate(df.columns):
        color = _GROUP_COLORS[i] if i < len(_GROUP_COLORS) else f"hsl({i * 360 // n}, 70%, 55%)"
        fig.add_trace(
            go.Scatter(x=df.index, y=df[col].values, name=col,
                       line=dict(color=color, width=1.5))
        )

    fig.update_layout(
        template="plotly_dark", height=350, margin=dict(l=50, r=20, t=40, b=30),
        title=dict(text="分组累计收益 (等权)", font=dict(size=14)),
        yaxis_tickformat=".0%",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="x unified",
    )
    return fig


# ====================================================================
# 多空组合
# ====================================================================

def _long_short_fig(data) -> go.Figure:
    ls = data.long_short_cum
    if ls.empty:
        return go.Figure()

    fig = go.Figure(
        go.Scatter(x=ls.index, y=ls.values, name="多空组合",
                   fill="tozeroy", line=dict(color="#00d4ff", width=2),
                   fillcolor="rgba(0,212,255,0.15)")
    )
    fig.update_layout(
        template="plotly_dark", height=350, margin=dict(l=50, r=20, t=40, b=30),
        title=dict(text="多空组合累计收益 (G5 - G1)", font=dict(size=14)),
        yaxis_tickformat=".0%", showlegend=False,
    )
    return fig


# ====================================================================
# 分组统计表
# ====================================================================

def _group_summary_table(df) -> dbc.Table:
    if df.empty:
        return html.P("无数据", className="text-muted")

    header = html.Thead(html.Tr(
        [html.Th("组别")] + [html.Th(c) for c in df.columns]
    ))
    rows = []
    for idx, row in df.iterrows():
        cells = [html.Td(str(idx))]
        for col in df.columns:
            v = row[col]
            fmt = f"{v:.2%}" if "return" in col or "vol" in col else f"{v:.2f}"
            style = {}
            if col == "annual_return":
                style["color"] = "#2ed573" if v > 0 else "#ff4757"
                style["fontWeight"] = "600"
            cells.append(html.Td(fmt, style=style))
        rows.append(html.Tr(cells))

    return dbc.Table(
        [header, html.Tbody(rows)],
        bordered=False, hover=True, striped=True,
        size="sm", className="table-dark mb-0",
    )


# ====================================================================
def _placeholder():
    return html.Div(
        html.Div(
            [html.H5("请先运行回测", className="text-muted"),
             html.P("左侧面板配置参数并点击「运行回测」")],
            className="text-center py-5",
        ),
        style={"minHeight": "50vh"},
    )
