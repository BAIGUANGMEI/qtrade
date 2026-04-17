"""
绩效指标计算模块
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from qtrade.config import RISK_FREE_RATE, TRADING_DAYS_PER_YEAR


def annual_return(equity_curve: pd.Series) -> float:
    """年化收益率"""
    total_days = (equity_curve.index[-1] - equity_curve.index[0]).days
    if total_days <= 0:
        return 0.0
    total_return = equity_curve.iloc[-1] / equity_curve.iloc[0]
    return float(total_return ** (365.0 / total_days) - 1)


def annual_volatility(daily_returns: pd.Series) -> float:
    """年化波动率"""
    return float(daily_returns.std() * np.sqrt(TRADING_DAYS_PER_YEAR))


def sharpe_ratio(daily_returns: pd.Series, rf: float = RISK_FREE_RATE) -> float:
    """夏普比率"""
    ann_ret = daily_returns.mean() * TRADING_DAYS_PER_YEAR
    ann_vol = annual_volatility(daily_returns)
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


def win_rate(trade_returns: pd.Series) -> float:
    """胜率"""
    if len(trade_returns) == 0:
        return 0.0
    return float((trade_returns > 0).sum() / len(trade_returns))


def profit_loss_ratio(trade_returns: pd.Series) -> float:
    """盈亏比"""
    wins = trade_returns[trade_returns > 0]
    losses = trade_returns[trade_returns < 0]
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
    return float(excess.mean() / excess.std() * np.sqrt(TRADING_DAYS_PER_YEAR))


def sortino_ratio(daily_returns: pd.Series, rf: float = RISK_FREE_RATE) -> float:
    """索提诺比率 (只考虑下行波动)"""
    ann_ret = daily_returns.mean() * TRADING_DAYS_PER_YEAR
    downside = daily_returns[daily_returns < 0]
    downside_vol = downside.std() * np.sqrt(TRADING_DAYS_PER_YEAR) if len(downside) > 0 else 0
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
