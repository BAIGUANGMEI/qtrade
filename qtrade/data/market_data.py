"""
市场数据加载模块

支持从 Yahoo Finance 获取美股日线数据，并缓存到本地 parquet 文件。
返回统一的 Panel 数据结构 (dict of DataFrames)。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd
import yfinance as yf

from qtrade.config import BENCHMARK_SYMBOL, DATA_DIR, DEFAULT_DATA_SOURCE


def load_sp500_symbols(cache_dir: Path | None = None) -> list[str]:
    """
    获取标普500当前成分股列表 (从 Wikipedia 抓取, 本地缓存)。

    Returns
    -------
    list[str]  约 500 个股票代码
    """
    import io
    import requests

    cache_dir = cache_dir or DATA_DIR
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / "sp500_symbols.parquet"

    if cache_file.exists():
        df = pd.read_parquet(cache_file)
        return df["symbol"].tolist()

    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    resp = requests.get(url, headers={"User-Agent": "qtrade/0.1"}, timeout=15)
    resp.raise_for_status()
    tables = pd.read_html(io.StringIO(resp.text))
    df = tables[0][["Symbol"]].copy()
    df.columns = ["symbol"]
    # 处理特殊字符 (BRK.B → BRK-B)
    df["symbol"] = df["symbol"].str.replace(".", "-", regex=False)
    df.to_parquet(cache_file, index=False)
    return df["symbol"].tolist()


class MarketData:
    """美股行情数据加载器"""

    def __init__(self, cache_dir: Path | None = None, source: str = DEFAULT_DATA_SOURCE):
        self.cache_dir = cache_dir or DATA_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.source = source

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    def load(
        self,
        symbols: list[str],
        start: str,
        end: str,
        fields: list[str] | None = None,
        use_cache: bool = True,
    ) -> dict[str, pd.DataFrame]:
        """
        加载行情数据。

        Parameters
        ----------
        symbols : 股票代码列表, e.g. ["AAPL", "MSFT"]
        start, end : 起止日期 "YYYY-MM-DD"
        fields : 需要的字段, 默认全部 (open/high/low/close/volume)
        use_cache : 是否使用本地缓存

        Returns
        -------
        dict[str, DataFrame]  键为字段名 ("open", "close", …),
        值为 DataFrame (index=日期, columns=symbols)
        """
        fields = fields or ["open", "high", "low", "close", "volume"]
        raw = self._fetch(symbols, start, end, use_cache)
        return self._to_panel(raw, fields)

    def load_benchmark(
        self,
        start: str,
        end: str,
        symbol: str = BENCHMARK_SYMBOL,
        use_cache: bool = True,
    ) -> pd.Series:
        """
        加载基准指数收盘价序列 (默认 SPY = 标普500)。

        Returns
        -------
        pd.Series (index=日期, name=symbol)
        """
        panel = self.load([symbol], start, end, fields=["close"], use_cache=use_cache)
        series = panel["close"].iloc[:, 0]
        series.name = symbol
        return series

    def load_returns(
        self,
        symbols: list[str],
        start: str,
        end: str,
        period: int = 1,
    ) -> pd.DataFrame:
        """返回 period 日前瞻收益率 DataFrame (index=date, columns=symbols)"""
        panel = self.load(symbols, start, end, fields=["close"])
        close = panel["close"]
        fwd_ret = close.shift(-period) / close - 1
        return fwd_ret

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _cache_path(self, symbols: list[str], start: str, end: str) -> Path:
        key = hashlib.md5(
            f"{sorted(symbols)}_{start}_{end}".encode()
        ).hexdigest()[:12]
        return self.cache_dir / f"market_{key}.parquet"

    def _fetch(
        self,
        symbols: list[str],
        start: str,
        end: str,
        use_cache: bool,
    ) -> pd.DataFrame:
        cache_file = self._cache_path(symbols, start, end)

        if use_cache and cache_file.exists():
            return pd.read_parquet(cache_file)

        df = yf.download(
            tickers=symbols,
            start=start,
            end=end,
            auto_adjust=True,
            progress=False,
        )
        if isinstance(df.columns, pd.MultiIndex):
            # yfinance 多标的返回 MultiIndex columns
            df.columns = df.columns.set_names(["field", "symbol"])
        else:
            # 单标的
            df.columns = pd.MultiIndex.from_product(
                [df.columns, symbols], names=["field", "symbol"]
            )

        df.to_parquet(cache_file)
        return df

    @staticmethod
    def _to_panel(
        raw: pd.DataFrame, fields: list[str]
    ) -> dict[str, pd.DataFrame]:
        """将 MultiIndex DataFrame 转为 {field: DataFrame} 字典"""
        result: dict[str, pd.DataFrame] = {}
        raw.columns = raw.columns.set_names(["field", "symbol"])

        available = raw.columns.get_level_values("field").unique()
        # 统一为小写匹配
        field_map = {f.lower(): f for f in available}

        for f in fields:
            key = field_map.get(f.lower())
            if key is None:
                continue
            sub = raw.xs(key, level="field", axis=1).copy()
            sub.index = pd.to_datetime(sub.index)
            sub.sort_index(inplace=True)
            result[f.lower()] = sub

        return result
