"""
SQL schema 定义 (SQLAlchemy Core Table)

设计原则:
- 长表存储 (long-format) 以兼容所有 SQL 方言, 避免宽表在 MySQL/PG 上列数爆炸
- 关键字段建索引加速查询
- 使用 JSON 列存储 metrics / config, 避免 schema 演化困难
- 外键使用 CASCADE 删除保证数据一致性
"""

from __future__ import annotations

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
)

metadata = MetaData()


# ---------------------------------------------------------------
# backtest_runs: 每次回测的元数据
# ---------------------------------------------------------------
backtest_runs = Table(
    "qt_backtest_runs",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("name", String(255), nullable=False, index=True),
    Column("strategy_name", String(255), nullable=False, index=True),
    Column("start_date", DateTime, nullable=True),
    Column("end_date", DateTime, nullable=True),
    Column("initial_capital", Float, nullable=True),
    Column("commission", Float, nullable=True),
    Column("slippage", Float, nullable=True),
    Column("rebalance_freq", String(16), nullable=True),
    Column("created_at", DateTime, nullable=False, index=True),
    Column("config_json", JSON, nullable=True),  # 策略 / 引擎参数
    Column("metrics_json", JSON, nullable=True),  # 全部绩效指标
    Column("notes", Text, nullable=True),
)


# ---------------------------------------------------------------
# equity_points: 每日净值 + 基准
# ---------------------------------------------------------------
equity_points = Table(
    "qt_equity_points",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column(
        "run_id",
        Integer,
        ForeignKey("qt_backtest_runs.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("date", DateTime, nullable=False),
    Column("equity", Float, nullable=False),
    Column("benchmark", Float, nullable=True),
    Index("ix_equity_run_date", "run_id", "date"),
    UniqueConstraint("run_id", "date", name="uq_equity_run_date"),
)


# ---------------------------------------------------------------
# position_snapshots: 每日每股持仓权重 (长表: run × date × symbol)
# ---------------------------------------------------------------
position_snapshots = Table(
    "qt_position_snapshots",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column(
        "run_id",
        Integer,
        ForeignKey("qt_backtest_runs.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("date", DateTime, nullable=False),
    Column("symbol", String(32), nullable=False),
    Column("weight", Float, nullable=False),
    Index("ix_pos_run_date", "run_id", "date"),
    Index("ix_pos_run_symbol", "run_id", "symbol"),
)


# ---------------------------------------------------------------
# trade_signals: 策略输出的调仓信号 (signal + exec 两个时点)
# ---------------------------------------------------------------
trade_signals = Table(
    "qt_trade_signals",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column(
        "run_id",
        Integer,
        ForeignKey("qt_backtest_runs.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("signal_date", DateTime, nullable=False),
    Column("exec_date", DateTime, nullable=True),
    Column("symbol", String(32), nullable=False),
    Column("action", String(16), nullable=True),
    Column("status", String(16), nullable=True),
    Column("old_weight", Float, nullable=True),
    Column("new_weight", Float, nullable=True),
    Column("delta_weight", Float, nullable=True),
    Column("signal_close", Float, nullable=True),
    Column("exec_open", Float, nullable=True),
    Index("ix_sig_run_date", "run_id", "signal_date"),
    Index("ix_sig_run_symbol", "run_id", "symbol"),
)


# ---------------------------------------------------------------
# fills: 真实成交回报 (由 broker.notify_order 记录)
# ---------------------------------------------------------------
fills = Table(
    "qt_fills",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column(
        "run_id",
        Integer,
        ForeignKey("qt_backtest_runs.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("exec_datetime", DateTime, nullable=True),
    Column("symbol", String(32), nullable=False),
    Column("side", String(8), nullable=True),
    Column("size", Float, nullable=True),
    Column("fill_price", Float, nullable=True),
    Column("commission", Float, nullable=True),
    Column("value", Float, nullable=True),
    Column("status", String(16), nullable=True),
    Index("ix_fills_run_date", "run_id", "exec_datetime"),
    Index("ix_fills_run_symbol", "run_id", "symbol"),
)


ALL_TABLES = [
    backtest_runs,
    equity_points,
    position_snapshots,
    trade_signals,
    fills,
]
