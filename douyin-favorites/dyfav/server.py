"""FastAPI 接口 + 静态卡片流界面。"""
from __future__ import annotations

import base64

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db
from .config import STATIC_DIR, categories, server_config

app = FastAPI(title="抖音收藏盒")


@app.middleware("http")
async def basic_auth_gate(request: Request, call_next):  # noqa: ANN201
    """admin 设 share_password 后：公网访问要密码；本机与家庭局域网免密直通。"""
    password = str(server_config().get("share_password", "")).strip()
    if password:
        # 无头云隧道转发回来的请求，客户端地址是 127.0.0.1 但必然带真实来源头，
        # 用它识别"公网访客"；本机/局域网(192.168.*)直连则免密。
        via_tunnel = bool(request.headers.get("CF-Connecting-IP"))
        client_ip = request.client.host if request.client else ""
        is_local = client_ip in ("127.0.0.1", "::1") or client_ip.startswith("192.168.")
        if via_tunnel or not is_local:
            token = "Basic " + base64.b64encode(f"user:{password}".encode()).decode()
            if request.headers.get("Authorization", "") != token:
                return Response(
                    status_code=401,
                    headers={"WWW-Authenticate": 'Basic realm="fav", charset="UTF-8"'},
                )
    return await call_next(request)


class LabelsIn(BaseModel):
    labels: list[str]


@app.get("/api/items")
def api_items(
    type_: str | None = Query(None, alias="type"),
    label: str | None = Query(None),
    q: str | None = Query(None),
    limit: int = Query(60, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    items = db.list_items(category=type_, label=label, q=q, limit=limit, offset=offset)
    return {"items": items}


@app.get("/api/stats")
def api_stats():
    return db.stats()


@app.get("/api/categories")
def api_categories():
    return categories()


@app.post("/api/items/{aweme_id}/labels")
def api_set_labels(aweme_id: str, body: LabelsIn):
    ok = db.manual_labels(aweme_id, body.labels)
    if not ok:
        raise HTTPException(status_code=404, detail="条目不存在")
    return {"ok": True}


# 静态页面要放在 API 路由之后挂载，否则 "/" 会吞掉 /api
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
