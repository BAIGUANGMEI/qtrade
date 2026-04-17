"""
QTrade 专业分析面板

基于 Dash + Plotly 的交互式量化分析仪表盘。
启动: python -m qtrade.run_dashboard
"""

from __future__ import annotations

import logging
import threading
import time
import traceback
import uuid
from datetime import date
from urllib.parse import parse_qs, urlencode

import dash
import dash_bootstrap_components as dbc
from dash import Input, Output, State, callback, dcc, html

from qtrade.dashboard.data_provider import (
    DashboardData,
    load_run_from_store,
    run_backtest,
)
from qtrade.backtest.engine import BacktestResult
from qtrade.backtest.performance import full_metrics as _full_metrics
from qtrade.data.market_data import load_sp500_symbols

logger = logging.getLogger("qtrade.dashboard")

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

# 预加载各子页面模块, 确保其 @callback 在客户端获取依赖图前注册完毕
# (否则 pattern-matching / 动态 Input 的回调不会被浏览器感知, 点击无响应)
import qtrade.dashboard.pages.compare  # noqa: F401
import qtrade.dashboard.pages.factor  # noqa: F401
import qtrade.dashboard.pages.overview  # noqa: F401
import qtrade.dashboard.pages.positions  # noqa: F401
import qtrade.dashboard.pages.runs  # noqa: F401
import qtrade.dashboard.pages.trades  # noqa: F401

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

# 按 run_id (int) 缓存每次回测的可视化数据; "current" 指向当前查看的 run_id
_cache: dict[object, DashboardData] = {}


# ====================================================================
# 后台回测任务管理 (线程 + 轮询)
# ====================================================================

# job_id -> dict(status, progress[(ts, equity)], bar, total, error, run_id,
#                started_at, finished_at, cancel_event, data)
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()
# 单次最多保留进度点数, 避免内存持续增长
_MAX_PROGRESS_POINTS = 2000


def _job_snapshot(job_id: str) -> dict | None:
    """返回 job 的轻量级只读快照 (不含 data/cancel_event)。"""
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None:
            return None
        return {
            "status": job.get("status"),
            "bar": job.get("bar", 0),
            "total": job.get("total", 0),
            "progress": list(job.get("progress", [])),
            "error": job.get("error"),
            "run_id": job.get("run_id"),
            "started_at": job.get("started_at"),
            "finished_at": job.get("finished_at"),
        }


def _make_progress_callback(job_id: str):
    """为后台线程生成一个写入 _jobs[job_id] 的进度回调。"""
    def cb(bar: int, total: int, ts, equity: float) -> None:
        with _jobs_lock:
            job = _jobs.get(job_id)
            if job is None:
                return
            job["bar"] = int(bar)
            job["total"] = int(total)
            prog = job.setdefault("progress", [])
            # 降采样: 达到上限时, 均匀丢弃一半旧点
            if len(prog) >= _MAX_PROGRESS_POINTS:
                del prog[::2]
            prog.append((str(ts)[:10], float(equity)))
    return cb


def _start_backtest_job(kwargs: dict) -> str:
    """创建 job_id, 在后台线程运行 run_backtest, 立即返回 job_id。"""
    job_id = uuid.uuid4().hex[:12]
    cancel_event = threading.Event()
    with _jobs_lock:
        _jobs[job_id] = {
            "status": "running",
            "bar": 0,
            "total": 0,
            "progress": [],
            "error": None,
            "run_id": None,
            "data": None,
            "started_at": time.time(),
            "finished_at": None,
            "cancel_event": cancel_event,
            "save_config": kwargs.pop("_save_config", {}),
            "strategy_type": kwargs.get("strategy_type"),
        }

    def _runner():
        try:
            data = run_backtest(
                progress_callback=_make_progress_callback(job_id),
                cancel_event=cancel_event,
                **kwargs,
            )
            # 用户取消 — 不落库, 直接标记
            if cancel_event.is_set():
                with _jobs_lock:
                    job = _jobs.get(job_id)
                    if job is not None:
                        job["status"] = "cancelled"
                        job["finished_at"] = time.time()
                return

            # 自动保存到数据库
            run_id: int | None = None
            try:
                with _jobs_lock:
                    save_config = dict(_jobs[job_id].get("save_config", {}))
                    strategy_type = _jobs[job_id].get("strategy_type") or ""
                save_config.update({
                    "strategy_name": data.strategy_name,
                    "factor_name": data.factor_name,
                    "data_start": data.data_start,
                    "backtest_start": data.backtest_start,
                    "backtest_end": data.backtest_end,
                    "symbol_count": data.symbols_count,
                })
                run_id = data.result.save(
                    name=f"{strategy_type}_{data.backtest_start}_{data.backtest_end}",
                    strategy_name=strategy_type,
                    config=save_config,
                    notes="dashboard auto-save",
                )
                _cache[run_id] = data
                set_current_run(run_id, data)
            except Exception as save_exc:
                logger.exception("auto-save failed: %s", save_exc)
                _cache["current"] = data

            with _jobs_lock:
                job = _jobs.get(job_id)
                if job is not None:
                    job["status"] = "done"
                    job["data"] = data
                    job["run_id"] = run_id
                    job["finished_at"] = time.time()
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("backtest job %s failed", job_id)
            with _jobs_lock:
                job = _jobs.get(job_id)
                if job is not None:
                    job["status"] = "error"
                    job["error"] = {
                        "summary": _short_error_message(exc),
                        "traceback": traceback.format_exc(),
                    }
                    job["finished_at"] = time.time()

    th = threading.Thread(target=_runner, name=f"bt-{job_id}", daemon=True)
    th.start()
    return job_id


def _cancel_job(job_id: str) -> bool:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None or job.get("status") != "running":
            return False
        ev = job.get("cancel_event")
    if ev is not None:
        ev.set()
    return True


# 清理: 仅保留最近 20 个 job 的元数据
def _gc_jobs() -> None:
    with _jobs_lock:
        if len(_jobs) <= 20:
            return
        # 按 started_at 排序, 丢弃最旧的
        items = sorted(_jobs.items(),
                       key=lambda kv: kv[1].get("started_at") or 0)
        for jid, _ in items[:-20]:
            _jobs.pop(jid, None)


def _build_partial_data(snap: dict, strategy_type: str = "") -> DashboardData | None:
    """从 job 快照的进度点构建临时 DashboardData, 用于总览页实时预览。"""
    import pandas as pd

    progress = snap.get("progress") or []
    if len(progress) < 2:
        return None

    dates = pd.DatetimeIndex([pd.Timestamp(p[0]) for p in progress])
    values = [float(p[1]) for p in progress]
    equity = pd.Series(values, index=dates, name="equity")
    daily_ret = equity.pct_change().dropna()
    metrics = _full_metrics(equity)

    result = BacktestResult(
        equity_curve=equity,
        daily_returns=daily_ret,
        positions=pd.DataFrame(),
        trades=pd.DataFrame(),
        metrics=metrics,
        benchmark_curve=None,
        fills=pd.DataFrame(),
    )

    bar = int(snap.get("bar", 0))
    total = int(snap.get("total", 0))
    status = snap.get("status", "running")

    return DashboardData(
        strategy_name=strategy_type,
        result=result,
        backtest_start=str(dates[0].date()),
        backtest_end=str(dates[-1].date()),
        live=True,
        live_bar=bar,
        live_total=total,
        live_status=status,
    )


def get_data() -> DashboardData | None:
    """返回当前选中的回测数据。

    查找顺序:
    1. _cache['current'] 直接返回
    2. _cache['current_id'] 指向的 run_id
    """
    data = _cache.get("current")
    if data is not None:
        return data
    rid = _cache.get("current_id")
    if rid is not None:
        return _cache.get(rid)
    return None


def set_current_run(run_id: int | None, data: DashboardData | None = None) -> None:
    """设置当前选中的 run。"""
    if run_id is not None:
        if data is not None:
            _cache[run_id] = data
        _cache["current_id"] = run_id
        # 同步一份给老接口
        _cache["current"] = _cache.get(run_id)
    elif data is not None:
        _cache["current"] = data


def get_cached_run(run_id: int) -> DashboardData | None:
    return _cache.get(run_id)


def ensure_run_loaded(run_id: int) -> DashboardData | None:
    """如果 run_id 未在内存中, 从 DB 懒加载。"""
    if run_id in _cache:
        return _cache[run_id]
    try:
        data = load_run_from_store(run_id)
    except Exception as exc:
        logger.exception("load run %s failed: %s", run_id, exc)
        return None
    _cache[run_id] = data
    return data


# ====================================================================
# 侧边栏
# ====================================================================

SIDEBAR_STYLE = {
    "position": "fixed",
    "top": 0,
    "left": 0,
    "bottom": 0,
    "width": "260px",
    "padding": "16px 14px",
    "backgroundColor": "#0d0d0d",
    "borderRight": "1px solid #2a2a2a",
    "overflowY": "auto",
    "zIndex": 1000,
}

CONTENT_STYLE = {
    "marginLeft": "260px",
    "padding": "20px 30px",
    "minHeight": "100vh",
}

_today = date.today().isoformat()

def _section_label(text: str) -> html.Div:
    """小标题: 参数区块的分组标题。"""
    return html.Div(
        text,
        className="text-uppercase small fw-bold mt-2 mb-2",
        style={"letterSpacing": "1.5px", "fontSize": "0.68rem",
               "color": "#666",
               "borderLeft": "2px solid #444", "paddingLeft": "8px"},
    )


def _field_label(text: str) -> html.Label:
    return html.Label(text, className="text-muted small mb-1 d-block")


sidebar = html.Div(
    [
        # ============ 顶部品牌 ============
        html.Div(
            [
                html.Span("QTRADE",
                          style={"fontWeight": "700", "fontSize": "1.1rem",
                                 "letterSpacing": "3px", "color": "#fff"}),
                html.Span(" 量化面板",
                          style={"fontSize": "0.75rem", "color": "#666",
                                 "marginLeft": "6px"}),
            ],
            className="mb-3 pb-2",
            style={"borderBottom": "1px solid #222"},
        ),

        # ============ 导航 (置顶) ============
        dbc.Nav(
            id="nav-links",
            children=[
                dbc.NavLink("总览", id="nav-overview", href="/", active="exact"),
                dbc.NavLink("因子分析", id="nav-factor", href="/factor", active="exact"),
                dbc.NavLink("交易记录", id="nav-trades", href="/trades", active="exact"),
                dbc.NavLink("持仓分析", id="nav-positions", href="/positions", active="exact"),
                dbc.NavLink("历史回测", id="nav-runs", href="/runs", active="exact"),
                dbc.NavLink("多策略对比", id="nav-compare", href="/compare", active="exact"),
            ],
            pills=True,
            className="flex-column nav-compact mb-3",
        ),

        # ============ 当前 run + 分享 ============
        html.Div(
            [
                html.Div(
                    [
                        html.Span("当前 Run", className="small",
                                  style={"color": "#666"}),
                        dcc.Clipboard(
                            id="share-link-clip",
                            target_id="share-link-target",
                            title="复制分享链接",
                            style={"display": "inline-block", "cursor": "pointer",
                                   "fontSize": "0.85rem", "verticalAlign": "middle",
                                   "float": "right", "color": "#666"},
                        ),
                    ],
                    className="mb-1",
                ),
                html.Div(id="current-run-info",
                         className="small",
                         style={"minHeight": "18px", "color": "#aaa"}),
                html.Div(id="share-link-target", style={"display": "none"}),
            ],
            className="mb-3 py-2 px-2",
            style={"backgroundColor": "#111", "border": "1px solid #222"},
        ),

        # ============ 参数配置 ============
        _section_label("策略 & 因子"),
        _field_label("策略类型"),
        dbc.Select(
            id="strategy-type",
            options=get_strategy_options(),
            value="TopNStrategy",
            className="mb-2",
        ),
        _field_label("使用因子"),
        html.Div(
            id="factor-display",
            className="mb-2",
            style={"minHeight": "28px"},
        ),
        dbc.Checklist(
            id="enable-factor-analysis",
            options=[{"label": "启用因子分析 (IC / 分组)", "value": "on"}],
            value=["on"],
            switch=True,
            className="mb-2 small",
        ),

        _section_label("股票池"),
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
                    className="text-muted small mb-2",
                    style={"minHeight": "18px"},
                ),
            ],
        ),
        dcc.Store(id="selected-symbols", data=[]),

        _section_label("交易参数"),
        dbc.Row(
            [
                dbc.Col(
                    [
                        _field_label("选股数"),
                        dbc.Input(id="top-n", type="number", value=10,
                                  min=3, max=50, size="sm"),
                    ],
                    width=6,
                ),
                dbc.Col(
                    [
                        _field_label("调仓"),
                        dbc.Select(
                            id="rebalance-freq",
                            options=REBALANCE_OPTIONS,
                            value="W",
                            size="sm",
                        ),
                    ],
                    width=6,
                ),
            ],
            className="g-2 mb-2",
        ),
        _field_label("初始资金 (万)"),
        dbc.Input(id="initial-capital", type="number", value=100,
                  min=1, max=10000, size="sm", className="mb-2"),

        _section_label("时间区间"),
        _field_label("结束日期"),
        dbc.Input(id="end-date", type="date", value=_today,
                  size="sm", className="mb-2"),
        dbc.Row(
            [
                dbc.Col(
                    [
                        _field_label("回测月数"),
                        dbc.Input(id="bt-months", type="number", value=12,
                                  min=3, max=60, size="sm"),
                    ],
                    width=6,
                ),
                dbc.Col(
                    [
                        _field_label("预热月数"),
                        dbc.Input(id="warmup-months", type="number", value=10,
                                  min=1, max=36, size="sm"),
                    ],
                    width=6,
                ),
            ],
            className="g-2 mb-3",
        ),

        # ============ 运行 ============
        dbc.ButtonGroup(
            [
                dbc.Button(
                    "运行回测",
                    id="run-btn",
                    color="primary",
                    style={"fontWeight": "600"},
                ),
                dbc.Button(
                    "取消",
                    id="cancel-btn",
                    color="outline-danger",
                    disabled=True,
                ),
            ],
            className="w-100 mb-2",
        ),
        html.Div(id="run-validation", className="text-warning small mb-2",
                 style={"minHeight": "18px"}),
        html.Div(id="run-status"),
    ],
    id="sidebar",
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
                # 预设快捷按钮
                html.Div(
                    [
                        html.Span("预设:", className="text-muted small me-2"),
                        dbc.ButtonGroup(
                            [
                                dbc.Button("前 50", id="preset-top50",
                                           color="outline-info", size="sm"),
                                dbc.Button("前 100", id="preset-top100",
                                           color="outline-info", size="sm"),
                                dbc.Button("前 200", id="preset-top200",
                                           color="outline-info", size="sm"),
                                dbc.Button("全量", id="preset-all",
                                           color="outline-info", size="sm"),
                            ],
                            size="sm",
                            className="mb-2",
                        ),
                    ],
                ),
                # 粘贴 CSV / 逗号分隔代码
                dbc.InputGroup(
                    [
                        dbc.Textarea(
                            id="paste-symbols",
                            placeholder="粘贴代码 (逗号/空格/换行分隔): AAPL, MSFT, NVDA",
                            rows=2,
                            style={"fontSize": "0.85rem"},
                        ),
                        dbc.Button("解析", id="apply-paste",
                                   color="outline-primary", size="sm"),
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
        dcc.Store(id="current-run-id", data=None),
        dcc.Store(id="job-id", data=None),
        # 进度轮询: 启动后 disabled=False, 默认关闭以节省流量
        dcc.Interval(id="progress-interval", interval=500,
                     n_intervals=0, disabled=True),
        # 导出用
        dcc.Download(id="download-equity"),
        dcc.Download(id="download-positions"),
        dcc.Download(id="download-trades"),
        dcc.Download(id="download-fills"),
        sidebar,
        stock_picker_modal,
        # 主区: 页面内容
        html.Div(
            [
                html.Div(id="page-content"),
            ],
            style=CONTENT_STYLE,
            id="main-wrap",
        ),
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
    Output("stock-checklist", "value", allow_duplicate=True),
    Input("preset-top50", "n_clicks"),
    Input("preset-top100", "n_clicks"),
    Input("preset-top200", "n_clicks"),
    Input("preset-all", "n_clicks"),
    prevent_initial_call=True,
)
def apply_preset(n50, n100, n200, n_all):
    """预设股票池按钮: 按 symbol 字母序取前 N 只 (稳定可复现, 不依赖市值数据)。"""
    ctx = dash.callback_context
    trigger = ctx.triggered[0]["prop_id"].split(".")[0] if ctx.triggered else ""
    preset_map = {
        "preset-top50": _sp500_all[:50],
        "preset-top100": _sp500_all[:100],
        "preset-top200": _sp500_all[:200],
        "preset-all": list(_sp500_all),
    }
    return preset_map.get(trigger, dash.no_update)


@callback(
    Output("stock-checklist", "value", allow_duplicate=True),
    Output("paste-symbols", "value"),
    Input("apply-paste", "n_clicks"),
    State("paste-symbols", "value"),
    State("stock-checklist", "value"),
    prevent_initial_call=True,
)
def apply_pasted_symbols(n_clicks, text, current):
    """解析粘贴的 CSV / 空格 / 换行分隔的代码, 与现有已选合并。"""
    if not text:
        return dash.no_update, dash.no_update
    import re
    tokens = [t.upper() for t in re.split(r"[,\s;]+", text) if t.strip()]
    valid = [t for t in tokens if t in set(_sp500_all)]
    merged = sorted(set((current or []) + valid))
    return merged, ""


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
    Output("job-id", "data"),
    Output("run-status", "children", allow_duplicate=True),
    Output("progress-interval", "disabled", allow_duplicate=True),
    Output("run-btn", "disabled", allow_duplicate=True),
    Output("cancel-btn", "disabled", allow_duplicate=True),
    Output("url", "pathname", allow_duplicate=True),
    Output("backtest-done", "data", allow_duplicate=True),
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
    State("enable-factor-analysis", "value"),
    State("backtest-done", "data"),
    prevent_initial_call=True,
)
def on_run(n_clicks, strategy_type, pool_type, selected_symbols, top_n,
           rebalance_freq, initial_capital, end_date, bt_months, warmup_months,
           factor_analysis_value, done_count):
    """启动后台回测任务并立即返回; 具体进度 / 完成状态由 Interval 轮询。"""
    if not n_clicks:
        return (dash.no_update,) * 7

    try:
        capital = float(initial_capital or 100) * 10_000
        symbols: list[str] | None = None
        if pool_type == "custom" and selected_symbols:
            symbols = list(selected_symbols) or None

        run_factor_analysis = bool(factor_analysis_value) and "on" in (factor_analysis_value or [])

        kwargs = dict(
            strategy_type=strategy_type,
            top_n=int(top_n or 10),
            rebalance_freq=rebalance_freq or "W",
            initial_capital=capital,
            backtest_months=int(bt_months or 12),
            warmup_months=int(warmup_months or 10),
            end_date=end_date or None,
            symbols=symbols,
            run_factor_analysis=run_factor_analysis,
            # 持久化到 DB 的元数据 (不传给 run_backtest, 由 _start_backtest_job 取出)
            _save_config={
                "strategy_type": strategy_type,
                "top_n": int(top_n or 10),
                "rebalance_freq": rebalance_freq or "W",
                "initial_capital": capital,
                "backtest_months": int(bt_months or 12),
                "warmup_months": int(warmup_months or 10),
                "end_date": end_date,
                "pool_type": pool_type,
                "commission": 0.001,
                "slippage": 0.001,
                "run_factor_analysis": run_factor_analysis,
            },
        )
        job_id = _start_backtest_job(kwargs)
        _gc_jobs()

        # 清除旧数据, 让总览页显示「准备中」占位
        _cache["current"] = DashboardData(
            strategy_name=strategy_type,
            live=True,
            live_status="preparing",
        )

        status = dbc.Spinner(
            size="sm", color="light",
            spinner_style={"width": "1rem", "height": "1rem"},
        )
        return (job_id, status, False, True, False,
                "/", (done_count or 0) + 1)
    except Exception as exc:  # 参数解析等同步错误
        logger.exception("failed to start backtest job")
        err = dbc.Alert(_short_error_message(exc), color="danger",
                        className="py-1 px-2 mb-0 small")
        return (dash.no_update, err, dash.no_update,
                dash.no_update, dash.no_update,
                dash.no_update, dash.no_update)


@callback(
    Output("cancel-btn", "disabled", allow_duplicate=True),
    Input("cancel-btn", "n_clicks"),
    State("job-id", "data"),
    prevent_initial_call=True,
)
def on_cancel(n_clicks, job_id):
    if not n_clicks or not job_id:
        return dash.no_update
    _cancel_job(job_id)
    # 按钮保持禁用避免重复点击, Interval 后续会刷新为最终状态
    return True


@callback(
    Output("run-status", "children", allow_duplicate=True),
    Output("backtest-done", "data", allow_duplicate=True),
    Output("current-run-id", "data", allow_duplicate=True),
    Output("url", "search", allow_duplicate=True),
    Output("progress-interval", "disabled", allow_duplicate=True),
    Output("run-btn", "disabled", allow_duplicate=True),
    Output("cancel-btn", "disabled", allow_duplicate=True),
    Input("progress-interval", "n_intervals"),
    State("job-id", "data"),
    State("backtest-done", "data"),
    prevent_initial_call=True,
)
def on_progress_tick(_n, job_id, done_count):
    if not job_id:
        return (dash.no_update,) * 7

    snap = _job_snapshot(job_id)
    if snap is None:
        return (dash.no_update,) * 7

    total = max(int(snap.get("total") or 0), 1)
    bar = int(snap.get("bar") or 0)
    pct = max(0, min(100, int(100 * bar / total))) if total > 0 else 0
    status = snap.get("status")

    # 读取策略名 (如果已保存)
    strategy_type = ""
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is not None:
            strategy_type = job.get("strategy_type") or ""

    # 构建 / 更新临时 DashboardData, 写入 _cache 让总览页实时渲染
    partial = _build_partial_data(snap, strategy_type=strategy_type)
    if partial is not None:
        _cache["current"] = partial

    # 运行中: 触发总览页刷新 (每 tick 递增 backtest-done)
    if status == "running":
        # 不更新 run-status (避免侧边栏 alert 反复重建导致闪烁)
        return (dash.no_update, (done_count or 0) + 1,
                dash.no_update, dash.no_update,
                dash.no_update, dash.no_update, dash.no_update)

    # ---- 终态 ----
    if status == "done":
        run_id = snap.get("run_id")
        alert = dbc.Alert(
            f"回测完成{f' · run_id={run_id}' if run_id else ''}",
            color="success", className="py-1 px-2 mb-0 small",
        )
        new_search = f"?run_id={run_id}" if run_id else dash.no_update
        return (alert, (done_count or 0) + 1, run_id, new_search,
                True, False, True)

    if status == "cancelled":
        # 保留最后的 partial 数据 (标记非 live), 用户可查看已跑完的部分
        if partial is not None:
            partial.live = False
            partial.live_status = "cancelled"
            _cache["current"] = partial
        alert = dbc.Alert("已取消", color="warning",
                          className="py-1 px-2 mb-0 small")
        return (alert, (done_count or 0) + 1,
                dash.no_update, dash.no_update,
                True, False, True)

    if status == "error":
        err_info = snap.get("error") or {}
        summary = err_info.get("summary") or "回测失败"
        tb = err_info.get("traceback") or ""
        alert = dbc.Alert(
            [
                html.Div(summary, className="fw-bold"),
                html.Details(
                    [
                        html.Summary("查看详细错误",
                                     className="text-muted small"),
                        html.Pre(tb,
                                 style={"whiteSpace": "pre-wrap",
                                        "fontSize": "0.72rem",
                                        "maxHeight": "200px",
                                        "overflow": "auto",
                                        "marginTop": "6px"}),
                    ],
                ),
            ],
            color="danger", className="py-2 px-2 mb-0 small",
        )
        return (alert, (done_count or 0) + 1,
                dash.no_update, dash.no_update,
                True, False, True)

    return (dash.no_update,) * 7


def _short_error_message(exc: Exception) -> str:
    text = str(exc) or type(exc).__name__
    if "No data" in text or "yfinance" in text or "HTTPError" in text:
        return "行情数据下载失败，请检查网络或稍后重试。"
    if "top_n" in text.lower():
        return "选股数量不合法（大于可用股池）。"
    if "smart_dates" in text or "backtest" in text.lower() and "date" in text.lower():
        return "日期区间不合法，请检查结束日期 / 回测月数 / 预热月数。"
    return text[:160]


# ====================================================================
# 页面路由
# ====================================================================


@callback(
    Output("page-content", "children"),
    Input("url", "pathname"),
    Input("url", "search"),
    Input("backtest-done", "data"),
)
def render_page(pathname, search, _backtest_done):
    from qtrade.dashboard.pages.compare import layout as compare_layout
    from qtrade.dashboard.pages.factor import layout as factor_layout
    from qtrade.dashboard.pages.overview import layout as overview_layout
    from qtrade.dashboard.pages.positions import layout as positions_layout
    from qtrade.dashboard.pages.runs import layout as runs_layout
    from qtrade.dashboard.pages.trades import layout as trades_layout

    # 解析 ?run_id=N 并切换当前 run
    run_id = _parse_run_id(search)
    if run_id is not None:
        if ensure_run_loaded(run_id) is not None:
            set_current_run(run_id)

    if pathname == "/factor":
        return factor_layout()
    if pathname == "/trades":
        return trades_layout()
    if pathname == "/positions":
        return positions_layout()
    if pathname == "/runs":
        return runs_layout()
    if pathname == "/compare":
        return compare_layout()
    return overview_layout()


def _parse_run_id(search: str | None) -> int | None:
    if not search:
        return None
    q = parse_qs(search.lstrip("?"))
    v = q.get("run_id", [None])[0]
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


# ====================================================================
# 参数校验: 禁用/激活运行按钮
# ====================================================================


@callback(
    Output("run-btn", "disabled"),
    Output("run-validation", "children"),
    Input("pool-type", "value"),
    Input("selected-symbols", "data"),
    Input("top-n", "value"),
    Input("bt-months", "value"),
    Input("warmup-months", "value"),
    Input("initial-capital", "value"),
    Input("end-date", "value"),
)
def validate_run(pool_type, selected, top_n, bt_months, warmup_months, capital, end_date):
    issues: list[str] = []

    pool_size = len(selected) if (pool_type == "custom" and selected) else len(_sp500_all)
    if pool_type == "custom" and not selected:
        issues.append("自定义股池为空")

    try:
        n = int(top_n) if top_n is not None else 0
    except (TypeError, ValueError):
        n = 0
    if n < 3:
        issues.append("选股数量 ≥ 3")
    elif n > pool_size:
        issues.append(f"选股数量 ({n}) 大于股池 ({pool_size})")

    try:
        bm = int(bt_months) if bt_months is not None else 0
        wm = int(warmup_months) if warmup_months is not None else 0
    except (TypeError, ValueError):
        bm = wm = 0
    if bm < 3:
        issues.append("回测月数 ≥ 3")
    if wm < 1:
        issues.append("预热月数 ≥ 1")

    if not capital or float(capital) <= 0:
        issues.append("初始资金 > 0")

    if not end_date:
        issues.append("缺少结束日期")

    if issues:
        return True, " · ".join(issues)
    return False, ""


# ====================================================================
# 当前 run 信息 + 分享链接
# ====================================================================


@callback(
    Output("current-run-info", "children"),
    Output("share-link-target", "children"),
    Input("url", "href"),
    Input("current-run-id", "data"),
    Input("backtest-done", "data"),
)
def update_current_run_info(href, run_id, _done):
    # 优先从 URL 解析 run_id, 其次用回调 Store
    effective = None
    if href:
        from urllib.parse import urlparse
        parsed = urlparse(href)
        effective = _parse_run_id(parsed.query and f"?{parsed.query}")
    if effective is None:
        effective = run_id

    if effective is None:
        return "尚未选中回测", ""

    base = (href.split("?")[0]) if href else ""
    share_url = f"{base}?run_id={effective}"
    return f"当前 run_id = {effective}", share_url


_NAV_PATHS = {
    "nav-overview": "/",
    "nav-factor": "/factor",
    "nav-trades": "/trades",
    "nav-positions": "/positions",
    "nav-runs": "/runs",
    "nav-compare": "/compare",
}


@callback(
    *[Output(nid, "href") for nid in _NAV_PATHS],
    Input("current-run-id", "data"),
    Input("url", "search"),
)
def update_nav_hrefs(run_id, search):
    """Nav 链接始终携带当前 run_id, 避免切换页面时丢失。"""
    # 优先用 Store 中的 run_id, 其次从 URL search 解析
    rid = run_id
    if rid is None:
        rid = _parse_run_id(search)
    suffix = f"?run_id={rid}" if rid is not None else ""
    return tuple(f"{path}{suffix}" for path in _NAV_PATHS.values())


# ====================================================================
# CSV 导出
# ====================================================================


@callback(
    Output("download-equity", "data"),
    Input({"type": "export-btn", "kind": "equity"}, "n_clicks"),
    prevent_initial_call=True,
)
def export_equity(n):
    data = get_data()
    if not n or data is None or data.result is None:
        return dash.no_update
    df = data.result.equity_curve.rename("equity").to_frame()
    if data.result.benchmark_curve is not None:
        df["benchmark"] = data.result.benchmark_curve.reindex(df.index)
    return dcc.send_data_frame(df.to_csv, "equity.csv")


@callback(
    Output("download-positions", "data"),
    Input({"type": "export-btn", "kind": "positions"}, "n_clicks"),
    prevent_initial_call=True,
)
def export_positions(n):
    data = get_data()
    if not n or data is None or data.result is None:
        return dash.no_update
    return dcc.send_data_frame(data.result.positions.to_csv, "positions.csv")


@callback(
    Output("download-trades", "data"),
    Input({"type": "export-btn", "kind": "trades"}, "n_clicks"),
    prevent_initial_call=True,
)
def export_trades(n):
    data = get_data()
    if not n or data is None or data.result is None or data.result.trades is None:
        return dash.no_update
    return dcc.send_data_frame(data.result.trades.to_csv, "trades.csv", index=False)


@callback(
    Output("download-fills", "data"),
    Input({"type": "export-btn", "kind": "fills"}, "n_clicks"),
    prevent_initial_call=True,
)
def export_fills(n):
    data = get_data()
    if not n or data is None or data.result is None or data.result.fills is None:
        return dash.no_update
    return dcc.send_data_frame(data.result.fills.to_csv, "fills.csv", index=False)


# ====================================================================
# 入口
# ====================================================================


def run_server(debug: bool = True, port: int = 8050):
    """启动 Dashboard 服务"""
    app.run(debug=debug, port=port)
