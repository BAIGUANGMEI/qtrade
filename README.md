# QTrade - 个人美股因子量化系统

基于 Python 的美股多因子量化研究框架，集成因子计算、IC/RankIC 分析、因子相关性分析和基于 [backtrader](https://github.com/mementum/backtrader) 的回测引擎。支持 S&P 500 全成分股。

## 系统架构

```
qtrade/
├── config.py             # 全局配置 (资金、费率、基准等)
├── run_example.py        # 运行入口示例
├── data/
│   └── market_data.py    # Yahoo Finance 行情获取 + Parquet 本地缓存
├── factor/
│   ├── base.py           # 因子基类 Factor + @register_factor 注册器
│   └── engine.py         # FactorEngine: 批量计算、横截面中性化
├── analysis/
│   ├── ic_analysis.py    # ICAnalyzer: Pearson IC / Spearman Rank IC
│   ├── correlation.py    # CorrelationAnalyzer: 多因子相关性矩阵
│   └── group_analysis.py # GroupAnalyzer: 分位数分组回测
├── strategy/
│   └── base.py           # Strategy ABC (generate_weights 接口)
├── backtest/
│   ├── engine.py         # BacktestEngine (backtrader 驱动)
│   └── performance.py    # 绩效指标计算 (夏普、最大回撤等)
├── examples/
│   ├── custom_factors.py # 内置 20 个因子
│   └── custom_strategies.py # 内置 4 个策略模板
└── utils/
    ├── display.py        # Rich 终端格式化输出
    └── plotting.py       # Matplotlib 可视化
```

## 快速开始

### 1. 安装

```bash
# 推荐使用 uv
uv sync

# 或 pip
pip install -r requirements.txt
```

### 2. 一键运行示例

```bash
uv run python -m qtrade.run_example
```

该示例会自动执行完整流程：加载 S&P 500 成分股 → 计算日内动量因子 → IC 分析 → 因子相关性 → 策略回测 → 输出绩效报告。

### 3. 编写自定义因子

```python
from qtrade.factor.base import Factor, register_factor
import pandas as pd

@register_factor("my_momentum")
class MyMomentum(Factor):
    """自定义动量因子"""
    window = 20

    def compute(self, data: dict[str, pd.DataFrame]) -> pd.DataFrame:
        close = data["close"]
        return close / close.shift(self.window) - 1
```

### 4. 因子分析

```python
from qtrade.data.market_data import MarketData
from qtrade.factor.engine import FactorEngine
from qtrade.analysis.ic_analysis import ICAnalyzer

md = MarketData()
data = md.load(symbols=["AAPL", "MSFT", "GOOGL"], start="2020-01-01", end="2024-12-31")

engine = FactorEngine()
factor_values = engine.compute_factor("momentum_20d", data)

analyzer = ICAnalyzer(factor_values, data["close"])
analyzer.ic_summary()       # Pearson IC
analyzer.rank_ic_summary()  # Spearman Rank IC
```

### 5. 策略回测

```python
from qtrade.backtest.engine import BacktestEngine
from qtrade.examples.custom_strategies import TopNStrategy

engine = BacktestEngine(
    initial_capital=1_000_000,
    start_date="2020-01-01",
    end_date="2024-12-31",
    rebalance_freq="M",   # D/W/M/Q
    commission=0.001,
    slippage=0.001,
)
result = engine.run(TopNStrategy(factor_name="momentum_20d", top_n=10))
result.report()
```

回测引擎基于 backtrader，支持真实逐笔撮合、下一根 bar 开盘成交、现金管理、手续费和滑点。

## 内置因子 (20 个)

| 类别 | 因子名 | 说明 |
|---|---|---|
| 动量 | `momentum_20d` | 20 日价格动量 |
| 动量 | `momentum_60d` | 60 日价格动量 |
| 动量 | `momentum_custom` | 自定义窗口动量 |
| 反转 | `reversal_5d` | 5 日短期反转 |
| 波动率 | `volatility_20d` | 20 日波动率 |
| 波动率 | `downside_vol_20d` | 20 日下行波动率 |
| 量价 | `volume_ratio_20d` | 20 日成交量比率 |
| 量价 | `price_volume_corr` | 价量相关性 |
| 量价 | `vwap_bias` | VWAP 偏离度 |
| 均线 | `ma_cross` | 均线交叉信号 |
| 均线 | `bollinger_position` | 布林带位置 |
| 技术 | `rsi` | RSI 相对强弱 |
| 技术 | `atr_ratio` | ATR 比率 |
| 基本面代理 | `52w_high_pct` | 52 周新高距离 |
| 基本面代理 | `illiquidity` | Amihud 非流动性 |
| 日内动量 | `intraday_momentum_5d` | 5 日日内动量 (Close-Open)/Open |
| 日内动量 | `intraday_momentum_weighted_5d` | 5 日线性加权日内动量 |
| 日内动量 | `intraday_momentum_vol_adj` | 日内动量波动率调整 (日内夏普) |
| 日内动量 | `overnight_gap` | 隔夜跳空 |
| 日内动量 | `intraday_consistency` | 日内一致性 (阳线胜率) |

## 内置策略

| 策略 | 说明 |
|---|---|
| `TopNStrategy` | 单因子选股 Top-N 等权做多 |
| `LongShortStrategy` | 多空策略：做多 Top-N，做空 Bottom-N |
| `MultiFactorStrategy` | 多因子复合排名选股 |
| `IntradayMomentumStrategy` | 日内动量复合策略 (vol_adj + consistency + gap boost) |

## 因子分析指标

| 指标 | 说明 |
|---|---|
| IC | 因子值与未来收益的 Pearson 相关系数 |
| Rank IC | 因子排名与收益排名的 Spearman 相关系数 |
| IC IR | IC 均值 / IC 标准差，衡量预测稳定性 |
| IC 衰减 | 不同持有期 (1/5/10/20 日) 下的 IC 变化 |
| 因子相关性 | 因子间横截面 Spearman 相关矩阵 |
| 分组回测 | 按因子值分 N 组，比较各组收益 |

## 回测绩效指标

| 指标 | 说明 |
|---|---|
| 年化收益率 | 组合年化复合收益率 |
| 年化波动率 | 收益率年化标准差 |
| 夏普比率 | (年化收益 − 无风险利率) / 年化波动 |
| 索提诺比率 | (年化收益 − 无风险利率) / 下行波动 |
| 最大回撤 | 峰值到谷值的最大损失比例 |
| 卡尔马比率 | 年化收益 / 最大回撤 |
| 胜率 | 盈利交易日占比 |
| 盈亏比 | 平均盈利 / 平均亏损 |
| 信息比率 | 超额收益 / 跟踪误差 |
| 基准收益 | SPY 同期收益率 |
| 超额收益 | 组合收益 − 基准收益 |

## 数据

- **数据源**: Yahoo Finance (via `yfinance`)
- **缓存**: 本地 Parquet 文件 (`data_cache/`)，避免重复下载
- **股票池**: `load_sp500_symbols()` 从 Wikipedia 获取 S&P 500 最新成分股
- **基准**: SPY (可在 `config.py` 中修改 `BENCHMARK_SYMBOL`)

## 默认参数

| 参数 | 默认值 |
|---|---|
| 初始资金 | $1,000,000 |
| 手续费率 | 0.1% (单边) |
| 滑点 | 0.1% |
| 无风险利率 | 4% |
| 年交易日 | 252 |
| 基准 | SPY |
