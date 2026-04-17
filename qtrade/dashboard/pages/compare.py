"""多回测对比页 — 叠加净值曲线 + 指标横向表。"""

from __future__ import annotations

import dash_bootstrap_components as dbc
import plotly.graph_objects as go
from dash import Input, Output, callback, dcc, html

from qtrade.persistence import get_default_store


_COLORS = [
    "#00d4ff", "#2ed573", "#ffa502", "#ff4757", "#a29bfe",
    "#fdcb6e", "#00cec9", "#e17055",
]


def _run_options():
    try:
        store = get_default_store()
        df = store.list_runs(limit=200)
    except Exception:
        return []
    opts = []
    for _, row in df.iterrows():
        rid = int(row["id"])
        label = f"#{rid} · {row['name']}"
        opts.append({"label": label, "value": rid})
    return opts


def layout():
    opts = _run_options()
    disabled = len(opts) < 2
    hint = (
        "数据库中至少需要 2 条已保存的回测才能进行对比。"
        if disabled else
        f"共 {len(opts)} 条可选 · 勾选 2 ~ 5 条进行叠加对比"
    )

    return html.Div([
        html.H4("多回测对比", className="mb-1"),
        html.Small(hint, className="text-muted"),
        html.Hr(className="mt-2 mb-3"),
        dbc.Row([
            dbc.Col(
                dcc.Dropdown(
                    id="compare-runs",
                    options=opts,
                    value=[],
                    multi=True,
                    placeholder="选择 2 ~ 5 条 run 进行对比…",
                    style={"color": "#000"},
                    maxHeight=260,
                    disabled=disabled,
                ),
                md=12,
            ),
        ], className="mb-3"),
        html.Div(id="compare-body"),
    ])


@callback(
    Output("compare-body", "children"),
    Input("compare-runs", "value"),
)
def on_select(run_ids):
    if not run_ids:
        return html.Div(
            html.P("请从上方选择至少 2 条回测进行对比。", className="text-muted"),
            className="text-center py-4",
        )
    if len(run_ids) < 2:
        return html.Div(
            html.P("至少选择 2 条回测。", className="text-muted"),
            className="text-center py-4",
        )
    if len(run_ids) > 5:
        return dbc.Alert("最多选择 5 条。", color="warning")

    try:
        store = get_default_store()
        runs = {int(rid): store.load(int(rid)) for rid in run_ids}
    except Exception as exc:
        return dbc.Alert(f"加载失败: {exc}", color="danger")

    return html.Div([
        dbc.Card(
            dbc.CardBody(dcc.Graph(figure=_equity_overlay(runs),
                                   config={"displaylogo": False})),
            className="mb-3",
        ),
        dbc.Card(
            dbc.CardBody(dcc.Graph(figure=_drawdown_overlay(runs),
                                   config={"displaylogo": False})),
            className="mb-3",
        ),
        dbc.Card(
            dbc.CardBody([
                html.H6("指标对比", className="mb-2 text-muted"),
                _metrics_table(runs),
            ]),
            className="mb-3",
        ),
    ])


def _equity_overlay(runs) -> go.Figure:
    fig = go.Figure()
    for i, (rid, r) in enumerate(runs.items()):
        eq = r.equity_curve
        if eq is None or len(eq) == 0:
            continue
        norm = eq / eq.iloc[0]
        fig.add_trace(go.Scatter(
            x=norm.index, y=norm.values, name=f"run #{rid}",
            line=dict(color=_COLORS[i % len(_COLORS)], width=1.8),
        ))
    fig.update_layout(
        template="plotly_dark", height=420,
        margin=dict(l=50, r=20, t=40, b=30),
        title=dict(text="净值对比 (归一化)", font=dict(size=14)),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="x unified",
    )
    return fig


def _drawdown_overlay(runs) -> go.Figure:
    fig = go.Figure()
    for i, (rid, r) in enumerate(runs.items()):
        eq = r.equity_curve
        if eq is None or len(eq) == 0:
            continue
        dd = (eq - eq.cummax()) / eq.cummax()
        fig.add_trace(go.Scatter(
            x=dd.index, y=dd.values, name=f"run #{rid}",
            line=dict(color=_COLORS[i % len(_COLORS)], width=1.5),
        ))
    fig.update_layout(
        template="plotly_dark", height=300,
        margin=dict(l=50, r=20, t=40, b=30),
        title=dict(text="回撤对比", font=dict(size=14)),
        yaxis_tickformat=".0%",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="x unified",
    )
    return fig


_METRIC_KEYS = [
    ("total_return", "总收益", "pct"),
    ("annual_return", "年化收益", "pct"),
    ("annual_volatility", "年化波动", "f4"),
    ("sharpe_ratio", "夏普", "f2"),
    ("sortino_ratio", "索提诺", "f2"),
    ("max_drawdown", "最大回撤", "pct"),
    ("calmar_ratio", "Calmar", "f2"),
    ("daily_win_rate", "日胜率", "pct"),
    ("trade_win_rate", "交易胜率", "pct"),
    ("trade_count", "成交笔数", "int"),
    ("total_commission", "累计手续费", "money"),
]


def _fmt(v, kind):
    if v is None:
        return "-"
    try:
        if kind == "pct":
            return f"{v:+.2%}"
        if kind == "f2":
            return f"{v:.2f}"
        if kind == "f4":
            return f"{v:.4f}"
        if kind == "int":
            return f"{int(v)}"
        if kind == "money":
            return f"{v:,.0f}"
    except (TypeError, ValueError):
        return str(v)
    return str(v)


def _metrics_table(runs) -> dbc.Table:
    rids = list(runs.keys())
    header = html.Thead(html.Tr(
        [html.Th("指标")] + [html.Th(f"run #{rid}") for rid in rids]
    ))

    rows = []
    for key, label, kind in _METRIC_KEYS:
        cells = [html.Td(label, style={"fontWeight": "600"})]
        values = [runs[rid].metrics.get(key) for rid in rids]
        # 找最优值用于高亮 (return/sharpe 越大越好; drawdown/volatility 越小越好)
        numeric = [v for v in values if isinstance(v, (int, float))]
        best = None
        if numeric:
            if key == "annual_volatility":
                best = min(numeric)  # 波动越小越好
            elif key == "max_drawdown":
                best = max(numeric)  # 回撤是负数, 最大=最接近 0
            else:
                best = max(numeric)
        for v in values:
            style = {}
            if isinstance(v, (int, float)) and v == best and len(numeric) > 1:
                style["color"] = "#2ed573"
                style["fontWeight"] = "700"
            cells.append(html.Td(_fmt(v, kind), style=style))
        rows.append(html.Tr(cells))

    return dbc.Table(
        [header, html.Tbody(rows)],
        bordered=False, hover=True, striped=True, size="sm",
        className="table-dark mb-0",
    )
