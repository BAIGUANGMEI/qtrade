"""历史回测页 — 展示数据库中全部保存的 run, 支持加载 / 删除。"""

from __future__ import annotations

import dash
import dash_bootstrap_components as dbc
from dash import ALL, Input, Output, callback, dcc, html

from qtrade.persistence import get_default_store


def _header_row():
    return html.Thead(html.Tr([
        html.Th("#"),
        html.Th("名称"),
        html.Th("策略"),
        html.Th("区间"),
        html.Th("初始资金"),
        html.Th("调仓"),
        html.Th("创建时间"),
        html.Th("操作"),
    ]))


def _body_rows():
    try:
        store = get_default_store()
        df = store.list_runs(limit=500)
    except Exception:
        return []

    rows = []
    for _, row in df.iterrows():
        rid = int(row["id"])
        start = str(row["start_date"]).split(" ")[0] if row["start_date"] is not None else "-"
        end = str(row["end_date"]).split(" ")[0] if row["end_date"] is not None else "-"
        capital = row.get("initial_capital")
        capital_str = f"{capital:,.0f}" if capital is not None else "-"
        created = str(row["created_at"]).split(".")[0] if row["created_at"] is not None else "-"

        rows.append(html.Tr([
            html.Td(str(rid), style={"fontWeight": "600"}),
            html.Td(str(row["name"] or "-")),
            html.Td(str(row["strategy_name"] or "-")),
            html.Td(f"{start} ~ {end}", className="small"),
            html.Td(capital_str),
            html.Td(str(row.get("rebalance_freq") or "-")),
            html.Td(created, className="small text-muted"),
            html.Td([
                dcc.Link(
                    dbc.Button("加载", size="sm", color="primary", className="me-1"),
                    href=f"/?run_id={rid}",
                ),
                dcc.Link(
                    dbc.Button("交易", size="sm", color="outline-info", className="me-1"),
                    href=f"/trades?run_id={rid}",
                ),
                dbc.Button(
                    "删除", size="sm", color="outline-danger",
                    id={"type": "delete-run-btn", "run_id": rid},
                ),
            ]),
        ]))
    return rows


def layout():
    try:
        store = get_default_store()
        total = len(store.list_runs(limit=1000))
    except Exception as exc:
        return dbc.Alert(f"加载历史回测失败: {exc}", color="danger")

    rows = _body_rows()
    if not rows:
        return html.Div(
            html.Div(
                [
                    html.H5("尚无保存的回测", className="text-muted"),
                    html.P("在左侧运行一次回测即会自动保存到数据库。"),
                ],
                className="text-center py-5",
            ),
            style={"minHeight": "50vh"},
        )

    return html.Div([
        html.Div([
            html.H4("历史回测", className="mb-1 d-inline-block"),
            html.Span(f" · 共 {total} 条", className="text-muted small ms-2"),
        ]),
        html.Hr(className="mt-2 mb-3"),
        html.Div(id="runs-delete-feedback", className="mb-2"),
        dbc.Card(
            dbc.CardBody(
                dbc.Table(
                    [_header_row(), html.Tbody(rows, id="runs-tbody")],
                    bordered=False, hover=True, striped=True, size="sm",
                    className="table-dark mb-0",
                )
            )
        ),
    ])


# ====================================================================
# 删除 run
# ====================================================================


@callback(
    Output("runs-delete-feedback", "children"),
    Output("runs-tbody", "children"),
    Input({"type": "delete-run-btn", "run_id": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def on_delete(n_clicks_list):
    # 未点击过任何按钮 (全部 None/0) → 忽略 (发生在新 tbody 渲染后)
    if not n_clicks_list or not any((n or 0) > 0 for n in n_clicks_list):
        return dash.no_update, dash.no_update

    triggered_id = dash.ctx.triggered_id
    if not isinstance(triggered_id, dict) or "run_id" not in triggered_id:
        return dash.no_update, dash.no_update
    try:
        rid = int(triggered_id["run_id"])
    except (TypeError, ValueError):
        return dash.no_update, dash.no_update

    try:
        store = get_default_store()
        store.delete(rid)
    except Exception as exc:
        return (
            dbc.Alert(f"删除 run_id={rid} 失败: {exc}", color="danger",
                      className="py-1 px-2 small mb-0"),
            dash.no_update,
        )

    # 同步清理内存缓存
    try:
        from qtrade.dashboard import app as _app
        _app._cache.pop(rid, None)
        if _app._cache.get("current_id") == rid:
            _app._cache.pop("current_id", None)
            _app._cache.pop("current", None)
    except Exception:
        pass

    return (
        dbc.Alert(f"已删除 run_id={rid}", color="success",
                  className="py-1 px-2 small mb-0"),
        _body_rows(),
    )
