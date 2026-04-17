"""
绩效指标计算模块
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from qtrade.config import RISK_FREE_RATE, TRADING_DAYS_PER_YEAR


# ------------------------------------------------------------------
# 年化因子推断
# ------------------------------------------------------------------

def infer_periods_per_year(index: pd.DatetimeIndex) -> float:
    """
    根据时间索引推断 "每年观测期数" (年化因子)。

    依据真实交易时间 (起止日期跨度 + 观测数) 计算, 避免对日频/小时频/周频
    硬编码 252。当样本过少或跨度不足时, 回退到 ``TRADING_DAYS_PER_YEAR`` 作为默认值。

    公式: periods_per_year = n_obs / (span_days / 365.25)
    """
    if index is None or len(index) < 2:
        return float(TRADING_DAYS_PER_YEAR)
    span_days = (index[-1] - index[0]).days
    if span_days <= 0:
        return float(TRADING_DAYS_PER_YEAR)
    # 观测期数 = 观测点数 - 1 (相邻两点产生一次收益观测)
    n_periods = len(index) - 1
    years = span_days / 365.25
    if years <= 0 or n_periods <= 0:
        return float(TRADING_DAYS_PER_YEAR)
    return float(n_periods / years)


def _ppy_from_returns(returns: pd.Series) -> float:
    """从收益序列的 DatetimeIndex 推断年化因子"""
    if not isinstance(returns.index, pd.DatetimeIndex):
        return float(TRADING_DAYS_PER_YEAR)
    return infer_periods_per_year(returns.index)


def annual_return(equity_curve: pd.Series) -> float:
    """年化收益率 (基于真实交易时间跨度)"""
    n_bars = len(equity_curve) - 1  # 区间内的收益观测数
    if n_bars <= 0:
        return 0.0
    total_return = equity_curve.iloc[-1] / equity_curve.iloc[0]
    if total_return <= 0:
        # 爆仓 / 负净值场景下幂运算无定义, 回退为简单推算避免 NaN
        return float(total_return - 1)
    ppy = infer_periods_per_year(equity_curve.index) if isinstance(
        equity_curve.index, pd.DatetimeIndex
    ) else float(TRADING_DAYS_PER_YEAR)
    return float(total_return ** (ppy / n_bars) - 1)


def annual_volatility(daily_returns: pd.Series) -> float:
    """年化波动率 (基于真实交易频率)"""
    ppy = _ppy_from_returns(daily_returns)
    return float(daily_returns.std() * np.sqrt(ppy))


def sharpe_ratio(daily_returns: pd.Series, rf: float = RISK_FREE_RATE) -> float:
    """夏普比率"""
    ppy = _ppy_from_returns(daily_returns)
    ann_ret = daily_returns.mean() * ppy
    ann_vol = daily_returns.std() * np.sqrt(ppy)
    if ann_vol == 0:
        return 0.0
    return float((ann_ret - rf) / ann_vol)


def max_drawdown(equity_curve: pd.Series) -> float:
    """最大回撤"""
    running_max = equity_curve.cummax()
    drawdown = (equity_curve - running_max) / running_max
    return float(drawdown.min())


def max_drawdown_duration(equity_curve: pd.Series) -> int:
    """最大回撤持续天数"""
    running_max = equity_curve.cummax()
    underwater = running_max != equity_curve
    if not underwater.any():
        return 0
    groups = (~underwater).cumsum()
    durations = underwater.groupby(groups).sum()
    return int(durations.max()) if len(durations) > 0 else 0


def calmar_ratio(equity_curve: pd.Series) -> float:
    """卡尔马比率 (年化收益 / |最大回撤|)"""
    mdd = abs(max_drawdown(equity_curve))
    if mdd == 0:
        return 0.0
    return annual_return(equity_curve) / mdd


def win_rate(returns: pd.Series) -> float:
    """胜率 (正收益观测占比)

    注意: 传入 daily_returns 则得到 *日度胜率*; 传入逐笔 trade_returns 则得到
    *交易胜率*。本项目当前在 full_metrics 中以 daily_returns 作为输入。
    """
    if len(returns) == 0:
        return 0.0
    return float((returns > 0).sum() / len(returns))


def profit_loss_ratio(returns: pd.Series) -> float:
    """盈亏比 (正收益均值 / |负收益均值|)

    与 win_rate 同, 传入 daily_returns 得日度盈亏比, 传入 trade_returns 得交易盈亏比。
    """
    wins = returns[returns > 0]
    losses = returns[returns < 0]
    if len(losses) == 0 or losses.mean() == 0:
        return float("inf") if len(wins) > 0 else 0.0
    return float(abs(wins.mean() / losses.mean()))


def information_ratio(
    portfolio_returns: pd.Series, benchmark_returns: pd.Series
) -> float:
    """信息比率"""
    excess = portfolio_returns - benchmark_returns
    if excess.std() == 0:
        return 0.0
    ppy = _ppy_from_returns(portfolio_returns)
    return float(excess.mean() / excess.std() * np.sqrt(ppy))


def sortino_ratio(daily_returns: pd.Series, rf: float = RISK_FREE_RATE) -> float:
    """索提诺比率 (只考虑下行波动)"""
    ppy = _ppy_from_returns(daily_returns)
    ann_ret = daily_returns.mean() * ppy
    downside = daily_returns[daily_returns < 0]
    downside_vol = downside.std() * np.sqrt(ppy) if len(downside) > 0 else 0
    if downside_vol == 0:
        return 0.0
    return float((ann_ret - rf) / downside_vol)


def full_metrics(
    equity_curve: pd.Series,
    benchmark_curve: pd.Series | None = None,
) -> dict[str, float]:
    """计算完整绩效指标"""
    daily_ret = equity_curve.pct_change().dropna()

    metrics = {
        "total_return": float(equity_curve.iloc[-1] / equity_curve.iloc[0] - 1),
        "annual_return": annual_return(equity_curve),
        "annual_volatility": annual_volatility(daily_ret),
        "sharpe_ratio": sharpe_ratio(daily_ret),
        "sortino_ratio": sortino_ratio(daily_ret),
        "max_drawdown": max_drawdown(equity_curve),
        "max_drawdown_duration_days": max_drawdown_duration(equity_curve),
        "calmar_ratio": calmar_ratio(equity_curve),
        # 以下两项基于日度收益序列, 并非逐笔交易盈亏, 指标名称中已加 "daily_" 前缀
        # 以避免与真实交易胜率混淆; 同时保留旧 key 作为别名以兼容历史代码。
        "daily_win_rate": win_rate(daily_ret),
        "daily_profit_loss_ratio": profit_loss_ratio(daily_ret),
        "win_rate": win_rate(daily_ret),
        "profit_loss_ratio": profit_loss_ratio(daily_ret),
    }

    if benchmark_curve is not None:
        bench_ret = benchmark_curve.pct_change().dropna()
        common = daily_ret.index.intersection(bench_ret.index)
        metrics["information_ratio"] = information_ratio(
            daily_ret.loc[common], bench_ret.loc[common]
        )
        metrics["benchmark_return"] = float(
            benchmark_curve.iloc[-1] / benchmark_curve.iloc[0] - 1
        )
        metrics["excess_return"] = metrics["total_return"] - metrics["benchmark_return"]

    return metrics
