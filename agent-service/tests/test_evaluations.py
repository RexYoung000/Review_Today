"""Evaluator safety and accounting tests, never quality scores for real models."""

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from evals.core import (
    DIMENSIONS,
    MODES,
    aggregate,
    check_rules,
    classify,
    load_dataset,
    validate_judge,
    write_json,
)
from evals.feishu import CLI, LarkError, SCHEMAS, sample_rows
from evals.instrument import Meter


def empty_state():
    return dict(
        tasks=[],
        draft=None,
        pending=None,
        paused=False,
        commit_packages=[],
        memory_references=[],
        learning_evidence=[],
    )


def verdict():
    return dict(
        scores=dict.fromkeys(DIMENSIONS, 2), needs_review=False, critical_findings=[]
    )


class DatasetTests(unittest.TestCase):
    def test_coverage_and_versioned_sources(self):
        d, r, b = load_dataset()
        self.assertEqual(len(d["cases"]), 40)
        self.assertEqual(len(sample_rows(d, r)), 40)
        self.assertTrue(all(c["synthetic"] for c in d["cases"]))
        self.assertEqual(
            set(c["knowledge"] for c in d["cases"]), {"fact", "concept", "procedure"}
        )
        self.assertTrue(
            all(c["split"] == "dev" for c in d["cases"] if c["calibration"])
        )

    def test_family_leak_and_unknown_reference_rejected(self):
        d, r, b = load_dataset()
        with tempfile.TemporaryDirectory() as directory:
            for name, data in [("scenarios", d), ("references", r), ("rubric", b)]:
                write_json(Path(directory) / (name + ".json"), data)
            d["cases"][-1]["family"] = d["cases"][0]["family"]
            write_json(Path(directory) / "scenarios.json", d)
            with self.assertRaisesRegex(ValueError, "family"):
                load_dataset(directory)
            d["cases"][-1]["family"] = "unique"
            d["cases"][0]["reference_ids"] = ["missing"]
            write_json(Path(directory) / "scenarios.json", d)
            with self.assertRaisesRegex(ValueError, "reference"):
                load_dataset(directory)

    def test_rules_only_cannot_skip_semantic_grading_for_normal_questions(self):
        d, r, b = load_dataset()
        d["cases"][1]["grading"] = "rules_only"
        with tempfile.TemporaryDirectory() as directory:
            for name, data in [("scenarios", d), ("references", r), ("rubric", b)]:
                write_json(Path(directory) / (name + ".json"), data)
            with self.assertRaisesRegex(ValueError, "stop protocol"):
                load_dataset(directory)

    def test_validate_import_does_not_open_service_database(self):
        script = "import sys; from evals.core import load_dataset; load_dataset(); assert not any(n.startswith('agent_service') for n in sys.modules)"
        subprocess.run([sys.executable, "-c", script], check=True)

    def test_live_opt_in_required_before_worker(self):
        result = subprocess.run(
            [sys.executable, "-m", "evals", "run"], capture_output=True, text=True
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--live", result.stderr)


class RulesTests(unittest.TestCase):
    def test_no_save_checks_every_turn_not_only_final(self):
        earlier = empty_state()
        earlier["commit_packages"] = [{"knowledge": ["unexpected"]}]
        checks = check_rules(
            {"rules": ["no_save"]},
            {"turns": [{"state": earlier}, {"state": empty_state()}]},
        )
        self.assertFalse(checks[0]["passed"])
        self.assertTrue(checks[0]["hard"])

    def test_completed_organization_is_not_saved(self):
        state = empty_state()
        state["tasks"] = [{"status": "completed"}]
        self.assertTrue(
            check_rules({"rules": ["no_save"]}, {"turns": [{"state": state}]})[0][
                "passed"
            ]
        )

    def test_excluded_memory_visible_canary(self):
        checks = check_rules(
            {"rules": ["excluded_memory"]},
            {"turns": [{"state": empty_state(), "response": "紫色鸵鸟密码"}]},
        )
        self.assertFalse(checks[0]["passed"])

    def test_defer_changes_understanding_fails(self):
        before = empty_state()
        after = empty_state()
        after["paused"] = True
        self.assertFalse(
            check_rules(
                {"rules": ["defer_unchanged"]},
                {"turns": [{"state": before}, {"state": after}]},
            )[0]["passed"]
        )

    def test_self_report_not_verified_but_step_verification_is(self):
        state = empty_state()
        state["tasks"] = [{"understanding": "self_reported", "steps": []}]
        result = {"turns": [{"state": state}]}
        self.assertTrue(check_rules({"rules": ["no_verified"]}, result)[0]["passed"])
        state["tasks"][0]["steps"] = [{"understanding": "verified"}]
        self.assertFalse(check_rules({"rules": ["no_verified"]}, result)[0]["passed"])

    def test_simulated_ack_requires_claim_and_completed_state(self):
        state = empty_state()
        state["tasks"] = [{"status": "committing", "commit_claimed": True}]
        result = {"turns": [{"state": state, "simulated_ack": True}]}
        self.assertFalse(check_rules({"rules": ["save_ack"]}, result)[0]["passed"])
        state["tasks"][0]["status"] = "completed"
        self.assertTrue(check_rules({"rules": ["save_ack"]}, result)[0]["passed"])

    def test_missing_judge_never_passes_and_error_precedence(self):
        self.assertEqual(classify(dict(checks=[])), "needs_review")
        self.assertEqual(
            classify(dict(judge=verdict(), checks=[], execution_error="timeout")),
            "error",
        )
        self.assertEqual(
            classify(dict(judge=verdict(), checks=[{"passed": False}])), "failed"
        )

    def test_stop_protocol_needs_all_rule_checks_and_no_execution_error(self):
        r = dict(grading="rules_only", checks=[dict(passed=True)], judge=None)
        self.assertEqual(classify(r), "passed")
        r["checks"][0]["passed"] = False
        self.assertEqual(classify(r), "failed")
        r["execution_error"] = "interrupted incorrectly"
        self.assertEqual(classify(r), "error")

    def test_critical_judge_requires_exact_public_quote(self):
        j = verdict()
        j["critical_findings"] = [dict(turn=1, quote="我已保存", kind="false_saved")]
        with self.assertRaises(ValueError):
            validate_judge(j, [dict(response="我还没有保存")])
        validate_judge(j, [dict(response="我已保存")])

    def test_judge_boolean_score_and_missing_dimension_rejected(self):
        j = verdict()
        j["scores"]["intent"] = True
        with self.assertRaises(ValueError):
            validate_judge(j, [])
        j = verdict()
        del j["scores"]["intent"]
        with self.assertRaises(ValueError):
            validate_judge(j, [])


class AggregateTests(unittest.TestCase):
    def fixture(self):
        cases = load_dataset()[0]["cases"]
        manifest = dict(
            suite="full",
            environment="fixture",
            plan=[dict(trial_key=c["id"], mode=c["mode"]) for c in cases],
        )
        results = [dict(trial_key=c["id"], status="passed") for c in cases]
        return manifest, results

    def test_errors_review_unrun_remain_in_denominator(self):
        m, r = self.fixture()
        r[0]["status"] = "error"
        r[1]["status"] = "needs_review"
        r.pop()
        s = aggregate(m, r)
        self.assertEqual(s["planned"], 40)
        self.assertEqual(s["pass_rate"], 37 / 40)
        self.assertFalse(s["baseline_gate"])
        self.assertEqual(s["counts"]["not_run"], 1)

    def test_per_mode_gate_prevents_masking_local_failure(self):
        m, r = self.fixture()
        r[0]["status"] = r[1]["status"] = "failed"
        self.assertFalse(aggregate(m, r)["baseline_gate"])
        r[1]["status"] = "passed"
        r[8]["status"] = "failed"
        self.assertTrue(aggregate(m, r)["baseline_gate"])

    def test_hard_failure_online_and_changed_code_cannot_pass(self):
        m, r = self.fixture()
        self.assertTrue(aggregate(m, r)["baseline_gate"])
        r[0]["checks"] = [dict(passed=False, hard=True)]
        self.assertFalse(aggregate(m, r)["baseline_gate"])
        r[0].pop("checks")
        m["environment"] = "online"
        self.assertFalse(aggregate(m, r)["baseline_gate"])
        m["environment"] = "fixture"
        m["invalidated"] = "source changed"
        self.assertFalse(aggregate(m, r)["baseline_gate"])

    def test_critical_requires_all_30_and_not_release(self):
        m, r = self.fixture()
        m["suite"] = "critical"
        m["plan"] = [
            dict(trial_key=f"{i}-{n}", case_id=str(i), repeat=n, mode="auto")
            for i in range(10)
            for n in (1, 2, 3)
        ]
        r = [dict(trial_key=p["trial_key"], status="passed") for p in m["plan"]]
        self.assertTrue(aggregate(m, r)["stability_gate"])
        self.assertEqual(aggregate(m, r)["release_gate"], "not_assessed")
        r[0]["status"] = "failed"
        self.assertFalse(aggregate(m, r)["stability_gate"])


class MeterTests(unittest.TestCase):
    def test_limit_counts_real_calls_including_fallback_and_judge(self):
        calls = []

        def create(**kw):
            calls.append(kw)
            return SimpleNamespace(usage=SimpleNamespace(total_tokens=12))

        endpoint = SimpleNamespace(create=create, parse=create)
        client = SimpleNamespace(
            responses=endpoint, chat=SimpleNamespace(completions=endpoint)
        )
        meter = Meter(2)
        proxy = meter.wrap(client)
        proxy.responses.create(model="flash")
        meter.phase = "judge"
        proxy.chat.completions.parse(model="pro")
        with self.assertRaisesRegex(RuntimeError, "EVAL_BUDGET"):
            proxy.responses.create(model="flash")
        self.assertEqual(len(calls), 2)
        self.assertEqual(meter.calls[-1]["phase"], "judge")
        self.assertEqual(meter.calls[0]["usage"]["total_tokens"], 12)

    def test_stream_usage_without_reasoning_capture(self):
        class Stream:
            def __enter__(self):
                return self

            def __iter__(self):
                yield SimpleNamespace(
                    type="response.reasoning.delta", delta="private hidden"
                )
                yield SimpleNamespace(
                    type="response.completed",
                    response=SimpleNamespace(usage=SimpleNamespace(total_tokens=5)),
                )

            def __exit__(self, *args):
                pass

        ep = SimpleNamespace(create=lambda **kw: Stream())
        client = SimpleNamespace(responses=ep, chat=SimpleNamespace(completions=ep))
        meter = Meter(1)
        with meter.wrap(client).responses.create(model="flash", stream=True) as stream:
            list(stream)
        self.assertEqual(meter.calls[0]["usage"]["total_tokens"], 5)
        self.assertNotIn("private hidden", json.dumps(meter.calls))


class FakeCLI(CLI):
    def __init__(self):
        self.config = {"base_token": "base", "tables": {"结果明细": "tbl"}}
        self.rows = []
        self.creates = 0
        self.fail_after_write = False
        self.fail_before_write = False

    def save(self):
        pass

    def fields(self, table):
        return {f["name"]: f for f in SCHEMAS["结果明细"]}

    def records(self, table):
        return copy.deepcopy(self.rows)

    def call(self, command, **kw):
        if command == "record-batch-create":
            self.creates += 1
            if self.fail_before_write:
                raise LarkError("unknown network outcome")
            ids = []
            for row in kw["json"]["create_records"]:
                rid = "rec" + str(len(self.rows))
                self.rows.append({**copy.deepcopy(row), "record_id": rid})
                ids.append(rid)
            if self.fail_after_write:
                raise LarkError("response lost")
            return dict(record_id_list=ids)
        if command == "record-batch-update":
            for rid, fields in kw["json"]["update_records"].items():
                next(r for r in self.rows if r["record_id"] == rid).update(
                    copy.deepcopy(fields)
                )
            return {}
        raise AssertionError(command)


class SyncTests(unittest.TestCase):
    def test_repeated_sync_preserves_human_feedback(self):
        cli = FakeCLI()
        row = {
            "结果键": "run/a",
            "机器诊断": "old",
            "人工结论": ["待复核"],
            "人工原因": "",
        }
        cli.upsert("结果明细", [row])
        cli.rows[0]["人工原因"] = "人工不同意"
        cli.rows[0]["人工结论"] = ["机器误判"]
        row["机器诊断"] = "new"
        cli.upsert("结果明细", [row])
        self.assertEqual(cli.creates, 1)
        self.assertEqual(cli.rows[0]["机器诊断"], "new")
        self.assertEqual(cli.rows[0]["人工原因"], "人工不同意")
        self.assertEqual(cli.rows[0]["人工结论"], ["机器误判"])

    def test_response_lost_recovers_without_second_create(self):
        cli = FakeCLI()
        cli.fail_after_write = True
        cli.upsert("结果明细", [{"结果键": "run/a"}])
        cli.upsert("结果明细", [{"结果键": "run/a"}])
        self.assertEqual(cli.creates, 1)
        self.assertEqual(len(cli.rows), 1)

    def test_uncertain_absent_create_blocks_blind_retry(self):
        cli = FakeCLI()
        cli.fail_before_write = True
        with self.assertRaises(LarkError):
            cli.upsert("结果明细", [{"结果键": "run/a"}])
        cli.fail_before_write = False
        with self.assertRaisesRegex(LarkError, "uncertain"):
            cli.upsert("结果明细", [{"结果键": "run/a"}])
        self.assertEqual(cli.creates, 1)

    def test_duplicate_existing_key_and_unknown_field_fail_before_write(self):
        cli = FakeCLI()
        cli.rows = [
            {"结果键": "a", "record_id": "r1"},
            {"结果键": "a", "record_id": "r2"},
        ]
        with self.assertRaisesRegex(LarkError, "duplicate"):
            cli.upsert("结果明细", [{"结果键": "a"}])
        cli.rows = []
        with self.assertRaisesRegex(LarkError, "schema"):
            cli.upsert("结果明细", [{"结果键": "a", "typo": "x"}])
        self.assertEqual(cli.creates, 0)


class WorkerIntegrationTests(unittest.TestCase):
    def test_real_store_restart_path_without_model_or_private_db(self):
        import os
        from agent_service import config, conversation
        from agent_service.schemas import IntentDecision
        from evals.worker import execute

        with tempfile.TemporaryDirectory(
            prefix="review-today-eval-integration-"
        ) as folder:
            args = SimpleNamespace(
                trial_key="restart",
                output=Path(folder) / "result.json",
                env_file=[],
                max_calls=5,
                environment="fixture",
            )
            case = dict(
                id="restart",
                mode="auto",
                setup={},
                rules=["no_save", "no_task"],
                turns=[{"text": "你好"}, {"text": "你好", "action": "restart"}],
            )
            decision = IntentDecision(
                intents=["greeting"],
                relation="continuation",
                scope="conversation",
                rationale="受控路径验证",
                light_reply="你好",
            )
            with patch.dict(os.environ), patch.object(
                config, "HARNESS_DB", str(Path(folder) / "checkpoint.sqlite3")
            ), patch.object(config, "PROVIDER", "deepseek"), patch.object(
                config, "openai_key", return_value="synthetic-never-sent"
            ), patch.object(
                conversation, "parse_model", return_value=decision
            ), patch(
                "evals.judge.grade", return_value=verdict()
            ):
                result = execute(case, {}, {}, args, folder)
            self.assertEqual(result["status"], "passed", result)
            self.assertEqual([t["response"] for t in result["turns"]], ["你好", "你好"])
            self.assertEqual(result["calls"], [])
            self.assertTrue((Path(folder) / "checkpoint.sqlite3").exists())


class DashboardCohortTests(unittest.TestCase):
    def test_critical_and_online_never_replace_full_fixture_baseline(self):
        from evals.feishu import latest_flags

        def b(id, kind, env, date, n):
            return {
                "批次键": id,
                "批类型": kind,
                "工具环境": env,
                "开始时间": date,
                "计划数": n,
            }

        flags = latest_flags(
            [
                b("old", "full", "fixture", "1", 40),
                b("full", "full", "fixture", "2", 40),
                b("critical", "critical", "fixture", "3", 30),
                b("online", "full", "online", "4", 1),
            ]
        )
        self.assertTrue(flags["full"]["最新批次"])
        self.assertFalse(flags["critical"]["最新批次"])
        self.assertFalse(flags["online"]["最新批次"])
        self.assertTrue(flags["critical"]["最新同类批次"])
        self.assertFalse(flags["old"]["最新同类批次"])

    def test_error_codes_point_to_the_responsible_layer(self):
        from evals.feishu import error_category

        self.assertEqual(error_category("RT.INTENT.INVALID_TARGET"), "intent")
        self.assertEqual(
            error_category("RT.PLAN.INVALID_STEP_REFERENCE"), "learning_state"
        )
        self.assertEqual(error_category("RT.MODEL.SCHEMA"), "structured_output")
        self.assertEqual(
            error_category("EVAL.SAVE_PRECONDITION_MISSING"), "scenario_precondition"
        )

    def test_calibration_is_visible_until_full_baseline_exists(self):
        from evals.feishu import latest_flags

        self.assertTrue(
            latest_flags(
                [
                    {
                        "批次键": "cal",
                        "批类型": "calibration",
                        "工具环境": "fixture",
                        "开始时间": "1",
                        "计划数": 12,
                    }
                ]
            )["cal"]["最新批次"]
        )


if __name__ == "__main__":
    unittest.main()
