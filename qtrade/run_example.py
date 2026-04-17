"""
QTrade 运行入口示例

演示默认 TopN 因子选股策略回测。
直接运行: python -m qtrade.run_example
"""

from __future__ import annotations

import pandas as pd

from qtrade.backtest.engine import BacktestEngine
from qtrade.config import smart_dates
from qtrade.data.market_data import MarketData, load_sp500_symbols
from qtrade.factor.engine import FactorEngine
from qtrade.utils.display import (
    console,
    df_to_table,
    info,
    kv,
    section,
)

# 注册内置因子
import qtrade.examples.custom_factors  # noqa: F401
from qtrade.examples.custom_strategies import TopNStrategy


def main():
    console.print()
    console.rule("[bold]QTrade - 美股因子量化系统", style="bright_blue")
    console.print()

    # ============ 参数设置 ============
    section("加载标普500成分股")
    symbols = load_sp500_symbols()
    kv("成分股数量", str(len(symbols)))

    dates = smart_dates()
    data_start = dates["data_start"]
    start = dates["backtest_start"]
    end = dates["backtest_end"]
    kv("数据起点", data_start)
    kv("回测区间", f"{start} ~ {end}")

    # ============ 加载数据 ============
    section("加载市场数据")
    md = MarketData()
    data = md.load(symbols=symbols, start=data_start, end=end)
    kv("数据范围", f"{data['close'].index[0].date()} ~ {data['close'].index[-1].date()}")
    kv("股票数量", str(len(data["close"].columns)))
    kv("交易日数", str(len(data["close"])))

    section("加载基准 - SPY (S&P 500)")
    benchmark = md.load_benchmark(start=data_start, end=end)
    kv("基准", f"SPY  {benchmark.index[0].date()} ~ {benchmark.index[-1].date()}")

    # ============ 计算因子 ============
    section("计算因子")
    engine = FactorEngine()
    factor_name = "momentum_20d"
    factor_values = engine.compute_factor(factor_name, data)
    info(f"[bold]{factor_name}[/bold]  shape={factor_values.shape}  NaN={factor_values.isna().mean().mean():.1%}")

    # ============ 策略回测 ============
    bt_engine = BacktestEngine(
        initial_capital=1_000_000,
        start_date=start,
        end_date=end,
        rebalance_freq="W",
        commission=0.001,
        slippage=0.001,
    )

    section("策略回测 - TopN 动量选股")
    strategy = TopNStrategy(
        factor_name=factor_name,
        top_n=10,
        symbols=symbols,
        start_date=data_start,
        end_date=end,
    )
    result = bt_engine.run(strategy, benchmark=benchmark)
    result.report(title="TopN 动量选股 绩效")
    info(f"调仓次数: {len(result.trades)}")

    console.print()
    console.rule("[dim]分析完成[/dim]", style="dim")
    console.print()


if __name__ == "__main__":
    main()
