# Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md
"""Offline unit tests for ancestor and runtime part/connector model allowlists."""
from types import SimpleNamespace
import unittest

from stepkit import omninode as O

TASK = {"id": "model-auth", "question": "What is 6 + 3?"}


class ModelAllowlistRuntimeTests(unittest.TestCase):
    def test_child_cannot_widen_model_allowlist_spawn_or_replay(self):
        probe_calls = []

        def probe(call_name, task, seed=None):
            probe_calls.append(call_name)
            return {"answer": 9.0, "ok": True, "form_ok": True, "cost": {"calls": 1, "model_s": 1.0, "tok_in": 4, "tok_out": 2}}

        replay_parts = {
            "B": O.Part(
                "B",
                calls=[{"call": "B_worked"}],
                model=None,
                info={"model": "larger", "prompt_form": "worked"},
            )
        }
        source = O.PartsSource(probe, replay_parts)
        parent = O.OmniNode(
            O.contract_for(
                O.profile_of(TASK),
                {
                    "budget.depth": 1,
                    "budget.nodes": 2,
                    "permissions.spawn": True,
                    "resources.parts": ["B"],
                    "resources.models": ["small"],
                },
            ),
            O.PARAMETERS,
        )
        with self.assertRaises(O.ContractError):
            parent.spawn(parent.derive({"resources.models": ["larger"]}), O.PARAMETERS.with_({"arrangement": [["B", "take"]]}))
        self.assertEqual(parent.children, [])

        child = parent.spawn(parent.derive(), O.PARAMETERS.with_({"arrangement": [["B", "take"]]}))
        with self.assertRaises(O.ContractError):
            child.run(TASK, source)
        self.assertEqual(probe_calls, [])

    def test_runtime_refuses_part_model_via_parameters_evidence_and_store(self):
        for mode in ("shared_param", "part_param", "evidence", "configured_store"):
            with self.subTest(mode=mode):
                calls = []
                source = O.PartsSource(
                    None,
                    {"B": O.Part("B", model="small", value=lambda task: calls.append(task["id"]) or 9)},
                )
                params = {"arrangement": [["B", "take"]]}
                resolver = O.Resolver()
                if mode == "shared_param":
                    params["part.model"] = "larger"
                elif mode == "part_param":
                    params["part.B.model"] = "larger"
                elif mode == "evidence":
                    resolver = O.Resolver(evidence={"part.B.model": {"value": "larger", "source": "recorded"}})
                node = O.OmniNode(
                    O.CONTRACT.with_({"output.form": "number", "resources.parts": ["B"], "resources.models": ["small"]}),
                    O.PARAMETERS.with_(params),
                    resolver=resolver,
                )
                if mode == "configured_store":
                    admitted = O.PARAMETERS.with_({"arrangement": [["B", "take"]], "part.B.model": "larger"})
                    store = SimpleNamespace(nearest=lambda *a: {"parameters": admitted, "key": "profile-a", "tried": ["profile-a"]})
                    node.configure(TASK, store)
                with self.assertRaises(O.ContractError):
                    node.run(TASK, source)
                self.assertEqual(calls, [])

    def test_required_model_and_info_metadata_enforced_before_callable(self):
        cases = (
            ("required_model_field", O.Part("B", required_model="larger", value=lambda _: 9), {}),
            ("info_required_model", O.Part("B", info={"required_model": "larger"}, value=lambda _: 9), {}),
            ("conflicting_part_models", O.Part("B", model="small", required_model="larger", value=lambda _: 9), {}),
            (
                "conflicting_resolved_vs_required",
                O.Part("B", required_model="small", value=lambda _: 9),
                {"part.B.model": "small"},
            ),
            ("malformed_numeric_model", O.Part("B", info={"model": 123}, value=lambda _: 9), {}),
            ("malformed_blank_model", O.Part("B", required_model="   ", value=lambda _: 9), {}),
        )
        for label, part_obj, extra_params in cases:
            with self.subTest(case=label):
                calls = []
                part_obj.value = lambda task, c=calls: c.append(task["id"]) or 9
                node = O.OmniNode(
                    O.CONTRACT.with_({"output.form": "number", "resources.models": ["small"]}),
                    O.PARAMETERS.with_({"arrangement": [["B", "take"]], **extra_params}),
                )
                if label == "conflicting_resolved_vs_required":
                    record = node.run(TASK, O.PartsSource(None, {"B": part_obj}))
                    self.assertTrue(record.accepted)
                    self.assertEqual(record.answer, 9)
                    self.assertEqual(calls, [TASK["id"]])
                else:
                    with self.assertRaises(O.ContractError):
                        node.run(TASK, O.PartsSource(None, {"B": part_obj}))
                    self.assertEqual(calls, [])

        calls = []
        override_conflict = O.OmniNode(
            O.CONTRACT.with_({"output.form": "number", "resources.models": ["small", "larger"]}),
            O.PARAMETERS.with_({"arrangement": [["B", "take"]], "part.B.model": "small"}),
        )
        with self.assertRaises(O.ContractError):
            override_conflict.run(
                TASK,
                O.PartsSource(None, {"B": O.Part("B", required_model="larger", value=lambda t: calls.append(t["id"]) or 9)}),
            )
        self.assertEqual(calls, [])

    def test_multi_generation_ancestor_chain_monotonic_model_narrowing(self):
        root = O.OmniNode(
            O.CONTRACT.with_(
                {
                    "output.form": "number",
                    "budget.depth": 3,
                    "budget.nodes": 3,
                    "permissions.spawn": True,
                    "resources.models": ["small", "medium"],
                }
            ),
            O.PARAMETERS,
        )
        mid = root.spawn(root.derive({"budget.nodes": 2, "permissions.spawn": True, "resources.models": ["small"]}))
        self.assertEqual(mid.derive()["resources.models"].suggested[0], ["small"])
        with self.assertRaises(O.ContractError):
            mid.spawn(mid.derive({"resources.models": ["medium"]}))
        leaf = mid.spawn(mid.derive(), O.PARAMETERS.with_({"arrangement": [["B", "take"]], "part.B.model": "larger"}))
        mid.contract = mid.contract.with_({"resources.models": None})
        leaf.contract = leaf.contract.with_({"resources.models": None})
        calls = []
        with self.assertRaises(O.ContractError):
            leaf.run(TASK, O.PartsSource(None, {"B": O.Part("B", value=lambda t: calls.append(t["id"]) or 9)}))
        self.assertEqual(calls, [])

    def test_permissions_models_alias_and_empty_allowlist_behavior(self):
        parent = O.OmniNode(
            O.CONTRACT.with_(
                {
                    "output.form": "number",
                    "budget.depth": 1,
                    "budget.nodes": 2,
                    "permissions.spawn": True,
                    "permissions.models": ["small"],
                }
            ),
            O.PARAMETERS,
        )
        with self.assertRaises(O.ContractError):
            parent.spawn(parent.derive({"permissions.models": ["larger"]}))
        child = parent.spawn(parent.derive(), O.PARAMETERS.with_({"arrangement": [["B", "take"]]}))
        self.assertEqual(child.effective_models(), ["small"])

        calls = []
        with self.assertRaises(O.ContractError):
            child.run(
                TASK,
                O.PartsSource(None, {"B": O.Part("B", required_model="larger", value=lambda t: calls.append(t["id"]) or 9)}),
            )
        self.assertEqual(calls, [])

        ok_record = child.run(
            TASK,
            O.PartsSource(None, {"B": O.Part("B", model="small", value=lambda t: calls.append(t["id"]) or 9)}),
        )
        self.assertTrue(ok_record.accepted)
        self.assertEqual(ok_record.answer, 9)

        empty_node = O.OmniNode(
            O.CONTRACT.with_({"output.form": "number", "resources.models": []}),
            O.PARAMETERS.with_({"arrangement": [["probe_part", "take"]]}),
        )
        probe_calls = []
        with self.assertRaises(O.ContractError):
            empty_node.run(
                TASK,
                O.PartsSource(
                    lambda c, t, seed=None: probe_calls.append(c) or {"answer": 9, "ok": True, "cost": {}},
                    {"probe_part": O.Part("probe_part", calls=[{"call": "c1"}])},
                ),
            )
        self.assertEqual(probe_calls, [])

        exact_node = O.OmniNode(
            O.CONTRACT.with_({"output.form": "number", "resources.models": []}),
            O.PARAMETERS.with_({"arrangement": [["calc", "take"]]}),
        )
        exact_record = exact_node.run(TASK, O.PartsSource(None, {"calc": O.Part("calc", value=lambda _: 9)}))
        self.assertTrue(exact_record.accepted)
        self.assertEqual(exact_record.answer, 9)

    def test_zero_and_exhausted_model_calls_budget(self):
        calls = []
        zero_calls_node = O.OmniNode(
            O.CONTRACT.with_({"output.form": "number", "budget.model_calls": 0}),
            O.PARAMETERS.with_({"arrangement": [["B", "take"]], "stop_rules": []}),
        )
        stopped = zero_calls_node.run(
            TASK,
            O.PartsSource(None, {"B": O.Part("B", model="small", value=lambda t: calls.append(t["id"]) or 9)}),
        )
        self.assertEqual(calls, [])
        self.assertFalse(stopped.accepted)
        self.assertEqual(stopped.steps, [])
        self.assertIn("model calls", stopped.reason)

        probe_calls = []

        def probe(call_name, task, seed=None):
            probe_calls.append(call_name)
            return {"answer": None, "ok": False, "cost": {"calls": 1, "model_s": 0.5, "tok_in": 2, "tok_out": 1}}

        one_call_node = O.OmniNode(
            O.CONTRACT.with_({"output.form": "number", "budget.model_calls": 1}),
            O.PARAMETERS.with_({"arrangement": [["miss", "take"], ["second", "take"]], "stop_rules": []}),
        )
        one_record = one_call_node.run(
            TASK,
            O.PartsSource(
                probe,
                {
                    "miss": O.Part("miss", calls=[{"call": "p1"}]),
                    "second": O.Part("second", value=lambda t: probe_calls.append("second") or 9),
                },
            ),
        )
        self.assertEqual(probe_calls, ["p1"])
        self.assertFalse(one_record.accepted)
        self.assertEqual(len(one_record.steps), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
