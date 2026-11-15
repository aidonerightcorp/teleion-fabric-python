# Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md
"""Offline unit tests for NodeRecord echo redaction, execution_report, and data_use boundaries."""
import json
import unittest

from stepkit import omninode as O
from stepkit import retention as R


class RecordPrivacyRedactionTests(unittest.TestCase):
    def test_l0_summary_redacts_echo_long_and_nested_task_text(self):
        cases = (
            ("echo", "Authored private sentence retained only in this local fixture.", "echo", False),
            ("long_echo", "Private authored sequence for truncation. " * 35, "echo", False),
            ("nested_echo", "Authored private nested answer for record boundary checking.", "nested", False),
            ("allowed", "Authored task text explicitly allowed in this control.", "echo", True),
            ("ordinary", "Authored private task sentence unrelated to numeric answer.", "ordinary", False),
        )
        for name, task_text, answer_kind, allowed in cases:
            with self.subTest(case=name):
                task = {"id": name, "question": task_text}
                answer = (
                    task_text
                    if answer_kind == "echo"
                    else {"note": task_text}
                    if answer_kind == "nested"
                    else 42
                )
                node = O.OmniNode(
                    O.CONTRACT.with_({"output.form": "any", "records.task_text": allowed}),
                    O.PARAMETERS.with_({"arrangement": [["answer", "take"]]}),
                )
                record = node.run(task, O.PartsSource(None, {"answer": O.Part("answer", value=lambda _: answer)}))
                port = R.MemoryRecordPort(clock=lambda: "2026-11-14T00:00:00Z")
                sink = R.NodeRecordSink(port, name, when="2026-11-14T00:00:00Z")
                done = sink.write(record, task)
                stored = port.get(sink.store, done["key"])["value"]
                summary = stored["l0_summary"]
                prefix_exposed = task_text[:30] in summary
                expected = allowed and answer_kind == "echo"
                self.assertEqual(prefix_exposed, expected)
                self.assertEqual(task_text[:30] in json.dumps(stored), allowed)
                self.assertTrue(all(row["equal"] for row in sink.verify()))
                if answer_kind == "ordinary":
                    self.assertIn("42", summary)

    def test_telemetry_execution_report_and_delivery_separation(self):
        cases = (
            ("echo", False, False, True, False),
            ("long", False, False, True, False),
            ("numeric_reason", False, False, True, True),
            ("allowed", True, False, True, False),
            ("no_context", False, False, False, False),
            ("narrowed", True, True, True, False),
        )
        for name, allowed, narrow, context, numeric in cases:
            with self.subTest(case=name):
                text = "Authored private task sentence for retained telemetry checks." * (
                    30 if name == "long" else 1
                )
                task = {"id": name, "question": text}
                params = {"arrangement": [["answer", "take"]]}
                if narrow:
                    params["records.task_text"] = False
                node = O.OmniNode(
                    O.CONTRACT.with_({"output.form": "any", "records.task_text": allowed}),
                    O.PARAMETERS.with_(params),
                )
                answer = 42 if numeric else text
                record = node.run(task, O.PartsSource(None, {"answer": O.Part("answer", value=lambda _: answer)}))
                record.reason = "Echo " + text
                port = R.MemoryRecordPort(clock=lambda: "2026-11-14T00:00:00Z")
                sink = R.NodeRecordSink(port, name, when="2026-11-14T00:00:00Z")
                sink.submit("queue-" + name, 1, record, task=task if context else None)
                submitted = port.results["queue-" + name]
                expected = allowed and not narrow
                self.assertEqual(text[:30] in json.dumps(submitted["execution_report"]), expected)
                stored_body = sink.value_of(record, task if context else None)
                self.assertEqual(text[:30] in json.dumps(stored_body), expected)
                self.assertEqual(
                    submitted["output"],
                    {"answer": record.answer, "accepted": record.accepted, "reason": record.reason},
                )

    def test_all_fifteen_independent_boundary_cases(self):
        secret = "Authored confidential sentence retained only with explicit permission."
        known = {"id": "review", "question": secret}
        cases = (
            ("none", False, {}, None, False),
            ("empty_dict", False, {}, {}, False),
            ("id_only", False, {}, {"id": "review"}, False),
            ("empty_question", False, {}, {"question": ""}, False),
            ("null_question_text_present", False, {}, {"question": None, "text": secret}, False),
            ("unknown_shape", False, {}, {"input": secret}, False),
            ("non_string_question", False, {}, {"question": 42}, False),
            ("explicit_allowed", True, {"records.task_text": True}, known, True),
            ("narrowed", True, {"records.task_text": False}, known, False),
            ("no_widen", False, {"records.task_text": True}, known, False),
            ("effective_string_value", True, {"records.task_text": "true"}, known, False),
            ("effective_false_scalar", True, False, known, False),
            ("effective_empty_list", True, [], known, False),
            ("effective_truthy_list", True, [True], known, False),
            ("legacy_missing", True, "ABSENT", known, True),
        )
        for name, declared, effective, context, visible in cases:
            with self.subTest(case=name):
                node = O.OmniNode(
                    O.CONTRACT.with_({"output.form": "any", "records.task_text": declared}),
                    O.PARAMETERS.with_({"arrangement": [["answer", "take"]]}),
                )
                record = node.run(known, O.PartsSource(None, {"answer": O.Part("answer", value=lambda _: secret)}))
                record.reason = "Echo " + secret
                if effective == "ABSENT":
                    del record.effective_policy
                else:
                    record.effective_policy = effective
                port = R.MemoryRecordPort(clock=lambda: "2026-11-14T00:00:00Z")
                sink = R.NodeRecordSink(port, name, when="2026-11-14T00:00:00Z")
                sink.submit(name, 1, record, task=context)
                submitted = port.results[name]
                self.assertEqual(secret in json.dumps(submitted["execution_report"]), visible)
                self.assertEqual(
                    submitted["output"],
                    {"answer": record.answer, "accepted": record.accepted, "reason": record.reason},
                )
                persisted = sink.value_of(record, task=context)
                self.assertEqual(secret in json.dumps(persisted), visible)

    def test_data_use_monotonic_narrowing_and_widening_refusal(self):
        task = {"id": "gov", "question": "Authored task sentence for data governance check."}
        for via in ("parameters", "evidence"):
            with self.subTest(via=via):
                params = {"arrangement": [["answer", "take"]]}
                if via == "parameters":
                    params["records.data_use"] = "open"
                resolver = (
                    O.Resolver(evidence={"records.data_use": {"value": "open", "source": "proposal"}})
                    if via == "evidence"
                    else O.Resolver()
                )
                restricted = O.OmniNode(
                    O.CONTRACT.with_({"output.form": "number", "records.data_use": "benchmark: no training"}),
                    O.PARAMETERS.with_(params),
                    resolver=resolver,
                )
                with self.assertRaises(O.ContractError):
                    restricted.run(task, O.PartsSource(None, {"answer": O.Part("answer", value=lambda _: 7)}))

        open_node = O.OmniNode(
            O.CONTRACT.with_({"output.form": "number", "records.data_use": "open"}),
            O.PARAMETERS.with_({"arrangement": [["answer", "take"]], "records.data_use": "benchmark: no training"}),
        )
        narrowed_record = open_node.run(task, O.PartsSource(None, {"answer": O.Part("answer", value=lambda _: 7)}))
        self.assertEqual(narrowed_record.contract["records.data_use"], "open")
        self.assertEqual(narrowed_record.effective_policy["records.data_use"], "benchmark: no training")

        port = R.MemoryRecordPort(clock=lambda: "2026-11-14T00:00:00Z")
        sink = R.NodeRecordSink(port, "gov-run", when="2026-11-14T00:00:00Z")
        with self.assertRaises(O.ContractError):
            sink.write(narrowed_record, task=task, data_use="open")
        self.assertEqual(port.writes, 0)
        with self.assertRaises(O.ContractError):
            sink.submit("gov-q", 1, narrowed_record, task=task, data_use="open")
        self.assertEqual(port.writes, 0)

        done = sink.write(narrowed_record, task=task)
        stored = port.get(sink.store, done["key"])
        self.assertEqual(stored["value"]["data_use"], "benchmark: no training")
        self.assertIn("data-use:benchmark-no-training", stored["tags"])
        sink.submit("gov-q", 1, narrowed_record, task=task)
        self.assertEqual(port.results["gov-q"]["execution_report"]["data_use"], "benchmark: no training")

        parent = O.OmniNode(
            O.CONTRACT.with_(
                {
                    "budget.depth": 2,
                    "budget.nodes": 2,
                    "permissions.spawn": True,
                    "records.task_text": False,
                    "records.data_use": "benchmark: no training",
                }
            ),
            O.PARAMETERS,
        )
        with self.assertRaises(O.ContractError):
            parent.spawn(parent.derive({"records.data_use": "open"}))
        with self.assertRaises(O.ContractError):
            parent.spawn(parent.derive({"records.task_text": True}))
        child = parent.spawn(parent.derive(), O.PARAMETERS.with_({"arrangement": [["answer", "take"]]}))
        child.contract = child.contract.with_({"records.data_use": "open"})
        with self.assertRaises(O.ContractError):
            child.run(task, O.PartsSource(None, {"answer": O.Part("answer", value=lambda _: 7)}))

    def test_write_tree_verify_conflict_and_max_writes_grid(self):
        task = {"id": "tree", "question": "Authored confidential parent-child task sentence."}
        parent = O.OmniNode(
            O.CONTRACT.with_(
                {
                    "output.form": "number",
                    "permissions.spawn": True,
                    "budget.depth": 1,
                    "budget.nodes": 1,
                }
            ),
            O.PARAMETERS.with_(
                {
                    "children.rule": "steps",
                    "children.steps": [
                        {
                            "name": "leaf",
                            "contract": {"output.form": "number"},
                            "parameters": {"children.rule": "none", "arrangement": [["answer", "take"]]},
                        }
                    ],
                }
            ),
        )
        record = parent.run(task, O.PartsSource(None, {"answer": O.Part("answer", value=lambda _: 12)}))
        port = R.MemoryRecordPort(clock=lambda: "2026-11-14T00:00:00Z")
        sink = R.NodeRecordSink(port, "tree-run", when="2026-11-14T00:00:00Z")
        done = sink.write(record, task=task)
        self.assertEqual(len(sink.written), 2)
        self.assertTrue(all(row["equal"] for row in sink.verify()))
        parent_value = port.get(sink.store, done["key"])["value"]
        self.assertEqual(len(parent_value["record"]["children"]), 1)
        self.assertNotIn("confidential", json.dumps(parent_value))

        with self.assertRaises(R.RecordConflictError):
            port.put(sink.store, done["key"], parent_value, expected_version=0)

        capped_resolver = O.Resolver(evidence={"records.max_writes": {"value": 1, "source": "grid cap"}})
        capped_sink = R.NodeRecordSink(port, "capped-run", resolver=capped_resolver, when="2026-11-14T00:00:00Z")
        with self.assertRaises(R.RecordLimitError):
            capped_sink.write(record, task=task)


if __name__ == "__main__":
    unittest.main(verbosity=2)
