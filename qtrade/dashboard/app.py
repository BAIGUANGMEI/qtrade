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
from qtrade.data.market_data import load_sp500_symbols

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
        # -------- 股票池 --------
        html.Label("股票池", className="text-muted small mb-1"),
        dbc.Select(
            id="pool-type",
            options=[
                {"label": "S&P 500 全成分股", "value": "sp500"},
                {"label": "自定义股票池", "value": "custom"},
            ],
            value="sp500",
            className="mb-2",
        ),
        html.Div(
            [
                dbc.Button(
                    "选择股票…",
                    id="open-stock-picker",
                    color="outline-info",
                    size="sm",
                    className="w-100 mb-1",
                    style={"display": "none"},
                ),
                html.Div(
                    id="pool-summary",
                    className="text-muted small mb-3",
                    style={"minHeight": "20px"},
                ),
            ],
        ),
        # 存放已选股票代码列表
        dcc.Store(id="selected-symbols", data=[]),
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
# 股票选择器弹窗
# ====================================================================

_sp500_all = sorted(load_sp500_symbols())

stock_picker_modal = dbc.Modal(
    [
        dbc.ModalHeader(dbc.ModalTitle("选择股票"), close_button=True),
        dbc.ModalBody(
            [
                dbc.Row(
                    [
                        dbc.Col(
                            dbc.Input(
                                id="stock-search",
                                placeholder="搜索股票代码…",
                                type="text",
                                debounce=True,
                                className="mb-2",
                            ),
                            width=8,
                        ),
                        dbc.Col(
                            [
                                dbc.Button("全选", id="stock-select-all",
                                           color="outline-secondary", size="sm",
                                           className="me-1"),
                                dbc.Button("清空", id="stock-clear-all",
                                           color="outline-secondary", size="sm"),
                            ],
                            width=4,
                            className="text-end",
                        ),
                    ],
                    className="mb-2",
                ),
                html.Div(
                    id="stock-count",
                    className="text-muted small mb-2",
                ),
                html.Div(
                    dbc.Checklist(
                        id="stock-checklist",
                        options=[{"label": s, "value": s} for s in _sp500_all],
                        value=[],
                        inline=True,
                        className="stock-checklist-grid",
                        input_class_name="me-1",
                        label_class_name="me-3 mb-1 small",
                    ),
                    style={
                        "maxHeight": "400px",
                        "overflowY": "auto",
                        "border": "1px solid #444",
                        "borderRadius": "6px",
                        "padding": "10px",
                    },
                ),
            ]
        ),
        dbc.ModalFooter(
            [
                html.Span(id="modal-selected-count", className="text-muted small me-auto"),
                dbc.Button("确认", id="stock-picker-confirm", color="primary"),
            ]
        ),
    ],
    id="stock-picker-modal",
    size="lg",
    scrollable=True,
    is_open=False,
)

# ====================================================================
# 布局
# ====================================================================

app.layout = html.Div(
    [
        dcc.Location(id="url"),
        dcc.Store(id="backtest-done", data=0),
        sidebar,
        stock_picker_modal,
        html.Div(id="page-content", style=CONTENT_STYLE),
    ]
)


# ====================================================================
# 运行回测回调
# ====================================================================


@callback(
    Output("open-stock-picker", "style"),
    Output("pool-summary", "children"),
    Input("pool-type", "value"),
    Input("selected-symbols", "data"),
)
def toggle_stock_picker_button(pool_type, selected):
    """切换股票池类型时显示/隐藏选股按钮"""
    if pool_type == "custom":
        n = len(selected) if selected else 0
        summary = f"已选 {n} 只股票" if n else "尚未选择"
        return {}, html.Span(summary, className="text-info")
    return {"display": "none"}, html.Span(f"共 {len(_sp500_all)} 只", className="text-muted")


@callback(
    Output("stock-picker-modal", "is_open"),
    Output("stock-checklist", "value"),
    Input("open-stock-picker", "n_clicks"),
    Input("stock-picker-confirm", "n_clicks"),
    State("stock-picker-modal", "is_open"),
    State("selected-symbols", "data"),
    prevent_initial_call=True,
)
def toggle_modal(open_clicks, confirm_clicks, is_open, current_selected):
    """打开/关闭选股弹窗"""
    ctx = dash.callback_context
    trigger = ctx.triggered[0]["prop_id"].split(".")[0] if ctx.triggered else ""
    if trigger == "open-stock-picker":
        # 打开弹窗时回填已选
        return True, current_selected or []
    if trigger == "stock-picker-confirm":
        return False, dash.no_update
    return not is_open, dash.no_update


@callback(
    Output("selected-symbols", "data"),
    Input("stock-picker-confirm", "n_clicks"),
    State("stock-checklist", "value"),
    prevent_initial_call=True,
)
def confirm_selection(n_clicks, checked):
    """确认选择后把结果写入 Store"""
    return sorted(checked) if checked else []


@callback(
    Output("stock-checklist", "options"),
    Input("stock-search", "value"),
)
def filter_stock_list(search):
    """搜索过滤股票列表"""
    if not search:
        return [{"label": s, "value": s} for s in _sp500_all]
    q = search.strip().upper()
    filtered = [s for s in _sp500_all if q in s]
    return [{"label": s, "value": s} for s in filtered]


@callback(
    Output("stock-checklist", "value", allow_duplicate=True),
    Input("stock-select-all", "n_clicks"),
    State("stock-checklist", "options"),
    prevent_initial_call=True,
)
def select_all_stocks(n_clicks, options):
    """全选当前可见股票"""
    return [o["value"] for o in options]


@callback(
    Output("stock-checklist", "value", allow_duplicate=True),
    Input("stock-clear-all", "n_clicks"),
    prevent_initial_call=True,
)
def clear_all_stocks(n_clicks):
    """清空所有选择"""
    return []


@callback(
    Output("stock-count", "children"),
    Output("modal-selected-count", "children"),
    Input("stock-checklist", "value"),
    Input("stock-checklist", "options"),
)
def update_stock_counts(selected, options):
    """更新弹窗内的计数"""
    n_visible = len(options) if options else 0
    n_selected = len(selected) if selected else 0
    return (
        f"显示 {n_visible} / {len(_sp500_all)} 只",
        f"已选 {n_selected} 只",
    )


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
    State("pool-type", "value"),
    State("selected-symbols", "data"),
    State("top-n", "value"),
    State("rebalance-freq", "value"),
    State("initial-capital", "value"),
    State("end-date", "value"),
    State("bt-months", "value"),
    State("warmup-months", "value"),
    State("backtest-done", "data"),
    prevent_initial_call=True,
)
def on_run(n_clicks, strategy_type, pool_type, selected_symbols, top_n, rebalance_freq,
           initial_capital, end_date, bt_months, warmup_months, done_count):
    if not n_clicks:
        return "", dash.no_update
    try:
        capital = float(initial_capital or 100) * 10_000  # 万 → 元
        # 解析股票池
        symbols: list[str] | None = None
        if pool_type == "custom" and selected_symbols:
            symbols = list(selected_symbols)
            if not symbols:
                symbols = None
        data = run_backtest(
            strategy_type=strategy_type,
            top_n=int(top_n or 10),
            rebalance_freq=rebalance_freq or "W",
            initial_capital=capital,
            backtest_months=int(bt_months or 12),
            warmup_months=int(warmup_months or 10),
            end_date=end_date or None,
            symbols=symbols,
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
