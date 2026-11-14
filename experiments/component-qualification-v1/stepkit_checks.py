# Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md
"""Individual installed-stepkit behavioral contracts; no provider calls.

Run with the target environment's python -I, outside the source checkout.
Fixtures are authored tiny inputs using existing stepkit mechanisms. These are
bounded mechanism checks, not historical benchmark replays or release approval.
"""
import argparse
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import tempfile
import traceback


class Checks:
    def __init__(self):
        self.items = []

    def equal(self, name, actual, expected):
        ok = actual == expected
        self.items.append({"name": name, "status": "pass" if ok else "fail",
                           "actual": actual, "expected": expected})

    def raises(self, name, error_type, call):
        try:
            call()
        except error_type as error:
            self.items.append({"name": name, "status": "pass", "exception": type(error).__name__})
        except Exception as error:
            self.items.append({"name": name, "status": "fail", "error": repr(error),
                               "expected_exception": error_type.__name__})
        else:
            self.items.append({"name": name, "status": "fail", "error": "expected exception not raised",
                               "expected_exception": error_type.__name__})


def initializer(m, c):
    c.equal("declared exports resolve", all(hasattr(m, key) for key in m.__all__), True)
    c.equal("exports are nonempty and unique", bool(m.__all__) and len(set(m.__all__)) == len(m.__all__), True)


def answers(m, c):
    c.equal("comma number parsing", m.to_number("1,234.5"), 1234.5)
    c.equal("relative numeric equivalence", m.same_answer(100, 100.01), True)
    c.equal("different values rejected", m.same_answer(2, 9), False)
    c.equal("missing value type", m.plain_value(None), (None, "none"))


def sources(m, c):
    tasks = [{"kind": k, "id": str(i)} for i, k in enumerate(["a", "b", "a", "a"])]
    result = m.split_by_position(tasks, n_library=1, n_fit=2)
    c.equal("per-kind positional split", [(r["pos"], r["split"]) for r in result],
            [(0, "library"), (0, "library"), (1, "fit"), (2, "test")])
    c.equal("source dictionaries unchanged", all("split" not in r for r in tasks), True)


def assembler(m, c):
    stages = [("calc", "take"), ("small", "agree")]
    c.equal("arrangement roundtrip", m.parse(m.show(stages, bare=("calc",))), stages)
    c.equal("held-back gate admits equal results", m.admission([True, False], [True, False], 0, 2)["admitted"], True)
    c.equal("held-back gate rejects regression", m.admission([False, False], [True, True], 0, 2)["admitted"], False)
    c.equal("held-back gate rejects insufficient sample", m.admission([True], [False], 0, 2)["admitted"], False)


def attributes(m, c):
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "ledger.jsonl")
        ledger = m.Ledger(path, when="2026-11-13T00:00:00Z")
        first = ledger.append(m.AttributeRecord("fixture", "evidence.set", ["r1"]))
        ledger.append(m.AttributeRecord("fixture", "evidence.set", ["r1"]))
        c.equal("content-addressed deduplication", len(ledger), 1)
        replacement = ledger.supersede([first.id], m.AttributeRecord("fixture", "evidence.set", ["r2"]))
        restored = m.Ledger(path)
        c.equal("supersession retains old record", (len(restored), restored.is_current(restored.get(first.id)),
                restored.is_current(restored.get(replacement.id))), (2, False, True))
        c.raises("maker cannot check own claim", ValueError,
                 lambda: m.AttributeRecord("fixture", "evidence.set", [], checks=[first.id],
                                           maker={"id": "same"}, checker={"id": "same"}))


def decide(m, c):
    calls = []
    def probe(node, task, step_input=None, seed=None):
        calls.append(node)
        answer = None if node == "tool" else 36
        return {"answer": answer, "ok": answer is not None, "cost": {"calls": 1, "model_s": 1.5}}
    trace = m.first_accepted({"id": "t1", "question": "3 boxes of 12 pens. How many pens?"},
                             [("tool", m.has_answer), ("small", m.has_answer), ("large", m.always)], probe)
    c.equal("fallback stops at accepted node", calls, ["tool", "small"])
    c.equal("chosen answer and acceptance trace", (trace.answer, [s.accepted for s in trace]), (36, [False, True]))
    c.equal("only attempted costs charged", trace.total_cost()["calls"], 2)


def dimension(m, c):
    d = m.Dimension("fixture.count", [2], grid=[1, 2, 3], kind=m.NUMBERS, limits={"min": 1, "max": 3})
    c.equal("resolver default", m.Resolver().value(d), 2)
    c.equal("caller narrowing", m.Resolver().value(d.narrowed(3)), 3)
    c.equal("dimension serialization", m.Dimension.from_dict(d.to_dict()).to_dict(), d.to_dict())
    c.raises("hard limit refusal", m.LimitError, lambda: d.narrowed(4))


def live(m, c):
    # Do not call _load/request/__call__: all need unbundled historical files.
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "attempts.jsonl"
        probe = m.LiveProbes(attempts_path=str(path))
        probe._write({"node": "fixture", "error": "authored failure"})
        row = json.loads(path.read_text())
        c.equal("local failure log retained", (row["node"], row["error"]), ("fixture", "authored failure"))
        c.equal("tool-only cost has no provider calls", probe._cost(None, 2)["calls"], 0)
    c.items.append({"name": "live execution", "status": "blocked",
                    "reason": "LiveProbes._load requires unbundled toolsmith/benchmark/spec files; no provider calls authorized"})


def omninode(m, c):
    store = m.ProvenStore()
    params = m.Parameters()
    store.put("fixture", params, admitted=False)
    c.equal("unadmitted parameters withheld", store.get("fixture"), None)
    c.equal("negative gate does not admit", store.admit("fixture", params, {"admitted": False}), False)
    c.equal("positive gate admits", store.admit("fixture", params, {"admitted": True}), True)
    c.equal("admitted parameters available", isinstance(store.get("fixture"), m.Parameters), True)
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "store.json")
        store.save(path)
        c.equal("admitted parameters survive persistence", isinstance(m.ProvenStore.load(path).get("fixture"), m.Parameters), True)


def profile(m, c):
    c.equal("numeric output normalized", m.output_profile("How many?", "12", form="number")["answer"], 12.)
    c.equal("nonfinite output rejected", m.output_profile("How many?", float("inf"), form="number")["form_ok"], False)
    c.equal("missing answer lowers agreement", m.agreement([2, 2, None])["top_share"], 2 / 3)
    c.equal("grounded literals accepted", m.grounded_numbers("12 * 3", "12 boxes with 3 items")["ok"], True)
    c.equal("invented literal rejected", m.grounded_numbers("12 * 9", "12 boxes with 3 items")["ok"], False)


def quota(m, c):
    events = [{"event": m.RESERVE, "route": "fixture", "day": "2026-11-13", "id": "a", "who": "one"},
              {"event": m.RESERVE, "route": "fixture", "day": "2026-11-13", "id": "b", "who": "two"},
              {"event": m.SETTLE, "id": "a", "ran": False}]
    c.equal("never release reserved attempts", m._used(events, "fixture", "2026-11-13", m.RELEASE_NEVER), 2)
    c.equal("release only not-started attempts", m._used(events, "fixture", "2026-11-13", m.RELEASE_IF_NOT_STARTED), 1)
    c.equal("caller isolation", m._used(events, "fixture", "2026-11-13", m.RELEASE_NEVER, who="one"), 1)
    c.equal("day isolation", m._used(events, "fixture", "2026-11-14", m.RELEASE_NEVER), 0)


def record(m, c):
    trace = m.Trace("fixture")
    trace.append(m.StepRecord("fixture", 1, "calc", answer=6, accepted=True, cost=m.cost_of({"calls": 1, "tool_ms": 2})))
    trace.finish(6, "calculated")
    c.equal("trace roundtrip", m.Trace.from_json(trace.to_json()).to_dict(), trace.to_dict())
    c.equal("cost aggregation", m.add_costs([{"calls": 1}, {"calls": 2}])["calls"], 3)
    c.equal("accepted step retained", trace.accepted_step.answer, 6)


def reply(m, c):
    c.equal("correct equation", m.check_equations("2 + 3 = 5")["false"], 0)
    c.equal("incorrect equation detected", m.check_equations("2 + 3 = 9")["false"], 1)
    c.equal("equation actually checked", m.check_equations("2 + 3 = 5")["checked"], 1)
    c.equal("perfect ranking AUC", m.auc([0, 1], [False, True]), 1.)
    c.equal("tied ranking AUC", m.auc([1, 1], [False, True]), .5)
    c.raises("single class AUC refused", ValueError, lambda: m.auc([1], [True]))


def store(m, c):
    s = m.CheckedStore()
    s.add("good", "apples", {"answer": 1}, checked=True, vector=[1., 0.])
    s.add("unchecked", "apples", {"answer": 2}, checked=False, vector=[1., 0.])
    s.add("other", "pears", {"answer": 3}, checked=True, vector=[0., 1.])
    c.equal("nearest vector honors checked filter", [r["key"] for r in s.nearest(vector=[1., 0.], k=3)], ["good", "other"])
    c.equal("exclusion avoids self retrieval", [r["key"] for r in s.nearest(vector=[1., 0.], k=3, exclude=["good"])], ["other"])
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "store.json")
        s.save(path)
        c.equal("payload persistence", m.CheckedStore.load(path).get("good")["payload"], {"answer": 1})


def tier_ladder(m, c):
    chain = []
    m.advance(chain, "attempted")
    c.raises("state cannot be skipped", m.StateError, lambda: m.advance(chain, "accepted", score=1, bar=1, verifier="b", maker="a"))
    m.advance(chain, "artifact_valid", digest="fixture-digest")
    m.advance(chain, "score_valid", score=1)
    c.raises("self-verification rejected", m.StateError, lambda: m.advance(chain, "accepted", score=1, bar=1, verifier="a", maker="a"))
    m.advance(chain, "accepted", score=1, bar=1, verifier="b", maker="a")
    c.equal("valid ordered acceptance", chain[-1]["state"], "accepted")
    m.advance(chain, "invalidated", why="fixture invalidation")
    c.raises("invalidated result is terminal", m.StateError, lambda: m.advance(chain, "attempted"))


def safe_runner(m, c):
    result = m.run_program("answer = sum([2, 3, 4])", timeout_s=2)
    c.equal("child process computes bounded program", (result["ok"], result["answer"]), (True, 9))
    refused = m.run_program("import os\nanswer = os.getcwd()", timeout_s=2)
    c.equal("forbidden import refused", (refused["ok"], refused["answer"]), (False, None))
    c.equal("refusal carries reason", bool(refused["error"]), True)


def calculator(m, c):
    c.equal("decimal expression", m.calculate("1.5 * 4 ="), 6.)
    c.equal("division by zero refused", m.calculate("1 / 0 ="), None)
    c.equal("prose is not executable arithmetic", m.calculate("Please read a file"), None)


def options(m, c):
    question = "Choose:\n(A) 12\n(B) 14"
    c.equal("option parse preserves order", m.parse_options(question), [("A", "12"), ("B", "14")])
    c.equal("number selects unique option", m.match(14, None, question), ("B", None))
    c.equal("ambiguous answer refused", m.match(12, None, "(A) 12\n(B) 12"), (None, "more than one option matched"))
    c.equal("unknown answer refused", m.match(99, None, question), (None, "no option matched"))


def programs(m, c):
    c.equal("arithmetic assignment sequence", m.run_arithmetic("x = 3\nanswer = x * 2"), (6, None))
    bad = m.run_arithmetic("x = 3")
    c.equal("missing answer is recorded failure", bad[0] is None and bool(bad[1]), True)
    c.equal("fenced code extraction", m.extract("```python\nx = 3\nprint(x)\nanswer = x * 2\n```"), "x = 3\nanswer = x * 2")
    result = m.run("answer = 6 * 5", timeout_s=2)
    c.equal("public runner wrapper computes", (result["ok"], result["answer"]), (True, 30))


def variants(m, c):
    mention = m.DateMention(0, 0, "ymd", (2000, 2, 29), "mdy_numeric", "")
    rendered = m.write_date(mention, "iso")
    found = m.date_mentions("Today is " + rendered + ".")
    c.equal("leap date render/parse roundtrip", [(x.kind, x.value) for x in found], [("ymd", (2000, 2, 29))])
    c.equal("invalid calendar date excluded", m.date_mentions("Today is 12/32/1929."), [])


# Explicit migration-entry ownership. A scoped pass never covers the limitations.
CONTRACTS = {
    "stepkit.__init__": (initializer, "Package export integrity", "No engine behavior qualified", "packaging_only"),
    "stepkit._answers": (answers, "Numeric parsing/equality and missing value typing", "Not all answer kinds or adversarial text", "pass_scoped"),
    "stepkit._sources": (sources, "Pure per-kind split boundaries and input preservation", "Historical by-path loaders/artifacts remain unavailable", "pass_scoped"),
    "stepkit.assembler": (assembler, "Arrangement roundtrip and admission gate boundaries", "No optimizer search, learned selection or held-out benefit measured", "pass_scoped"),
    "stepkit.attributes": (attributes, "Ledger deduplication, persistence, supersession and self-check refusal", "No statistical shrinkage calibration or historical evidence reapproval", "pass_scoped"),
    "stepkit.decide": (decide, "Authored first-accepted fallback and cost trace", "Authored probe; no live model or predictive decision quality", "pass_scoped"),
    "stepkit.dimension": (dimension, "Numeric dimension selection, serialization and hard bounds", "No full grid strategy/JOINT/STRUCTURED validation", "pass_scoped"),
    "stepkit.live": (live, "Local log writing and tool cost formatting only; live execution blocked", "Unbundled benchmark/spec dependencies; no model server/provider execution", "blocked"),
    "stepkit.omninode": (omninode, "ProvenStore admission visibility and persistence", "No full OmniNode orchestration, external sources or optimization benefit", "pass_scoped"),
    "stepkit.profile": (profile, "Output normalization, nonfinite refusal, agreement and grounded literals", "No profiler predictive calibration or all domain profiles", "pass_scoped"),
    "stepkit.quota": (quota, "Pure reservation accounting across release rules/callers/days", "No operator caps file, locking/concurrency or live quota enforcement tested", "pass_scoped"),
    "stepkit.record": (record, "Trace serialization, accepted step and cost aggregation", "No distributed persistence or external telemetry validation", "pass_scoped"),
    "stepkit.reply": (reply, "Arithmetic equation checks and exact AUC boundary fixtures", "No trained ReplyChecker artifact, fit or held-out calibration", "pass_scoped"),
    "stepkit.store": (store, "Checked-vector retrieval, exclusion and persisted payload", "No semantic embedding provider or retrieval quality benchmark", "pass_scoped"),
    "stepkit.tier_ladder": (tier_ladder, "Ordered state transitions, self-check refusal and terminal invalidation", "No live tiers, paired benchmark, promotion benefit or queue replacement", "pass_scoped"),
    "stepkit.tools.__init__": (initializer, "Tool export integrity", "No engine behavior qualified", "packaging_only"),
    "stepkit.tools._safe_runner": (safe_runner, "Bounded child execution and prohibited-import refusal", "Not a security audit; timeout/memory adversarial limits not exhaustively exercised; POSIX required", "pass_scoped"),
    "stepkit.tools.calculator": (calculator, "Arithmetic result, zero-division and prose refusal", "No broad numerical correctness or arbitrary natural-language solving", "pass_scoped"),
    "stepkit.tools.options": (options, "Option parsing, unique match and ambiguous/missing refusal", "No all date/text matching corner cases", "pass_scoped"),
    "stepkit.tools.programs": (programs, "Arithmetic sequence, missing-answer failure, extraction and runner wrapper", "No generated-program quality or security certification", "pass_scoped"),
    "stepkit.variants": (variants, "Leap-date render/parse and invalid-date rejection", "No historical variant generation/admission or tracking domain evaluation", "pass_scoped"),
}


def run(component):
    c = Checks()
    fn, scope, limit, status = CONTRACTS[component]
    out = {"component": component, "status": status, "checks": c.items,
           "scope": scope, "limits": [limit, "Local authored fixtures; not Kaggle evidence or independent release approval"]}
    try:
        version = importlib.metadata.version("teleion-fabric")
        roots = {name: str(Path(importlib.import_module(name).__file__).resolve()) for name in ("stepkit", "teleion_fabric")}
        out["environment"] = {"version": version, "prefix": sys.prefix, "origins": roots}
        if version != "0.2.0":
            raise RuntimeError("these frozen contracts require installed teleion-fabric 0.2.0")
        if not all(Path(path).is_relative_to(Path(sys.prefix).resolve()) and "site-packages" in Path(path).parts for path in roots.values()):
            raise RuntimeError("both package origins must be installed site-packages inside target environment")
        target = component.removesuffix(".__init__")
        module = importlib.import_module(target)
        origin = Path(module.__file__).resolve()
        out["module_origin"] = str(origin)
        if not origin.is_relative_to(Path(roots["stepkit"]).parent):
            raise RuntimeError("target module is outside installed stepkit")
        fn(module, c)
    except ModuleNotFoundError as error:
        out.update(status="blocked", error={"type": type(error).__name__, "message": str(error)})
        c.items.append({"name": "dependency availability", "status": "blocked", "missing": error.name})
    except Exception as error:
        out.update(status="fail", error={"type": type(error).__name__, "message": str(error), "traceback": traceback.format_exc()})
    if any(item["status"] == "fail" for item in c.items):
        out["status"] = "fail"
        out.setdefault("error", {"type": "CheckFailure", "message": "one or more behavioral expectations failed; see checks"})
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--component", required=True, choices=sorted(CONTRACTS))
    args = parser.parse_args()
    for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ[key] = "2"
    result = run(args.component)
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 1 if result["status"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
