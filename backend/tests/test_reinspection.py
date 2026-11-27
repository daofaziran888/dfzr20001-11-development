"""复检授权端到端业务测试。

对应业务场景：
- 内审巡查按「目标缺陷 + 受理班组」签发复检授权条，授权不跨缺陷共享；
- 同一包装缺陷两个审查人：甲领出实物并记录检查过程，班长在甲签结论前交班给乙；
- 一项复检只接收当前授权人的实际结论，甲乙同时（分别）提交时只有乙能签入；
- 不合格处置只能凭生效的复检「通过」凭据关闭包装缺陷；
- 重新打开已办理复检/缺陷后可核对当时资格与操作责任人，重复发起不产生第二份有效凭据；
- 重新打开缺陷草稿再关闭时，系统沿用既有凭据，并能核对原实物归还人；
- 未移交的仓储缺陷不要求复检凭据，照常办理；
- 没有任何有效复检凭据时包装缺陷无法关闭。
"""
from __future__ import annotations

import unittest

from app.services import service_for
from app.services.reinspection import (
    PASS_CONCLUSION,
    FAIL_CONCLUSION,
    STATUS_AUTHORIZED,
    STATUS_COMPLETED,
    reinspection,
)


def _create_defect(defect_type: str, node: str) -> dict:
    svc = service_for("defect")
    entry, errors = svc.create_entry({
        "缺陷类型": defect_type,
        "发现节点": node,
        "处置方式": "待复检后处置",
        "责任人": "品控员",
    })
    assert entry is not None, errors
    return entry


class ReinspectionAuthorizationTest(unittest.TestCase):
    """授权签发的归属与权限边界。"""

    def setUp(self) -> None:
        self.packaging = _create_defect("包装破损", "包装工序")
        self.storage = _create_defect("仓储条件不达标", "仓储养护")

    def test_authorization_binds_to_target_defect_and_team(self):
        entry, msg = reinspection.create_authorization(
            int(self.packaging["id"]), "包装一班", "甲")
        self.assertIsNotNone(entry, msg)
        self.assertEqual(entry["目标缺陷ID"], int(self.packaging["id"]))
        self.assertEqual(entry["受理班组"], "包装一班")
        self.assertEqual(entry["当前授权人"], "甲")
        self.assertEqual(entry["授权状态"], STATUS_AUTHORIZED)
        # 授权链保留签发时资格快照，供事后核对当时资格
        self.assertEqual(entry["授权链"][0]["资格"], "包装复检资格")

    def test_authorization_not_shared_with_another_defect_of_same_audit(self):
        """同一巡查的另一条缺陷不能共享本缺陷的授权条。"""
        entry, _ = reinspection.create_authorization(
            int(self.packaging["id"]), "包装一班", "甲")
        self.assertIsNotNone(entry)
        # 另一条仓储缺陷查不到任何授权
        self.assertEqual(reinspection.list_for_defect(int(self.storage["id"])), [])
        self.assertIsNone(reinspection.get_credential_for_defect(int(self.storage["id"])))

    def test_reviewer_outside_team_cannot_be_authorized(self):
        # 丙属于仓储班，不能受理包装一班的缺陷
        entry, msg = reinspection.create_authorization(
            int(self.packaging["id"]), "包装一班", "丙")
        self.assertIsNone(entry)
        self.assertIn("不属于受理班组", msg)

    def test_unknown_reviewer_and_leader_role_rejected(self):
        entry, msg = reinspection.create_authorization(
            int(self.packaging["id"]), "包装一班", "临时工")
        self.assertIsNone(entry)
        self.assertIn("没有复检账号", msg)

        entry, msg = reinspection.create_authorization(
            int(self.packaging["id"]), "包装一班", "班长")
        self.assertIsNone(entry)
        self.assertIn("班长账号", msg)

    def test_generic_create_entry_is_blocked(self):
        svc = service_for("reinspection")
        entry, errors = svc.create_entry({"目标缺陷ID": 1})
        self.assertIsNone(entry)
        self.assertTrue(any("专用入口" in e for e in errors))


class HandoverAndConclusionTest(unittest.TestCase):
    """交班、实物领还、检查过程与结论签入的完整链路。"""

    def setUp(self) -> None:
        self.packaging = _create_defect("包装破损", "包装工序")
        self.auth, msg = reinspection.create_authorization(
            int(self.packaging["id"]), "包装一班", "甲")
        self.assertIsNotNone(self.auth, msg)
        self.auth_id = int(self.auth["id"])

    def test_full_handover_flow_only_current_authorizer_concludes(self):
        # 甲凭授权领出实物并记录检查过程
        entry, msg = reinspection.checkout_physical(self.auth_id, "甲")
        self.assertIsNotNone(entry, msg)
        self.assertEqual(entry["实物领出人"], "甲")
        self.assertTrue(entry["实物在外"])

        entry, msg = reinspection.add_inspection_note(self.auth_id, "甲", "外箱封口开裂检查")
        self.assertIsNotNone(entry, msg)
        self.assertEqual(len(entry["检查过程"]), 1)

        # 非当前授权人不能领出/记录
        entry, msg = reinspection.checkout_physical(self.auth_id, "乙")
        self.assertIsNone(entry)
        entry, msg = reinspection.add_inspection_note(self.auth_id, "乙", "乙的检查")
        self.assertIsNone(entry)

        # 班长在甲签结论前交班给乙（同班组）
        entry, msg = reinspection.handover(self.auth_id, "乙", "班长")
        self.assertIsNotNone(entry, msg)
        self.assertEqual(entry["当前授权人"], "乙")
        self.assertEqual(len(entry["授权链"]), 2)
        self.assertEqual(entry["授权链"][1]["操作"], "交班")
        # 交班不改变实物 custody：仍是甲领出、实物在外
        self.assertEqual(entry["实物领出人"], "甲")
        self.assertTrue(entry["实物在外"])

        # 甲已经不是当前授权人，其结论提交被拒绝（模拟甲账号并发提交）
        entry, msg = reinspection.submit_conclusion(self.auth_id, "甲", PASS_CONCLUSION)
        self.assertIsNone(entry)
        self.assertIn("当前授权人", msg)
        # 被拒绝后授权仍处于授权中，未被甲签入
        self.assertEqual(reinspection.get_authorization(self.auth_id)["授权状态"],
                         STATUS_AUTHORIZED)

        # 乙作为当前授权人补记检查并签入通过结论
        entry, msg = reinspection.add_inspection_note(self.auth_id, "乙", "乙复核封口修复情况")
        self.assertIsNotNone(entry, msg)
        entry, msg = reinspection.submit_conclusion(self.auth_id, "乙", PASS_CONCLUSION)
        self.assertIsNotNone(entry, msg)
        self.assertEqual(entry["授权状态"], STATUS_COMPLETED)
        self.assertEqual(entry["结论签发人"], "乙")
        self.assertEqual(entry["复查结论"], PASS_CONCLUSION)
        self.assertTrue(entry["有效关闭凭据"])
        # 结论签入时实物随结论归还，实际归还人是乙，原领出人仍是甲
        self.assertFalse(entry["实物在外"])
        self.assertEqual(entry["实物领出人"], "甲")
        self.assertEqual(entry["实物归还人"], "乙")

    def test_conclusion_requires_checkout_and_notes(self):
        # 没领实物、没检查过程不能签结论
        entry, msg = reinspection.submit_conclusion(self.auth_id, "甲", PASS_CONCLUSION)
        self.assertIsNone(entry)
        self.assertIn("实物领出", msg)

        reinspection.checkout_physical(self.auth_id, "甲")
        entry, msg = reinspection.submit_conclusion(self.auth_id, "甲", PASS_CONCLUSION)
        self.assertIsNone(entry)
        self.assertIn("检查过程", msg)

    def test_fail_conclusion_is_not_a_closing_credential(self):
        reinspection.checkout_physical(self.auth_id, "甲")
        reinspection.add_inspection_note(self.auth_id, "甲", "复检仍不达标")
        entry, msg = reinspection.submit_conclusion(self.auth_id, "甲", FAIL_CONCLUSION)
        self.assertIsNotNone(entry, msg)
        self.assertFalse(entry["有效关闭凭据"])
        self.assertIsNone(reinspection.get_credential_for_defect(int(self.packaging["id"])))

    def test_concurrent_submissions_from_two_accounts_only_one_accepted(self):
        """甲乙不同账号同时提交复查请求：交班后只有乙（当前授权人）能签入。"""
        reinspection.checkout_physical(self.auth_id, "甲")
        reinspection.add_inspection_note(self.auth_id, "甲", "初检记录")
        reinspection.handover(self.auth_id, "乙", "班长")

        # 两个账号先后（等价于并发竞争）提交，甲被拒、乙成功
        rejected, reject_msg = reinspection.submit_conclusion(
            self.auth_id, "甲", PASS_CONCLUSION)
        accepted, ok_msg = reinspection.submit_conclusion(
            self.auth_id, "乙", PASS_CONCLUSION)
        self.assertIsNone(rejected)
        self.assertIsNotNone(accepted)
        self.assertEqual(accepted["结论签发人"], "乙")
        self.assertTrue(accepted["有效关闭凭据"])

        # 乙再重复提交，不生成另一份关闭记录
        again, again_msg = reinspection.submit_conclusion(
            self.auth_id, "乙", PASS_CONCLUSION)
        self.assertIsNotNone(again)
        self.assertIn("不生成另一份", again_msg)
        self.assertEqual(again["结论时间"], accepted["结论时间"])


class CredentialAndDefectClosureTest(unittest.TestCase):
    """复检凭据与不合格处置关闭规则的联动。"""

    def setUp(self) -> None:
        self.defect_svc = service_for("defect")
        self.packaging = _create_defect("包装破损", "包装工序")
        self.storage = _create_defect("仓储条件不达标", "仓储养护")
        self.defect_id = int(self.packaging["id"])

    def _pass_reinspection(self, defect_id: int, reviewer: str = "甲") -> dict:
        auth, msg = reinspection.create_authorization(defect_id, "包装一班", reviewer)
        assert auth is not None, msg
        auth_id = int(auth["id"])
        reinspection.checkout_physical(auth_id, reviewer)
        reinspection.add_inspection_note(auth_id, reviewer, "复检检查过程")
        entry, msg = reinspection.submit_conclusion(auth_id, reviewer, PASS_CONCLUSION)
        assert entry is not None, msg
        return entry

    def test_packaging_defect_cannot_close_without_effective_credential(self):
        entry, msg = self.defect_svc.run_action(self.defect_id, "关闭缺陷")
        self.assertIsNone(entry)
        self.assertIn("没有任何有效复检凭据", msg)
        # 缺陷仍是草稿，未被关闭
        self.assertEqual(self.defect_svc.get_entry(self.defect_id)["status"], "草稿")

    def test_packaging_defect_closes_with_effective_pass_credential(self):
        cred = self._pass_reinspection(self.defect_id)
        entry, msg = self.defect_svc.run_action(self.defect_id, "关闭缺陷")
        self.assertIsNotNone(entry, msg)
        self.assertEqual(entry["status"], "已确认")
        snapshot = entry["复检关闭凭据"]
        self.assertEqual(snapshot["授权条ID"], cred["id"])
        self.assertEqual(snapshot["复查结论"], PASS_CONCLUSION)
        self.assertEqual(snapshot["结论签发人"], "甲")
        self.assertEqual(snapshot["实物领出人"], "甲")
        self.assertEqual(snapshot["实物归还人"], "甲")

    def test_reopen_then_close_uses_existing_credential_and_keeps_responsibility(self):
        """重新打开缺陷草稿后再关闭：沿用谁的结论、原实物由谁归还都可核对。"""
        self._pass_reinspection(self.defect_id)
        closed, _ = self.defect_svc.run_action(self.defect_id, "关闭缺陷")
        self.assertEqual(closed["status"], "已确认")

        # 重新打开为草稿，凭据历史保留
        reopened, msg = self.defect_svc.reopen_defect(self.defect_id, "品控主管")
        self.assertIsNotNone(reopened, msg)
        self.assertEqual(reopened["status"], "草稿")
        self.assertEqual(reopened["关闭凭据历史"][0]["结论签发人"], "甲")
        self.assertEqual(reopened["关闭凭据历史"][0]["实物归还人"], "甲")

        # 重新打开已办理的复检：授权链/资格/责任人均可核对
        auth_id = reopened["关闭凭据历史"][0]["授权条ID"]
        record = reinspection.get_authorization(auth_id)
        self.assertEqual(record["结论签发资格"], "包装复检资格")
        self.assertEqual(record["授权链"][0]["审查人"], "甲")
        self.assertEqual(record["实物领出人"], "甲")
        self.assertEqual(record["实物归还人"], "甲")

        # 再发起一次复检并通过，也不会产生第二份有效关闭记录
        second, s_msg = reinspection.create_authorization(
            self.defect_id, "包装一班", "乙")
        self.assertIsNotNone(second)
        second_id = int(second["id"])
        reinspection.checkout_physical(second_id, "乙")
        reinspection.add_inspection_note(second_id, "乙", "再次复检")
        second_done, _ = reinspection.submit_conclusion(second_id, "乙", PASS_CONCLUSION)
        self.assertFalse(second_done["有效关闭凭据"])
        # 唯一生效凭据仍来自甲的第一份
        effective = reinspection.get_credential_for_defect(self.defect_id)
        self.assertEqual(effective["结论签发人"], "甲")

        # 重新关闭仍使用甲的生效结论，原实物归还人仍可核对
        closed_again, msg = self.defect_svc.run_action(self.defect_id, "关闭缺陷")
        self.assertIsNotNone(closed_again, msg)
        self.assertEqual(closed_again["复检关闭凭据"]["结论签发人"], "甲")
        self.assertEqual(closed_again["复检关闭凭据"]["实物归还人"], "甲")

    def test_handover_reopen_shows_yi_conclusion_and_jia_returned_physical_origin(self):
        """交班场景重开：系统使用乙的复检结论，原实物领出人是甲、归还人是乙。"""
        auth, _ = reinspection.create_authorization(self.defect_id, "包装一班", "甲")
        auth_id = int(auth["id"])
        reinspection.checkout_physical(auth_id, "甲")
        reinspection.add_inspection_note(auth_id, "甲", "初检")
        reinspection.handover(auth_id, "乙", "班长")
        reinspection.add_inspection_note(auth_id, "乙", "复核")
        reinspection.submit_conclusion(auth_id, "乙", PASS_CONCLUSION)

        self.defect_svc.run_action(self.defect_id, "关闭缺陷")
        snapshot = self.defect_svc.get_entry(self.defect_id)["复检关闭凭据"]
        self.assertEqual(snapshot["结论签发人"], "乙")
        self.assertEqual(snapshot["实物领出人"], "甲")
        self.assertEqual(snapshot["实物归还人"], "乙")

        reopened, _ = self.defect_svc.reopen_defect(self.defect_id, "主管")
        self.assertEqual(reopened["关闭凭据历史"][0]["结论签发人"], "乙")
        self.assertEqual(reopened["关闭凭据历史"][0]["实物领出人"], "甲")

    def test_non_transferred_storage_defect_closes_normally_without_credential(self):
        """另一条未移交的仓储缺陷照常办理，不强制复检凭据。"""
        self.assertFalse(reinspection.is_packaging_defect(self.storage))
        entry, msg = self.defect_svc.run_action(int(self.storage["id"]), "关闭缺陷")
        self.assertIsNotNone(entry, msg)
        self.assertEqual(entry["status"], "已确认")
        self.assertNotIn("复检关闭凭据", entry)

    def test_only_draft_or_pending_can_be_reopened(self):
        entry, msg = self.defect_svc.reopen_defect(self.defect_id)
        self.assertIsNone(entry)
        self.assertIn("已关闭缺陷", msg)


if __name__ == "__main__":
    unittest.main()
