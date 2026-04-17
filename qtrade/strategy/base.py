"""
策略基类

用户继承 Strategy 基类，实现 generate_weights() 方法来构建策略。
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd


class Strategy(ABC):
    """
    策略基类。

    子类须实现:
    - generate_weights(date, data) : 返回目标权重 Series
    - load_data() : 返回 Panel 数据 (可选，也可外部传入)
    """

    name: str = "BaseStrategy"

    @abstractmethod
    def generate_weights(
        self, date: pd.Timestamp, data: dict[str, pd.DataFrame]
    ) -> pd.Series | None:
        """
        在调仓日生成目标持仓权重。

        Parameters
        ----------
        date : 当前调仓日
        data : 截至 date 的 Panel 数据 (历史数据，不含未来)

        Returns
        -------
        pd.Series (index=股票代码, values=权重, 正值买入 / 负值卖出)
        返回 None 表示不调仓
        """
        ...

    def load_data(self) -> dict[str, pd.DataFrame]:
        """加载策略所需数据 (可在子类中覆盖)"""
        raise NotImplementedError("请传入 data 参数或在子类中实现 load_data()")
