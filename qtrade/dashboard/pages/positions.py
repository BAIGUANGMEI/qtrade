"""持仓分析页 — 当前持仓 + 持仓集中度 + 行业/个股权重变化"""

from __future__ import annotations

import plotly.graph_objects as go
from plotly.subplots import make_subplots
import dash_bootstrap_components as dbc
from dash import html, dcc
import pandas as pd
import numpy as np


def layout():
    from qtrade.dashboard.app import get_data

    data = get_data()
    if data is None or data.result is None:
        return _placeholder()

    positions = data.result.positions

    return html.Div(
        [
            html.H4("持仓分析", className="mb-1"),
            html.Small(
                f"{data.backtest_start} ~ {data.backtest_end}  ·  持仓日数: {len(positions)}",
                className="text-muted",
            ),
            html.Hr(className="mt-2 mb-3"),
            # 最终持仓
            dbc.Row(
                [
                    dbc.Col(
                        dbc.Card(dbc.CardBody([
                            html.H6("回测结束时持仓", className="mb-2 text-muted"),
                            _final_positions_table(positions),
                        ])),
                        md=5,
                    ),
                    dbc.Col(
                        dbc.Card(dbc.CardBody(
                            dcc.Graph(figure=_pie_fig(positions), config={"displaylogo": False})
                        )),
                        md=7,
                    ),
                ],
                className="mb-3 g-3",
            ),
            # 持仓数量变化 + HHI 集中度
            dbc.Row(
                [
                    dbc.Col(
                        dbc.Card(dbc.CardBody(
                            dcc.Graph(figure=_position_count_fig(positions),
                                      config={"displaylogo": False})
                        )),
                        md=6,
                    ),
                    dbc.Col(
                        dbc.Card(dbc.CardBody(
                            dcc.Graph(figure=_hhi_fig(positions),
                                      config={"displaylogo": False})
                        )),
                        md=6,
                    ),
                ],
                className="mb-3 g-3",
            ),
            # Top 持仓权重随时间变化
            dbc.Card(
                dbc.CardBody(
                    dcc.Graph(figure=_top_holdings_area(positions),
                              config={"displaylogo": False})
                ),
                className="mb-3",
            ),
            # 换手率
            dbc.Card(
                dbc.CardBody(
                    dcc.Graph(figure=_turnover_fig(positions),
                              config={"displaylogo": False})
                ),
                className="mb-3",
            ),
        ]
    )


# ====================================================================
# 最终持仓表
# ====================================================================

def _final_positions_table(positions) -> dbc.Table:
    final = positions.iloc[-1]
    final = final[final.abs() > 1e-6].sort_values(ascending=False)

    if final.empty:
        return html.P("回测结束时无持仓", className="text-muted")

    header = html.Thead(html.Tr([html.Th("股票"), html.Th("权重")]))
    rows = []
    for sym, w in final.items():
        color = "#2ed573" if w > 0 else "#ff4757"
        rows.append(html.Tr([
            html.Td(str(sym), style={"fontWeight": "600"}),
            html.Td(f"{w:.2%}", style={"color": color}),
        ]))

    return html.Div(
        dbc.Table([header, html.Tbody(rows)],
                  bordered=False, hover=True, striped=True, size="sm",
                  className="table-dark mb-0"),
        style={"maxHeight": "400px", "overflowY": "auto"},
    )


# ====================================================================
# 饼图
# ====================================================================

def _pie_fig(positions) -> go.Figure:
    final = positions.iloc[-1]
    final = final[final.abs() > 1e-6].sort_values(ascending=False)

    if final.empty:
        return go.Figure()

    fig = go.Figure(
        go.Pie(
            labels=final.index.tolist(),
            values=final.values.tolist(),
            hole=0.45,
            textinfo="label+percent",
            textfont=dict(size=10),
            marker=dict(line=dict(color="#1a1a2e", width=1)),
        )
    )
    fig.update_layout(
        template="plotly_dark", height=400,
        margin=dict(l=10, r=10, t=40, b=10),
        title=dict(text="持仓权重分布", font=dict(size=14)),
        showlegend=False,
    )
    return fig


# ====================================================================
# 持仓数量变化
# ====================================================================

def _position_count_fig(positions) -> go.Figure:
    count = (positions.abs() > 1e-6).sum(axis=1)

    fig = go.Figure(
        go.Scatter(x=count.index, y=count.values, name="持仓数量",
                   line=dict(color="#00d4ff", width=1.5), fill="tozeroy",
                   fillcolor="rgba(0,212,255,0.1)")
    )
    fig.update_layout(
        template="plotly_dark", height=300, margin=dict(l=50, r=20, t=40, b=30),
        title=dict(text="持仓数量变化", font=dict(size=14)),
        yaxis_title="只数", showlegend=False,
    )
    return fig


# ====================================================================
# HHI 集中度
# ====================================================================

def _hhi_fig(positions) -> go.Figure:
    # HHI = Σ(w_i^2), 越大越集中
    hhi = (positions ** 2).sum(axis=1)
    # 过滤无持仓日
    hhi = hhi[hhi > 0]

    fig = go.Figure(
        go.Scatter(x=hhi.index, y=hhi.values, name="HHI",
                   line=dict(color="#ffa502", width=1.5))
    )
    fig.add_hline(y=1.0 / 10, line_dash="dash", line_color="#666",
                  annotation_text="等权10只 (0.10)")
    fig.update_layout(
        template="plotly_dark", height=300, margin=dict(l=50, r=20, t=40, b=30),
        title=dict(text="持仓集中度 (HHI)", font=dict(size=14)),
        yaxis_title="HHI", showlegend=False,
    )
    return fig


# ====================================================================
# Top 持仓面积图
# ====================================================================

def _top_holdings_area(positions) -> go.Figure:
    # 取出现频率最高的 top 10 股票
    held = (positions.abs() > 1e-6).sum()
    top_syms = held.nlargest(10).index.tolist()

    if not top_syms:
        return go.Figure()

    fig = go.Figure()
    for sym in top_syms:
        fig.add_trace(
            go.Scatter(
                x=positions.index, y=positions[sym].values,
                name=sym, stackgroup="one", mode="lines",
                line=dict(width=0.5),
            )
        )

    fig.update_layout(
        template="plotly_dark", height=380, margin=dict(l=50, r=20, t=40, b=30),
        title=dict(text="Top 10 持仓权重变化 (堆叠面积)", font=dict(size=14)),
        yaxis_tickformat=".0%", hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
                    font=dict(size=9)),
    )
    return fig


# ====================================================================
# 换手率
# ====================================================================

def _turnover_fig(positions) -> go.Figure:
    # 单边换手 = Σ|w_t - w_{t-1}| / 2
    diff = positions.diff().abs().sum(axis=1) / 2
    diff = diff.iloc[1:]  # 去掉第一天 NaN

    fig = go.Figure(
        go.Bar(x=diff.index, y=diff.values, name="换手率",
               marker_color="#7bed9f", opacity=0.7)
    )
    # 滚动平均
    if len(diff) > 20:
        roll = diff.rolling(20).mean()
        fig.add_trace(
            go.Scatter(x=roll.index, y=roll.values, name="20日均线",
                       line=dict(color="#ffa502", width=2))
        )

    fig.update_layout(
        template="plotly_dark", height=300, margin=dict(l=50, r=20, t=40, b=30),
        title=dict(text="每日单边换手率", font=dict(size=14)),
        yaxis_tickformat=".0%",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    return fig


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
