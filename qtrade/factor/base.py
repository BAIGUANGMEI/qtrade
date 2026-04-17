"""
因子基类与注册机制

用户通过继承 Factor 并使用 @register_factor 装饰器来创建自定义因子。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import pandas as pd

# ============ 全局因子注册表 ============
_FACTOR_REGISTRY: dict[str, type["Factor"]] = {}


def register_factor(name: str):
    """
    因子注册装饰器。

    Usage:
        @register_factor("my_factor")
        class MyFactor(Factor):
            ...
    """

    def wrapper(cls: type[Factor]):
        if name in _FACTOR_REGISTRY:
            raise ValueError(f"因子 '{name}' 已注册，请使用其他名称")
        cls.factor_name = name
        _FACTOR_REGISTRY[name] = cls
        return cls

    return wrapper


def get_factor(name: str) -> type["Factor"]:
    """根据名称获取因子类"""
    if name not in _FACTOR_REGISTRY:
        raise KeyError(
            f"因子 '{name}' 未注册。已注册因子: {list(_FACTOR_REGISTRY.keys())}"
        )
    return _FACTOR_REGISTRY[name]


def list_factors() -> list[str]:
    """列出所有已注册因子名"""
    return list(_FACTOR_REGISTRY.keys())


class Factor(ABC):
    """
    因子基类。

    子类须实现 compute() 方法，接受 panel 数据，返回因子值 DataFrame。

    Attributes
    ----------
    factor_name : str  注册名 (由装饰器自动设置)
    params : dict      可调参数
    """

    factor_name: str = ""

    def __init__(self, **params: Any):
        self.params = params
        # 将 params 设置为实例属性，方便直接访问
        for k, v in params.items():
            setattr(self, k, v)

    @abstractmethod
    def compute(self, data: dict[str, pd.DataFrame]) -> pd.DataFrame:
        """
        计算因子值。

        Parameters
        ----------
        data : dict[str, DataFrame]
            Panel 数据, 键为 "open"/"close"/"high"/"low"/"volume",
            值为 DataFrame(index=日期, columns=股票代码)

        Returns
        -------
        DataFrame  index=日期, columns=股票代码, values=因子值
        """
        ...

    def __repr__(self) -> str:
        return f"<Factor: {self.factor_name} params={self.params}>"
