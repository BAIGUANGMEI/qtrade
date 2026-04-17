"""
策略基类与注册机制

用户继承 Strategy 基类，实现 generate_weights() 方法，
并使用 @register_strategy 装饰器注册策略。
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd

# ============ 全局策略注册表 ============
_STRATEGY_REGISTRY: dict[str, type["Strategy"]] = {}


def register_strategy(name: str, *, display_name: str | None = None):
    """
    策略注册装饰器。

    Usage:
        @register_strategy("TopNStrategy", display_name="TopN 等权选股")
        class TopNStrategy(Strategy):
            ...
    """

    def wrapper(cls: type[Strategy]):
        if name in _STRATEGY_REGISTRY:
            raise ValueError(f"策略 '{name}' 已注册，请使用其他名称")
        cls.name = name
        if display_name is not None:
            cls.display_name = display_name
        _STRATEGY_REGISTRY[name] = cls
        return cls

    return wrapper


def get_strategy(name: str) -> type["Strategy"]:
    """根据名称获取策略类"""
    if name not in _STRATEGY_REGISTRY:
        raise KeyError(
            f"策略 '{name}' 未注册。已注册策略: {list(_STRATEGY_REGISTRY.keys())}"
        )
    return _STRATEGY_REGISTRY[name]


def list_strategies() -> list[str]:
    """列出所有已注册策略名"""
    return list(_STRATEGY_REGISTRY.keys())


class Strategy(ABC):
    """
    策略基类。

    子类须实现:
    - generate_weights(date, data) : 返回目标权重 Series
    - load_data() : 返回 Panel 数据 (可选，也可外部传入)

    类属性:
    - name : 策略注册名 (由装饰器自动设置)
    - display_name : 策略显示名 (可选，默认同 name)
    - default_factor_names : 策略使用的因子列表 (用于面板展示)
    """

    name: str = "BaseStrategy"
    display_name: str = ""
    default_factor_names: list[str] = []

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
