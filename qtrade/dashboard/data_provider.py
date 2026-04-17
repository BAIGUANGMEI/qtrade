"""
Dashboard 数据供给层

运行回测并将结果缓存，供 Dashboard 各页面读取。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from qtrade.analysis.ic_analysis import ICAnalyzer
from qtrade.analysis.group_analysis import GroupAnalyzer
from qtrade.backtest.engine import BacktestEngine, BacktestResult
from qtrade.config import smart_dates
from qtrade.data.market_data import MarketData, load_sp500_symbols
from qtrade.factor.engine import FactorEngine

# 注册因子 -----------------------------------------------------------
import qtrade.examples.custom_factors  # noqa: F401

try:
    import qtrade.examples.composite_factors  # noqa: F401
except Exception:
    pass

# 注册策略 -----------------------------------------------------------
import qtrade.examples.custom_strategies  # noqa: F401

try:
    import qtrade.examples.composite_strategy  # noqa: F401
except Exception:
    pass

from qtrade.strategy.base import get_strategy


@dataclass
class DashboardData:
    """一次回测运行的全部可视化数据"""

    # 基本参数
    strategy_name: str = ""
    data_start: str = ""
    backtest_start: str = ""
    backtest_end: str = ""
    symbols_count: int = 0

    # 回测结果
    result: BacktestResult | None = None

    # 因子
    factor_values: pd.DataFrame = field(default_factory=pd.DataFrame)
    factor_name: str = ""

    # IC 分析
    ic_summary: pd.DataFrame = field(default_factory=pd.DataFrame)
    rank_ic_summary: pd.DataFrame = field(default_factory=pd.DataFrame)
    ic_decay: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    ic_series_1d: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))

    # 分组分析
    group_cum_returns: pd.DataFrame = field(default_factory=pd.DataFrame)
    group_summary: pd.DataFrame = field(default_factory=pd.DataFrame)
    long_short_cum: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))

    # 原始数据
    close_prices: pd.DataFrame = field(default_factory=pd.DataFrame)
    benchmark: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))

    # 实时回测标志
    live: bool = False
    live_bar: int = 0
    live_total: int = 0
    live_status: str = ""  # running / done / cancelled / error


def _cancelled(cancel_event) -> bool:
    return cancel_event is not None and cancel_event.is_set()


def run_backtest(
    strategy_type: str = "TopNStrategy",
    top_n: int = 10,
    rebalance_freq: str = "W",
    initial_capital: float = 1_000_000,
    backtest_months: int = 12,
    warmup_months: int = 10,
    end_date: str | None = None,
    symbols: list[str] | None = None,
    progress_callback=None,
    cancel_event=None,
    run_factor_analysis: bool = True,
) -> DashboardData:
    """运行一次完整回测并收集所有分析数据

    Parameters
    ----------
    run_factor_analysis : bool
        是否进行 IC / 分组 因子分析。关闭时相关字段保留为空, 可显著加快回测启动。
        当 cancel_event 被设置时, 因子分析阶段会在下一个 checkpoint 中断。
    """

    dates = smart_dates(
        backtest_months=backtest_months,
        warmup_months=warmup_months,
        end_date=end_date,
    )
    data_start = dates["data_start"]
    bt_start = dates["backtest_start"]
    bt_end = dates["backtest_end"]

    # 加载数据
    if symbols is None:
        symbols = load_sp500_symbols()
    md = MarketData()
    data = md.load(symbols=symbols, start=data_start, end=bt_end)

    if _cancelled(cancel_event):
        return DashboardData(strategy_name=strategy_type, data_start=data_start,
                             backtest_start=bt_start, backtest_end=bt_end)

    benchmark = md.load_benchmark(start=data_start, end=bt_end)

    if _cancelled(cancel_event):
        return DashboardData(strategy_name=strategy_type, data_start=data_start,
                             backtest_start=bt_start, backtest_end=bt_end)

    # 从注册表获取策略类
    strategy_cls = get_strategy(strategy_type)
    factor_names: list[str] = getattr(strategy_cls, "default_factor_names", [])
    effective_factor = factor_names[0] if factor_names else "momentum_20d"

    # 计算因子 (用于 IC / 分组分析展示 + 策略取值)
    engine = FactorEngine()
    fv = engine.compute_factor(effective_factor, data)

    if _cancelled(cancel_event):
        return DashboardData(strategy_name=strategy_type, data_start=data_start,
                             backtest_start=bt_start, backtest_end=bt_end)

    # IC / 分组 分析 (可选; 每步之前检查取消)
    ic_summary = pd.DataFrame()
    rank_ic_summary = pd.DataFrame()
    ic_decay: pd.Series = pd.Series(dtype=float)
    ic_series_1d: pd.Series = pd.Series(dtype=float)
    group_cum = pd.DataFrame()
    group_sum = pd.DataFrame()
    ls_cum: pd.Series = pd.Series(dtype=float)

    if run_factor_analysis and not _cancelled(cancel_event):
        ic_analyzer = ICAnalyzer(fv, data["close"])
        ic_summary = ic_analyzer.ic_summary()
        if not _cancelled(cancel_event):
            rank_ic_summary = ic_analyzer.rank_ic_summary()
        if not _cancelled(cancel_event):
            ic_decay = ic_analyzer.ic_decay(max_period=20, method="spearman")
        if not _cancelled(cancel_event):
            ic_series_1d = ic_analyzer.ic_series(period=1, method="spearman")

        if not _cancelled(cancel_event):
            ga = GroupAnalyzer(fv, data["close"])
            group_cum = ga.cumulative_group_returns()
            if not _cancelled(cancel_event):
                group_sum = ga.group_summary()
            if not _cancelled(cancel_event):
                ls_cum = ga.cumulative_long_short()

    # 如果因子分析阶段被取消, 直接返回空壳, runner 会识别 cancel_event
    if _cancelled(cancel_event):
        return DashboardData(
            strategy_name=strategy_cls.__name__,
            data_start=data_start,
            backtest_start=bt_start,
            backtest_end=bt_end,
            symbols_count=len(data["close"].columns),
            result=None,
            factor_values=fv,
            factor_name=effective_factor,
            close_prices=data["close"],
            benchmark=benchmark,
        )

    # 策略构建 — 尝试通用参数组合
    actual_symbols = list(data["close"].columns)

    if _cancelled(cancel_event):
        return DashboardData(strategy_name=strategy_type, data_start=data_start,
                             backtest_start=bt_start, backtest_end=bt_end,
                             factor_values=fv, factor_name=effective_factor,
                             close_prices=data["close"], benchmark=benchmark)

    try:
        # 优先尝试 factor_name + top_n (TopN / LongShort)
        strategy = strategy_cls(
            factor_name=effective_factor,
            top_n=top_n,
            symbols=actual_symbols,
            start_date=data_start,
            end_date=bt_end,
        )
    except TypeError:
        # 回退到 top_n only (MultiFactorStrategy / IntradayComposite)
        strategy = strategy_cls(
            top_n=top_n,
            symbols=actual_symbols,
            start_date=data_start,
            end_date=bt_end,
        )

    # 回测
    bt_engine = BacktestEngine(
        initial_capital=initial_capital,
        start_date=bt_start,
        end_date=bt_end,
        rebalance_freq=rebalance_freq,
        commission=0.001,
        slippage=0.001,
    )
    result = bt_engine.run(
        strategy,
        benchmark=benchmark,
        progress_callback=progress_callback,
        cancel_event=cancel_event,
    )

    return DashboardData(
        strategy_name=strategy.name,
        data_start=data_start,
        backtest_start=bt_start,
        backtest_end=bt_end,
        symbols_count=len(actual_symbols),
        result=result,
        factor_values=fv,
        factor_name=effective_factor,
        ic_summary=ic_summary,
        rank_ic_summary=rank_ic_summary,
        ic_decay=ic_decay,
        ic_series_1d=ic_series_1d,
        group_cum_returns=group_cum,
        group_summary=group_sum,
        long_short_cum=ls_cum,
        close_prices=data["close"],
        benchmark=benchmark,
    )


# ====================================================================
# 从数据库加载历史回测 (不重新计算因子)
# ====================================================================

def load_run_from_store(run_id: int, store=None) -> DashboardData:
    """根据 run_id 从数据库读取历史回测, 重建 DashboardData。

    因子分析 (IC / 分组) 的中间数据未持久化, 此处返回空表,
    因子分析页会提示「历史回测未保存因子分析明细」。
    """
    from qtrade.persistence import get_default_store

    if store is None:
        store = get_default_store()

    result = store.load(run_id)

    from sqlalchemy import select

    from qtrade.persistence.models import backtest_runs

    with store.engine.connect() as conn:
        row = conn.execute(
            select(
                backtest_runs.c.name,
                backtest_runs.c.strategy_name,
                backtest_runs.c.start_date,
                backtest_runs.c.end_date,
                backtest_runs.c.config_json,
            ).where(backtest_runs.c.id == run_id)
        ).mappings().first()

    if row is None:
        raise KeyError(f"run_id={run_id} 不存在")

    config = dict(row["config_json"] or {})
    strategy_name = str(row["strategy_name"] or config.get("strategy_name", ""))
    factor_name = str(
        config.get("factor_name")
        or config.get("effective_factor")
        or ""
    )
    bt_start = str(row["start_date"].date()) if row["start_date"] else ""
    bt_end = str(row["end_date"].date()) if row["end_date"] else ""

    symbols_count = int(config.get("symbol_count") or 0)
    if symbols_count == 0 and result.positions is not None:
        symbols_count = int(result.positions.shape[1])

    benchmark = (
        result.benchmark_curve
        if result.benchmark_curve is not None
        else pd.Series(dtype=float)
    )

    return DashboardData(
        strategy_name=strategy_name,
        data_start=str(config.get("data_start", "")),
        backtest_start=bt_start,
        backtest_end=bt_end,
        symbols_count=symbols_count,
        result=result,
        factor_name=factor_name,
        benchmark=benchmark,
    )
