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


def run_backtest(
    strategy_type: str = "TopNStrategy",
    top_n: int = 10,
    rebalance_freq: str = "W",
    initial_capital: float = 1_000_000,
    backtest_months: int = 12,
    warmup_months: int = 10,
    end_date: str | None = None,
) -> DashboardData:
    """运行一次完整回测并收集所有分析数据"""

    dates = smart_dates(
        backtest_months=backtest_months,
        warmup_months=warmup_months,
        end_date=end_date,
    )
    data_start = dates["data_start"]
    bt_start = dates["backtest_start"]
    bt_end = dates["backtest_end"]

    # 加载数据
    symbols = load_sp500_symbols()
    md = MarketData()
    data = md.load(symbols=symbols, start=data_start, end=bt_end)
    benchmark = md.load_benchmark(start=data_start, end=bt_end)

    # 从注册表获取策略类
    strategy_cls = get_strategy(strategy_type)
    factor_names: list[str] = getattr(strategy_cls, "default_factor_names", [])
    effective_factor = factor_names[0] if factor_names else "momentum_20d"

    # 计算因子 (用于 IC / 分组分析展示)
    engine = FactorEngine()
    fv = engine.compute_factor(effective_factor, data)

    # IC 分析
    ic_analyzer = ICAnalyzer(fv, data["close"])
    ic_summary = ic_analyzer.ic_summary()
    rank_ic_summary = ic_analyzer.rank_ic_summary()
    ic_decay = ic_analyzer.ic_decay(max_period=20, method="spearman")
    ic_series_1d = ic_analyzer.ic_series(period=1, method="spearman")

    # 分组分析
    ga = GroupAnalyzer(fv, data["close"])
    group_cum = ga.cumulative_group_returns()
    group_sum = ga.group_summary()
    ls_cum = ga.cumulative_long_short()

    # 策略构建 — 尝试通用参数组合
    actual_symbols = list(data["close"].columns)
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
    result = bt_engine.run(strategy, benchmark=benchmark)

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
