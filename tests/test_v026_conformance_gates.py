# Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md
"""Mechanical AST zero-magic-literal, domain-agnostic naming, settings grid, and public hygiene gates."""
import ast
import hashlib
import inspect
from pathlib import Path
import re
import subprocess
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
FORBIDDEN_TOKEN_SHA256 = frozenset(
    (
        "250cbac9037ac2bf5b7ae28410f9a7fc5a5d14bdd0c2208a1fb78dd94d23b84f",
        "2f1e83d30fff12f10f4a956d08bd6b200ae89e24621c2066c1a902aab2da7acb",
        "4322a6b237d4d0f47990bad6edf90913cd88d2a1a6a9698a756b73e4dfd69329",
        "4e381c0c4a030b7d7400d79b5075afc82231c2c0f812db2489aeb17e76a6f8c0",
        "6a7fe783de7cc1b32cb7a035115841b2f03a7fe014a2b3e61f07e91af5deec25",
        "76e3c7bfe641ea125c0c2e1c5f89349e17b352ed128d528de2443794e7acf870",
        "9410a442dd664c9234966c5ecc0ff595431749474bc67b7e2ce5ccaaed7793ec",
        "9487383d51a2ced05ed2fd66f7789f51794e8eba04167737518fcd3b1b558499",
        "b3cc0475bb78a5026098858e9889acf666d31062d513d303314eca31d36e72f2",
        "b9202caba466d1bf108f5143959b9fc897a6ca3d881ef96cfa332bbadc7da774",
        "c33ad02d415db403ff4336eb3cd3de97c05f144cfe50816b450c3968bc187580",
        "c56a6b2453ec7e601ec43eb9eff3dc57639b189b4047f36c854bbc97d3e31611",
        "d488476689bd8ff0424956c989ae7508815f2821f9524dfd3ea5aea931911978",
        "fc5a1047f5919892fcdf8aa79ea5d6bb6531b5c176939ef0110906cb225941c1",
    )
)
FORBIDDEN_SUBSTRING_CODEPOINTS = (
    (47, 104, 111, 109, 101, 47),
    (108, 108, 97, 109, 97),
    (111, 108, 108, 97, 109, 97),
    (115, 121, 110, 116, 104, 101, 116, 105, 99),
    (98, 97, 108, 116, 111, 114),
    (116, 97, 101, 100, 114, 105),
    (107, 111, 116, 104, 97, 114),
    (116, 101, 115, 115, 101, 114, 97),
    (110, 97, 110, 111, 109, 117, 115, 101),
)
ALWAYS_WORD_TAIL_CODEPOINTS = (97, 109, 97)


def _decode_codepoints(seq: tuple) -> str:
    return "".join(chr(c) for c in seq)


def _scan_text_hygiene(label: str, text: str) -> list:
    hits = []
    lowered = text.lower()
    always_regex = re.compile(r"\bl+" + _decode_codepoints(ALWAYS_WORD_TAIL_CODEPOINTS) + r"\b", re.IGNORECASE)
    if always_regex.search(text):
        hits.append((label, "always_regex"))
    for seq in FORBIDDEN_SUBSTRING_CODEPOINTS:
        sub = _decode_codepoints(seq)
        if sub in lowered:
            hits.append((label, "forbidden_substring:" + hashlib.sha256(sub.encode("utf-8")).hexdigest()[:12]))
    for token in re.findall(r"[a-z0-9]+", lowered):
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        if digest in FORBIDDEN_TOKEN_SHA256:
            hits.append((label, "forbidden_token:" + digest[:12]))
    return hits


def _repository_files(repo_root: Path) -> list:
    if (repo_root / ".git").exists():
        raw = subprocess.check_output(["git", "-C", str(repo_root), "ls-files", "-z"])
        rels = [entry.decode("utf-8") for entry in raw.split(b"\x00") if entry]
        return [repo_root / rel for rel in sorted(rels) if (repo_root / rel).is_file()]
    skipped = {"__pycache__", ".git", "build", "dist"}
    collected = []
    for path in sorted(repo_root.rglob("*")):
        if not path.is_file():
            continue
        parts = path.relative_to(repo_root).parts
        if any(part in skipped or part.endswith(".egg-info") for part in parts):
            continue
        collected.append(path)
    return collected


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

    def test_public_repository_hygiene_gate(self):
        repo_root = Path(__file__).resolve().parents[1]
        files = _repository_files(repo_root)
        self.assertGreater(len(files), 0)
        violations = []
        for path in files:
            rel = str(path.relative_to(repo_root))
            violations.extend(_scan_text_hygiene(rel, path.read_text(encoding="utf-8", errors="replace")))
        self.assertEqual(violations, [])

        # Negative self-checks verify the gate catches path, always-word, and codename leaks
        for seq in FORBIDDEN_SUBSTRING_CODEPOINTS[:3]:
            self.assertTrue(_scan_text_hygiene("sample", "prefix " + _decode_codepoints(seq) + " suffix"))
        self.assertTrue(_scan_text_hygiene("sample_codename", "stepkit." + _decode_codepoints((116, 97, 101, 100, 114, 105)) + "_bridge"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
