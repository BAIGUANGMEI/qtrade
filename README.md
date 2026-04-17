# QTrade - 个人美股因子量化系统

基于 Python 的美股因子研究与回测框架，包含因子计算、IC / Rank IC 分析、分组回测、基于 backtrader 的实盘风格撮合，以及专业级 Web 分析面板。默认支持 S&P 500 全成分股，数据来自 Yahoo Finance，并在本地以 Parquet 缓存。

## 当前能力

- 单因子 TopN 选股回测
- 多空对冲策略
- 多因子复合排名策略
- IC / Rank IC / IC 衰减分析
- 分组收益与多空组合分析
- 买卖点位展示、交易 CSV 导出、持仓历史 CSV 导出
- Dash + Plotly 交互式前端分析面板（策略/因子自动发现）
- 因子注册机制：`@register_factor` 自动接入系统
- 策略注册机制：`@register_strategy` 自动接入面板
- 智能日期识别：默认自动使用最近 12 个月回测和 10 个月预热

## 项目结构

```text
qtrade/
├── config.py                  # 全局配置、smart_dates() 智能日期工具
├── run_example.py             # 默认入口：TopN 动量策略
├── run_dashboard.py           # Web 分析面板入口
├── analysis/
│   ├── correlation.py         # 因子相关性分析
│   ├── group_analysis.py      # 分组回测分析
│   └── ic_analysis.py         # IC / Rank IC / IC 衰减
├── backtest/
│   ├── engine.py              # BacktestEngine / BacktestResult
│   └── performance.py         # 绩效指标计算
├── dashboard/
│   ├── app.py                 # Dash 应用主入口
│   ├── data_provider.py       # 回测与分析数据装配层
│   └── pages/
│       ├── factor.py          # 因子分析页
│       ├── overview.py        # 总览页
│       ├── positions.py       # 持仓分析页
│       └── trades.py          # 交易记录页
├── data/
│   └── market_data.py         # Yahoo Finance 行情加载 + 本地缓存
├── examples/
│   ├── custom_factors.py      # 内置因子集合
│   └── custom_strategies.py   # TopN / LongShort / MultiFactor 示例策略
├── factor/
│   ├── base.py                # Factor 基类与注册器
│   └── engine.py              # FactorEngine
├── strategy/
│   └── base.py                # Strategy 基类与注册器
└── utils/
    ├── display.py             # Rich 终端展示
    └── plotting.py            # Matplotlib 图表
```

## 安装

推荐使用 uv：

```bash
uv sync
```

如果使用现有虚拟环境，也可以：

```bash
pip install -r requirements.txt
```

主要依赖包括：

- pandas / numpy / scipy
- yfinance / pyarrow / lxml
- rich / matplotlib
- backtrader
- dash / dash-bootstrap-components / plotly

## 快速开始

### 1. 运行默认策略

```bash
uv run python -m qtrade.run_example
```

默认流程：

1. 自动获取 S&P 500 成分股
2. 通过 `smart_dates()` 自动推导数据起点、回测起点、回测终点
3. 加载行情与 SPY 基准
4. 计算 `momentum_20d` 因子
5. 运行 `TopNStrategy` 周频调仓回测
6. 输出绩效报告

### 2. 启动专业分析面板

```bash
uv run python -m qtrade.run_dashboard
```

启动后访问：

```text
http://127.0.0.1:8050
```

前端面板包含 4 个核心页面：

- 总览：收益、回撤、滚动指标、月度热力图
- 因子分析：IC 汇总、IC 时序、IC 衰减、分组收益、多空组合
- 交易记录：买卖点、交易频率、交易明细
- 持仓分析：最终持仓、集中度、换手率、权重演化

## 智能日期逻辑

系统默认不需要手动填写日期。`smart_dates()` 会自动生成：

- `backtest_end`: 今天
- `backtest_start`: 今天往前 12 个月
- `data_start`: 再往前 10 个月作为预热期

默认返回：

```python
{
    "data_start": "YYYY-MM-DD",
    "backtest_start": "YYYY-MM-DD",
    "backtest_end": "YYYY-MM-DD",
}
```

这套逻辑已经用于：

- `qtrade.run_example`
- `examples/custom_strategies.py` 中的默认策略实例

## 回测结果说明

`BacktestEngine.run()` 返回 `BacktestResult`，核心字段包括：

- `equity_curve`: 组合净值曲线
- `daily_returns`: 日收益率
- `positions`: 每日持仓权重历史
- `trades`: 交易记录
- `metrics`: 绩效指标
- `benchmark_curve`: 基准净值曲线

其中交易记录当前包含以下字段：

- `date`: 信号日期
- `exec_date`: 实际成交日期
- `symbol`: 股票代码
- `action`: 买入 / 卖出 / 加仓 / 减仓
- `status`: 已成交 / 未成交
- `old_weight`: 原权重
- `new_weight`: 新权重
- `delta_weight`: 权重变化
- `signal_close`: 信号日收盘价
- `exec_open`: 次日开盘成交价

## 导出文件

```python
result.export_positions_csv("outputs/positions.csv")
result.export_trades_csv("outputs/trades.csv")
```

## 当前内置策略

| 策略 | 说明 |
|---|---|
| `TopNStrategy` | 单因子 TopN 等权买入 |
| `LongShortStrategy` | 多空对冲 |
| `MultiFactorStrategy` | 多因子加权排名 |

## 当前内置因子

内置因子位于 `examples/custom_factors.py`。

| 因子名 | 说明 |
|---|---|
| `momentum_20d` | 20 日动量 |
| `momentum_60d` | 60 日动量 |
| `momentum_custom` | 自定义窗口动量 |
| `reversal_5d` | 5 日反转 |
| `volatility_20d` | 20 日波动率 |
| `downside_vol_20d` | 20 日下行波动率 |
| `volume_ratio_20d` | 量比 |
| `price_volume_corr` | 量价相关性 |
| `vwap_bias` | VWAP 偏离度 |
| `ma_cross` | 均线交叉 |
| `bollinger_position` | 布林带位置 |
| `rsi` | RSI |
| `atr_ratio` | ATR 比率 |
| `52w_high_pct` | 52 周高点距离 |
| `illiquidity` | 非流动性 |

## 开发指南：自定义因子

### 因子注册机制

系统通过 `@register_factor` 装饰器实现因子的自动发现。注册后的因子可被 `FactorEngine`、IC 分析、分组分析、Web 面板等所有模块直接使用。

核心 API：

```python
from qtrade.factor.base import register_factor, get_factor, list_factors

list_factors()          # → ["momentum_20d", "reversal_5d", ...]
get_factor("rsi")       # → RSI 因子类
```

### 最小因子模板

```python
from __future__ import annotations

import pandas as pd

from qtrade.factor.base import Factor, register_factor


@register_factor("my_momentum")
class MyMomentum(Factor):
    """20 日动量因子"""

    def compute(self, data: dict[str, pd.DataFrame]) -> pd.DataFrame:
        close = data["close"]
        return close / close.shift(20) - 1
```

`compute()` 的输入是一个字典，包含 `"open"` / `"close"` / `"high"` / `"low"` / `"volume"` 五个 DataFrame（index 为日期，columns 为股票代码）。返回值是一个同形状的 DataFrame，每个格子是该股票在该日期的因子值。

### 带参数的因子

```python
@register_factor("momentum_custom")
class MomentumCustom(Factor):
    def compute(self, data: dict[str, pd.DataFrame]) -> pd.DataFrame:
        window = self.params.get("window", 20)
        close = data["close"]
        return close / close.shift(window) - 1
```

使用时传参：

```python
engine = FactorEngine()
fv = engine.compute_factor("momentum_custom", data, window=60)
```

### 因子计算与分析

```python
from qtrade.factor.engine import FactorEngine
from qtrade.analysis.ic_analysis import ICAnalyzer
from qtrade.analysis.group_analysis import GroupAnalyzer

engine = FactorEngine()
fv = engine.compute_factor("my_momentum", data)

# IC 分析
ic = ICAnalyzer(fv, data["close"])
ic.ic_summary()                              # Pearson IC 汇总
ic.rank_ic_summary()                         # Rank IC 汇总
ic.ic_decay(max_period=20, method="spearman") # IC 衰减
ic.ic_series(period=1, method="spearman")    # 逐日 IC 序列

# 分组分析
ga = GroupAnalyzer(fv, data["close"])
ga.group_summary()                # 各组统计
ga.cumulative_group_returns()     # 各组累计收益
ga.cumulative_long_short()        # 多空组合累计收益
```

### 让新因子被面板发现

只需确保因子模块在面板启动时被 import。在 `qtrade/dashboard/app.py` 顶部添加：

```python
import my_package.my_factors  # noqa: F401
```

面板的因子展示区会自动读取策略类上的 `default_factor_names`，无需手动维护映射表。

---

## 开发指南：自定义策略

### 策略注册机制

系统通过 `@register_strategy` 装饰器实现策略的自动发现。注册后的策略可在 Web 面板下拉菜单中直接选择运行。

核心 API：

```python
from qtrade.strategy.base import register_strategy, get_strategy, list_strategies

list_strategies()               # → ["TopNStrategy", "LongShortStrategy", ...]
get_strategy("TopNStrategy")    # → TopNStrategy 类
```

### 策略基类接口

| 成员 | 类型 | 说明 |
|---|---|---|
| `name` | `str` | 策略注册名（由装饰器自动设置） |
| `display_name` | `str` | 面板显示名 |
| `default_factor_names` | `list[str]` | 使用的因子列表（面板展示用） |
| `generate_weights(date, data)` | 抽象方法 | 返回目标权重 `pd.Series`，或 `None` 表示不调仓 |
| `load_data()` | 可选方法 | 未外部传 data 时由引擎调用 |

### 最小策略模板

```python
from __future__ import annotations

import pandas as pd

from qtrade.strategy.base import Strategy, register_strategy
from qtrade.factor.engine import FactorEngine
from qtrade.data.market_data import MarketData
from qtrade.config import smart_dates

import qtrade.examples.custom_factors  # noqa: F401  确保因子已注册


@register_strategy("MyStrategy", display_name="我的策略")
class MyStrategy(Strategy):
    """基于 20 日动量的简单选股策略"""

    default_factor_names = ["momentum_20d"]

    def __init__(
        self,
        factor_name: str = "momentum_20d",
        top_n: int = 10,
        symbols: list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ):
        self.factor_name = factor_name
        self.top_n = top_n
        self.symbols = symbols or ["AAPL", "MSFT", "GOOGL", "AMZN", "META"]
        _dates = smart_dates()
        self.start_date = start_date or _dates["data_start"]
        self.end_date = end_date or _dates["backtest_end"]

        self._engine = FactorEngine()
        self._data = None
        self._factor_values = None

    def load_data(self) -> dict[str, pd.DataFrame]:
        if self._data is None:
            md = MarketData()
            self._data = md.load(self.symbols, self.start_date, self.end_date)
        return self._data

    def generate_weights(
        self, date: pd.Timestamp, data: dict[str, pd.DataFrame]
    ) -> pd.Series | None:
        # 延迟计算因子
        if self._factor_values is None:
            self._factor_values = self._engine.compute_factor(
                self.factor_name, data
            )

        if date not in self._factor_values.index:
            return None

        row = self._factor_values.loc[date].dropna()
        if len(row) < self.top_n:
            return None

        selected = row.nlargest(self.top_n)
        return pd.Series(1.0 / self.top_n, index=selected.index)
```

### `generate_weights()` 约定

| 规则 | 说明 |
|---|---|
| 返回值 index | 股票代码 |
| 返回值 values | 目标权重（正数做多，负数做空） |
| 返回 `None` | 本次不调仓，维持现有持仓 |
| 未出现的股票 | 视为目标权重 0，会被自动清仓 |
| 归一化 | 引擎会自动按绝对值和归一化权重 |

### 回测引擎交互流程

```text
BacktestEngine.run(strategy)
  ├─ 加载数据 (strategy.load_data() 或外部传入)
  ├─ 生成调仓日 (根据 rebalance_freq: D/W/M/Q)
  └─ 逐日运行 backtrader
       ├─ 每日记录净值和持仓
       ├─ 调仓日调用 strategy.generate_weights(date, data)
       ├─ 引擎归一化权重
       ├─ 先卖后买 (order_target_percent)
       └─ 下一根 bar 开盘价成交
```

关键行为：
- **次日开盘成交**：信号在当天收盘后产出，次日开盘执行
- **先卖后买**：避免资金不足
- **因子延迟计算**：建议在首次调用时缓存因子结果，避免每次调仓重复计算

### 让新策略被面板发现

1. 在策略模块中使用 `@register_strategy` 装饰器
2. 设置 `display_name` 和 `default_factor_names` 类属性
3. 在 `qtrade/dashboard/app.py` 顶部 import 该模块触发注册：

```python
try:
    import my_package.my_strategy  # noqa: F401
except Exception:
    pass
```

面板会自动从注册表读取策略列表和对应因子，无需修改任何面板代码。

### 单独运行策略

```python
from qtrade.backtest.engine import BacktestEngine
from qtrade.config import smart_dates
from qtrade.data.market_data import MarketData, load_sp500_symbols

dates = smart_dates()
symbols = load_sp500_symbols()
md = MarketData()
data = md.load(symbols, dates["data_start"], dates["backtest_end"])
benchmark = md.load_benchmark(dates["data_start"], dates["backtest_end"])

strategy = MyStrategy(
    symbols=symbols,
    start_date=dates["data_start"],
    end_date=dates["backtest_end"],
)

engine = BacktestEngine(
    initial_capital=1_000_000,
    start_date=dates["backtest_start"],
    end_date=dates["backtest_end"],
    rebalance_freq="W",
)
result = engine.run(strategy, benchmark=benchmark)
result.report()
```

## 绩效指标

当前 `full_metrics()` 默认输出：

| 指标 | 含义 |
|---|---|
| `total_return` | 总收益率 |
| `annual_return` | 年化收益率 |
| `annual_volatility` | 年化波动率 |
| `sharpe_ratio` | 夏普比率 |
| `sortino_ratio` | 索提诺比率 |
| `max_drawdown` | 最大回撤 |
| `max_drawdown_duration_days` | 最大回撤持续天数 |
| `calmar_ratio` | 卡尔马比率 |
| `win_rate` | 日频胜率 |
| `profit_loss_ratio` | 盈亏比 |
| `information_ratio` | 信息比率（有基准时） |
| `benchmark_return` | 基准收益率 |
| `excess_return` | 超额收益率 |

## 数据说明

- 数据源：Yahoo Finance
- 本地缓存目录：`data_cache/`
- 基准：`SPY`
- 股票池：默认从 Wikipedia 拉取最新 S&P 500 成分股

首次运行会下载较多数据，后续会优先使用本地缓存。

## 注意事项

- `run_dashboard` 需要联网获取行情或使用已有缓存
- Web 面板首次点击“运行回测”时，耗时取决于 S&P 500 数据下载速度
- 交易记录中的 `未成交` 通常表示回测最后一个信号日之后没有下一个交易日可成交
- 自定义策略文件当前已在 `.gitignore` 中排除，不会被 Git 自动跟踪
