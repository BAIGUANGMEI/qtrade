"""
IC / Rank IC 分析模块

提供 Information Coefficient 的完整分析框架。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

from qtrade.config import DEFAULT_FORWARD_PERIODS


class ICAnalyzer:
    """
    因子 IC 分析器

    Parameters
    ----------
    factor_values : DataFrame (index=日期, columns=股票) — 因子值
    close_prices  : DataFrame (同结构) — 收盘价
    """

    def __init__(
        self,
        factor_values: pd.DataFrame,
        close_prices: pd.DataFrame,
    ):
        # 对齐索引
        common_dates = factor_values.index.intersection(close_prices.index)
        common_cols = factor_values.columns.intersection(close_prices.columns)
        self.factor = factor_values.loc[common_dates, common_cols]
        self.close = close_prices.loc[common_dates, common_cols]

    # ------------------------------------------------------------------
    # 核心计算
    # ------------------------------------------------------------------

    def forward_returns(self, period: int = 1) -> pd.DataFrame:
        """计算 period 日前瞻收益率"""
        return self.close.shift(-period) / self.close - 1

    def ic_series(self, period: int = 1, method: str = "pearson") -> pd.Series:
        """
        逐日 IC 序列。

        method: "pearson" (IC) 或 "spearman" (Rank IC)
        """
        fwd = self.forward_returns(period)
        ic_list = []
        for date in self.factor.index:
            f = self.factor.loc[date].dropna()
            r = fwd.loc[date].dropna()
            common = f.index.intersection(r.index)
            if len(common) < 5:
                ic_list.append(np.nan)
                continue
            if method == "pearson":
                corr, _ = stats.pearsonr(f[common], r[common])
            else:
                corr, _ = stats.spearmanr(f[common], r[common])
            ic_list.append(corr)
        return pd.Series(ic_list, index=self.factor.index, name=f"IC_{period}d")

    def rank_ic_series(self, period: int = 1) -> pd.Series:
        """Rank IC 序列 (Spearman)"""
        return self.ic_series(period, method="spearman")

    # ------------------------------------------------------------------
    # 汇总统计
    # ------------------------------------------------------------------

    def ic_summary(
        self,
        periods: list[int] | None = None,
        method: str = "pearson",
    ) -> pd.DataFrame:
        """
        多个持有期的 IC 汇总表。

        返回列: IC_mean, IC_std, IC_IR, IC>0占比, |IC|>0.02占比
        """
        periods = periods or DEFAULT_FORWARD_PERIODS
        rows = []
        for p in periods:
            s = self.ic_series(p, method=method).dropna()
            rows.append(
                {
                    "period": p,
                    "IC_mean": s.mean(),
                    "IC_std": s.std(),
                    "IC_IR": s.mean() / s.std() if s.std() != 0 else 0,
                    "IC>0_pct": (s > 0).mean(),
                    "|IC|>0.02_pct": (s.abs() > 0.02).mean(),
                    "t_stat": s.mean() / (s.std() / np.sqrt(len(s))) if s.std() != 0 else 0,
                }
            )
        return pd.DataFrame(rows).set_index("period")

    def rank_ic_summary(
        self,
        periods: list[int] | None = None,
    ) -> pd.DataFrame:
        """Rank IC 汇总表"""
        return self.ic_summary(periods, method="spearman")

    # ------------------------------------------------------------------
    # IC 衰减
    # ------------------------------------------------------------------

    def ic_decay(
        self,
        max_period: int = 20,
        method: str = "spearman",
    ) -> pd.Series:
        """IC 随持有期的衰减曲线"""
        return pd.Series(
            {p: self.ic_series(p, method).dropna().mean() for p in range(1, max_period + 1)},
            name="IC_decay",
        )

    # ------------------------------------------------------------------
    # 完整报告
    # ------------------------------------------------------------------

    def full_report(
        self,
        periods: list[int] | None = None,
    ) -> dict[str, pd.DataFrame]:
        """返回完整 IC 分析字典"""
        periods = periods or DEFAULT_FORWARD_PERIODS
        return {
            "ic_summary": self.ic_summary(periods, method="pearson"),
            "rank_ic_summary": self.rank_ic_summary(periods),
            "ic_decay": self.ic_decay(),
        }
