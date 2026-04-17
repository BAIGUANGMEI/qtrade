"""
内置因子库

提供常用的量价因子，作为参考和直接使用。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from qtrade.factor.base import Factor, register_factor


# ==============================================================
# 动量类因子
# ==============================================================


@register_factor("momentum_20d")
class Momentum20D(Factor):
    """20 日动量因子 (收益率)"""

    def compute(self, data: dict[str, pd.DataFrame]) -> pd.DataFrame:
        close = data["close"]
        window = self.params.get("window", 20)
        return close / close.shift(window) - 1


@register_factor("momentum_60d")
class Momentum60D(Factor):
    """60 日动量因子"""

    def compute(self, data: dict[str, pd.DataFrame]) -> pd.DataFrame:
        close = data["close"]
        window = self.params.get("window", 60)
        return close / close.shift(window) - 1


@register_factor("momentum_custom")
class MomentumCustom(Factor):
    """自定义窗口动量因子, 使用 window 参数"""

    def compute(self, data: dict[str, pd.DataFrame]) -> pd.DataFrame:
        close = data["close"]
        window = self.params.get("window", 20)
        return close / close.shift(window) - 1


# ==============================================================
# 反转类因子
# ==============================================================


@register_factor("reversal_5d")
class Reversal5D(Factor):
    """5 日反转因子 (短期反转)"""

    def compute(self, data: dict[str, pd.DataFrame]) -> pd.DataFrame:
        close = data["close"]
        return -(close / close.shift(5) - 1)


# ==============================================================
# 波动率类因子
# ==============================================================


@register_factor("volatility_20d")
class Volatility20D(Factor):
    """20 日收益率波动率"""

    def compute(self, data: dict[str, pd.DataFrame]) -> pd.DataFrame:
        close = data["close"]
        returns = close.pct_change()
        window = self.params.get("window", 20)
        return returns.rolling(window).std()


@register_factor("downside_vol_20d")
class DownsideVol20D(Factor):
    """20 日下行波动率"""

    def compute(self, data: dict[str, pd.DataFrame]) -> pd.DataFrame:
        close = data["close"]
        returns = close.pct_change()
        neg_returns = returns.clip(upper=0)
        window = self.params.get("window", 20)
        return neg_returns.rolling(window).std()


# ==============================================================
# 量价类因子
# ==============================================================


@register_factor("volume_ratio_20d")
class VolumeRatio20D(Factor):
    """20 日成交量比率 (当日 / 20日均量)"""

    def compute(self, data: dict[str, pd.DataFrame]) -> pd.DataFrame:
        volume = data["volume"]
        window = self.params.get("window", 20)
        avg_vol = volume.rolling(window).mean()
        return volume / avg_vol.replace(0, np.nan)


@register_factor("price_volume_corr")
class PriceVolumeCorr(Factor):
    """20 日量价相关性"""

    def compute(self, data: dict[str, pd.DataFrame]) -> pd.DataFrame:
        close = data["close"]
        volume = data["volume"]
        returns = close.pct_change()
        window = self.params.get("window", 20)
        return returns.rolling(window).corr(volume)


@register_factor("vwap_bias")
class VWAPBias(Factor):
    """VWAP 偏离度 (收盘价 vs 简易 VWAP)"""

    def compute(self, data: dict[str, pd.DataFrame]) -> pd.DataFrame:
        close = data["close"]
        high = data["high"]
        low = data["low"]
        volume = data["volume"]
        typical_price = (high + low + close) / 3
        window = self.params.get("window", 20)
        vwap = (typical_price * volume).rolling(window).sum() / volume.rolling(window).sum()
        return close / vwap - 1


# ==============================================================
# 均线类因子
# ==============================================================


@register_factor("ma_cross")
class MACross(Factor):
    """均线交叉因子 (短期均线 / 长期均线 - 1)"""

    def compute(self, data: dict[str, pd.DataFrame]) -> pd.DataFrame:
        close = data["close"]
        short_window = self.params.get("short_window", 5)
        long_window = self.params.get("long_window", 20)
        ma_short = close.rolling(short_window).mean()
        ma_long = close.rolling(long_window).mean()
        return ma_short / ma_long - 1


@register_factor("bollinger_position")
class BollingerPosition(Factor):
    """布林带位置 (价格在布林带中的相对位置)"""

    def compute(self, data: dict[str, pd.DataFrame]) -> pd.DataFrame:
        close = data["close"]
        window = self.params.get("window", 20)
        ma = close.rolling(window).mean()
        std = close.rolling(window).std()
        upper = ma + 2 * std
        lower = ma - 2 * std
        band_width = upper - lower
        return (close - lower) / band_width.replace(0, np.nan)


# ==============================================================
# 技术指标类因子
# ==============================================================


@register_factor("rsi")
class RSI(Factor):
    """RSI 相对强弱指标"""

    def compute(self, data: dict[str, pd.DataFrame]) -> pd.DataFrame:
        close = data["close"]
        window = self.params.get("window", 14)
        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = (-delta).clip(lower=0)
        avg_gain = gain.rolling(window).mean()
        avg_loss = loss.rolling(window).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        return 100 - 100 / (1 + rs)


@register_factor("atr_ratio")
class ATRRatio(Factor):
    """ATR 比率 (ATR / 收盘价)"""

    def compute(self, data: dict[str, pd.DataFrame]) -> pd.DataFrame:
        close = data["close"]
        high = data["high"]
        low = data["low"]
        window = self.params.get("window", 14)

        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=0).max(level=0) if False else tr1
        # 正确的 True Range
        tr = pd.DataFrame(
            np.maximum(np.maximum(tr1.values, tr2.values), tr3.values),
            index=close.index,
            columns=close.columns,
        )
        atr = tr.rolling(window).mean()
        return atr / close


# ==============================================================
# 基本面代理因子 (仅基于价格数据)
# ==============================================================


@register_factor("52w_high_pct")
class High52WPct(Factor):
    """距离52周高点的百分比"""

    def compute(self, data: dict[str, pd.DataFrame]) -> pd.DataFrame:
        close = data["close"]
        high_52w = close.rolling(252, min_periods=60).max()
        return close / high_52w - 1


@register_factor("illiquidity")
class Illiquidity(Factor):
    """Amihud 非流动性指标 (|收益| / 成交量)"""

    def compute(self, data: dict[str, pd.DataFrame]) -> pd.DataFrame:
        close = data["close"]
        volume = data["volume"]
        returns = close.pct_change().abs()
        window = self.params.get("window", 20)
        daily_illiq = returns / volume.replace(0, np.nan)
        return daily_illiq.rolling(window).mean()


