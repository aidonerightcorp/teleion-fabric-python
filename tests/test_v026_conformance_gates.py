# Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md
"""Mechanical AST zero-magic-literal, domain-agnostic naming, and settings grid conformance gates."""
import ast
import inspect
import re
import unittest

import stepkit.omninode as omninode_mod
import stepkit.retention as retention_mod
import teleion_fabric.boundary_provenance as boundary_mod
import teleion_fabric.prose_tools as prose_mod
from teleion_fabric.settings import load, select

ALLOWED_NUMERIC_IDENTITIES = {-1, 0, 1, 0.0, 1.0}
FORBIDDEN_DOMAIN_TERMS = (
    "real_estate",
    "realestate",
    "mortgage",
    "parcel",
    "healthcare",
    "hospitality",
    "fintech",
    "ecommerce",
)


def _numeric_violations(source_text: str, label: str) -> list:
    tree = ast.parse(source_text, filename=label)
    violations = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            if node.value not in ALLOWED_NUMERIC_IDENTITIES:
                violations.append((label, getattr(node, "lineno", 0), node.value))
        elif (
            isinstance(node, ast.UnaryOp)
            and isinstance(node.op, ast.USub)
            and isinstance(node.operand, ast.Constant)
            and isinstance(node.operand.value, (int, float))
            and not isinstance(node.operand.value, bool)
        ):
            if -node.operand.value not in ALLOWED_NUMERIC_IDENTITIES:
                violations.append((label, getattr(node, "lineno", 0), -node.operand.value))
    return violations


class V026ConformanceGates(unittest.TestCase):
    def test_zero_hardcoded_values_ast_gate(self):
        targets = (
            ("stepkit.retention", inspect.getsource(retention_mod)),
            ("teleion_fabric.boundary_provenance", inspect.getsource(boundary_mod)),
            ("prose_tools.strict_json", inspect.getsource(prose_mod.strict_json)),
            ("prose_tools.diagnose_json_boundary", inspect.getsource(prose_mod.diagnose_json_boundary)),
            ("omninode._part_model_labels", inspect.getsource(omninode_mod._part_model_labels)),
        )
        violations = []
        for label, src in targets:
            violations.extend(_numeric_violations(src, label))
        self.assertEqual(violations, [])

    def test_domain_agnostic_naming_gate(self):
        pattern = re.compile("|".join(FORBIDDEN_DOMAIN_TERMS), re.IGNORECASE)
        for mod in (retention_mod, boundary_mod, prose_mod):
            self.assertIsNone(pattern.search(mod.__name__))
            tree = ast.parse(inspect.getsource(mod), filename=mod.__name__)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    self.assertIsNone(pattern.search(node.name), f"domain-coupled symbol {node.name}")

    def test_retention_and_boundary_settings_grids(self):
        for resource_name in ("retention", "boundary"):
            raw = load(resource_name)
            selected = select(raw)
            self.assertTrue(selected)
            first_key = next(iter(raw))
            with self.assertRaises(ValueError):
                select(raw, {first_key: "__not_in_grid__"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
