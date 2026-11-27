"""复检授权领域服务。

内审巡查发现的缺陷需要复检办理权限，本服务按「目标缺陷 + 受理班组」签发复检授权条，
并围绕授权条管理实物领还、检查过程、班长交班与复查结论。

核心规则：
- 授权条只归属目标缺陷和受理班组，同一巡查下的另一条缺陷不会共享授权；
- 同一授权条同一时刻只有一个当前授权人，交班由班长发起并保留完整授权链；
- 一项复检只接收当前授权人的实际结论，非当前授权人（例如交班后的甲）提交被拒绝；
- 同一缺陷只有第一份「通过」结论成为有效关闭凭据，重复发起/重复提交不会生成第二份；
- 不合格处置关闭包装缺陷时，只能使用生效的复检通过凭据。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.base import BaseModuleService
from app.store import store

PASS_CONCLUSION = "通过"
FAIL_CONCLUSION = "不通过"
VALID_CONCLUSIONS = (PASS_CONCLUSION, FAIL_CONCLUSION)

STATUS_AUTHORIZED = "授权中"
STATUS_COMPLETED = "已完成"
STATUS_VOID = "已作废"

# 内置审查人名录（真实项目由账号与权限系统提供，这里用内存目录模拟账号/班组/资格）
BUILTIN_REVIEWERS: dict[str, dict[str, str]] = {
    "甲": {"班组": "包装一班", "资格": "包装复检资格", "角色": "审查人"},
    "乙": {"班组": "包装一班", "资格": "包装复检资格", "角色": "审查人"},
    "班长": {"班组": "包装一班", "资格": "班组管理权限", "角色": "班长"},
    "丙": {"班组": "仓储班", "资格": "仓储复检资格", "角色": "审查人"},
}

PACKAGE_TYPE_KEYWORDS = ("包装", "标签")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class ReinspectionService(BaseModuleService):
    MODULE = "reinspection"
    ENTITY = "复检授权条"
    OPERATION_TERM = "复检授权"
    LIST_FIELDS = ["目标缺陷ID", "受理班组", "当前授权人", "授权状态", "复查结论",
                   "实物领出人", "实物归还人", "登记编号", "备注说明"]
    REQUIRED_FIELDS: list[str] = []
    STATUS_ORDER = [STATUS_AUTHORIZED, STATUS_COMPLETED, STATUS_VOID]
    ACTION_RULES = {"作废授权": STATUS_VOID}
    NEGATIVE_ACTIONS: list[str] = []

    def __init__(self) -> None:
        # 账号 -> {班组, 资格, 角色}，模拟账号体系
        self._reviewers: dict[str, dict[str, str]] = {
            name: dict(info) for name, info in BUILTIN_REVIEWERS.items()
        }

    # ── 通用入口屏蔽：复检授权必须走专用接口，保证授权链与凭据规则不被绕过 ──

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        return None, ["复检授权条请使用 /api/reinspection/authorizations 专用入口办理"]

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        return None, "复检授权条不支持通用动作，请使用复检授权专用接口"

    # ── 审查人名录（账号/班组/资格）──

    def register_reviewer(self, reviewer: str, team: str,
                          qualification: str, role: str = "审查人") -> tuple[bool, str]:
        reviewer = str(reviewer).strip()
        team = str(team).strip()
        if not reviewer or not team:
            return False, "审查人账号与受理班组不能为空"
        self._reviewers[reviewer] = {"班组": team, "资格": qualification or "复检资格",
                                     "角色": role or "审查人"}
        return True, f"审查人 {reviewer} 已登记到 {team}"

    def list_reviewers(self) -> list[dict[str, str]]:
        return [{"账号": name, **info} for name, info in self._reviewers.items()]

    def _reviewer(self, name: str) -> dict[str, str] | None:
        info = self._reviewers.get(str(name).strip())
        return dict(info) if info else None

    # ── 查询 ──

    def list_authorizations(self, *, defect_id: int | None = None,
                            team: str | None = None,
                            status: str | None = None,
                            current_authorizer: str | None = None) -> list[dict[str, Any]]:
        rows = store.rows(self.MODULE)
        if defect_id is not None:
            rows = [r for r in rows if int(r.get("目标缺陷ID", 0)) == int(defect_id)]
        if team:
            rows = [r for r in rows if r.get("受理班组") == team]
        if status:
            rows = [r for r in rows if r.get("授权状态") == status]
        if current_authorizer:
            rows = [r for r in rows if r.get("当前授权人") == current_authorizer]
        return list(rows)

    def get_authorization(self, auth_id: int) -> dict[str, Any] | None:
        return store.find(self.MODULE, auth_id)

    def list_for_defect(self, defect_id: int) -> list[dict[str, Any]]:
        return self.list_authorizations(defect_id=int(defect_id))

    def get_credential_for_defect(self, defect_id: int) -> dict[str, Any] | None:
        """返回缺陷当前唯一生效的复检通过凭据；没有则 None。"""
        for row in store.rows(self.MODULE):
            if int(row.get("目标缺陷ID", 0)) == int(defect_id) and row.get("有效关闭凭据"):
                return row
        return None

    def has_effective_pass(self, defect_id: int) -> bool:
        return self.get_credential_for_defect(defect_id) is not None

    @staticmethod
    def is_packaging_defect(defect_entry: dict[str, Any]) -> bool:
        """包装类缺陷：缺陷类型或发现节点指向包装/标签环节。"""
        text = f"{defect_entry.get('缺陷类型', '')}{defect_entry.get('发现节点', '')}"
        return any(keyword in text for keyword in PACKAGE_TYPE_KEYWORDS)

    # ── 授权签发 ──

    def create_authorization(self, defect_id: int, team: str, reviewer: str,
                             operator: str | None = None) -> tuple[dict[str, Any] | None, str]:
        """按目标缺陷和受理班组签发复检授权条，权限不跨缺陷共享。"""
        defect = store.find("defect", int(defect_id))
        if defect is None:
            return None, f"目标缺陷 {defect_id} 不存在，无法签发复检授权"
        if defect.get("status") == "已撤回":
            return None, f"缺陷 {defect_id} 已撤回，不再受理复检"

        team = str(team).strip()
        reviewer = str(reviewer).strip()
        if not team or not reviewer:
            return None, "受理班组与被授权审查人不能为空"

        info = self._reviewer(reviewer)
        if info is None:
            return None, f"审查人 {reviewer} 没有复检账号，请先登记资格"
        if info["班组"] != team:
            return None, (f"审查人 {reviewer} 归属 {info['班组']}，"
                          f"不属于受理班组 {team}，不能授权")
        if info["角色"] == "班长":
            return None, "班长账号不承担复检办理，只能发起交班"

        rows = store.rows(self.MODULE)
        new_id = max((int(r.get("id", 0)) for r in rows), default=0) + 1
        entry: dict[str, Any] = {
            "id": new_id,
            "登记编号": f"REIN-{new_id:04d}",
            "目标缺陷ID": int(defect_id),
            "受理班组": team,
            "授权状态": STATUS_AUTHORIZED,
            "当前授权人": reviewer,
            "授权资格": info["资格"],
            "授权链": [{
                "顺序": 1,
                "审查人": reviewer,
                "资格": info["资格"],
                "班组": team,
                "操作": "授权",
                "操作人": operator or "系统",
                "时间": _now(),
            }],
            # 实物 custody
            "实物领出人": None,
            "领出时间": None,
            "实物在外": False,
            "实物归还人": None,
            "归还时间": None,
            # 检查过程与结论
            "检查过程": [],
            "复查结论": None,
            "结论签发人": None,
            "结论签发资格": None,
            "结论时间": None,
            "有效关闭凭据": False,
            "备注说明": "",
        }
        rows.append(entry)
        store.log_event(self.MODULE, new_id, "授权签发",
                        {"defect_id": int(defect_id), "team": team, "reviewer": reviewer,
                         "operator": operator})
        return entry, f"复检授权条 {entry['登记编号']} 已签发，当前授权人：{reviewer}"

    # ── 班长交班 ──

    def handover(self, auth_id: int, to_reviewer: str,
                 operator: str) -> tuple[dict[str, Any] | None, str]:
        """班长在当前授权人签结论前发起交班，授权链保留交班痕迹。"""
        entry = store.find(self.MODULE, auth_id)
        if entry is None:
            return None, f"复检授权条 {auth_id} 不存在"
        if entry.get("授权状态") != STATUS_AUTHORIZED:
            return None, f"授权条已{entry.get('授权状态')}，不能再交班"

        leader = self._reviewer(operator)
        if leader is None or leader.get("角色") != "班长":
            return None, "只有班长账号可以发起交班申请"
        if leader["班组"] != entry.get("受理班组"):
            return None, "班长不属于该授权条的受理班组，无权交班"

        target = self._reviewer(to_reviewer)
        if target is None:
            return None, f"审查人 {to_reviewer} 没有复检账号"
        if target["班组"] != entry.get("受理班组"):
            return None, f"审查人 {to_reviewer} 不属于受理班组 {entry['受理班组']}"
        if target["角色"] == "班长":
            return None, "班长账号不能作为复检办理人"
        if to_reviewer == entry.get("当前授权人"):
            return None, f"{to_reviewer} 已是当前授权人，无需交班"

        chain: list[dict[str, Any]] = entry["授权链"]
        chain.append({
            "顺序": len(chain) + 1,
            "审查人": to_reviewer,
            "资格": target["资格"],
            "班组": target["班组"],
            "操作": "交班",
            "操作人": operator,
            "时间": _now(),
        })
        previous = entry["当前授权人"]
        entry["当前授权人"] = to_reviewer
        store.log_event(self.MODULE, auth_id, "交班",
                        {"from": previous, "to": to_reviewer, "operator": operator})
        return entry, f"授权已由 {previous} 交班给 {to_reviewer}，实物领出状态保持不变"

    # ── 实物领还 ──

    def checkout_physical(self, auth_id: int,
                          operator: str) -> tuple[dict[str, Any] | None, str]:
        """当前授权人凭授权领出实物。"""
        entry = store.find(self.MODULE, auth_id)
        if entry is None:
            return None, f"复检授权条 {auth_id} 不存在"
        if entry.get("授权状态") != STATUS_AUTHORIZED:
            return None, f"授权条已{entry.get('授权状态')}，不能领出实物"
        if operator != entry.get("当前授权人"):
            return None, (f"只有当前授权人 {entry.get('当前授权人')} 可以领出实物，"
                          f"{operator} 无权办理")
        if entry.get("实物在外"):
            return entry, f"实物已由 {entry.get('实物领出人')} 领出且尚未归还，无需重复领出"

        entry["实物领出人"] = operator
        entry["领出时间"] = _now()
        entry["实物在外"] = True
        store.log_event(self.MODULE, auth_id, "实物领出", {"operator": operator})
        return entry, f"{operator} 已凭授权领出实物"

    def return_physical(self, auth_id: int,
                        operator: str) -> tuple[dict[str, Any] | None, str]:
        """归还实物，记录实际归还人。"""
        entry = store.find(self.MODULE, auth_id)
        if entry is None:
            return None, f"复检授权条 {auth_id} 不存在"
        if not entry.get("实物在外"):
            return entry, "实物当前不在外，无需归还"
        entry["实物在外"] = False
        entry["实物归还人"] = operator
        entry["归还时间"] = _now()
        store.log_event(self.MODULE, auth_id, "实物归还",
                        {"operator": operator, "领出人": entry.get("实物领出人")})
        return entry, f"实物已由 {operator} 归还（原领出人：{entry.get('实物领出人')}）"

    # ── 检查过程 ──

    def add_inspection_note(self, auth_id: int, operator: str,
                            note: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(self.MODULE, auth_id)
        if entry is None:
            return None, f"复检授权条 {auth_id} 不存在"
        if entry.get("授权状态") != STATUS_AUTHORIZED:
            return None, f"授权条已{entry.get('授权状态')}，不能再补检查记录"
        if operator != entry.get("当前授权人"):
            return None, f"只有当前授权人 {entry.get('当前授权人')} 可以记录检查过程"
        if not entry.get("实物在外"):
            return None, "请先凭授权领出实物，再记录检查过程"
        if not str(note).strip():
            return None, "检查过程记录不能为空"
        entry["检查过程"].append({"记录人": operator, "时间": _now(), "内容": str(note).strip()})
        store.log_event(self.MODULE, auth_id, "检查记录", {"operator": operator})
        return entry, "检查过程已记录"

    # ── 复查结论 ──

    def submit_conclusion(self, auth_id: int, operator: str,
                          conclusion: str) -> tuple[dict[str, Any] | None, str]:
        """一项复检只接收当前授权人的一份实际结论。"""
        entry = store.find(self.MODULE, auth_id)
        if entry is None:
            return None, f"复检授权条 {auth_id} 不存在"
        if entry.get("授权状态") == STATUS_COMPLETED:
            # 重复提交：原样返回既有结论，不生成第二份关闭记录
            return entry, (f"该复检已由 {entry.get('结论签发人')} 办理完成，"
                           "重复提交不生成另一份关闭记录")
        if entry.get("授权状态") != STATUS_AUTHORIZED:
            return None, f"授权条已{entry.get('授权状态')}，不能提交结论"
        if operator != entry.get("当前授权人"):
            return None, (f"一项复检只接收当前授权人的实际结论："
                          f"当前授权人为 {entry.get('当前授权人')}，{operator} 的提交被拒绝")
        if conclusion not in VALID_CONCLUSIONS:
            return None, f"复查结论只能是 {VALID_CONCLUSIONS} 之一"
        if not entry.get("实物在外") and not entry.get("实物领出人"):
            return None, "尚未发生实物领出，不能签发复检结论"
        if not entry.get("检查过程"):
            return None, "缺少检查过程记录，不能签发复检结论"

        info = self._reviewer(operator) or {}
        entry["复查结论"] = conclusion
        entry["结论签发人"] = operator
        entry["结论签发资格"] = info.get("资格", entry.get("授权资格"))
        entry["结论时间"] = _now()
        entry["授权状态"] = STATUS_COMPLETED

        # 同一缺陷只允许第一份通过结论成为有效关闭凭据
        already_effective = self.has_effective_pass(int(entry["目标缺陷ID"]))
        if conclusion == PASS_CONCLUSION and not already_effective:
            entry["有效关闭凭据"] = True
            credential_msg = "已成为该缺陷的有效关闭凭据"
        elif conclusion == PASS_CONCLUSION:
            entry["有效关闭凭据"] = False
            credential_msg = "该缺陷已有生效通过凭据，本次结论仅留档，不生成另一份有效关闭记录"
        else:
            entry["有效关闭凭据"] = False
            credential_msg = "结论为不通过，不能作为关闭凭据"

        # 结论签发时实物仍在外的，随结论归还，实际归还人留痕
        if entry.get("实物在外"):
            entry["实物在外"] = False
            entry["实物归还人"] = operator
            entry["归还时间"] = _now()

        store.log_event(self.MODULE, auth_id, "复查结论",
                        {"operator": operator, "conclusion": conclusion,
                         "effective": entry["有效关闭凭据"]})
        return entry, f"{operator} 的「{conclusion}」结论已记录，{credential_msg}"

    # ── 作废 ──

    def void_authorization(self, auth_id: int,
                           operator: str | None = None) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(self.MODULE, auth_id)
        if entry is None:
            return None, f"复检授权条 {auth_id} 不存在"
        if entry.get("授权状态") != STATUS_AUTHORIZED:
            return None, f"授权条已{entry.get('授权状态')}，不能作废"
        entry["授权状态"] = STATUS_VOID
        store.log_event(self.MODULE, auth_id, "作废授权", {"operator": operator})
        return entry, f"复检授权条 {entry.get('登记编号')} 已作废"

    # ── 凭据快照（供不合格处置关闭时核对）──

    def credential_snapshot(self, defect_id: int) -> dict[str, Any] | None:
        cred = self.get_credential_for_defect(defect_id)
        if cred is None:
            return None
        return {
            "授权条ID": cred["id"],
            "登记编号": cred.get("登记编号"),
            "受理班组": cred.get("受理班组"),
            "结论签发人": cred.get("结论签发人"),
            "结论签发资格": cred.get("结论签发资格"),
            "复查结论": cred.get("复查结论"),
            "结论时间": cred.get("结论时间"),
            "实物领出人": cred.get("实物领出人"),
            "实物归还人": cred.get("实物归还人"),
            "归还时间": cred.get("归还时间"),
        }


# 领域服务单例，与其他模块的服务注册方式保持一致
reinspection = ReinspectionService()
