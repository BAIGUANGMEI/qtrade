"""
分组回测分析模块

按因子值分 N 组，计算各组累计收益、多空收益等。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from qtrade.config import DEFAULT_QUANTILE_GROUPS


class GroupAnalyzer:
    """
    因子分组回测分析器

    Parameters
    ----------
    factor_values : DataFrame (index=日期, columns=股票)
    close_prices  : DataFrame (同结构)
    n_groups      : 分组数量
    """

    def __init__(
        self,
        factor_values: pd.DataFrame,
        close_prices: pd.DataFrame,
        n_groups: int = DEFAULT_QUANTILE_GROUPS,
    ):
        common_dates = factor_values.index.intersection(close_prices.index)
        common_cols = factor_values.columns.intersection(close_prices.columns)
        self.factor = factor_values.loc[common_dates, common_cols]
        self.close = close_prices.loc[common_dates, common_cols]
        self.n_groups = n_groups
        self.daily_returns = self.close.pct_change()

    def group_labels(self) -> pd.DataFrame:
        """
        逐日将股票分配到 1~n_groups 组。

        返回 DataFrame (同 factor 形状), 值为组号 (1=最低, n_groups=最高)
        """

        def _row_qcut(row):
            valid = row.dropna()
            if len(valid) < self.n_groups:
                return row * np.nan
            try:
                labels = pd.qcut(valid, self.n_groups, labels=False, duplicates="drop") + 1
            except ValueError:
                return row * np.nan
            return labels.reindex(row.index)

        return self.factor.apply(_row_qcut, axis=1)

    def group_returns(self, period: int = 1) -> pd.DataFrame:
        """
        各组等权日收益率。

        Returns
        -------
        DataFrame (index=日期, columns=[Group_1 … Group_N])
        """
        labels = self.group_labels()
        fwd = self.daily_returns.shift(-1) if period == 1 else (
            self.close.shift(-period) / self.close - 1
        )

        result = {}
        for g in range(1, self.n_groups + 1):
            mask = labels == g
            group_ret = (fwd * mask).sum(axis=1) / mask.sum(axis=1).replace(0, np.nan)
            result[f"Group_{g}"] = group_ret

        return pd.DataFrame(result).dropna()

    def cumulative_group_returns(self, period: int = 1) -> pd.DataFrame:
        """各组累计收益"""
        gr = self.group_returns(period)
        return (1 + gr).cumprod() - 1

    def long_short_return(self, period: int = 1) -> pd.Series:
        """多空组合日收益 (最高组 - 最低组)"""
        gr = self.group_returns(period)
        return gr[f"Group_{self.n_groups}"] - gr["Group_1"]

    def cumulative_long_short(self, period: int = 1) -> pd.Series:
        """多空组合累计收益"""
        ls = self.long_short_return(period)
        return (1 + ls).cumprod() - 1

    def group_summary(self, period: int = 1) -> pd.DataFrame:
        """各组年化收益与夏普"""
        gr = self.group_returns(period)
        annual_ret = gr.mean() * 252
        annual_vol = gr.std() * np.sqrt(252)
        sharpe = annual_ret / annual_vol.replace(0, np.nan)
        return pd.DataFrame(
            {"annual_return": annual_ret, "annual_vol": annual_vol, "sharpe": sharpe}
        )

    def turnover(self) -> pd.DataFrame:
        """各组每日换手率"""
        labels = self.group_labels()
        result = {}
        for g in range(1, self.n_groups + 1):
            mask = (labels == g).astype(float)
            # 换手 = 成分变化比例
            changed = (mask.diff().abs().sum(axis=1)) / (2 * mask.sum(axis=1).replace(0, np.nan))
            result[f"Group_{g}"] = changed
        return pd.DataFrame(result).dropna()
