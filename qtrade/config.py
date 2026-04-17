"""全局配置"""

from datetime import date, timedelta
from pathlib import Path

# ============ 路径配置 ============
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data_cache"
DATA_DIR.mkdir(exist_ok=True)

# ============ 数据配置 ============
# Yahoo Finance 为默认免费数据源
DEFAULT_DATA_SOURCE = "yahoo"

# ============ 基准配置 ============
BENCHMARK_SYMBOL = "SPY"  # 标普500 ETF 作为基准

# ============ 回测默认配置 ============
DEFAULT_INITIAL_CAPITAL = 1_000_000.0
DEFAULT_COMMISSION_RATE = 0.001  # 0.1% 单边手续费
DEFAULT_SLIPPAGE = 0.001  # 0.1% 滑点
RISK_FREE_RATE = 0.04  # 无风险利率 (年化)
TRADING_DAYS_PER_YEAR = 252
DEFAULT_BACKTEST_MONTHS = 12  # 默认回测区间: 最近 12 个月
DEFAULT_WARMUP_MONTHS = 6   # 默认因子热身期: 10 个月

# ============ 因子分析配置 ============
DEFAULT_QUANTILE_GROUPS = 5  # 默认分组数
DEFAULT_FORWARD_PERIODS = [1, 5, 10, 20]  # 默认前瞻期(交易日)

# ============ 持久化配置 ============
# 支持任意 SQLAlchemy URL:
#   sqlite:///{path}
#   mysql+pymysql://user:pwd@host:3306/db
#   postgresql+psycopg2://user:pwd@host:5432/db
# 可通过环境变量 QTRADE_DB_URL 覆盖。
DEFAULT_DB_URL = f"sqlite:///{(DATA_DIR / 'backtests.db').as_posix()}"


# ============ 智能日期工具 ============

def smart_dates(
    backtest_months: int = DEFAULT_BACKTEST_MONTHS,
    warmup_months: int = DEFAULT_WARMUP_MONTHS,
    end_date: str | None = None,
) -> dict[str, str]:
    """
    自动推算数据加载起点、回测起点、回测终点。

    Parameters
    ----------
    backtest_months : 回测区间长度 (月)
    warmup_months : 因子 / IC 热身期长度 (月)
    end_date : 回测终点, 默认今天

    Returns
    -------
    dict  {"data_start": ..., "backtest_start": ..., "backtest_end": ...}
    """
    if end_date is None:
        end_dt = date.today()
    else:
        end_dt = date.fromisoformat(end_date)

    bt_start_dt = _subtract_months(end_dt, backtest_months)
    data_start_dt = _subtract_months(bt_start_dt, warmup_months)

    return {
        "data_start": data_start_dt.isoformat(),
        "backtest_start": bt_start_dt.isoformat(),
        "backtest_end": end_dt.isoformat(),
    }


def _subtract_months(d: date, months: int) -> date:
    """日期减去若干月 (自动处理月末溢出)"""
    year = d.year
    month = d.month - months
    while month <= 0:
        month += 12
        year -= 1
    # 防止日期溢出 (如 3-31 减 1 月 → 2-28)
    import calendar
    max_day = calendar.monthrange(year, month)[1]
    day = min(d.day, max_day)
    return date(year, month, day)
