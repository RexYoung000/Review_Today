import copy
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from evals.core import load_dataset, write_json, digest
from evals.spec import (
    DIMENSIONS,
    validate,
    validate_verdict,
    classify,
    quality_tier,
    aggregate,
    reviewed_result,
    evidence_hash,
    audit_selection,
)
from evals.calibration import approval_status, material_hash, summarize, binding
from evals.schedule import choose, weekly_slot, ZONE


def make_result(case):
    response = "这是合成的判分器输入，不是产品真实回答。"
    return dict(
        schema_version=2,
        case_id=case["id"],
        trial_key=case["id"] + "-r1",
        case_contract=case,
        mode=case["mode"],
        domain=case["domain"],
        grading=case["grading"],
        status="passed",
        quality_tier="qualified",
        turns=[dict(response=response)],
        checks=[],
        judge=dict(
            scores={
                d: 2 if d in case["applicable_dimensions"] else None for d in DIMENSIONS
            },
            requirements=[
                dict(id=c["id"], passed=True, reason="覆盖要求")
                for c in case["pass_criteria"]
            ],
            excellence=[
                dict(id=c["id"], passed=False, reason="未达到优秀")
                for c in case["excellent_criteria"]
            ],
            evidence=[dict(turn=1, quote=response)],
            critical_findings=[],
            needs_review=False,
        ),
    )


def batch(suite="full"):
    d, _, _ = load_dataset()
    cases = [c for c in d["cases"] if suite == "full" or c["critical"]]
    plan = [
        dict(
            trial_key=c["id"] + f"-r{repeat}",
            case_id=c["id"],
            mode=c["mode"],
            domain=c["domain"],
            critical=c["critical"],
            repeat=repeat,
        )
        for c in cases
        for repeat in (range(1, 4) if suite == "critical" else [1])
    ]
    m = dict(
        schema_version=2,
        run_id="test",
        suite=suite,
        environment="fixture",
        finished_at="2026-09-08",
        plan=plan,
        gate_policy=d["gate_policy"],
        calibration_status="verified",
        rubric_hash="rubric",
    )
    results = [
        dict(
            trial_key=p["trial_key"],
            mode=p["mode"],
            domain=p["domain"],
            status="passed",
            quality_tier="qualified",
        )
        for p in plan
    ]
    return m, results


class V2Contracts(unittest.TestCase):
    def test_cross_domain_coverage_and_frozen_families(self):
        d, refs, r = load_dataset()
        validate(d, refs, r)
        self.assertEqual(len(d["cases"]), 100)
        self.assertEqual(sum(c["smoke"] for c in d["cases"]), 25)
        self.assertTrue(
            any("mastery_complete" in c["rules"] and c["critical"] for c in d["cases"])
        )
        d["cases"][-1]["family"] = d["cases"][0]["family"]
        with self.assertRaisesRegex(ValueError, "family"):
            validate(d, refs, r)

    def test_required_dimension_cannot_be_waived(self):
        d, refs, r = load_dataset()
        d["cases"][0]["applicable_dimensions"].remove("correctness")
        with self.assertRaisesRegex(ValueError, "required dimensions"):
            validate(d, refs, r)

    def test_protocol_cannot_be_a_teaching_escape(self):
        d, refs, r = load_dataset()
        d["cases"][1]["grading"] = "rules_only"
        with self.assertRaisesRegex(ValueError, "stop protocol"):
            validate(d, refs, r)

    def test_missing_criterion_and_fake_evidence_cannot_pass(self):
        case = load_dataset()[0]["cases"][0]
        r = make_result(case)
        self.assertEqual(classify(r), "passed")
        r["judge"]["requirements"].pop()
        self.assertEqual(classify(r), "needs_review")
        r = make_result(case)
        r["judge"]["evidence"][0]["quote"] = "编造的原文"
        self.assertEqual(classify(r), "needs_review")

    def test_na_is_not_zero_and_model_cannot_make_its_own_na(self):
        c = load_dataset()[0]["cases"][0]
        r = make_result(c)
        self.assertIsNone(r["judge"]["scores"]["teaching"])
        self.assertEqual(classify(r), "passed")
        r["judge"]["scores"]["correctness"] = None
        self.assertEqual(classify(r), "needs_review")

    def test_high_scores_cannot_mask_missing_delivery(self):
        r = make_result(load_dataset()[0]["cases"][0])
        r["judge"]["scores"] = {
            d: 3 if v is not None else None for d, v in r["judge"]["scores"].items()
        }
        r["judge"]["requirements"][0]["passed"] = False
        self.assertEqual(classify(r), "failed")

    def test_excellence_requires_both_conditions_and_associated_threes(self):
        r = make_result(load_dataset()[0]["cases"][0])
        self.assertEqual(quality_tier(r), "qualified")
        for e in r["judge"]["excellence"]:
            e["passed"] = True
        self.assertEqual(quality_tier(r), "qualified")
        for c in r["case_contract"]["excellent_criteria"]:
            r["judge"]["scores"][c["dimension"]] = 3
        self.assertEqual(quality_tier(r), "excellent")
        r["checks"] = [dict(passed=False, hard=True)]
        self.assertIsNone(quality_tier(r))


class V2Accounting(unittest.TestCase):
    def test_per_mode_eighteen_and_critical_gate(self):
        m, rs = batch()
        self.assertTrue(aggregate(m, rs)["baseline_gate"])
        noncritical = [
            p for p in m["plan"] if p["mode"] == "auto" and not p["critical"]
        ]
        idx = {r["trial_key"]: r for r in rs}
        for p in noncritical[:2]:
            idx[p["trial_key"]]["status"] = "failed"
        self.assertTrue(aggregate(m, rs)["baseline_gate"])
        idx[noncritical[2]["trial_key"]]["status"] = "failed"
        self.assertFalse(aggregate(m, rs)["baseline_gate"])
        m, rs = batch()
        i = next(i for i, p in enumerate(m["plan"]) if p["critical"])
        rs[i]["status"] = "failed"
        self.assertFalse(aggregate(m, rs)["baseline_gate"])

    def test_no_green_gate_before_calibration_or_finish(self):
        m, rs = batch()
        m["calibration_status"] = "pending_human"
        s = aggregate(m, rs)
        self.assertTrue(s["candidate_baseline_gate"])
        self.assertFalse(s["baseline_gate"])
        m["calibration_status"] = "verified"
        del m["finished_at"]
        self.assertFalse(aggregate(m, rs)["candidate_baseline_gate"])

    def test_errors_and_missing_stay_in_denominator(self):
        m, rs = batch()
        rs[0]["status"] = "error"
        rs[1]["status"] = "needs_review"
        rs.pop()
        s = aggregate(m, rs)
        self.assertEqual(s["planned"], 100)
        self.assertEqual(s["pass_rate"], 0.97)
        self.assertFalse(s["baseline_gate"])
        self.assertEqual(s["counts"]["not_run"], 1)

    def test_excellent_is_subset_not_additional_pass(self):
        m, rs = batch()
        rs[0]["quality_tier"] = "excellent"
        s = aggregate(m, rs)
        self.assertEqual(s["counts"]["passed"], 100)
        self.assertEqual(s["excellent_rate"], 0.01)

    def test_repeated_gate_checks_all_sixty_and_distinct_repeats(self):
        m, rs = batch("critical")
        self.assertTrue(aggregate(m, rs)["stability_gate"])
        m["plan"][1]["repeat"] = 1
        self.assertFalse(aggregate(m, rs)["stability_gate"])
        m, rs = batch("critical")
        rs.pop()
        self.assertFalse(aggregate(m, rs)["stability_gate"])

    def test_sampling_covers_all_modes_and_hard_failures(self):
        m, rs = batch()
        keys = audit_selection(m, rs)
        self.assertEqual(len(keys), 10)
        self.assertEqual(len({r["mode"] for r in rs if r["trial_key"] in keys}), 5)
        rs[0].update(status="failed", checks=[dict(hard=True, passed=False)])
        self.assertIn(rs[0]["trial_key"], audit_selection(m, rs))


class ReviewAndCalibration(unittest.TestCase):
    def review(self, r):
        return dict(
            verdict="qualified",
            reviewer="TEST ONLY",
            reviewed_at="2026-09-08",
            reason="测试裁判误判纠正",
            evidence="核对过的原文",
            rubric_hash="r",
            result_hash=evidence_hash(r),
        )

    def test_manual_review_preserves_raw_and_rejects_stale_binding(self):
        r = make_result(load_dataset()[0]["cases"][0])
        r["status"] = "failed"
        review = self.review(r)
        effective = reviewed_result(r, review, "r")
        self.assertEqual(effective["status"], "passed")
        self.assertEqual(r["status"], "failed")
        self.assertEqual(reviewed_result(r, review, "new")["status"], "failed")
        r["turns"][0]["response"] = "修改后的证据"
        self.assertEqual(reviewed_result(r, review, "r")["status"], "failed")

    def test_manual_pass_cannot_hide_execution_or_objective_failure(self):
        for update in (
            dict(execution_error="timeout", status="error"),
            dict(checks=[dict(passed=False, hard=True)], status="failed"),
        ):
            r = make_result(load_dataset()[0]["cases"][0])
            r.update(update)
            self.assertEqual(
                reviewed_result(r, self.review(r), "r")["status"], r["status"]
            )

    def fixture(self):
        from evals.core import read_json, DATA

        contrasts = read_json(DATA / "calibration.json")
        rubric = load_dataset()[2]
        b = binding(rubric, contrasts, dict(provider="test", judge="test"))
        approvals = {
            "approvals": {
                e["case_id"]: dict(
                    approved=True,
                    reviewer="TEST ONLY",
                    reviewed_at="2026-09-08",
                    material_hash=material_hash(e),
                )
                for e in contrasts["cases"]
            }
        }
        run = dict(
            binding=b,
            results=[
                dict(case_id=e["case_id"], expected=v["tier"], observed=v["tier"])
                for e in contrasts["cases"]
                if e["split"] == "verify"
                for v in e["variants"]
            ],
        )
        return contrasts, approvals, b, run

    def test_no_self_approval_and_material_changes_invalidate(self):
        c, a, b, r = self.fixture()
        self.assertEqual(summarize(c, {}, b, r)["status"], "pending_human")
        self.assertEqual(summarize(c, a, b, r)["status"], "verified")
        c["cases"][0]["variants"][0]["result"]["turns"][0]["response"] = "更改材料"
        self.assertTrue(approval_status(c, a))

    def test_judge_agreement_cannot_hide_critical_false_accept(self):
        c, a, b, r = self.fixture()
        r["results"][0]["observed"] = "qualified"
        s = summarize(c, a, b, r)
        self.assertGreater(s["agreement"], 0.9)
        self.assertEqual(s["critical_false_accept"], 1)
        self.assertNotEqual(s["status"], "verified")

    def test_model_change_or_incomplete_verification_invalidates(self):
        c, a, b, r = self.fixture()
        changed = {**b, "model_identity": dict(judge="other")}
        self.assertNotEqual(summarize(c, a, changed, r)["status"], "verified")
        r["results"].pop()
        self.assertNotEqual(summarize(c, a, b, r)["status"], "verified")


class Scheduling(unittest.TestCase):
    def test_monday_slot_and_missed_run_coalesce(self):
        monday = datetime(2026, 9, 7, 9, 0, tzinfo=ZONE)
        tuesday = datetime(2026, 9, 8, 11, 0, tzinfo=ZONE)
        self.assertTrue(weekly_slot(monday).startswith("2026-08-31"))
        self.assertTrue(weekly_slot(tuesday).startswith("2026-09-07"))
        d = choose(tuesday, "new", {}, True, weekly=True)
        self.assertEqual(d["action"], "weekly")
        state = {"weekly_slot": d["slot"], "fingerprint": "new"}
        self.assertEqual(
            choose(tuesday, "new", state, True, weekly=True)["action"], "unchanged"
        )

    def test_no_model_dispatch_until_human_calibration_and_new_fingerprint(self):
        now = datetime.now(ZONE)
        self.assertEqual(choose(now, "a", {}, False)["action"], "blocked")
        self.assertEqual(
            choose(now, "a", {"fingerprint": "a"}, True)["action"], "unchanged"
        )
        self.assertEqual(
            choose(now, "b", {"fingerprint": "a"}, True)["action"], "smoke"
        )


if __name__ == "__main__":
    unittest.main()


class WorkflowTests(unittest.TestCase):
    def test_issue_replay_cannot_reopen_closed_later_issue(self):
        from evals.feishu_v2 import issue_update

        previous = {"最近出现时间": "2026-09-09", "处理状态": ["已关闭"]}
        self.assertIsNone(issue_update({"最近出现时间": "2026-09-08"}, previous))
        self.assertIsNone(issue_update({"最近出现时间": "2026-09-09"}, previous))
        updated = issue_update({"最近出现时间": "2026-09-10"}, previous)
        self.assertEqual(updated["处理状态"], ["待分析"])
        self.assertTrue(updated["再次出现"])

    def test_open_issue_retains_existing_recurrence_marker(self):
        from evals.feishu_v2 import issue_update

        previous = {
            "最近出现时间": "2026-09-09",
            "处理状态": ["修复中"],
            "再次出现": True,
        }
        updated = issue_update(
            {"最近出现时间": "2026-09-10", "处理状态": ["待分析"]}, previous
        )
        self.assertTrue(updated["再次出现"])

    def test_v2_judge_schema_accepts_na_and_rejects_boolean_score(self):
        from evals.judge import VerdictV2
        from pydantic import ValidationError

        case = load_dataset()[0]["cases"][0]
        verdict = make_result(case)["judge"]
        verdict.update(
            summary="满足场景", diagnosis="none", repair_direction="无需修复"
        )
        VerdictV2.model_validate(verdict)
        verdict["scores"]["intent"] = True
        with self.assertRaises(ValidationError):
            VerdictV2.model_validate(verdict)

    def test_running_and_old_standard_do_not_hide_current_completed_results(self):
        from evals.feishu import latest_flags

        rows = [
            dict(
                批次键="old",
                标准版本="v1",
                开始时间="1",
                批类型="full",
                工具环境="fixture",
                计划数=40,
            ),
            dict(
                批次键="new",
                标准版本="v2",
                开始时间="2",
                批类型="smoke",
                工具环境="fixture",
                计划数=25,
                运行状态="已结束",
            ),
            dict(
                批次键="running",
                标准版本="v2",
                开始时间="3",
                批类型="full",
                工具环境="fixture",
                计划数=100,
                运行状态="运行中",
            ),
        ]
        flags = latest_flags(rows)
        self.assertTrue(flags["old"]["最新批次"])
        self.assertTrue(flags["new"]["最新批次"])
        self.assertFalse(flags["running"]["最新批次"])
        self.assertFalse(flags["running"]["最新同类批次"])

    def test_verified_critical_failure_blocks_even_when_judge_requests_review(self):
        c = load_dataset()[0]["cases"][0]
        r = make_result(c)
        r["judge"]["needs_review"] = True
        r["judge"]["critical_findings"] = [
            dict(
                kind="false_mastery",
                turn=1,
                quote=r["turns"][0]["response"],
                explanation="测试已验证的原文严重违规",
            )
        ]
        self.assertEqual(classify(r), "failed")
        r["judge"]["critical_findings"][0]["quote"] = "不存在的引用"
        self.assertEqual(classify(r), "needs_review")

    def test_positive_mastery_cases_bind_the_initial_exercise(self):
        for c in load_dataset()[0]["cases"]:
            if "mastery_complete" in c["rules"]:
                self.assertIn("本轮只练这一题", c["turns"][0]["text"])
                self.assertIn("约定练习题", c["turns"][1]["text"])

    def test_invalid_verdict_preserves_raw_evidence_without_accepting_it(self):
        from evals.judge import grade, VerdictV2, VerdictValidationError
        from unittest.mock import patch

        c = load_dataset()[0]["cases"][0]
        r = make_result(c)
        r["tools"] = []
        j = r["judge"]
        j.update(summary="测试证据校验", diagnosis="none", repair_direction="")
        j["evidence"][0]["quote"] = "不存在的引用"
        with patch(
            "agent_service.openai_client.parse_model",
            return_value=VerdictV2.model_validate(j),
        ):
            with self.assertRaises(VerdictValidationError) as ctx:
                grade(c, r, {}, load_dataset()[2], "test")
        self.assertEqual(ctx.exception.verdict, j)
        self.assertIn("exact public quote", ctx.exception.reason)

    def test_scheduler_lock_prevents_any_config_or_model_access(self):
        import fcntl, io
        from contextlib import redirect_stdout
        from types import SimpleNamespace
        from evals.schedule import run

        with tempfile.TemporaryDirectory() as directory:
            with (Path(directory) / "schedule.lock").open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                output = io.StringIO()
                with redirect_stdout(output):
                    run(
                        SimpleNamespace(repo="/nonexistent-eval-repo", output=directory)
                    )
                self.assertIn("already_running", output.getvalue())
