"""
SQL 持久化模块

支持将回测结果 (BacktestResult) 保存到任意 SQLAlchemy 兼容的关系数据库:
- SQLite (默认, 无需额外安装)
- PostgreSQL (pip install psycopg2-binary)
- MySQL (pip install pymysql 或 mysqlclient)
- 其它 SQLAlchemy 支持的方言 (Oracle, MSSQL 等)

用法:
    from qtrade.persistence import BacktestStore

    store = BacktestStore("sqlite:///backtests.db")
    # 或 store = BacktestStore("mysql+pymysql://user:pwd@host/db")
    # 或 store = BacktestStore("postgresql+psycopg2://user:pwd@host/db")

    run_id = store.save(result, name="my_strategy_v1",
                        strategy_name="IntradayCompositeStrategy",
                        config={"top_n": 10, "rebalance_freq": "W"})
    loaded = store.load(run_id)
    runs = store.list_runs()
"""

from qtrade.persistence.store import (
    BacktestStore,
    get_default_store,
    set_default_store,
)

__all__ = ["BacktestStore", "get_default_store", "set_default_store"]
