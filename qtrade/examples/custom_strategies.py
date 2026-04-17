"""
示例策略

展示如何基于因子构建交易策略。
"""

from __future__ import annotations

import pandas as pd

from qtrade.strategy.base import Strategy
from qtrade.factor.engine import FactorEngine
from qtrade.data.market_data import MarketData
from qtrade.config import smart_dates

# 确保内置因子已注册
import qtrade.examples.custom_factors  # noqa: F401


class TopNStrategy(Strategy):
    """
    Top-N 因子选股策略

    每个调仓日选因子值最高的 top_n 只股票等权买入。

    Parameters
    ----------
    factor_name : 注册的因子名
    top_n : 选股数量
    symbols : 股票池
    start_date, end_date : 数据日期范围
    ascending : 是否按因子值升序排列选最小的 (默认 False = 选最大)
    factor_params : 因子的额外参数
    """

    name = "TopNStrategy"

    def __init__(
        self,
        factor_name: str = "momentum_20d",
        top_n: int = 10,
        symbols: list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        ascending: bool = False,
        **factor_params,
    ):
        self.factor_name = factor_name
        self.top_n = top_n
        self.symbols = symbols or [
            "AAPL", "MSFT", "GOOGL", "AMZN", "META",
            "NVDA", "TSLA", "JPM", "V", "JNJ",
            "WMT", "PG", "UNH", "HD", "MA",
            "DIS", "BAC", "XOM", "PFE", "CSCO",
            "NFLX", "ADBE", "CRM", "AMD", "INTC",
            "QCOM", "TXN", "COST", "AVGO", "ORCL",
        ]
        _dates = smart_dates()
        self.start_date = start_date or _dates["data_start"]
        self.end_date = end_date or _dates["backtest_end"]
        self.ascending = ascending
        self.factor_params = factor_params

        self._engine = FactorEngine()
        self._data: dict[str, pd.DataFrame] | None = None
        self._factor_values: pd.DataFrame | None = None

    def load_data(self) -> dict[str, pd.DataFrame]:
        if self._data is None:
            md = MarketData()
            self._data = md.load(self.symbols, self.start_date, self.end_date)
        return self._data

    def _ensure_factor(self, data: dict[str, pd.DataFrame]):
        if self._factor_values is None:
            self._factor_values = self._engine.compute_factor(
                self.factor_name, data, **self.factor_params
            )

    def generate_weights(
        self, date: pd.Timestamp, data: dict[str, pd.DataFrame]
    ) -> pd.Series | None:
        self._ensure_factor(data)
        if date not in self._factor_values.index:
            return None

        row = self._factor_values.loc[date].dropna()
        if len(row) < self.top_n:
            return None

        ranked = row.sort_values(ascending=self.ascending)
        selected = ranked.tail(self.top_n) if not self.ascending else ranked.head(self.top_n)
        weights = pd.Series(1.0 / self.top_n, index=selected.index)
        return weights


class LongShortStrategy(Strategy):
    """
    多空因子策略

    买入因子值最高的 top_n 只，卖出因子值最低的 top_n 只。
    """

    name = "LongShortStrategy"

    def __init__(
        self,
        factor_name: str = "momentum_20d",
        top_n: int = 5,
        symbols: list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        **factor_params,
    ):
        self.factor_name = factor_name
        self.top_n = top_n
        self.symbols = symbols or [
            "AAPL", "MSFT", "GOOGL", "AMZN", "META",
            "NVDA", "TSLA", "JPM", "V", "JNJ",
            "WMT", "PG", "UNH", "HD", "MA",
            "DIS", "BAC", "XOM", "PFE", "CSCO",
        ]
        _dates = smart_dates()
        self.start_date = start_date or _dates["data_start"]
        self.end_date = end_date or _dates["backtest_end"]
        self.factor_params = factor_params

        self._engine = FactorEngine()
        self._data: dict[str, pd.DataFrame] | None = None
        self._factor_values: pd.DataFrame | None = None

    def load_data(self) -> dict[str, pd.DataFrame]:
        if self._data is None:
            md = MarketData()
            self._data = md.load(self.symbols, self.start_date, self.end_date)
        return self._data

    def _ensure_factor(self, data: dict[str, pd.DataFrame]):
        if self._factor_values is None:
            self._factor_values = self._engine.compute_factor(
                self.factor_name, data, **self.factor_params
            )

    def generate_weights(
        self, date: pd.Timestamp, data: dict[str, pd.DataFrame]
    ) -> pd.Series | None:
        self._ensure_factor(data)
        if date not in self._factor_values.index:
            return None

        row = self._factor_values.loc[date].dropna()
        if len(row) < 2 * self.top_n:
            return None

        ranked = row.sort_values()
        longs = ranked.tail(self.top_n)
        shorts = ranked.head(self.top_n)

        weights = pd.Series(0.0, index=row.index)
        weights[longs.index] = 1.0 / self.top_n
        weights[shorts.index] = -1.0 / self.top_n
        return weights


class MultiFactorStrategy(Strategy):
    """
    多因子复合策略

    将多个因子的排名加权合成，然后选 top_n。
    """

    name = "MultiFactorStrategy"

    def __init__(
        self,
        factor_weights: dict[str, float] | None = None,
        top_n: int = 10,
        symbols: list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ):
        self.factor_weights = factor_weights or {
            "momentum_20d": 0.4,
            "reversal_5d": 0.3,
            "volatility_20d": -0.3,  # 低波动偏好
        }
        self.top_n = top_n
        self.symbols = symbols or [
            "AAPL", "MSFT", "GOOGL", "AMZN", "META",
            "NVDA", "TSLA", "JPM", "V", "JNJ",
            "WMT", "PG", "UNH", "HD", "MA",
            "DIS", "BAC", "XOM", "PFE", "CSCO",
        ]
        _dates = smart_dates()
        self.start_date = start_date or _dates["data_start"]
        self.end_date = end_date or _dates["backtest_end"]

        self._engine = FactorEngine()
        self._data: dict[str, pd.DataFrame] | None = None
        self._composite: pd.DataFrame | None = None

    def load_data(self) -> dict[str, pd.DataFrame]:
        if self._data is None:
            md = MarketData()
            self._data = md.load(self.symbols, self.start_date, self.end_date)
        return self._data

    def _build_composite(self, data: dict[str, pd.DataFrame]):
        if self._composite is not None:
            return
        factor_dfs = self._engine.compute_factors(
            list(self.factor_weights.keys()), data
        )
        # 排名标准化后加权
        composite = None
        for name, weight in self.factor_weights.items():
            ranked = self._engine.neutralize(factor_dfs[name], method="rank")
            if composite is None:
                composite = ranked * weight
            else:
                composite = composite.add(ranked * weight, fill_value=0)
        self._composite = composite

    def generate_weights(
        self, date: pd.Timestamp, data: dict[str, pd.DataFrame]
    ) -> pd.Series | None:
        self._build_composite(data)
        if date not in self._composite.index:
            return None

        row = self._composite.loc[date].dropna()
        if len(row) < self.top_n:
            return None

        selected = row.nlargest(self.top_n)
        return pd.Series(1.0 / self.top_n, index=selected.index)



