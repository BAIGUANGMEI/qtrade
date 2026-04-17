"""
回测引擎

基于目标权重的向量化回测框架，支持手续费、滑点。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from qtrade.config import (
    DEFAULT_COMMISSION_RATE,
    DEFAULT_INITIAL_CAPITAL,
    DEFAULT_SLIPPAGE,
)
from qtrade.backtest.performance import full_metrics


@dataclass
class BacktestResult:
    """回测结果"""

    equity_curve: pd.Series
    daily_returns: pd.Series
    positions: pd.DataFrame  # (date, symbol) -> weight
    trades: pd.DataFrame  # 调仓记录
    metrics: dict[str, float] = field(default_factory=dict)
    benchmark_curve: pd.Series | None = None

    def report(self, title: str = "回测绩效报告") -> None:
        """打印绩效报告 (rich 格式)"""
        from qtrade.utils.display import print_backtest_report
        print_backtest_report(self.metrics, title=title)


class BacktestEngine:
    """
    向量化回测引擎

    策略在每个调仓日产出目标权重，引擎根据权重和收盘价计算组合净值。

    Parameters
    ----------
    initial_capital : 初始资金
    start_date, end_date : 回测区间
    rebalance_freq : 调仓频率 "D"(日) / "W"(周) / "M"(月) / "Q"(季)
    commission : 单边手续费率
    slippage : 滑点率
    """

    def __init__(
        self,
        initial_capital: float = DEFAULT_INITIAL_CAPITAL,
        start_date: str = "2020-01-01",
        end_date: str = "2024-12-31",
        rebalance_freq: str = "M",
        commission: float = DEFAULT_COMMISSION_RATE,
        slippage: float = DEFAULT_SLIPPAGE,
    ):
        self.initial_capital = initial_capital
        self.start_date = pd.Timestamp(start_date)
        self.end_date = pd.Timestamp(end_date)
        self.rebalance_freq = rebalance_freq
        self.commission = commission
        self.slippage = slippage

    def run(
        self,
        strategy,
        data: dict[str, pd.DataFrame] | None = None,
        benchmark: pd.Series | None = None,
    ) -> BacktestResult:
        """
        执行回测。

        Parameters
        ----------
        strategy : Strategy 实例 (须实现 generate_weights 方法)
        data : 如果 strategy 内部未加载数据，这里传入
        benchmark : 基准价格序列 (如 SPY 收盘价), 用于计算超额收益等指标

        Returns
        -------
        BacktestResult
        """
        if data is None:
            data = strategy.load_data()

        close = data["close"]
        # 过滤日期范围
        mask = (close.index >= self.start_date) & (close.index <= self.end_date)
        close = close.loc[mask]
        daily_returns = close.pct_change().fillna(0)

        # 确定调仓日
        rebalance_dates = self._get_rebalance_dates(close.index)

        # 初始化
        n_dates = len(close)
        symbols = close.columns.tolist()
        weights = pd.DataFrame(0.0, index=close.index, columns=symbols)
        current_weights = pd.Series(0.0, index=symbols)

        equity = np.zeros(n_dates)
        equity[0] = self.initial_capital
        trade_records = []

        for i in range(n_dates):
            date = close.index[i]

            # 调仓日
            if date in rebalance_dates:
                # 裁剪数据到当前日期
                data_slice = {k: v.loc[:date] for k, v in data.items() if date in v.index}
                target_weights = strategy.generate_weights(date, data_slice)
                if target_weights is not None:
                    target_weights = target_weights.reindex(symbols).fillna(0)
                    # 权重归一化
                    w_sum = target_weights.abs().sum()
                    if w_sum > 0:
                        target_weights = target_weights / w_sum

                    # 换手成本
                    turnover = (target_weights - current_weights).abs().sum()
                    cost = turnover * (self.commission + self.slippage)

                    # 记录交易
                    changed = target_weights[target_weights != current_weights]
                    for sym in changed.index:
                        trade_records.append(
                            {
                                "date": date,
                                "symbol": sym,
                                "old_weight": current_weights.get(sym, 0),
                                "new_weight": target_weights[sym],
                            }
                        )

                    current_weights = target_weights.copy()
                else:
                    cost = 0.0
            else:
                cost = 0.0

            weights.iloc[i] = current_weights

            # 计算当日收益
            if i > 0:
                port_return = (current_weights * daily_returns.iloc[i]).sum() - cost
                equity[i] = equity[i - 1] * (1 + port_return)
            else:
                equity[i] = self.initial_capital

        equity_series = pd.Series(equity, index=close.index, name="equity")
        daily_ret = equity_series.pct_change().dropna()

        # 基准净值 (对齐到回测区间并归一化到同样初始资金)
        benchmark_curve = None
        if benchmark is not None:
            bench = benchmark.reindex(close.index).dropna()
            if len(bench) > 0:
                benchmark_curve = bench / bench.iloc[0] * self.initial_capital
                benchmark_curve.name = "benchmark"

        # 绩效
        metrics = full_metrics(equity_series, benchmark_curve=benchmark_curve)

        trades_df = pd.DataFrame(trade_records) if trade_records else pd.DataFrame(
            columns=["date", "symbol", "old_weight", "new_weight"]
        )

        return BacktestResult(
            equity_curve=equity_series,
            daily_returns=daily_ret,
            positions=weights,
            trades=trades_df,
            metrics=metrics,
            benchmark_curve=benchmark_curve,
        )

    def _get_rebalance_dates(self, index: pd.DatetimeIndex) -> set[pd.Timestamp]:
        """根据频率获取调仓日"""
        if self.rebalance_freq == "D":
            return set(index)

        # to_period 需要旧式别名 (M, Q), 不能用 ME/QE
        freq_map = {"W": "W-FRI", "M": "M", "Q": "Q"}
        freq = freq_map.get(self.rebalance_freq, self.rebalance_freq)

        # 找每个周期最后一个交易日
        periods = index.to_period(freq)
        last_days = set()
        for period in periods.unique():
            mask = periods == period
            dates_in_period = index[mask]
            if len(dates_in_period) > 0:
                last_days.add(dates_in_period[-1])
        return last_days
