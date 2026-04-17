"""
终端显示工具 (基于 rich)

提供统一的专业终端输出格式。
"""

from __future__ import annotations

import pandas as pd
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.columns import Columns
from rich.rule import Rule

console = Console()


# ------------------------------------------------------------------
# 通用 DataFrame -> Rich Table
# ------------------------------------------------------------------

def df_to_table(
    df: pd.DataFrame,
    title: str = "",
    float_fmt: str = ".4f",
    index_name: str = "",
    highlight_positive: bool = False,
) -> Table:
    """将 pandas DataFrame 渲染为 rich Table"""
    table = Table(
        title=title,
        show_header=True,
        header_style="bold cyan",
        border_style="dim",
        title_style="bold white",
        padding=(0, 1),
    )

    # 索引列
    idx_label = index_name or (df.index.name if df.index.name else "")
    table.add_column(idx_label, style="bold yellow", no_wrap=True)

    # 数据列
    for col in df.columns:
        table.add_column(str(col), justify="right")

    # 填充行
    for idx, row in df.iterrows():
        cells = [str(idx)]
        for val in row:
            if isinstance(val, float):
                text = f"{val:{float_fmt}}"
                if highlight_positive:
                    if val > 0:
                        text = f"[green]{text}[/green]"
                    elif val < 0:
                        text = f"[red]{text}[/red]"
                cells.append(text)
            else:
                cells.append(str(val))
        table.add_row(*cells)

    return table


def series_to_table(
    s: pd.Series,
    title: str = "",
    float_fmt: str = ".4f",
    highlight_positive: bool = False,
) -> Table:
    """将 pandas Series 渲染为 rich Table"""
    table = Table(
        title=title,
        show_header=True,
        header_style="bold cyan",
        border_style="dim",
        title_style="bold white",
        padding=(0, 1),
    )

    idx_label = s.index.name if s.index.name else ""
    table.add_column(idx_label, style="bold yellow", no_wrap=True)
    table.add_column(s.name or "value", justify="right")

    for idx, val in s.items():
        if isinstance(val, float):
            text = f"{val:{float_fmt}}"
            if highlight_positive:
                if val > 0:
                    text = f"[green]{text}[/green]"
                elif val < 0:
                    text = f"[red]{text}[/red]"
        else:
            text = str(val)
        table.add_row(str(idx), text)

    return table


# ------------------------------------------------------------------
# 回测绩效报告
# ------------------------------------------------------------------

_METRIC_LABELS = {
    "total_return": ("总收益率", True),
    "annual_return": ("年化收益率", True),
    "annual_volatility": ("年化波动率", False),
    "sharpe_ratio": ("夏普比率", False),
    "sortino_ratio": ("索提诺比率", False),
    "max_drawdown": ("最大回撤", False),
    "max_drawdown_duration_days": ("最大回撤持续(天)", False),
    "calmar_ratio": ("卡尔马比率", False),
    "win_rate": ("胜率", True),
    "profit_loss_ratio": ("盈亏比", False),
    "information_ratio": ("信息比率", False),
    "benchmark_return": ("基准收益", True),
    "excess_return": ("超额收益", True),
}


def backtest_report_table(metrics: dict[str, float], title: str = "回测绩效报告") -> Table:
    """将回测指标渲染为专业表格"""
    table = Table(
        title=title,
        show_header=True,
        header_style="bold cyan",
        border_style="dim",
        title_style="bold white",
        padding=(0, 2),
        min_width=48,
    )
    table.add_column("指标", style="bold", no_wrap=True)
    table.add_column("值", justify="right")

    for key, value in metrics.items():
        label, is_pct = _METRIC_LABELS.get(key, (key, False))
        if isinstance(value, float):
            if is_pct:
                text = f"{value:+.2%}"
            elif "duration" in key:
                text = str(int(value))
            else:
                text = f"{value:.4f}"

            # 颜色标记
            if key == "max_drawdown":
                text = f"[bold red]{text}[/bold red]"
            elif key in ("annual_return", "total_return", "excess_return") and value > 0:
                text = f"[bold green]{text}[/bold green]"
            elif key in ("annual_return", "total_return", "excess_return") and value < 0:
                text = f"[bold red]{text}[/bold red]"
            elif key == "sharpe_ratio":
                color = "green" if value > 1 else ("yellow" if value > 0.5 else "red")
                text = f"[{color}]{text}[/{color}]"
        else:
            text = str(value)

        table.add_row(label, text)

    return table


def print_backtest_report(metrics: dict[str, float], title: str = "回测绩效报告"):
    """打印回测绩效报告"""
    console.print()
    console.print(backtest_report_table(metrics, title))
    console.print()


def trade_points_table(
    trades: pd.DataFrame,
    title: str = "买卖点位",
    max_rows: int = 20,
) -> Table:
    """将交易点位渲染为 rich Table"""
    table = Table(
        title=title,
        show_header=True,
        header_style="bold cyan",
        border_style="dim",
        title_style="bold white",
        padding=(0, 1),
    )

    table.add_column("信号日", style="bold yellow", no_wrap=True)
    table.add_column("成交日", style="bold yellow", no_wrap=True)
    table.add_column("股票", no_wrap=True)
    table.add_column("动作", justify="center")
    table.add_column("旧权重", justify="right")
    table.add_column("新权重", justify="right")
    table.add_column("变化", justify="right")
    table.add_column("信号收盘", justify="right")
    table.add_column("次日开盘", justify="right")

    for row in trades.tail(max_rows).itertuples(index=False):
        action_color = "green" if row.action in ("买入", "加仓") else "red"
        exec_date = "-" if pd.isna(row.exec_date) else pd.Timestamp(row.exec_date).date().isoformat()
        signal_close = "-" if pd.isna(row.signal_close) else f"{row.signal_close:.2f}"
        exec_open = "-" if pd.isna(row.exec_open) else f"{row.exec_open:.2f}"
        table.add_row(
            pd.Timestamp(row.date).date().isoformat(),
            exec_date,
            str(row.symbol),
            f"[{action_color}]{row.action}[/{action_color}]",
            f"{row.old_weight:.2%}",
            f"{row.new_weight:.2%}",
            f"{row.delta_weight:+.2%}",
            signal_close,
            exec_open,
        )

    return table


# ------------------------------------------------------------------
# 分段标题
# ------------------------------------------------------------------

def section(title: str, style: str = "bold blue"):
    """打印分段标题"""
    console.print()
    console.print(Rule(title, style=style))


def info(message: str):
    """打印信息行"""
    console.print(f"  [dim]>[/dim] {message}")


def success(message: str):
    """打印成功信息"""
    console.print(f"  [green]>[/green] {message}")


def kv(key: str, value: str):
    """打印键值对"""
    console.print(f"  [dim]{key}:[/dim] [white]{value}[/white]")


# ------------------------------------------------------------------
# 相关性矩阵 (带色彩)
# ------------------------------------------------------------------

def correlation_table(
    corr: pd.DataFrame,
    title: str = "因子相关性矩阵",
) -> Table:
    """将相关性矩阵渲染为带色彩的 rich Table"""
    table = Table(
        title=title,
        show_header=True,
        header_style="bold cyan",
        border_style="dim",
        title_style="bold white",
        padding=(0, 1),
    )

    table.add_column("", style="bold yellow", no_wrap=True)
    for col in corr.columns:
        table.add_column(str(col), justify="right", min_width=10)

    for idx, row in corr.iterrows():
        cells = [str(idx)]
        for val in row:
            if abs(val) > 0.7:
                color = "bold red"
            elif abs(val) > 0.4:
                color = "yellow"
            elif abs(val) > 0.2:
                color = "white"
            else:
                color = "dim"
            cells.append(f"[{color}]{val:+.4f}[/{color}]")
        table.add_row(*cells)

    return table
