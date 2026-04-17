"""
因子相关性分析模块
"""

from __future__ import annotations

import pandas as pd
import numpy as np


class CorrelationAnalyzer:
    """
    分析多因子间的相关性

    Parameters
    ----------
    factor_dict : dict[str, DataFrame] — {因子名: 因子值 DataFrame}
    """

    def __init__(self, factor_dict: dict[str, pd.DataFrame]):
        self.factor_dict = factor_dict

    def _stack_factors(self) -> pd.DataFrame:
        """将多个因子合并为长表 (date, symbol, factor_name, value)"""
        frames = []
        for name, df in self.factor_dict.items():
            s = df.stack()
            s.name = name
            frames.append(s)
        combined = pd.concat(frames, axis=1)
        return combined

    def cross_sectional_corr(self, method: str = "spearman") -> pd.DataFrame:
        """
        逐日横截面相关性的时间序列均值。

        Returns
        -------
        DataFrame (因子×因子) — 平均相关系数矩阵
        """
        stacked = self._stack_factors()
        names = list(self.factor_dict.keys())
        n = len(names)
        corr_sum = np.zeros((n, n))
        count = 0

        dates = stacked.index.get_level_values(0).unique()
        for dt in dates:
            row = stacked.loc[dt].dropna()
            if len(row) < 5:
                continue
            c = row[names].corr(method=method).values
            if not np.isnan(c).any():
                corr_sum += c
                count += 1

        if count == 0:
            return pd.DataFrame(np.nan, index=names, columns=names)
        return pd.DataFrame(corr_sum / count, index=names, columns=names)

    def time_series_corr(self, method: str = "pearson") -> pd.DataFrame:
        """
        因子均值时序相关性 (每日截面均值的时间序列相关)。
        """
        means = pd.DataFrame(
            {name: df.mean(axis=1) for name, df in self.factor_dict.items()}
        )
        return means.corr(method=method)

    def vif(self) -> pd.Series:
        """
        方差膨胀因子 (VIF)，衡量多重共线性。
        """
        stacked = self._stack_factors().dropna()
        names = list(self.factor_dict.keys())
        from numpy.linalg import inv

        corr = stacked[names].corr().values
        try:
            inv_corr = inv(corr)
            vif_values = pd.Series(np.diag(inv_corr), index=names, name="VIF")
        except np.linalg.LinAlgError:
            vif_values = pd.Series(np.nan, index=names, name="VIF")
        return vif_values
