"""
可视化工具

提供因子分析与回测结果的绘图函数。
"""

from __future__ import annotations

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib

matplotlib.rcParams["font.sans-serif"] = ["SimHei", "Arial Unicode MS", "DejaVu Sans"]
matplotlib.rcParams["axes.unicode_minus"] = False


def plot_ic_series(ic_series: pd.Series, title: str = "IC Series", save_path: str | None = None):
    """绘制 IC 时间序列 + 累计 IC"""
    fig, axes = plt.subplots(2, 1, figsize=(14, 8), sharex=True)

    axes[0].bar(ic_series.index, ic_series.values, color="steelblue", alpha=0.7, width=2)
    axes[0].axhline(0, color="black", linewidth=0.5)
    axes[0].axhline(ic_series.mean(), color="red", linestyle="--", label=f"均值={ic_series.mean():.4f}")
    axes[0].set_title(f"{title} (Daily)")
    axes[0].legend()

    cum_ic = ic_series.cumsum()
    axes[1].plot(cum_ic.index, cum_ic.values, color="darkorange")
    axes[1].set_title("累计 IC")
    axes[1].set_xlabel("日期")

    plt.tight_layout()
    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.show()


def plot_group_returns(
    cum_returns: pd.DataFrame, title: str = "分组累计收益", save_path: str | None = None
):
    """绘制分组累计收益曲线"""
    fig, ax = plt.subplots(figsize=(14, 7))
    for col in cum_returns.columns:
        ax.plot(cum_returns.index, cum_returns[col], label=col)
    ax.set_title(title)
    ax.set_xlabel("日期")
    ax.set_ylabel("累计收益")
    ax.legend()
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.show()


def plot_long_short(
    cum_ls: pd.Series, title: str = "多空组合累计收益", save_path: str | None = None
):
    """绘制多空组合净值曲线"""
    fig, ax = plt.subplots(figsize=(14, 5))
    ax.plot(cum_ls.index, cum_ls.values, color="darkgreen", linewidth=1.5)
    ax.fill_between(cum_ls.index, 0, cum_ls.values, alpha=0.15, color="green")
    ax.axhline(0, color="black", linewidth=0.5)
    ax.set_title(title)
    ax.set_xlabel("日期")
    ax.set_ylabel("累计收益")
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.show()


def plot_backtest_result(result, title: str = "回测净值曲线", save_path: str | None = None):
    """绘制回测结果: 净值曲线 + 回撤"""
    equity = result.equity_curve

    fig, axes = plt.subplots(2, 1, figsize=(14, 9), gridspec_kw={"height_ratios": [3, 1]})

    # 净值曲线
    axes[0].plot(equity.index, equity.values, color="steelblue", linewidth=1.2)
    axes[0].set_title(title)
    axes[0].set_ylabel("组合净值")
    axes[0].grid(True, alpha=0.3)

    # 添加关键指标文字
    metrics = result.metrics
    text = (
        f"年化收益: {metrics.get('annual_return', 0):.2%}  "
        f"夏普: {metrics.get('sharpe_ratio', 0):.2f}  "
        f"最大回撤: {metrics.get('max_drawdown', 0):.2%}  "
        f"卡尔马: {metrics.get('calmar_ratio', 0):.2f}"
    )
    axes[0].annotate(text, xy=(0.02, 0.95), xycoords="axes fraction", fontsize=10,
                     verticalalignment="top", bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.5))

    # 回撤曲线
    running_max = equity.cummax()
    drawdown = (equity - running_max) / running_max
    axes[1].fill_between(drawdown.index, 0, drawdown.values, color="tomato", alpha=0.5)
    axes[1].set_title("回撤")
    axes[1].set_ylabel("回撤幅度")
    axes[1].set_xlabel("日期")
    axes[1].grid(True, alpha=0.3)

    plt.tight_layout()
    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.show()


def plot_backtest_with_trade_points(
    result,
    trades: pd.DataFrame | None = None,
    title: str = "回测净值曲线与买卖点",
    save_path: str | None = None,
):
    """绘制净值曲线，并在图上标出买卖点。"""
    equity = result.equity_curve
    benchmark = getattr(result, "benchmark_curve", None)

    fig, axes = plt.subplots(2, 1, figsize=(15, 9), gridspec_kw={"height_ratios": [3, 1]})

    axes[0].plot(equity.index, equity.values, color="steelblue", linewidth=1.4, label="组合净值")
    if benchmark is not None:
        aligned_benchmark = benchmark.reindex(equity.index).dropna()
        if not aligned_benchmark.empty:
            axes[0].plot(
                aligned_benchmark.index,
                aligned_benchmark.values,
                color="dimgray",
                linewidth=1.0,
                linestyle="--",
                label="基准净值",
            )

    if trades is not None and not trades.empty:
        executed = trades.copy()
        if "status" in executed.columns:
            executed = executed[executed["status"] == "已成交"]
        executed = executed.dropna(subset=["exec_date"])

        if not executed.empty:
            executed["exec_date"] = pd.to_datetime(executed["exec_date"])

            buy_actions = {"买入", "加仓"}
            sell_actions = {"卖出", "减仓"}

            buy_dates = sorted(executed.loc[executed["action"].isin(buy_actions), "exec_date"].unique())
            sell_dates = sorted(executed.loc[executed["action"].isin(sell_actions), "exec_date"].unique())

            buy_y = equity.reindex(pd.to_datetime(buy_dates)).dropna()
            sell_y = equity.reindex(pd.to_datetime(sell_dates)).dropna()

            if not buy_y.empty:
                axes[0].scatter(
                    buy_y.index,
                    buy_y.values,
                    marker="^",
                    s=70,
                    color="forestgreen",
                    edgecolors="white",
                    linewidths=0.6,
                    zorder=5,
                    label="买点",
                )
            if not sell_y.empty:
                axes[0].scatter(
                    sell_y.index,
                    sell_y.values,
                    marker="v",
                    s=70,
                    color="crimson",
                    edgecolors="white",
                    linewidths=0.6,
                    zorder=5,
                    label="卖点",
                )

    axes[0].set_title(title)
    axes[0].set_ylabel("组合净值")
    axes[0].grid(True, alpha=0.3)

    metrics = result.metrics
    text = (
        f"年化收益: {metrics.get('annual_return', 0):.2%}  "
        f"夏普: {metrics.get('sharpe_ratio', 0):.2f}  "
        f"最大回撤: {metrics.get('max_drawdown', 0):.2%}  "
        f"卡尔马: {metrics.get('calmar_ratio', 0):.2f}"
    )
    axes[0].annotate(
        text,
        xy=(0.02, 0.95),
        xycoords="axes fraction",
        fontsize=10,
        verticalalignment="top",
        bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.5),
    )
    axes[0].legend(loc="upper left")

    running_max = equity.cummax()
    drawdown = (equity - running_max) / running_max
    axes[1].fill_between(drawdown.index, 0, drawdown.values, color="tomato", alpha=0.5)
    axes[1].set_title("回撤")
    axes[1].set_ylabel("回撤幅度")
    axes[1].set_xlabel("日期")
    axes[1].grid(True, alpha=0.3)

    plt.tight_layout()
    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.show()


def plot_correlation_matrix(
    corr_matrix: pd.DataFrame, title: str = "因子相关性矩阵", save_path: str | None = None
):
    """绘制相关性热力图"""
    fig, ax = plt.subplots(figsize=(10, 8))
    im = ax.imshow(corr_matrix.values, cmap="RdBu_r", vmin=-1, vmax=1, aspect="auto")
    ax.set_xticks(range(len(corr_matrix.columns)))
    ax.set_yticks(range(len(corr_matrix.index)))
    ax.set_xticklabels(corr_matrix.columns, rotation=45, ha="right")
    ax.set_yticklabels(corr_matrix.index)

    # 标注数值
    for i in range(len(corr_matrix.index)):
        for j in range(len(corr_matrix.columns)):
            val = corr_matrix.iloc[i, j]
            ax.text(j, i, f"{val:.2f}", ha="center", va="center", fontsize=9)

    fig.colorbar(im, ax=ax)
    ax.set_title(title)

    plt.tight_layout()
    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.show()


def plot_ic_decay(decay: pd.Series, title: str = "IC 衰减曲线", save_path: str | None = None):
    """绘制 IC 衰减曲线"""
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.bar(decay.index, decay.values, color="teal", alpha=0.7)
    ax.axhline(0, color="black", linewidth=0.5)
    ax.set_xlabel("持有期 (天)")
    ax.set_ylabel("平均 IC")
    ax.set_title(title)
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.show()
