"""交易记录页 — 交易明细表 + 买卖点净值图 + 统计"""

from __future__ import annotations

import plotly.graph_objects as go
from plotly.subplots import make_subplots
import dash_bootstrap_components as dbc
from dash import html, dcc
import pandas as pd


def layout():
    from qtrade.dashboard.app import get_data

    data = get_data()
    if data is None or data.result is None:
        return _placeholder()

    trades = data.result.trades
    executed = trades[trades["status"] == "已成交"] if not trades.empty else trades

    return html.Div(
        [
            html.H4("交易记录", className="mb-1"),
            html.Small(
                f"共 {len(trades)} 笔信号  ·  {len(executed)} 笔已成交",
                className="text-muted",
            ),
            html.Hr(className="mt-2 mb-3"),
            # 交易统计卡片
            _trade_stats_row(executed),
            # 净值 + 买卖点
            dbc.Card(
                dbc.CardBody(
                    dcc.Graph(figure=_equity_with_trades(data, executed),
                              config={"displaylogo": False})
                ),
                className="mb-3",
            ),
            # 每周交易笔数
            dbc.Card(
                dbc.CardBody(
                    dcc.Graph(figure=_trade_frequency_fig(executed),
                              config={"displaylogo": False})
                ),
                className="mb-3",
            ),
            # 明细表
            dbc.Card(
                dbc.CardBody([
                    html.H6("交易明细 (最近 100 笔)", className="mb-2 text-muted"),
                    _trades_table(executed),
                ]),
                className="mb-3",
            ),
        ]
    )


# ====================================================================
# 交易统计卡片
# ====================================================================

def _trade_stats_row(trades) -> dbc.Row:
    if trades.empty:
        return dbc.Row()

    buys = trades[trades["action"].isin(["买入", "加仓"])]
    sells = trades[trades["action"].isin(["卖出", "减仓"])]
    symbols_traded = trades["symbol"].nunique()

    # 平均持仓权重变化
    avg_delta = trades["delta_weight"].abs().mean() if "delta_weight" in trades.columns else 0

    cards = [
        _stat_card("买入/加仓", f"{len(buys)} 笔", "success"),
        _stat_card("卖出/减仓", f"{len(sells)} 笔", "danger"),
        _stat_card("涉及股票", f"{symbols_traded} 只", "info"),
        _stat_card("平均权重变化", f"{avg_delta:.2%}", "warning"),
    ]
    return dbc.Row(cards, className="mb-3 g-2")


def _stat_card(title, value, color):
    return dbc.Col(
        dbc.Card(
            dbc.CardBody([
                html.P(title, className="text-muted mb-1", style={"fontSize": "0.78rem"}),
                html.H5(value, className="mb-0", style={"fontWeight": "700"}),
            ], className="py-2 px-3"),
            color=color, outline=True,
        ),
        md=3,
    )


# ====================================================================
# 净值 + 买卖标注
# ====================================================================

def _equity_with_trades(data, trades) -> go.Figure:
    r = data.result
    eq = r.equity_curve / r.equity_curve.iloc[0]

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(x=eq.index, y=eq.values, name="策略净值",
                   line=dict(color="#00d4ff", width=2))
    )

    if not trades.empty and "exec_date" in trades.columns:
        buy_mask = trades["action"].isin(["买入", "加仓"])
        sell_mask = trades["action"].isin(["卖出", "减仓"])

        buy_trades = trades[buy_mask].copy()
        sell_trades = trades[sell_mask].copy()

        # 在净值曲线上标注买卖点
        for label, df, color, symbol in [
            ("买入", buy_trades, "#2ed573", "triangle-up"),
            ("卖出", sell_trades, "#ff4757", "triangle-down"),
        ]:
            if df.empty:
                continue
            dates = pd.to_datetime(df["exec_date"])
            valid = dates[dates.isin(eq.index)]
            if valid.empty:
                continue
            fig.add_trace(
                go.Scatter(
                    x=valid, y=eq.loc[valid].values,
                    mode="markers", name=label,
                    marker=dict(symbol=symbol, size=7, color=color, opacity=0.7),
                    hovertemplate="%{x|%Y-%m-%d}<br>净值: %{y:.4f}<extra>" + label + "</extra>",
                )
            )

    fig.update_layout(
        template="plotly_dark", height=420, margin=dict(l=50, r=20, t=40, b=30),
        title=dict(text="净值曲线与买卖点", font=dict(size=14)),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="x unified",
    )
    return fig


# ====================================================================
# 交易频率
# ====================================================================

def _trade_frequency_fig(trades) -> go.Figure:
    if trades.empty:
        return go.Figure()

    trades_dt = trades.copy()
    trades_dt["exec_date"] = pd.to_datetime(trades_dt["exec_date"])
    weekly = trades_dt.set_index("exec_date").resample("W").size()

    buy_mask = trades_dt["action"].isin(["买入", "加仓"])
    sell_mask = trades_dt["action"].isin(["卖出", "减仓"])
    weekly_buy = trades_dt[buy_mask].set_index("exec_date").resample("W").size()
    weekly_sell = trades_dt[sell_mask].set_index("exec_date").resample("W").size()

    fig = go.Figure()
    fig.add_trace(go.Bar(x=weekly_buy.index, y=weekly_buy.values, name="买入/加仓",
                         marker_color="#2ed573", opacity=0.8))
    fig.add_trace(go.Bar(x=weekly_sell.index, y=weekly_sell.values, name="卖出/减仓",
                         marker_color="#ff4757", opacity=0.8))

    fig.update_layout(
        template="plotly_dark", height=280, margin=dict(l=50, r=20, t=40, b=30),
        title=dict(text="每周交易笔数", font=dict(size=14)),
        barmode="stack",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    return fig


# ====================================================================
# 交易明细表
# ====================================================================

def _trades_table(trades) -> dbc.Table:
    if trades.empty:
        return html.P("无交易记录", className="text-muted")

    cols = ["date", "exec_date", "symbol", "action", "old_weight", "new_weight",
            "delta_weight", "signal_close", "exec_open"]
    display_cols = ["信号日", "成交日", "股票", "动作", "旧权重", "新权重",
                    "变化", "信号收盘", "次日开盘"]
    available = [c for c in cols if c in trades.columns]
    display = [display_cols[cols.index(c)] for c in available]

    header = html.Thead(html.Tr([html.Th(d) for d in display]))

    recent = trades.tail(100).iloc[::-1]  # 最新在上
    rows = []
    for _, row in recent.iterrows():
        cells = []
        for c in available:
            v = row[c]
            style = {}
            if c == "action":
                style["color"] = "#2ed573" if v in ("买入", "加仓") else "#ff4757"
                style["fontWeight"] = "600"
            if c in ("old_weight", "new_weight", "delta_weight"):
                v = f"{v:.2%}" if pd.notna(v) else ""
            elif c in ("signal_close", "exec_open"):
                v = f"{v:.2f}" if pd.notna(v) else ""
            elif c in ("date", "exec_date"):
                v = str(v)[:10]
            cells.append(html.Td(str(v), style=style))
        rows.append(html.Tr(cells))

    return html.Div(
        dbc.Table(
            [header, html.Tbody(rows)],
            bordered=False, hover=True, striped=True,
            size="sm", responsive=True, className="table-dark mb-0",
        ),
        style={"maxHeight": "500px", "overflowY": "auto"},
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
