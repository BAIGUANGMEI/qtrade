"""
回测引擎 (基于 backtrader)

使用 backtrader 作为底层撮合引擎，支持真实的逐笔下单、现金管理、
下一根 bar 开盘成交、手续费和滑点。

对外保持 BacktestEngine / BacktestResult 接口不变。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import backtrader as bt
import numpy as np
import pandas as pd

from qtrade.config import (
    DEFAULT_COMMISSION_RATE,
    DEFAULT_INITIAL_CAPITAL,
    DEFAULT_SLIPPAGE,
)
from qtrade.backtest.performance import full_metrics


# ====================================================================
# BacktestResult — 与之前完全相同的数据容器
# ====================================================================


@dataclass
class BacktestResult:
    """回测结果"""

    equity_curve: pd.Series
    daily_returns: pd.Series
    positions: pd.DataFrame
    trades: pd.DataFrame
    metrics: dict[str, float] = field(default_factory=dict)
    benchmark_curve: pd.Series | None = None
    fills: pd.DataFrame = field(default_factory=pd.DataFrame)  # 真实成交回报

    def report(self, title: str = "回测绩效报告") -> None:
        """打印绩效报告 (rich 格式)"""
        from qtrade.utils.display import print_backtest_report

        print_backtest_report(self.metrics, title=title)

    def export_positions_csv(self, file_path: str | Path) -> Path:
        """导出持仓历史到 CSV"""
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        positions = self.positions.copy()
        positions.index.name = positions.index.name or "date"
        positions.to_csv(path, encoding="utf-8-sig")
        return path

    def export_trades_csv(self, file_path: str | Path) -> Path:
        """导出交易点位到 CSV"""
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        trades = self.trades.copy()
        if "date" in trades.columns:
            trades["date"] = pd.to_datetime(trades["date"])
        if "exec_date" in trades.columns:
            trades["exec_date"] = pd.to_datetime(trades["exec_date"])
        trades.to_csv(path, index=False, encoding="utf-8-sig")
        return path

    # ------------------------------------------------------------------
    # 数据库持久化 (SQLite / MySQL / PostgreSQL)
    # ------------------------------------------------------------------
    def save(
        self,
        name: str,
        strategy_name: str = "",
        config: dict | None = None,
        notes: str | None = None,
        store=None,
    ) -> int:
        """保存回测结果到 SQL 数据库, 返回 run_id。

        参数
        ----
        name : 本次运行的业务名称 (如 "MyStrategy-v2")
        strategy_name : 策略类名 (可选)
        config : 任意可 JSON 序列化的参数 dict
        notes : 备注
        store : 可选 BacktestStore, 默认使用 qtrade.persistence.get_default_store()
        """
        if store is None:
            from qtrade.persistence import get_default_store

            store = get_default_store()
        return store.save(
            self, name=name, strategy_name=strategy_name, config=config, notes=notes
        )

    @classmethod
    def load(cls, run_id: int, store=None) -> "BacktestResult":
        """从数据库读取回测结果。"""
        if store is None:
            from qtrade.persistence import get_default_store

            store = get_default_store()
        return store.load(run_id)

    @classmethod
    def list_runs(cls, limit: int = 100, store=None) -> pd.DataFrame:
        """列出数据库中已保存的回测。"""
        if store is None:
            from qtrade.persistence import get_default_store

            store = get_default_store()
        return store.list_runs(limit=limit)


# ====================================================================
# 内部: backtrader Strategy 适配器
# ====================================================================


class _WeightRebalanceStrategy(bt.Strategy):
    """
    backtrader Strategy 适配器。

    在调仓日从外部 qtrade Strategy 获取目标权重，
    然后通过 order_target_percent 下单调仓。
    订单在下一根 bar 开盘价成交 (backtrader 默认行为)。
    """

    params = (
        ("qtrade_strategy", None),
        ("panel_data", None),
        ("rebalance_dates", None),
        ("symbol_list", None),
        ("commission_rate", 0.0),
        ("slippage_rate", 0.0),
        ("allow_short", False),
        ("progress_callback", None),
        ("cancel_event", None),
        ("total_bars", 0),
    )

    def __init__(self):
        self._trade_log: list[dict] = []
        self._daily_positions: list[dict] = []
        self._equity_log: list[dict] = []
        self._fill_log: list[dict] = []  # 实际成交回报 (价格 / 手续费)

    def notify_order(self, order):
        """捕获 broker 回报: 记录真实成交价、成交数量、手续费。"""
        if order.status in (order.Completed, order.Partial):
            data_feed = order.data
            sym = getattr(data_feed, "_name", None)
            try:
                exec_dt = pd.Timestamp(bt.num2date(order.executed.dt))
            except Exception:
                exec_dt = pd.NaT
            side = "BUY" if order.isbuy() else "SELL"
            self._fill_log.append(
                {
                    "exec_datetime": exec_dt,
                    "symbol": sym,
                    "side": side,
                    "size": float(order.executed.size),
                    "fill_price": float(order.executed.price),
                    "commission": float(order.executed.comm),
                    "value": float(order.executed.value),
                    "status": "Completed" if order.status == order.Completed else "Partial",
                }
            )
        elif order.status in (order.Canceled, order.Margin, order.Rejected):
            data_feed = order.data
            sym = getattr(data_feed, "_name", None)
            reason = {
                order.Canceled: "Canceled",
                order.Margin: "Margin",
                order.Rejected: "Rejected",
            }.get(order.status, "Unknown")
            self._fill_log.append(
                {
                    "exec_datetime": pd.NaT,
                    "symbol": sym,
                    "side": "BUY" if order.isbuy() else "SELL",
                    "size": 0.0,
                    "fill_price": float("nan"),
                    "commission": 0.0,
                    "value": 0.0,
                    "status": reason,
                }
            )

    def next(self):
        dt = self.datas[0].datetime.date(0)
        current_date = pd.Timestamp(dt)

        total_value = self.broker.getvalue()

        # 记录每日净值
        self._equity_log.append({"date": current_date, "equity": total_value})

        # 取消 / 进度回调 (每个 bar 触发一次)
        cancel_event = self.p.cancel_event
        if cancel_event is not None and cancel_event.is_set():
            try:
                self.env.runstop()
            except Exception:
                pass
            return
        progress_cb = self.p.progress_callback
        if progress_cb is not None:
            try:
                bar_idx = len(self._equity_log)
                progress_cb(bar_idx, int(self.p.total_bars or 0),
                            current_date, float(total_value))
            except Exception:
                # 进度回调失败不应打断回测
                pass

        # 记录每日持仓权重
        total_value = self.broker.getvalue()
        pos_record = {"date": current_date}
        for i, sym in enumerate(self.p.symbol_list):
            pos = self.getposition(self.datas[i])
            if pos.size != 0:
                pos_record[sym] = pos.size * self.datas[i].close[0] / total_value
            else:
                pos_record[sym] = 0.0
        self._daily_positions.append(pos_record)

        # 非调仓日跳过
        if current_date not in self.p.rebalance_dates:
            return

        # 截取至当日的历史数据 (防止策略前视): 任何 generate_weights 访问
        # 的 data[k] 都不能包含 current_date 之后的行。
        # 注: 策略内部的因子预计算应该基于 strategy.load_data() 返回的
        # 完整面板 (包含 warmup); 引擎不对此做任何特殊补偿。
        data_slice = {
            k: v.loc[:current_date]
            for k, v in self.p.panel_data.items()
            if current_date in v.index
        }

        target_weights = self.p.qtrade_strategy.generate_weights(
            current_date, data_slice
        )
        if target_weights is None:
            return

        # 归一化: 多空对冲策略会出现负权重, 此时归一化分母用总投线比例 (sum(|w|))
        # 并保留符号。对于纯多策略, 最终 sum(w) == 1。
        w_sum = target_weights.abs().sum()
        if w_sum <= 0:
            return
        target_weights = target_weights / w_sum

        # 若策略输出了负权重却未开启做空, 将负权重强制截断为 0 并告警 (仅首次)。
        has_short = (target_weights < 0).any()
        if has_short and not self.p.allow_short:
            if not getattr(self, "_warned_short", False):
                import warnings

                warnings.warn(
                    "策略输出了负权重但 BacktestEngine(allow_short=False) 未开启做空, "
                    "负权重将被截断为 0。如需多空对冲请显式传入 allow_short=True。",
                    stacklevel=2,
                )
                self._warned_short = True
            target_weights = target_weights.clip(lower=0.0)
            w_sum = target_weights.abs().sum()
            if w_sum <= 0:
                return
            target_weights = target_weights / w_sum

        # 预留现金缓冲区: 避免因手续费 + 滑点导致实际所需资金超过账户可用
        # 现金, 从而被 broker 拒单。每笔交易雙边成本 ≈ commission + slippage,
        # 为整体调仓留出 2x 的缓冲。
        cost_buffer = 2.0 * (
            float(self.p.commission_rate or 0.0)
            + float(self.p.slippage_rate or 0.0)
        )
        cost_buffer = min(max(cost_buffer, 0.0), 0.05)  # 上限 5%
        target_weights = target_weights * (1.0 - cost_buffer)

        # 调仓: 先卖后买 (避免资金不足)
        sym_to_idx = {s: i for i, s in enumerate(self.p.symbol_list)}

        # 1) 减仓 / 清仓
        for sym in self.p.symbol_list:
            target_w = target_weights.get(sym, 0.0)
            data_feed = self.datas[sym_to_idx[sym]]
            pos = self.getposition(data_feed)
            current_w = (
                pos.size * data_feed.close[0] / total_value if pos.size else 0.0
            )
            if target_w < current_w:
                self.order_target_percent(data_feed, target=target_w)
                self._trade_log.append(
                    {
                        "date": current_date,
                        "symbol": sym,
                        "old_weight": round(current_w, 6),
                        "new_weight": round(target_w, 6),
                    }
                )

        # 2) 加仓 / 新开仓
        for sym in self.p.symbol_list:
            target_w = target_weights.get(sym, 0.0)
            data_feed = self.datas[sym_to_idx[sym]]
            pos = self.getposition(data_feed)
            current_w = (
                pos.size * data_feed.close[0] / total_value if pos.size else 0.0
            )
            if target_w > current_w:
                self.order_target_percent(data_feed, target=target_w)
                self._trade_log.append(
                    {
                        "date": current_date,
                        "symbol": sym,
                        "old_weight": round(current_w, 6),
                        "new_weight": round(target_w, 6),
                    }
                )


# ====================================================================
# BacktestEngine — 对外接口保持一致
# ====================================================================


class BacktestEngine:
    """
    基于 backtrader 的回测引擎。

    策略在调仓日产出目标权重，引擎通过 backtrader broker 真实撮合下单。
    订单在下一根 bar 开盘价成交 (backtrader 默认行为)。

    Parameters
    ----------
    initial_capital : 初始资金
    start_date, end_date : 回测区间
    rebalance_freq : 调仓频率 "D"/"W"/"M"/"Q"
    commission : 单边手续费率
    slippage : 滑点率
    allow_short : 是否允许做空 (多空策略需开启, 默认 False)
    """

    def __init__(
        self,
        initial_capital: float = DEFAULT_INITIAL_CAPITAL,
        start_date: str = "2020-01-01",
        end_date: str = "2024-12-31",
        rebalance_freq: str = "M",
        commission: float = DEFAULT_COMMISSION_RATE,
        slippage: float = DEFAULT_SLIPPAGE,
        allow_short: bool = False,
    ):
        self.initial_capital = initial_capital
        self.start_date = pd.Timestamp(start_date)
        self.end_date = pd.Timestamp(end_date)
        self.rebalance_freq = rebalance_freq
        self.commission = commission
        self.slippage = slippage
        self.allow_short = allow_short

    def run(
        self,
        strategy,
        data: dict[str, pd.DataFrame] | None = None,
        benchmark: pd.Series | None = None,
        progress_callback=None,
        cancel_event=None,
    ) -> BacktestResult:
        """
        执行回测。

        Parameters
        ----------
        strategy : qtrade Strategy 实例 (须实现 generate_weights)
        data : Panel 数据 (若 strategy 内部未加载)
        benchmark : 基准价格序列 (如 SPY 收盘价)

        Returns
        -------
        BacktestResult
        """
        if data is None:
            data = strategy.load_data()

        close = data["close"]
        mask = (close.index >= self.start_date) & (close.index <= self.end_date)
        close = close.loc[mask]
        symbols = close.columns.tolist()

        rebalance_dates = self._get_rebalance_dates(close.index)

        # ---- 构建 Cerebro ----
        cerebro = bt.Cerebro(stdstats=False)
        cerebro.broker.setcash(self.initial_capital)
        cerebro.broker.setcommission(commission=self.commission)
        cerebro.broker.set_slippage_perc(self.slippage)
        if not self.allow_short:
            # 禁止做空 (backtrader 默认也不允许做空现金账户, 这里显式声明)
            cerebro.broker.set_shortcash(False)

        # 净值观察器
        cerebro.addobserver(bt.observers.Broker)

        # 为每只股票添加 data feed
        # 注意: backtrader 多数据源会按全体 feed 时钟同步推进, 只要任一 feed 起始日期
        # 晚于回测首日 (如回测期内 IPO 的新股), next() 的首次触发就会被延后到
        # 迟到 feed 的首日, 导致真实回测窗口被大幅压缩, 年化指标随之严重失真。
        # 因此这里剔除首个有效日期晚于回测首个交易日的股票。
        bt_first_day = close.index[0] if len(close.index) > 0 else self.start_date
        valid_symbols = []
        skipped_late_start: list[str] = []
        for sym in symbols:
            ohlcv = pd.DataFrame(
                {
                    "open": data["open"][sym]
                    if sym in data["open"].columns
                    else close[sym],
                    "high": data["high"][sym]
                    if sym in data["high"].columns
                    else close[sym],
                    "low": data["low"][sym]
                    if sym in data["low"].columns
                    else close[sym],
                    "close": close[sym],
                    "volume": data["volume"][sym]
                    if sym in data["volume"].columns
                    else 0,
                },
                index=close.index,
            ).dropna()

            if len(ohlcv) < 2:
                continue

            # 剔除回测期中途才有数据的股票 (新上市 / 数据缺失前段),
            # 避免 backtrader 时钟同步导致回测窗口被截断。
            if ohlcv.index[0] > bt_first_day:
                skipped_late_start.append(sym)
                continue

            valid_symbols.append(sym)
            bt_data = bt.feeds.PandasData(
                dataname=ohlcv,
                fromdate=self.start_date.to_pydatetime(),
                todate=self.end_date.to_pydatetime(),
            )
            cerebro.adddata(bt_data, name=sym)

        symbols = valid_symbols

        if skipped_late_start:
            import warnings

            preview = ", ".join(skipped_late_start[:5])
            more = f" 等共 {len(skipped_late_start)} 只" if len(skipped_late_start) > 5 else ""
            warnings.warn(
                f"回测期内首日无数据的股票已被剔除 (例: {preview}{more}), "
                "以避免 backtrader 时钟同步导致回测窗口被截断。",
                stacklevel=2,
            )

        # 添加策略适配器
        cerebro.addstrategy(
            _WeightRebalanceStrategy,
            qtrade_strategy=strategy,
            panel_data=data,
            rebalance_dates=rebalance_dates,
            symbol_list=symbols,
            commission_rate=self.commission,
            slippage_rate=self.slippage,
            allow_short=self.allow_short,
            progress_callback=progress_callback,
            cancel_event=cancel_event,
            total_bars=len(close.index),
        )

        # ---- 运行 ----
        results = cerebro.run()
        strat = results[0]

        # ---- 提取结果 ----
        # 净值曲线 (从策略内部记录)
        equity_df = pd.DataFrame(strat._equity_log)
        equity_series = equity_df.set_index("date")["equity"]
        equity_series.name = "equity"
        equity_series = equity_series[~equity_series.index.duplicated(keep="last")]
        daily_ret = equity_series.pct_change().dropna()

        # 持仓矩阵
        if strat._daily_positions:
            positions = pd.DataFrame(strat._daily_positions).set_index("date")
            positions = positions.reindex(columns=symbols, fill_value=0.0)
        else:
            positions = pd.DataFrame(
                0.0, index=equity_series.index, columns=symbols
            )

        # 交易记录
        trades_df = (
            pd.DataFrame(strat._trade_log)
            if strat._trade_log
            else pd.DataFrame(
                columns=["date", "symbol", "old_weight", "new_weight"]
            )
        )
        if not trades_df.empty:
            trades_df["date"] = pd.to_datetime(trades_df["date"])
            trades_df["delta_weight"] = (
                trades_df["new_weight"] - trades_df["old_weight"]
            )

            action_labels = []
            for row in trades_df.itertuples(index=False):
                if row.old_weight <= 0 and row.new_weight > 0:
                    action_labels.append("买入")
                elif row.old_weight > 0 and row.new_weight <= 0:
                    action_labels.append("卖出")
                elif row.delta_weight > 0:
                    action_labels.append("加仓")
                else:
                    action_labels.append("减仓")
            trades_df["action"] = action_labels

            next_date_map = pd.Series(
                close.index[1:].tolist() + [pd.NaT],
                index=close.index,
            )
            trades_df["exec_date"] = trades_df["date"].map(next_date_map)
            trades_df["status"] = np.where(
                trades_df["exec_date"].isna(),
                "未成交",
                "已成交",
            )

            signal_close = []
            exec_open = []
            for row in trades_df.itertuples(index=False):
                signal_price = np.nan
                if (
                    row.symbol in data["close"].columns
                    and row.date in data["close"].index
                ):
                    signal_price = float(data["close"].at[row.date, row.symbol])
                signal_close.append(signal_price)

                exec_price = np.nan
                if (
                    pd.notna(row.exec_date)
                    and row.symbol in data["open"].columns
                    and row.exec_date in data["open"].index
                ):
                    exec_price = float(data["open"].at[row.exec_date, row.symbol])
                exec_open.append(exec_price)

            trades_df["signal_close"] = signal_close
            trades_df["exec_open"] = exec_open
            trades_df = trades_df[
                [
                    "date",
                    "exec_date",
                    "symbol",
                    "action",
                    "status",
                    "old_weight",
                    "new_weight",
                    "delta_weight",
                    "signal_close",
                    "exec_open",
                ]
            ]

        # 基准净值
        benchmark_curve = None
        if benchmark is not None:
            bench = benchmark.reindex(equity_series.index).dropna()
            # 日期对齐校验: 若基准覆盖率过低, 超额收益/信息比率将严重失真
            coverage = len(bench) / max(len(equity_series), 1)
            if coverage < 0.95:
                import warnings

                warnings.warn(
                    f"基准与组合净值的日期重合度仅 {coverage:.1%} "
                    f"(基准 {len(bench)} / 组合 {len(equity_series)} 日), "
                    "可能导致信息比率/超额收益失真, 请检查基准数据范围。",
                    stacklevel=2,
                )
            if len(bench) > 0:
                benchmark_curve = (
                    bench / bench.iloc[0] * self.initial_capital
                )
                benchmark_curve.name = "benchmark"

        # 绩效指标
        metrics = full_metrics(equity_series, benchmark_curve=benchmark_curve)

        # 真实成交回报 & 逐笔交易胜率/盈亏比
        fills_df = (
            pd.DataFrame(strat._fill_log)
            if strat._fill_log
            else pd.DataFrame(
                columns=[
                    "exec_datetime", "symbol", "side", "size",
                    "fill_price", "commission", "value", "status",
                ]
            )
        )
        trade_metrics = _compute_trade_metrics(fills_df)
        metrics.update(trade_metrics)

        return BacktestResult(
            equity_curve=equity_series,
            daily_returns=daily_ret,
            positions=positions,
            trades=trades_df,
            metrics=metrics,
            benchmark_curve=benchmark_curve,
            fills=fills_df,
        )

    def _get_rebalance_dates(
        self, index: pd.DatetimeIndex
    ) -> set[pd.Timestamp]:
        """根据频率获取调仓日"""
        if self.rebalance_freq == "D":
            return set(index)

        freq_map = {"W": "W-FRI", "M": "M", "Q": "Q"}
        freq = freq_map.get(self.rebalance_freq, self.rebalance_freq)

        periods = index.to_period(freq)
        last_days = set()
        for period in periods.unique():
            mask = periods == period
            dates_in_period = index[mask]
            if len(dates_in_period) > 0:
                last_days.add(dates_in_period[-1])
        return last_days


# ====================================================================
# 辅助: 从成交回报计算逐笔交易盈亏指标 (FIFO 配对)
# ====================================================================


def _compute_trade_metrics(fills: pd.DataFrame) -> dict[str, float]:
    """
    基于真实成交回报用 FIFO 法配对平仓, 得到逐笔交易盈亏。

    返回 trade_win_rate / trade_profit_loss_ratio / trade_count / total_commission。
    未配对的尾部持仓 (未平仓) 不计入胜率统计。
    """
    if fills is None or fills.empty:
        return {
            "trade_win_rate": 0.0,
            "trade_profit_loss_ratio": 0.0,
            "trade_count": 0,
            "total_commission": 0.0,
        }

    completed = fills[fills["status"] == "Completed"].copy()
    if completed.empty:
        return {
            "trade_win_rate": 0.0,
            "trade_profit_loss_ratio": 0.0,
            "trade_count": 0,
            "total_commission": float(fills["commission"].sum()),
        }

    total_commission = float(completed["commission"].sum())

    # 按 symbol FIFO 配对: 以首次开仓方向 (long/short) 为基准, 反向成交视为平仓
    trade_pnls: list[float] = []
    for sym, grp in completed.groupby("symbol", sort=False):
        grp = grp.sort_values("exec_datetime", kind="stable")
        # 队列存 (size, price), size 带正负号
        queue: list[list[float]] = []
        for row in grp.itertuples(index=False):
            signed = row.size  # backtrader: buy +size, sell -size
            if not queue or (queue[0][0] >= 0) == (signed >= 0):
                # 同向加仓
                queue.append([signed, float(row.fill_price)])
                continue
            # 反向: 逐批平仓
            remaining = signed
            while queue and remaining != 0 and (queue[0][0] >= 0) != (remaining >= 0):
                open_size, open_price = queue[0]
                match = min(abs(open_size), abs(remaining))
                # 多头: pnl = (close - open) * match; 空头相反
                if open_size > 0:
                    pnl = (float(row.fill_price) - open_price) * match
                else:
                    pnl = (open_price - float(row.fill_price)) * match
                trade_pnls.append(pnl)
                if abs(open_size) - match <= 1e-9:
                    queue.pop(0)
                else:
                    queue[0][0] = open_size - (match if open_size > 0 else -match)
                remaining = remaining + match if remaining < 0 else remaining - match
            if abs(remaining) > 1e-9:
                # 反手开新仓
                queue.append([remaining, float(row.fill_price)])

    trade_count = len(trade_pnls)
    if trade_count == 0:
        return {
            "trade_win_rate": 0.0,
            "trade_profit_loss_ratio": 0.0,
            "trade_count": 0,
            "total_commission": total_commission,
        }

    wins = [p for p in trade_pnls if p > 0]
    losses = [p for p in trade_pnls if p < 0]
    win_rate_val = len(wins) / trade_count
    if losses and sum(losses) != 0:
        avg_win = sum(wins) / len(wins) if wins else 0.0
        avg_loss = abs(sum(losses) / len(losses))
        pl_ratio = avg_win / avg_loss if avg_loss > 0 else float("inf")
    else:
        pl_ratio = float("inf") if wins else 0.0

    return {
        "trade_win_rate": float(win_rate_val),
        "trade_profit_loss_ratio": float(pl_ratio),
        "trade_count": int(trade_count),
        "total_commission": total_commission,
    }