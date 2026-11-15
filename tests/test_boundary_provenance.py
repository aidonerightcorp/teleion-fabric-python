# Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md
"""Offline unit tests for BoundaryProvenance and fail-closed strict-output diagnostics."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from teleion_fabric import BoundaryProvenance, diagnose_json_boundary, strict_json
from teleion_fabric import opencode_omninode as Node


class BoundaryProvenanceAndDiagnosisTests(unittest.TestCase):
    def test_unicode_exact_body_hashes_and_detached_snapshot(self):
        provenance = BoundaryProvenance("attempt-1", "fixture-model")
        provenance.bind("task-1", "attempt-1")
        content = "é 雪\n{\"status\":\"ok\"}"
        payloads = {
            "native_request": b'{"prompt":"Unicode \xe9\x9b\xaa"}',
            "native_response": json.dumps({"content": content}, ensure_ascii=False).encode("utf-8"),
            "native_content": content.encode("utf-8"),
            "emitted_response": json.dumps({"choices": [{"text": content}]}, ensure_ascii=False).encode("utf-8"),
        }
        for name, body in payloads.items():
            provenance.capture(name, body)
        provenance.link_harness('{"type":"text"}\n', content)
        snap = provenance.snapshot()
        self.assertEqual(snap["link_status"], "matched")
        for name, body in payloads.items():
            self.assertEqual(snap["boundaries"][name]["sha256"], hashlib.sha256(body).hexdigest())
        dumped = json.dumps(snap)
        self.assertNotIn("Unicode", dumped)
        snap["identity"]["task_id"] = "mutated"
        self.assertEqual(provenance.snapshot()["identity"]["task_id"], "task-1")

    def test_optional_cas_sink_and_reference_validation(self):
        retained = {}

        def valid_sink(body):
            digest = hashlib.sha256(body).hexdigest()
            retained[digest] = body
            return {"digest": digest, "size_bytes": len(body)}

        provenance = BoundaryProvenance("attempt-2", "fixture-model", sink=valid_sink)
        provenance.bind("task-2", "attempt-2")
        entry = provenance.capture("native_request", b"hello")
        self.assertEqual(retained[entry["cas_ref"]["digest"]], b"hello")

        extra_key_sink = BoundaryProvenance(
            "attempt-3",
            "fixture-model",
            sink=lambda b: {"digest": hashlib.sha256(b).hexdigest(), "size_bytes": len(b), "token": "secret-val"},
        )
        with self.assertRaises(RuntimeError):
            extra_key_sink.capture("native_request", b"x")
        self.assertEqual(extra_key_sink.snapshot()["link_status"], "capture_failed")
        self.assertNotIn("secret-val", json.dumps(extra_key_sink.snapshot()))

        def raising_sink(_body):
            raise OSError("sensitive-exception-detail")

        failing = BoundaryProvenance("attempt-4", "fixture-model", sink=raising_sink)
        with self.assertRaises(RuntimeError):
            failing.capture("native_request", b"x")
        snap = failing.snapshot()
        self.assertEqual(snap["link_status"], "capture_failed")
        self.assertEqual(snap["boundaries"]["native_request"]["retention_error_type"], "OSError")
        self.assertNotIn("sensitive-exception-detail", json.dumps(snap))

    def test_partial_unavailable_oversized_and_identity_mismatch(self):
        provenance = BoundaryProvenance("attempt-5", "fixture-model", config_overrides={"max_body_bytes": 65536})
        provenance.bind("task-5", "attempt-5")
        with self.assertRaises(ValueError):
            provenance.bind("other-task", "attempt-5")
        with self.assertRaises(ValueError):
            provenance.bind("task-5", "other-attempt")

        partial = provenance.capture("native_request", b"part", complete=False)
        self.assertEqual(partial["status"], "partial")
        self.assertIn("partial_sha256", partial)
        self.assertNotIn("sha256", partial)

        oversized = provenance.capture("native_response", b"a" * 65537, complete=True)
        self.assertEqual(oversized["status"], "partial")
        self.assertTrue(oversized["truncated_at_cap"])

        provenance.unavailable("emitted_response", "TimeoutError")
        self.assertEqual(provenance.snapshot()["boundaries"]["emitted_response"]["status"], "unavailable")
        provenance.capture("native_content", b"expected")
        provenance.link_harness("out", "expected")
        self.assertEqual(provenance.snapshot()["link_status"], "incomplete")

        mismatch = BoundaryProvenance("attempt-6", "fixture-model")
        mismatch.bind("task-6", "attempt-6")
        for key in ("native_request", "native_response", "emitted_response"):
            mismatch.capture(key, b"ok")
        mismatch.capture("native_content", b"expected")
        mismatch.link_harness("out", "different")
        self.assertEqual(mismatch.snapshot()["link_status"], "text_mismatch")

    def test_strict_json_fail_closed_vs_envelope_and_fence_diagnostics(self):
        clean = diagnose_json_boundary('["001", "002"]', "array")
        self.assertTrue(clean["strict_valid"])
        self.assertEqual(clean["value"], ["001", "002"])
        self.assertEqual(clean["failure_kind"], "none")
        self.assertFalse(clean["contamination_detected"])
        self.assertFalse(clean["task_accepted"])
        self.assertFalse(clean["execution_authorized"])

        prefixed = '<system-reminder>operational reminder</system-reminder>\n{"count": 3}'
        self.assertFalse(strict_json(prefixed, "object")["strict_valid"])
        self.assertIsNone(strict_json(prefixed, "object")["value"])
        diag_prefix = diagnose_json_boundary(prefixed, "object")
        self.assertFalse(diag_prefix["strict_valid"])
        self.assertIsNone(diag_prefix["value"])
        self.assertEqual(diag_prefix["failure_kind"], "envelope_prefix_only")
        self.assertTrue(diag_prefix["leading_envelope_prefix"])
        self.assertEqual(diag_prefix["contamination_layers"], ["instruction_envelope"])
        self.assertEqual(diag_prefix["diagnostic_candidate"], {"count": 3})
        self.assertTrue(diag_prefix["diagnostic_only"])
        self.assertFalse(diag_prefix["task_accepted"])

        fenced = '```json\n["001"]\n```'
        self.assertFalse(strict_json(fenced, "array")["strict_valid"])
        diag_fence = diagnose_json_boundary(fenced, "array")
        self.assertFalse(diag_fence["strict_valid"])
        self.assertEqual(diag_fence["failure_kind"], "markdown_fence_only")
        self.assertEqual(diag_fence["diagnostic_candidate"], ["001"])
        self.assertTrue(diag_fence["diagnostic_only"])

        mixed = '<system-reminder>note</system-reminder>\nHere is the array:\n```json\n[1, 2]\n```'
        diag_mixed = diagnose_json_boundary(mixed, "array")
        self.assertFalse(diag_mixed["strict_valid"])
        self.assertEqual(diag_mixed["failure_kind"], "envelope_and_fence_or_prose")
        self.assertEqual(
            diag_mixed["contamination_layers"],
            ["instruction_envelope", "markdown_fence", "surrounding_prose"],
        )
        self.assertEqual(diag_mixed["diagnostic_candidate"], [1, 2])

        literal_inside_json = '{"note": "<system-reminder>kept as string</system-reminder>"}'
        diag_literal = diagnose_json_boundary(literal_inside_json, "object")
        self.assertTrue(diag_literal["strict_valid"])
        self.assertEqual(diag_literal["failure_kind"], "none")

        ambiguous = "```json\n[1]\n```\n```json\n[2]\n```"
        diag_amb = diagnose_json_boundary(ambiguous, "array")
        self.assertFalse(diag_amb["strict_valid"])
        self.assertEqual(diag_amb["failure_kind"], "ambiguous_embedded_candidates")
        self.assertIsNone(diag_amb["diagnostic_candidate"])

        for bad in ('{"a": 1, "a": 2}', "NaN", "1e999", '"wrong-type"'):
            with self.subTest(bad=bad):
                diag_bad = diagnose_json_boundary(bad, "object")
                self.assertFalse(diag_bad["strict_valid"])
                self.assertEqual(diag_bad["failure_kind"], "type_mismatch_or_malformed_json")
                self.assertIsNone(diag_bad["diagnostic_candidate"])

    def test_opencode_omninode_consume_and_execute_with_provenance(self):
        request = {
            "task_id": "t-boundary",
            "attempt_id": "a-boundary",
            "task": "Return a JSON array.",
            "harness": {"name": "opencode", "model": "fixture", "version": "1.0"},
            "output_contract": {"kind": "json", "json_type": "array"},
        }
        consumed = Node.consume(request, '<system-reminder> tag </system-reminder>\n```json\n["x"]\n```')
        self.assertEqual(consumed["normalized_output"]["value"], ["x"])
        self.assertFalse(consumed["boundary_diagnosis"]["strict_valid"])
        self.assertEqual(consumed["boundary_diagnosis"]["failure_kind"], "envelope_and_fence_or_prose")
        self.assertFalse(consumed["task_accepted"])

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            stub = root / "opencode"
            stub.write_text(
                '#!/usr/bin/env python3\nimport json\nprint(json.dumps({"type": "text", "part": {"text": "[10, 20]"}}))\n',
                encoding="utf-8",
            )
            stub.chmod(0o700)
            env = {**os.environ, "PATH": str(root) + ":" + os.environ["PATH"]}
            for key in ("XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME", "XDG_CONFIG_HOME"):
                env[key] = str(root / key)
            provenance = BoundaryProvenance("a-boundary", "fixture", config_overrides={"required_boundaries": ["native_content", "harness_text"]})
            provenance.capture("native_content", b"[10, 20]")
            saved = []
            result, _ref = Node.execute(request, env, lambda rec: saved.append(rec) or {"idx": len(saved)}, 5, provenance=provenance)
            self.assertTrue(result["boundary_diagnosis"]["strict_valid"])
            self.assertEqual(result["execution_record"]["boundary_provenance"]["link_status"], "matched")
            self.assertEqual(len(saved), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
