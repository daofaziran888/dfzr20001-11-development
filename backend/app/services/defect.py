"""不合格处置领域服务：记录缺陷、触发冻结、关联发现节点与处置方式。

关闭规则与复检授权联动：
- 包装类缺陷没有生效的复检通过凭据时，不允许关闭；
- 关闭时把生效凭据（结论签发人、资格、实物领出/归还人）固化到缺陷上，便于重新打开后核对；
- 已关闭缺陷可重新打开为草稿，历史凭据保留可查，重复复检不会产生第二份有效关闭记录。
"""
from __future__ import annotations
from typing import Any
from app.services.base import BaseModuleService
from app.store import store

class DefectService(BaseModuleService):
    MODULE = "defect"
    ENTITY = "缺陷记录"
    OPERATION_TERM = "关闭缺陷"
    LIST_FIELDS = ["缺陷类型", "发现节点", "处置方式", "责任人", "登记编号", "负责人", "生效版本", "备注说明"]
    REQUIRED_FIELDS = ["缺陷类型", "发现节点", "处置方式", "责任人"]
    STATUS_ORDER = ["草稿", "待确认", "已确认", "已撤回"]
    ACTION_RULES = {"关闭缺陷": "已确认", "提交确认": "待确认", "撤回记录": "已撤回"}
    NEGATIVE_ACTIONS = []

    VALID_DEFECT_TYPES = ["农残超标", "含水率不合格", "外形缺陷", "异味污染", "包装破损",
                          "标签错误", "重量不足", "霉菌污染", "异物混入", "仓储条件不达标"]

    def validate_entry(self, values: dict[str, Any]) -> list[str]:
        errors = []
        dtype = values.get("缺陷类型", "")
        if dtype not in self.VALID_DEFECT_TYPES:
            pass  # 允许自定义缺陷类型
        # 校验发现节点对应的工序记录存在
        process_module = values.get("process_module")
        process_entry_id = values.get("process_entry_id")
        if process_module and process_entry_id is not None:
            process_entry = store.find(process_module, int(process_entry_id))
            if process_entry is None:
                errors.append(f"发现节点工序记录 {process_module}/{process_entry_id} 不存在")
        return errors

    def on_confirm(self, entry: dict[str, Any], action: str) -> tuple[bool, str | None]:
        """不合格处置确认时，自动冻结同批次发现节点之后的下游记录。"""
        if action == "关闭缺陷":
            # 包装类缺陷必须持有生效的复检通过凭据
            from app.services.reinspection import reinspection as rs
            if rs.is_packaging_defect(entry):
                snapshot = rs.credential_snapshot(int(entry["id"]))
                if snapshot is None:
                    return False, ("包装缺陷没有任何有效复检凭据，不能关闭；"
                                   "请先由内审巡查签发复检授权并取得「通过」结论")
                entry["复检关闭凭据"] = snapshot

            batch_no = entry.get("批次号", "")
            reason = entry.get("缺陷类型", "不合格")
            discovered = entry.get("发现节点", "")
            if batch_no and discovered:
                from app.services.pipeline import pipeline as pl
                count, keys = pl.freeze_batch_downstream(batch_no, int(entry["id"]), reason)
                entry["冻结记录数"] = count
        return True, None

    def reopen_defect(self, defect_id: int,
                      operator: str | None = None) -> tuple[dict[str, Any] | None, str]:
        """重新打开已关闭的缺陷为草稿，保留当时的复检凭据与操作责任人供核对。"""
        entry = store.find(self.MODULE, defect_id)
        if entry is None:
            return None, f"缺陷记录 {defect_id} 不存在或已归档"
        if entry.get("status") != "已确认":
            return None, f"缺陷当前状态为「{entry.get('status')}」，只有已关闭缺陷可以重新打开"

        previous_credential = entry.get("复检关闭凭据")
        history: list[dict[str, Any]] = entry.setdefault("关闭凭据历史", [])
        if previous_credential and previous_credential not in history:
            history.append(dict(previous_credential))

        entry["status"] = "草稿"
        entry["pending"] = True
        store.log_event(self.MODULE, defect_id, "重新打开",
                        {"operator": operator, "保留凭据编号":
                            previous_credential.get("登记编号") if previous_credential else None})
        return entry, ("缺陷已重新打开为草稿，原复检凭据保留可查；"
                       "重复发起复检不会生成另一份有效关闭记录")

    def get_defects_by_batch(self, batch_no: str) -> list[dict[str, Any]]:
        """获取指定批次的不合格处置记录。"""
        rows = store.rows(self.MODULE)
        return [r for r in rows if r.get("批次号") == batch_no]

    def get_open_defects(self) -> list[dict[str, Any]]:
        """获取所有未关闭的缺陷记录。"""
        return [r for r in store.rows(self.MODULE) if r.get("status") != "已确认"]

    def get_defects_by_node(self, process_module: str, process_entry_id: int) -> list[dict[str, Any]]:
        """获取关联到指定工序的不合格处置记录。"""
        rows = store.rows(self.MODULE)
        node_str = str(process_entry_id)
        return [r for r in rows
                if process_module in str(r.get("发现节点", ""))
                and node_str in str(r.get("发现节点", ""))]

    def get_frozen_records(self, batch_no: str) -> list[dict[str, Any]]:
        """获取批次中被冻结的记录。"""
        lineage = store.get_batch_lineage_nodes(batch_no)
        frozen = []
        for node in lineage:
            if store.is_frozen(node["module"], node["entry_id"]):
                row = store.find(node["module"], node["entry_id"])
                if row:
                    frozen.append(row)
        return frozen
