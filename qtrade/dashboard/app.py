"""
QTrade 专业分析面板

基于 Dash + Plotly 的交互式量化分析仪表盘。
启动: python -m qtrade.run_dashboard
"""

from __future__ import annotations

from datetime import date

import dash
import dash_bootstrap_components as dbc
from dash import Input, Output, State, callback, dcc, html

from qtrade.dashboard.data_provider import DashboardData, run_backtest

# 自动发现策略 & 因子 -----------------------------------------------
# 触发因子注册
import qtrade.examples.custom_factors  # noqa: F401

try:
    import qtrade.examples.composite_factors  # noqa: F401
except Exception:
    pass

# 触发策略注册
import qtrade.examples.custom_strategies  # noqa: F401

try:
    import qtrade.examples.composite_strategy  # noqa: F401
except Exception:
    pass

from qtrade.strategy.base import get_strategy, list_strategies

# 引擎支持的调仓频率
REBALANCE_OPTIONS = [
    {"label": "每日", "value": "D"},
    {"label": "每周", "value": "W"},
    {"label": "每月", "value": "M"},
    {"label": "每季", "value": "Q"},
]


def get_strategy_options():
    """从策略注册表动态生成下拉选项"""
    opts = []
    for key in list_strategies():
        cls = get_strategy(key)
        label = getattr(cls, "display_name", "") or key
        opts.append({"label": label, "value": key})
    return opts


def get_strategy_factor_names(strategy_name: str) -> list[str]:
    """从策略类的 default_factor_names 获取该策略使用的因子"""
    try:
        cls = get_strategy(strategy_name)
        return list(getattr(cls, "default_factor_names", []))
    except KeyError:
        return []


# ====================================================================
# App 初始化
# ====================================================================

app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.DARKLY],
    suppress_callback_exceptions=True,
    title="QTrade 量化分析面板",
    update_title="计算中...",
)

# ====================================================================
# 全局状态
# ====================================================================

_cache: dict[str, DashboardData] = {}


def get_data() -> DashboardData | None:
    return _cache.get("current")


# ====================================================================
# 侧边栏
# ====================================================================

SIDEBAR_STYLE = {
    "position": "fixed",
    "top": 0,
    "left": 0,
    "bottom": 0,
    "width": "280px",
    "padding": "20px 15px",
    "backgroundColor": "#1a1a2e",
    "overflowY": "auto",
    "zIndex": 1000,
}

CONTENT_STYLE = {
    "marginLeft": "280px",
    "padding": "20px 30px",
    "minHeight": "100vh",
}

_today = date.today().isoformat()

sidebar = html.Div(
    [
        html.Div(
            [
                html.H4("QTrade", className="text-primary mb-0",
                         style={"fontWeight": "800", "letterSpacing": "2px"}),
                html.Small("量化分析面板", className="text-muted"),
            ],
            className="mb-4 pb-3",
            style={"borderBottom": "1px solid #333"},
        ),
        # -------- 策略 --------
        html.Label("策略", className="text-muted small mb-1"),
        dbc.Select(
            id="strategy-type",
            options=get_strategy_options(),
            value="TopNStrategy",
            className="mb-2",
        ),
        # -------- 因子 (只读展示) --------
        html.Label("使用因子", className="text-muted small mb-1"),
        html.Div(
            id="factor-display",
            className="mb-3",
            style={"minHeight": "28px"},
        ),
        # -------- 选股数量 --------
        html.Label("选股数量", className="text-muted small mb-1"),
        dbc.Input(id="top-n", type="number", value=10, min=3, max=50, className="mb-3"),
        # -------- 调仓频率 --------
        html.Label("调仓频率", className="text-muted small mb-1"),
        dbc.Select(
            id="rebalance-freq",
            options=REBALANCE_OPTIONS,
            value="W",
            className="mb-3",
        ),
        # -------- 初始资金 --------
        html.Label("初始资金 (万)", className="text-muted small mb-1"),
        dbc.Input(id="initial-capital", type="number", value=100, min=1, max=10000, className="mb-3"),
        # -------- 日期区间 --------
        html.Label("回测结束日期", className="text-muted small mb-1"),
        dbc.Input(id="end-date", type="date", value=_today, className="mb-2"),
        html.Label("回测月数", className="text-muted small mb-1"),
        dbc.Input(id="bt-months", type="number", value=12, min=3, max=60, className="mb-2"),
        html.Label("预热月数", className="text-muted small mb-1"),
        dbc.Input(id="warmup-months", type="number", value=10, min=1, max=36, className="mb-3"),
        # -------- 运行 --------
        dbc.Button(
            "运行回测",
            id="run-btn",
            color="primary",
            className="w-100 mt-2 mb-4",
            style={"fontWeight": "600"},
        ),
        dbc.Spinner(
            html.Div(id="run-status"),
            color="primary",
            size="sm",
            spinner_class_name="me-2",
        ),
        html.Hr(style={"borderColor": "#333"}),
        # 页面导航
        html.Label("导航", className="text-muted small mb-2"),
        dbc.Nav(
            [
                dbc.NavLink("总览", href="/", active="exact", className="mb-1"),
                dbc.NavLink("因子分析", href="/factor", active="exact", className="mb-1"),
                dbc.NavLink("交易记录", href="/trades", active="exact", className="mb-1"),
                dbc.NavLink("持仓分析", href="/positions", active="exact", className="mb-1"),
            ],
            vertical=True,
            pills=True,
        ),
    ],
    style=SIDEBAR_STYLE,
)

# ====================================================================
# 布局
# ====================================================================

app.layout = html.Div(
    [
        dcc.Location(id="url"),
        dcc.Store(id="backtest-done", data=0),
        sidebar,
        html.Div(id="page-content", style=CONTENT_STYLE),
    ]
)


# ====================================================================
# 运行回测回调
# ====================================================================


@callback(
    Output("factor-display", "children"),
    Input("strategy-type", "value"),
)
def update_factor_display(strategy_type):
    """切换策略时更新因子展示"""
    factors = get_strategy_factor_names(strategy_type)
    if not factors:
        return html.Span("—", className="text-muted small")
    return html.Div(
        [dbc.Badge(f, color="info", className="me-1 mb-1") for f in factors],
        style={"lineHeight": "1.8"},
    )


@callback(
    Output("run-status", "children"),
    Output("backtest-done", "data"),
    Input("run-btn", "n_clicks"),
    State("strategy-type", "value"),
    State("top-n", "value"),
    State("rebalance-freq", "value"),
    State("initial-capital", "value"),
    State("end-date", "value"),
    State("bt-months", "value"),
    State("warmup-months", "value"),
    State("backtest-done", "data"),
    prevent_initial_call=True,
)
def on_run(n_clicks, strategy_type, top_n, rebalance_freq,
           initial_capital, end_date, bt_months, warmup_months, done_count):
    if not n_clicks:
        return "", dash.no_update
    try:
        capital = float(initial_capital or 100) * 10_000  # 万 → 元
        data = run_backtest(
            strategy_type=strategy_type,
            top_n=int(top_n or 10),
            rebalance_freq=rebalance_freq or "W",
            initial_capital=capital,
            backtest_months=int(bt_months or 12),
            warmup_months=int(warmup_months or 10),
            end_date=end_date or None,
        )
        _cache["current"] = data
        return (
            dbc.Alert("回测完成", color="success", className="py-1 px-2 mb-0 small"),
            (done_count or 0) + 1,
        )
    except Exception as exc:
        return (
            dbc.Alert(f"错误: {exc}", color="danger", className="py-1 px-2 mb-0 small"),
            dash.no_update,
        )


# ====================================================================
# 页面路由
# ====================================================================


@callback(
    Output("page-content", "children"),
    Input("url", "pathname"),
    Input("backtest-done", "data"),
)
def render_page(pathname, _backtest_done):
    from qtrade.dashboard.pages.overview import layout as overview_layout
    from qtrade.dashboard.pages.factor import layout as factor_layout
    from qtrade.dashboard.pages.trades import layout as trades_layout
    from qtrade.dashboard.pages.positions import layout as positions_layout

    if pathname == "/factor":
        return factor_layout()
    if pathname == "/trades":
        return trades_layout()
    if pathname == "/positions":
        return positions_layout()
    return overview_layout()


# ====================================================================
# 入口
# ====================================================================


def run_server(debug: bool = True, port: int = 8050):
    """启动 Dashboard 服务"""
    app.run(debug=debug, port=port)
