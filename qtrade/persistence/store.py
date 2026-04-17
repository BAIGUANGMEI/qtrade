"""
BacktestStore — 跨数据库 (SQLite / MySQL / PostgreSQL) 回测结果持久化。

使用 SQLAlchemy 2.x Core, 依赖项延迟导入, 不安装 SQLAlchemy 时 qtrade
其他模块不受影响。

典型用法
--------
>>> from qtrade.persistence import BacktestStore
>>> store = BacktestStore("sqlite:///./data_cache/backtests.db")
>>> store.init_schema()
>>> run_id = store.save(result, name="MyStrategy-v1", strategy_name="TopN")
>>> result2 = store.load(run_id)
>>> runs_df = store.list_runs()
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import TYPE_CHECKING, Any

import pandas as pd

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.engine import Engine

    from qtrade.backtest.engine import BacktestResult


# --------------------------------------------------------------------
# 延迟导入 SQLAlchemy: 保证 sqlalchemy 未安装时 qtrade 其余模块可用
# --------------------------------------------------------------------
def _require_sqlalchemy():
    try:
        import sqlalchemy  # noqa: F401
    except ImportError as e:
        raise ImportError(
            "持久化功能需要 SQLAlchemy, 请先安装:\n"
            "  pip install sqlalchemy\n"
            "  # MySQL 额外安装: pip install pymysql\n"
            "  # PostgreSQL 额外安装: pip install psycopg2-binary"
        ) from e


def _to_naive_dt(x) -> datetime | None:
    """统一为 naive datetime (多数 DB 不便处理时区)。"""
    if x is None or pd.isna(x):
        return None
    ts = pd.Timestamp(x)
    if ts.tzinfo is not None:
        ts = ts.tz_convert("UTC").tz_localize(None)
    return ts.to_pydatetime()


def _json_safe(obj: Any) -> Any:
    """递归处理 numpy / pandas 类型, 让其可 JSON 序列化。"""
    import math

    import numpy as np

    if obj is None:
        return None
    if isinstance(obj, (np.floating, float)):
        val = float(obj)
        if math.isnan(val) or math.isinf(val):
            return None
        return val
    if isinstance(obj, (np.integer, int, bool)):
        return int(obj) if not isinstance(obj, bool) else bool(obj)
    if isinstance(obj, (pd.Timestamp, datetime)):
        return pd.Timestamp(obj).isoformat()
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    return obj


# ====================================================================
# BacktestStore
# ====================================================================


class BacktestStore:
    """回测结果的数据库持久化接口。

    参数
    ----
    url : SQLAlchemy URL, 例如:
        - ``sqlite:///./data_cache/backtests.db``
        - ``mysql+pymysql://user:pwd@host:3306/qtrade``
        - ``postgresql+psycopg2://user:pwd@host:5432/qtrade``
    echo : 是否打印 SQL (调试用)
    """

    def __init__(self, url: str, echo: bool = False):
        _require_sqlalchemy()
        from sqlalchemy import create_engine

        self.url = url
        self._engine: "Engine" = create_engine(url, echo=echo, future=True)

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------
    def init_schema(self) -> None:
        """创建所有表 (幂等, 不存在才创建)。"""
        from qtrade.persistence.models import metadata

        metadata.create_all(self._engine)

    def drop_schema(self) -> None:
        """删除所有表 (危险操作)。"""
        from qtrade.persistence.models import metadata

        metadata.drop_all(self._engine)

    @property
    def engine(self) -> "Engine":
        return self._engine

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------
    def save(
        self,
        result: "BacktestResult",
        name: str,
        strategy_name: str = "",
        config: dict | None = None,
        notes: str | None = None,
    ) -> int:
        """保存一次回测, 返回自增 run_id。"""
        from sqlalchemy import insert

        from qtrade.persistence.models import (
            backtest_runs,
            equity_points,
            fills,
            position_snapshots,
            trade_signals,
        )

        self.init_schema()

        metrics = result.metrics or {}
        cfg = config or {}
        equity = result.equity_curve
        bench = result.benchmark_curve

        start_date = _to_naive_dt(equity.index[0]) if len(equity) else None
        end_date = _to_naive_dt(equity.index[-1]) if len(equity) else None

        with self._engine.begin() as conn:
            # --- 1) 写入 run metadata, 取回自增 id ---
            run_row = {
                "name": str(name),
                "strategy_name": str(strategy_name or cfg.get("strategy_name", "")),
                "start_date": start_date,
                "end_date": end_date,
                "initial_capital": _opt_float(cfg.get("initial_capital")),
                "commission": _opt_float(cfg.get("commission")),
                "slippage": _opt_float(cfg.get("slippage")),
                "rebalance_freq": str(cfg.get("rebalance_freq", "") or "") or None,
                "created_at": datetime.utcnow(),
                "config_json": _json_safe(cfg),
                "metrics_json": _json_safe(metrics),
                "notes": notes,
            }
            res = conn.execute(insert(backtest_runs).values(**run_row))
            run_id = int(res.inserted_primary_key[0])

            # --- 2) equity_points ---
            if equity is not None and len(equity):
                eq_df = pd.DataFrame(
                    {
                        "run_id": run_id,
                        "date": [_to_naive_dt(d) for d in equity.index],
                        "equity": equity.to_numpy(dtype=float),
                    }
                )
                if bench is not None and len(bench):
                    bench_aligned = bench.reindex(equity.index)
                    eq_df["benchmark"] = bench_aligned.to_numpy(dtype=float)
                else:
                    eq_df["benchmark"] = None
                _bulk_insert(conn, equity_points, eq_df)

            # --- 3) position_snapshots (宽表 -> 长表) ---
            if result.positions is not None and not result.positions.empty:
                pos = result.positions.copy()
                pos.index.name = pos.index.name or "date"
                long_pos = (
                    pos.reset_index()
                    .melt(id_vars=pos.index.name, var_name="symbol", value_name="weight")
                    .dropna(subset=["weight"])
                )
                # 过滤掉权重为 0 (节省空间)
                long_pos = long_pos[long_pos["weight"].abs() > 1e-12]
                long_pos = long_pos.rename(columns={pos.index.name: "date"})
                long_pos["date"] = [_to_naive_dt(d) for d in long_pos["date"]]
                long_pos.insert(0, "run_id", run_id)
                _bulk_insert(conn, position_snapshots, long_pos)

            # --- 4) trade_signals ---
            if result.trades is not None and not result.trades.empty:
                tr = result.trades.copy()
                rename_map = {"date": "signal_date"}
                tr = tr.rename(columns=rename_map)
                # 统一类型
                for col in ("signal_date", "exec_date"):
                    if col in tr.columns:
                        tr[col] = [_to_naive_dt(d) for d in tr[col]]
                tr.insert(0, "run_id", run_id)
                # 仅保留 schema 已知列
                valid_cols = {c.name for c in trade_signals.columns}
                tr = tr[[c for c in tr.columns if c in valid_cols]]
                _bulk_insert(conn, trade_signals, tr)

            # --- 5) fills ---
            if result.fills is not None and not result.fills.empty:
                fl = result.fills.copy()
                if "exec_datetime" in fl.columns:
                    fl["exec_datetime"] = [_to_naive_dt(d) for d in fl["exec_datetime"]]
                fl.insert(0, "run_id", run_id)
                valid_cols = {c.name for c in fills.columns}
                fl = fl[[c for c in fl.columns if c in valid_cols]]
                _bulk_insert(conn, fills, fl)

        return run_id

    # ------------------------------------------------------------------
    # Load
    # ------------------------------------------------------------------
    def load(self, run_id: int) -> "BacktestResult":
        """根据 run_id 重建 BacktestResult。"""
        from sqlalchemy import select

        from qtrade.backtest.engine import BacktestResult
        from qtrade.persistence.models import (
            backtest_runs,
            equity_points,
            fills,
            position_snapshots,
            trade_signals,
        )

        with self._engine.connect() as conn:
            row = conn.execute(
                select(backtest_runs).where(backtest_runs.c.id == run_id)
            ).mappings().first()
            if row is None:
                raise KeyError(f"run_id={run_id} 不存在")

            # equity
            eq_df = pd.read_sql(
                select(equity_points.c.date, equity_points.c.equity, equity_points.c.benchmark)
                .where(equity_points.c.run_id == run_id)
                .order_by(equity_points.c.date),
                conn,
            )
            if eq_df.empty:
                equity_curve = pd.Series(dtype=float)
                benchmark_curve = None
                daily_returns = pd.Series(dtype=float)
            else:
                eq_df["date"] = pd.to_datetime(eq_df["date"])
                eq_df = eq_df.set_index("date")
                equity_curve = eq_df["equity"].astype(float)
                equity_curve.name = "equity"
                if eq_df["benchmark"].notna().any():
                    benchmark_curve = eq_df["benchmark"].astype(float)
                    benchmark_curve.name = "benchmark"
                else:
                    benchmark_curve = None
                daily_returns = equity_curve.pct_change().fillna(0.0)
                daily_returns.name = "daily_returns"

            # positions (长表 -> 宽表)
            pos_df = pd.read_sql(
                select(
                    position_snapshots.c.date,
                    position_snapshots.c.symbol,
                    position_snapshots.c.weight,
                ).where(position_snapshots.c.run_id == run_id),
                conn,
            )
            if pos_df.empty:
                positions = pd.DataFrame()
            else:
                pos_df["date"] = pd.to_datetime(pos_df["date"])
                positions = (
                    pos_df.pivot_table(
                        index="date", columns="symbol", values="weight", aggfunc="last"
                    )
                    .sort_index()
                    .fillna(0.0)
                )
                positions.columns.name = None

            # trades
            tr_df = pd.read_sql(
                select(trade_signals)
                .where(trade_signals.c.run_id == run_id)
                .order_by(trade_signals.c.signal_date),
                conn,
            )
            if not tr_df.empty:
                tr_df = tr_df.drop(columns=["id", "run_id"], errors="ignore")
                tr_df = tr_df.rename(columns={"signal_date": "date"})
                for col in ("date", "exec_date"):
                    if col in tr_df.columns:
                        tr_df[col] = pd.to_datetime(tr_df[col])

            # fills
            fl_df = pd.read_sql(
                select(fills)
                .where(fills.c.run_id == run_id)
                .order_by(fills.c.exec_datetime),
                conn,
            )
            if not fl_df.empty:
                fl_df = fl_df.drop(columns=["id", "run_id"], errors="ignore")
                if "exec_datetime" in fl_df.columns:
                    fl_df["exec_datetime"] = pd.to_datetime(fl_df["exec_datetime"])

        metrics = dict(row["metrics_json"] or {})

        return BacktestResult(
            equity_curve=equity_curve,
            daily_returns=daily_returns,
            positions=positions,
            trades=tr_df if not tr_df.empty else pd.DataFrame(),
            metrics=metrics,
            benchmark_curve=benchmark_curve,
            fills=fl_df if not fl_df.empty else pd.DataFrame(),
        )

    # ------------------------------------------------------------------
    # List / Delete
    # ------------------------------------------------------------------
    def list_runs(self, limit: int = 100) -> pd.DataFrame:
        """返回 run metadata 列表 (不含 JSON 列, 方便展示)。"""
        from sqlalchemy import select

        from qtrade.persistence.models import backtest_runs

        cols = [
            backtest_runs.c.id,
            backtest_runs.c.name,
            backtest_runs.c.strategy_name,
            backtest_runs.c.start_date,
            backtest_runs.c.end_date,
            backtest_runs.c.initial_capital,
            backtest_runs.c.rebalance_freq,
            backtest_runs.c.created_at,
        ]
        stmt = select(*cols).order_by(backtest_runs.c.id.desc()).limit(limit)
        with self._engine.connect() as conn:
            df = pd.read_sql(stmt, conn)
        return df

    def get_metrics(self, run_id: int) -> dict:
        """仅读取某次运行的 metrics_json (轻量)。"""
        from sqlalchemy import select

        from qtrade.persistence.models import backtest_runs

        with self._engine.connect() as conn:
            row = conn.execute(
                select(backtest_runs.c.metrics_json).where(
                    backtest_runs.c.id == run_id
                )
            ).first()
        if row is None:
            raise KeyError(f"run_id={run_id} 不存在")
        return dict(row[0] or {})

    def delete(self, run_id: int) -> None:
        """删除一次 run 及其子表数据。"""
        from sqlalchemy import delete

        from qtrade.persistence.models import (
            backtest_runs,
            equity_points,
            fills,
            position_snapshots,
            trade_signals,
        )

        with self._engine.begin() as conn:
            # 某些 DB (SQLite) 默认不启用外键 CASCADE, 手动删除更稳妥
            for table in (equity_points, position_snapshots, trade_signals, fills):
                conn.execute(delete(table).where(table.c.run_id == run_id))
            conn.execute(delete(backtest_runs).where(backtest_runs.c.id == run_id))


# ====================================================================
# helpers
# ====================================================================


def _opt_float(x) -> float | None:
    if x is None:
        return None
    try:
        if pd.isna(x):
            return None
    except (TypeError, ValueError):
        pass
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _sql_scalar(value):
    """将 pandas / numpy 标量统一转成 DB 可接受的 Python 值。"""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, pd.Timestamp):
        return _to_naive_dt(value)
    item = getattr(value, "item", None)
    if callable(item):
        try:
            value = item()
        except (TypeError, ValueError):
            pass
    return value


def _bulk_insert(conn, table, df: pd.DataFrame) -> None:
    """批量插入 DataFrame 到 SQLAlchemy Table。"""
    if df is None or df.empty:
        return
    # 仅保留 schema 中存在的列
    valid_cols = {c.name for c in table.columns if c.name != "id"}
    df = df[[c for c in df.columns if c in valid_cols]]
    # 清理 NaN / NaT / pandas / numpy 标量
    records = [
        {k: _sql_scalar(v) for k, v in rec.items()}
        for rec in df.to_dict(orient="records")
    ]
    if records:
        conn.execute(table.insert(), records)


# ====================================================================
# 默认 store
# ====================================================================


_default_store: BacktestStore | None = None


def get_default_store() -> BacktestStore:
    """返回全局默认 store。URL 优先级:
    1. 环境变量 ``QTRADE_DB_URL``
    2. ``qtrade.config.DEFAULT_DB_URL``
    """
    global _default_store
    if _default_store is not None:
        return _default_store

    url = os.environ.get("QTRADE_DB_URL")
    if not url:
        from qtrade.config import DEFAULT_DB_URL

        url = DEFAULT_DB_URL

    _default_store = BacktestStore(url)
    _default_store.init_schema()
    return _default_store


def set_default_store(store: BacktestStore | None) -> None:
    """覆盖全局默认 store (测试/自定义连接用)。"""
    global _default_store
    _default_store = store
