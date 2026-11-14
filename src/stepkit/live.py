# Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md
"""A live probe: it runs a node for real. THIS IS THE ONLY PART OF THE KIT THAT CALLS A MODEL.

`LiveProbes` has the same call as `stepkit.decide.RecordedProbes`, so every rule of the kit runs live
with no change. A tool node (the calculator) runs in this process. A model node sends one request to
the local model server, through the call function of the November 9 benchmark, with the prompts of
the benchmarks that made the recorded answers. So a live answer is made the same way as a recorded one.

Nothing is contacted when this module is imported or when a LiveProbes object is made. The first
model node that is called asks the local model server which models it holds.

Sources (under the notes folder), imported by path when the first node is called, not copied:
  work-2026-11-09-real-benchmarks/bench.py               chat, resolve_tags, Meter (the call function)
  work-2026-11-10-node-sizer/mixed/spec.json             the nodes of the mixed benchmark and their prompts
                                                         (direct, worked, program) and token limits
  work-2026-11-10-node-sizer/mixed/bench_mixed.py        h_direct, h_worked, h_program (how a reply is read)
  work-2026-11-12-next-tests/t7-toolsmith/toolsmith.py   RULES, messages, MODELS, MAX_TOKENS, SEED,
                                                         NEIGHBOURS, attempt (the tool-building nodes)
Node names: "T.calc"; "<S or B>.direct", ".worked", ".program" (S is the small model, B the larger
one, as the spec names them); "<S or B>.reuse" (a program written with the nearest checked programs
as examples) and "<S or B>.plus" (the same with no examples).
"""
import json
import os
import re
import threading
import time

from . import _sources as S
from ._answers import answer_kind, parse_answer
from .profile import output_profile
from .record import task_id_of, task_text_of
from .tools import calculator, programs

_ANSWER_TAIL = re.compile(r"Answer:\s*(.*)")
SPEC_FILE = os.path.join(S.MIXED_DIR, "spec.json")


class LiveProbes:
    """Run a node for real: `probe(node_name, task, step_input=None, seed=None) -> dict`.

    store          a `CheckedStore` of checked programs; needed by the ".reuse" nodes only
    vectors        {Task id: text vector}, to find the nearest programs the way the source did; a Task
                   may also carry its own "vector"; with no vector the built-in text similarity is used
    seed           the seed of every call unless a call names one (None: the seed of the source)
    attempts_path  a file that gets one JSON line for EVERY attempt, failures included
    chat, tags     for tests only: a stand-in for the call function, and {model label: server tag}

    The result has "answer", "ok", "form_ok", "why", "reply" (the raw text), "cost", "output_profile",
    "node" and "seed"; a program node adds "code", "answer_type" and "neighbours". A failure of the
    model server is written to the attempts file and raised: it is never turned into an answer.
    """

    def __init__(self, store=None, vectors=None, seed=None, attempts_path=None, chat=None, tags=None):
        self.store = store
        self.vectors = vectors or {}
        self.seed = seed
        self.attempts_path = attempts_path
        self._chat = chat
        self._tags = tags
        self._lock = threading.Lock()
        self._bench = self._toolsmith = self._spec = None

    # ---- the sources, read when first needed ----
    def _load(self):
        if self._spec is None:
            self._toolsmith = S.load_by_path("toolsmith")
            self._bench = self._toolsmith.bench       # the benchmark module that toolsmith itself calls
            with open(SPEC_FILE, encoding="utf-8") as handle:
                self._spec = json.load(handle)
            if self._chat is None:
                self._chat = self._bench.chat
            if self.seed is None:
                self.seed = self._toolsmith.SEED

    def nodes(self):
        """The node names this probe can run."""
        self._load()
        return list(self._spec["probes"]) + [f"{model}.{way}" for model in self._toolsmith.MODELS for way in ("reuse", "plus")]

    def _way(self, node_name):
        """(way, harness settings, model label) of a node. The way is "tool-arithmetic", "direct",
        "worked", "program", "reuse" or "plus"."""
        probe = self._spec["probes"].get(node_name)
        if probe is not None:
            harness = self._spec["harnesses"][probe["harness"]]
            return harness["type"], harness, probe.get("model")
        model, _, way = node_name.partition(".")
        if way in ("reuse", "plus") and model in self._toolsmith.MODELS:
            return way, None, self._toolsmith.MODELS[model]
        raise KeyError(f"unknown node {node_name!r}; this probe can run: {self.nodes()}")

    def _tag(self, label, node_name):
        if self._tags is None:
            self._tags = self._bench.resolve_tags()     # asks the local model server which models it holds
        if label not in self._tags:
            raise RuntimeError(f"node {node_name!r}: its model is not on the local model server")
        return self._tags[label]

    def _examples(self, task, question):
        """The nearest checked programs, most similar last, as the source shows them to the model."""
        if self.store is None:
            raise ValueError("a .reuse node needs a CheckedStore of checked programs: LiveProbes(store=...)")
        task_id = task_id_of(task)
        vector = task.get("vector") if isinstance(task, dict) else None
        if vector is None:
            vector = self.vectors.get(task_id)
        k = self._toolsmith.NEIGHBOURS
        if vector is not None:
            found = self.store.nearest(vector=vector, k=k, exclude=[task_id])
        else:
            found = self.store.nearest(text=question, k=k, exclude=[task_id])
        return [{"item": e["key"], "kind": e["kind"], "sim": round(e["similarity"], 4), "question": e["text"],
                 "code": e["payload"]["code"]} for e in found[::-1]]

    def request(self, node_name, task, step_input=None):
        """What would be sent for this node and Task, without sending it: {"way", "model", "prompt",
        "system", "max_tokens", "examples"}. "prompt" is a text or a list of messages. For a tool node
        "model" and "prompt" are None."""
        self._load()
        question = step_input if isinstance(step_input, str) else task_text_of(task)
        if not isinstance(question, str):
            raise ValueError("a live probe needs the text of the Task: give a dictionary with a \"question\"")
        way, harness, label = self._way(node_name)
        out = {"way": way, "model": label, "question": question, "prompt": None, "system": None, "max_tokens": None,
               "examples": []}
        if way in ("direct", "worked"):
            out.update(prompt=harness["prompt"].replace("{q}", question), max_tokens=harness["max_tokens"])
        elif way == "program":
            out.update(prompt=[{"role": "user", "content": harness["prompt"].replace("{q}", question)}],
                       system=harness["system"], max_tokens=harness["max_tokens"])
        elif way in ("reuse", "plus"):
            examples = self._examples(task, question) if way == "reuse" else []
            out.update(prompt=self._toolsmith.messages(question, examples), system=self._toolsmith.RULES,
                       max_tokens=self._toolsmith.MAX_TOKENS, examples=examples)
        return out

    # ---- one call ----
    def __call__(self, node_name, task, step_input=None, seed=None):
        self._load()
        seed = self.seed if seed is None else seed
        log = {"node": node_name, "task": task_id_of(task), "seed": seed}
        try:
            result = self._run(node_name, task, step_input, seed)
        except Exception as error:
            self._write(dict(log, error=f"{type(error).__name__}: {error}"[:300]))
            raise
        result.update(node=node_name, seed=seed)
        self._write(dict(log, answer=result["answer"], ok=result["ok"], form_ok=result["form_ok"], why=result["why"],
                         cost=result["cost"], reply=(result.get("reply") or "")[:1500], code=result.get("code")))
        return result

    def _run(self, node_name, task, step_input, seed):
        req = self.request(node_name, task, step_input)
        question, way = req["question"], req["way"]
        if way == "tool-arithmetic":
            started = time.perf_counter()
            value, error = calculator.calculate_detail(question)
            ms = round((time.perf_counter() - started) * 1000.0, 3)
            return self._result(value, value is not None, value is not None, error, None, self._cost(None, ms))
        tag = self._tag(req["model"], node_name)
        meter = self._bench.Meter()
        if req["system"] is None:
            text = self._chat(tag, req["prompt"], seed, req["max_tokens"], meter)
        else:
            text = self._chat(tag, req["prompt"], seed, req["max_tokens"], meter, system=req["system"])
        if way == "direct":
            answer = parse_answer(text, answer_kind(question))
            return self._result(answer, answer is not None, answer is not None, None, text, self._cost(meter), meter)
        if way == "worked":
            tail = _ANSWER_TAIL.findall(text)
            answer = parse_answer(tail[-1], answer_kind(question)) if tail else None
            why = None if tail else "no answer line"
            return self._result(answer, answer is not None, answer is not None, why, text, self._cost(meter), meter)
        if way == "program":
            answer, why = programs.run_arithmetic(text)
            return self._result(answer, answer is not None, answer is not None, why, text, self._cost(meter), meter)
        # a program with tools (dates, lists, loops), run in the safe runner; its value is put into the
        # answer form of the question by the benchmark's own rule (letter or number)
        code = programs.extract(text)
        ran = programs.run(code)
        profile = output_profile(question, ran, form=answer_kind(question))
        result = self._result(profile["answer"], bool(ran["ok"]), profile["form_ok"], profile["why"], text,
                              self._cost(meter, ran["ms"]), meter)
        result.update(output_profile=profile, code=code[:1500], answer_type=ran["answer_type"],
                      neighbours=[{k: e[k] for k in ("item", "kind", "sim")} for e in req["examples"]])
        return result

    @staticmethod
    def _cost(meter, tool_ms=0.0):
        if meter is None:
            return {"calls": 0, "tok_in": 0, "tok_out": 0, "model_s": 0.0, "tool_ms": tool_ms}
        return {"calls": meter.calls, "tok_in": meter.tok_in, "tok_out": meter.tok_out,
                "model_s": round(meter.model_s, 3), "tool_ms": tool_ms}

    @staticmethod
    def _result(answer, ok, form_ok, why, reply, cost, meter=None):
        return {"answer": answer, "ok": bool(ok), "form_ok": bool(form_ok), "why": why, "reply": reply, "cost": cost,
                "hit_ceiling": bool(getattr(meter, "truncated", 0)),
                "output_profile": {"present": answer is not None, "ok": bool(ok), "form_ok": bool(form_ok),
                                   "answer": answer, "why": why}}

    def _write(self, line):
        """Every attempt is recorded, failures included."""
        if self.attempts_path:
            line = dict(line, time=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
            with self._lock, open(self.attempts_path, "a", encoding="utf-8") as out:
                out.write(json.dumps(line, default=str) + "\n")
