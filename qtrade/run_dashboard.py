"""
QTrade 量化分析面板

启动交互式 Web Dashboard。
直接运行: python -m qtrade.run_dashboard
"""

from __future__ import annotations

from qtrade.dashboard.app import run_server


def main():
    print()
    print("=" * 50)
    print("  QTrade 量化分析面板")
    print("  http://127.0.0.1:8050")
    print("=" * 50)
    print()
    print("  1. 在左侧面板选择策略参数")
    print("  2. 点击「运行回测」开始分析")
    print("  3. 通过导航切换各分析页面")
    print()
    run_server(debug=True, port=8050)


if __name__ == "__main__":
    main()
