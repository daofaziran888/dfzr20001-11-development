"""业务路由汇总：所有模块共用一套资源路由，流水线路由独立注册。"""
from __future__ import annotations

from app.routers import resource, pipeline_routes, reinspection_routes

# 复检授权的专用路径必须先于资源路由的 /{module}/{entry_id} 通配规则注册，
# 否则 /api/reinspection/authorizations 会被资源路由截获。
ROUTERS = [reinspection_routes, resource, pipeline_routes]