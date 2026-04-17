"""
因子计算引擎

负责调用已注册因子进行批量计算、横截面标准化等。
"""

from __future__ import annotations

import pandas as pd

from qtrade.factor.base import Factor, get_factor


class FactorEngine:
    """因子计算引擎"""

    def compute_factor(
        self,
        factor_name: str,
        data: dict[str, pd.DataFrame],
        **params,
    ) -> pd.DataFrame:
        """
        计算单个因子。

        Parameters
        ----------
        factor_name : 注册的因子名
        data : Panel 数据
        params : 因子参数

        Returns
        -------
        DataFrame (index=日期, columns=股票)
        """
        factor_cls = get_factor(factor_name)
        factor = factor_cls(**params)
        return factor.compute(data)

    def compute_factors(
        self,
        factor_names: list[str],
        data: dict[str, pd.DataFrame],
        params_map: dict[str, dict] | None = None,
    ) -> dict[str, pd.DataFrame]:
        """批量计算多个因子"""
        params_map = params_map or {}
        results: dict[str, pd.DataFrame] = {}
        for name in factor_names:
            p = params_map.get(name, {})
            results[name] = self.compute_factor(name, data, **p)
        return results

    @staticmethod
    def neutralize(
        factor_values: pd.DataFrame,
        method: str = "zscore",
    ) -> pd.DataFrame:
        """
        横截面标准化 (逐行)。

        method: "zscore" | "rank" | "minmax"
        """
        if method == "zscore":
            mean = factor_values.mean(axis=1)
            std = factor_values.std(axis=1)
            return factor_values.sub(mean, axis=0).div(std.replace(0, 1), axis=0)
        elif method == "rank":
            return factor_values.rank(axis=1, pct=True)
        elif method == "minmax":
            mn = factor_values.min(axis=1)
            mx = factor_values.max(axis=1)
            rng = (mx - mn).replace(0, 1)
            return factor_values.sub(mn, axis=0).div(rng, axis=0)
        else:
            raise ValueError(f"不支持的标准化方法: {method}")
