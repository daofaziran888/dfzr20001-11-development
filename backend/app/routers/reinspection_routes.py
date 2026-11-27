"""复检授权专用路由：授权签发、班长交班、实物领还、检查过程、复查结论与缺陷重开。

全部写操作都要求携带操作账号（operator，模拟登录态），领域服务据此判定当前授权人、
班长资格与受理班组归属。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from app.services import service_for
from app.services.reinspection import reinspection

router = APIRouter(prefix="/api/reinspection", tags=["复检授权"])


class OperatorPayload(BaseModel):
    operator: str = ""


class AuthorizePayload(BaseModel):
    defect_id: int
    team: str
    reviewer: str
    operator: str = ""


class HandoverPayload(BaseModel):
    to_reviewer: str
    operator: str


class NotePayload(BaseModel):
    operator: str
    note: str


class ConclusionPayload(BaseModel):
    operator: str
    conclusion: str


class ReviewerPayload(BaseModel):
    reviewer: str
    team: str
    qualification: str = "复检资格"
    role: str = "审查人"


def _unwrap(result: tuple[dict[str, Any] | None, str]) -> dict[str, Any]:
    entry, message = result
    return {"ok": entry is not None, "message": message, "entry": entry}


@router.get("/authorizations")
def list_authorizations(
    defect_id: int | None = None,
    team: str | None = None,
    status: str | None = None,
    current_authorizer: str | None = None,
) -> dict[str, Any]:
    items = reinspection.list_authorizations(
        defect_id=defect_id, team=team, status=status,
        current_authorizer=current_authorizer)
    return {"ok": True, "items": items, "total": len(items)}


@router.get("/authorizations/{auth_id}")
def get_authorization(auth_id: int) -> dict[str, Any]:
    """重新打开已办理复检的核对入口：返回授权链、资格快照、检查过程与实物领还责任。"""
    entry = reinspection.get_authorization(auth_id)
    if entry is None:
        return {"ok": False, "message": f"复检授权条 {auth_id} 不存在", "entry": None}
    return {"ok": True, "message": "复检记录（含当时资格与操作责任人）", "entry": entry}


@router.get("/defects/{defect_id}/credential")
def get_defect_credential(defect_id: int) -> dict[str, Any]:
    snapshot = reinspection.credential_snapshot(defect_id)
    if snapshot is None:
        return {"ok": False, "message": "该缺陷暂无生效的复检通过凭据", "credential": None}
    return {"ok": True, "message": "生效复检凭据", "credential": snapshot}


@router.post("/authorizations")
def create_authorization(payload: AuthorizePayload) -> dict[str, Any]:
    return _unwrap(reinspection.create_authorization(
        payload.defect_id, payload.team, payload.reviewer, payload.operator))


@router.post("/authorizations/{auth_id}/handover")
def handover(auth_id: int, payload: HandoverPayload) -> dict[str, Any]:
    return _unwrap(reinspection.handover(auth_id, payload.to_reviewer, payload.operator))


@router.post("/authorizations/{auth_id}/checkout")
def checkout(auth_id: int, payload: OperatorPayload) -> dict[str, Any]:
    return _unwrap(reinspection.checkout_physical(auth_id, payload.operator))


@router.post("/authorizations/{auth_id}/return")
def return_physical(auth_id: int, payload: OperatorPayload) -> dict[str, Any]:
    return _unwrap(reinspection.return_physical(auth_id, payload.operator))


@router.post("/authorizations/{auth_id}/notes")
def add_note(auth_id: int, payload: NotePayload) -> dict[str, Any]:
    return _unwrap(reinspection.add_inspection_note(
        auth_id, payload.operator, payload.note))


@router.post("/authorizations/{auth_id}/conclusion")
def submit_conclusion(auth_id: int, payload: ConclusionPayload) -> dict[str, Any]:
    return _unwrap(reinspection.submit_conclusion(
        auth_id, payload.operator, payload.conclusion))


@router.post("/authorizations/{auth_id}/void")
def void_authorization(auth_id: int, payload: OperatorPayload) -> dict[str, Any]:
    return _unwrap(reinspection.void_authorization(auth_id, payload.operator))


@router.get("/reviewers")
def list_reviewers() -> dict[str, Any]:
    return {"ok": True, "items": reinspection.list_reviewers()}


@router.post("/reviewers")
def register_reviewer(payload: ReviewerPayload) -> dict[str, Any]:
    ok, message = reinspection.register_reviewer(
        payload.reviewer, payload.team, payload.qualification, payload.role)
    return {"ok": ok, "message": message}


@router.post("/defects/{defect_id}/reopen")
def reopen_defect(defect_id: int, payload: OperatorPayload) -> dict[str, Any]:
    """不合格处置侧重新打开缺陷草稿，历史复检凭据保留可查。"""
    service = service_for("defect")
    return _unwrap(service.reopen_defect(defect_id, payload.operator))
