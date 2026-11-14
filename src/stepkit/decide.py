# Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md
"""Deciders: which node to try, and whether to accept its output, try the next node, or stop.

A decider never calls a model itself. It asks a PROBE: `probe(node_name, task)` returns what the node
answered and what that cost. With `RecordedProbes` the answers come from a records file (a replay);
with `LiveProbes` they come from real calls. The decider code is the same in both cases.

After each step an ACCEPT FUNCTION looks at the result and at the earlier steps and returns a
`Decision`: stop with an answer (this step's answer, an earlier answer, or a combined one), or go on.

Sources (under the notes folder):
  work-2026-11-12-next-tests/t7-toolsmith/replay_t7.py   table() (here: KindTable), arms E3 and E3b
                                                          (here: rule_e3, rule_e3b), cost()
  work-2026-11-12-next-tests/t4-whole-loop/replay.py     Path: the probes an arm used, in order
  work-2026-11-10-node-sizer/mixed/chooser.py            ladder_outcome (here: ladder)
  work-2026-11-12-next-tests/reply-profile/confirm.py    the cascade (here: rule_with_reply_checker)
Needs numpy (for the same means, and so the same ties, as the source).
"""
from dataclasses import dataclass
from typing import Callable, Optional, Protocol

import numpy as np

from .live import LiveProbes  # noqa: F401  (the live probe has its own file; it is given here too)
from .profile import agreement, text_profile, unfamiliar
from .record import StepRecord, Trace, cost_of, task_id_of, task_text_of


# ---------------------------------------------------------------------------
# 1. Decisions and steps
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Decision:
    """What an accept function decides after a step.

    accepted   True: stop here. False: try the next node.
    answer     the final answer when accepted. It need not be the answer of the step that was just
               made: a rule may accept an EARLIER answer (two ways agree, keep the first) or a combined one.
    reason     one short line for the record: why it stopped, or why it went on.
    """
    accepted: bool
    answer: object = None
    reason: str = ""


@dataclass
class Step:
    """One step of a rule. A plain pair (node, accept) is enough when the step works on the Task itself.

    node        the name of the node to try
    accept      accept(result, trace) -> Decision. `result` is the probe's dictionary for this step;
                `trace` holds the EARLIER steps of this Task. None means: never stop here.
    make_input  make_input(task, trace) -> this step's own input, for a step that works on the output
                of an earlier step (a table, a query result). None: the step works on the Task itself.
    profile     profile(step_input) -> dictionary, the profile of that input. None: `text_profile` for
                a text, an empty profile for anything else.
    """
    node: str
    accept: Optional[Callable] = None
    make_input: Optional[Callable] = None
    profile: Optional[Callable] = None


def _as_step(step):
    return step if isinstance(step, Step) else Step(*step)


def _as_decision(value, answer):
    """A Decision as it is. A plain True or False is read as: accept this step's own answer, or go on."""
    if isinstance(value, Decision):
        return value
    return Decision(True, answer, "") if value else Decision(False, None, "")


# ---------------------------------------------------------------------------
# 2. Probes
# ---------------------------------------------------------------------------

class Probe(Protocol):
    """What a decider needs from the world: run one node on one Task and report.

    `step_input` is the step's own input when it is not the Task itself (None: the Task's text).
    `seed` is the seed of the call (None: the probe's own default).
    Returns a dictionary with at least:
      answer    the node's answer in the answer form of the question, or None
      ok        the node ran and gave an answer
      cost      {"calls", "tok_in", "tok_out", "model_s", "tool_ms"}; missing keys count as 0
    and optionally:
      form_ok          the output could be put into the wanted form (see stepkit.profile.output_profile)
      output_profile   a ready profile of the output; when missing, one is made from the fields above
      why              a short reason when there is no answer
      reply            the raw text the model wrote (needed by stepkit.reply.ReplyChecker)
    A probe that cannot run the node on this Task raises an error. It never returns None.
    """

    def __call__(self, node_name: str, task, step_input=None, seed=None) -> dict: ...


class MissingRecord(LookupError):
    """A replay was asked for an answer that was never recorded."""


class RecordedProbes:
    """A probe that reads recorded answers: the same decider can be replayed with no model call.

    `records_by_probe` is {node name: {Task id: record}}. A record is a line of a benchmark records
    file: pred, correct, model_s, tok_in, tok_out, calls, and where recorded: ran_ok, form_ok, why,
    tool_ms, texts (the raw replies), seed. The recorded right-or-wrong flag is passed on as "correct";
    a decider must not read it.

    A missing record is an error (`MissingRecord`), never a silent "no answer": ask `has(node, task)`
    first when a rule may meet a node that was not run on every Task. A record made with another seed
    than the one asked for is an error too. A replay holds answers for the Task's own input only, so a
    `step_input` is an error unless you give `key(task, step_input)`, which says under which key the
    answer for that input was recorded.
    """

    def __init__(self, records_by_probe, key=None):
        self.records = records_by_probe
        self.key = key

    @classmethod
    def from_records(cls, records, key="item"):
        """Build from a list of record dictionaries that each name their "probe" and their Task."""
        by = {}
        for record in records:
            by.setdefault(record["probe"], {})[record[key]] = record
        return cls(by)

    def nodes(self):
        return list(self.records)

    def _find(self, node_name, task, step_input):
        if self.key is not None:
            return self.records.get(node_name, {}).get(self.key(task, step_input))
        return self.records.get(node_name, {}).get(task_id_of(task))

    def has(self, node_name, task, step_input=None) -> bool:
        """True when there is a recorded answer of this node for this Task."""
        return (self.key is not None or step_input is None) and self._find(node_name, task, step_input) is not None

    def __call__(self, node_name, task, step_input=None, seed=None):
        if step_input is not None and self.key is None:
            raise MissingRecord(f"node {node_name!r}, Task {task_id_of(task)!r}: a replay holds answers for the "
                                f"Task's own input only; give RecordedProbes a key function to replay a step input")
        if node_name not in self.records:
            raise MissingRecord(f"no records of node {node_name!r}; recorded nodes: {sorted(self.records)}")
        record = self._find(node_name, task, step_input)
        if record is None:
            raise MissingRecord(f"node {node_name!r} has no recorded answer for Task {task_id_of(task)!r}")
        if seed is not None and record.get("seed") is not None and record["seed"] != seed:
            raise MissingRecord(f"node {node_name!r}, Task {task_id_of(task)!r}: recorded with seed "
                                f"{record['seed']}, asked for seed {seed}")
        answer = record.get("pred")
        result = {"answer": answer,
                  "ok": bool(record["ran_ok"]) if "ran_ok" in record else answer is not None,
                  "cost": cost_of(record), "correct": record.get("correct"),
                  "why": record.get("why") or record.get("error")}
        if "form_ok" in record:
            result["form_ok"] = bool(record["form_ok"])
        if record.get("texts"):
            result["reply"] = record["texts"][-1]
        return result


# ---------------------------------------------------------------------------
# 3. Accept functions: accept(result, trace) -> Decision
# ---------------------------------------------------------------------------

def always(result, trace):
    """Stop with whatever came back."""
    return Decision(True, result.get("answer"), "accepted as it is")


def never(result, trace):
    """Never stop at this step: its answer is only kept for a later comparison."""
    return Decision(False, None, "kept for a later comparison")


def has_answer(result, trace):
    """Stop when the node gave an answer. Right for an exact tool that answers only what it can."""
    answer = result.get("answer")
    if answer is not None:
        return Decision(True, answer, "the node gave an answer")
    return Decision(False, None, result.get("why") or "the node gave no answer")


def ran_and_form_ok(result, trace):
    """Stop when the node ran and its output has the answer form of the question."""
    if result.get("ok") and result.get("form_ok", result.get("answer") is not None):
        return Decision(True, result.get("answer"), "the node ran and its output has the wanted form")
    return Decision(False, None, result.get("why") or "the node did not run, or its output has the wrong form")


def _accept_with(test, reason):
    """The accept function `test`, with its own reason when it stops."""
    def accept(result, trace):
        decision = test(result, trace)
        return Decision(True, decision.answer, reason) if decision.accepted else decision
    return accept


# ---------------------------------------------------------------------------
# 4. Try nodes in order
# ---------------------------------------------------------------------------

def first_accepted(task, steps, probe, input_profile=None, seed=None) -> Trace:
    """Try nodes in order until an accept function stops. Returns the Trace of every step that was tried.

    `steps` is a list of pairs (node_name, accept_fn) or of `Step` objects. After a node has answered,
    `accept_fn(result, trace)` returns a `Decision`: stop with an answer, or try the next node. The
    answer of a Decision may be this step's answer, an earlier answer, or a combined one; it becomes
    `trace.answer`, and its reason becomes `trace.reason`. The last node always ends the rule: when
    its accept function does not stop (or it has none), its own answer is final.

    Every step record carries the profile of ITS OWN input: for a step that works on the Task itself
    this is `input_profile` (or `text_profile` of the Task's text when None is given); for a step with
    `make_input` it is the profile of that input. Every tried step is recorded and its cost is counted
    in `trace.total_cost()`. `seed` is passed on to the probe.
    """
    steps = [_as_step(step) for step in steps]
    trace = Trace(task_id_of(task))
    own_profile = input_profile
    for number, step in enumerate(steps, 1):
        step_input = step.make_input(task, trace) if step.make_input is not None else None
        if step_input is not None:
            if step.profile is not None:
                profile = step.profile(step_input)
            else:
                profile = text_profile(step_input) if isinstance(step_input, str) else {}
        else:
            if own_profile is None:
                text = task_text_of(task)
                own_profile = text_profile(text) if isinstance(text, str) else {}
            profile = dict(own_profile)
        result = probe(step.node, task, step_input=step_input, seed=seed)
        if result is None:
            raise MissingRecord(f"the probe gave no result for node {step.node!r}, Task {trace.task_id!r}: "
                                f"a probe returns a result dictionary or raises")
        answer = result.get("answer")
        output = dict(result.get("output_profile") or
                      {"present": answer is not None, "form_ok": bool(result.get("form_ok", answer is not None)),
                       "answer": answer, "why": result.get("why")})
        output.setdefault("ok", bool(result.get("ok", answer is not None)))
        decision = _as_decision(step.accept(result, trace) if step.accept is not None else False, answer)
        if number == len(steps) and not decision.accepted:
            decision = Decision(True, answer, "the last node: its answer is final")
        trace.append(StepRecord(trace.task_id, number, step.node, profile, output, decision.accepted, answer,
                                cost_of(result.get("cost")), decision.reason))
        if decision.accepted:
            trace.finish(decision.answer, decision.reason)
            break
    return trace


def _rule(make_steps):
    """Turn a function that gives the steps for a Task into `run(task, probe, **options) -> Trace`."""
    def run(task, probe, input_profile=None, seed=None) -> Trace:
        if input_profile is None:
            text = task_text_of(task)
            input_profile = text_profile(text) if isinstance(text, str) else {}
        return first_accepted(task, make_steps(task, input_profile), probe, input_profile, seed)
    return run


# ---------------------------------------------------------------------------
# 5. Ready-made rules
# ---------------------------------------------------------------------------

def ladder(first_nodes, then_node, tol=1e-3):
    """The classic ladder: try the first nodes; when their answers agree, stop; else ask the then-node.

    Returns a function `run(task, probe) -> Trace`. The steps it uses are in `run.steps`.
    Rules, the same as the source (chooser.py, ladder_outcome):
      - the first nodes agree when no answer is missing and all are equal (`stepkit.profile.agreement`);
        the final answer is then the answer of the FIRST node, and the then-node is not paid for;
      - else the then-node's answer is final; when the then-node gives no answer, the answer of the
        first node is kept.
    With cheap first nodes and a strong then-node this is the two-level ladder of the proof sheet.
    One difference from the source: with ONE first node the source accepts that node even when its
    answer is missing; here a missing answer always goes to the then-node.
    """
    first_nodes = list(first_nodes)
    if not first_nodes:
        raise ValueError("a ladder needs at least one first node")

    def agree(result, trace):
        answers = [step.answer for step in trace] + [result.get("answer")]
        if agreement(answers, tol)["all_agree"]:
            return Decision(True, answers[0], "the first nodes agree: the answer of the first node is kept")
        return Decision(False, None, "the first nodes do not agree")

    def then(result, trace):
        answer = result.get("answer")
        if answer is None:
            return Decision(True, trace[0].answer, "the then-node gave no answer: the answer of the first node is kept")
        return Decision(True, answer, "the first nodes do not agree: the then-node's answer is final")

    steps = [(node, never) for node in first_nodes[:-1]] + [(first_nodes[-1], agree), (then_node, then)]
    run = _rule(lambda task, profile: steps)
    run.steps = steps
    return run


# The paths of the two step rules of test 7. A trace's `reason` is one of these lines.
BY_CALCULATOR = "calculator, no model"
BY_SMALL_PROGRAM = "the small model's program ran and its value has the wanted form"
BY_LARGER_PROGRAM = "the larger model's program ran and its value has the wanted form"
BY_LAST_RESORT = "last resort: the larger model's worked answer"
BY_TWO_SMALL_WAYS = "number: two ways of the small model agree"
BY_LARGER_AND_SMALL = "number: the larger model's program agrees with a small-model way"
BY_TWO_LARGER_WAYS = "number: the larger model's program agrees with its own worked answer"
BY_SMALL_OPTION = "options: the small model's program matches exactly one option"
BY_LARGER_OPTION = "options: the larger model's program matches exactly one option"


def _same_number(x, y, tol=1e-3):
    """True when two answers are numbers and equal within the tolerance (a text is never equal here)."""
    return (x is not None and y is not None and not isinstance(x, str) and not isinstance(y, str)
            and abs(x - y) <= tol * max(1.0, abs(y)))


def _usable(step):
    """True when an earlier step ran and its output had the wanted form."""
    return step is not None and bool(step.output_profile.get("ok")) and bool(step.output_profile.get("form_ok"))


def rule_e3(calc="T.calc", small_program="S.reuse", larger_program="B.reuse", larger_worked="B.worked"):
    """Arm E3 of test 7: decide from each step's data, with no kind label.

    The calculator, when it gives a value. Else the small model's program (written with three similar
    checked programs as examples): accepted when it ran and its value has the answer form of the
    question. Else the larger model's program, by the same check. Else the larger model's worked
    answer. Same decisions and same cost as the source (replay_t7.py). Measured there on 840 test
    Tasks: 78.0% right at 5.17 model seconds, against 72.0% at 9.78 s for the last node alone.
    Returns `run(task, probe) -> Trace`; `run.steps` holds the steps.
    """
    steps = [(calc, _accept_with(has_answer, BY_CALCULATOR)),
             (small_program, _accept_with(ran_and_form_ok, BY_SMALL_PROGRAM)),
             (larger_program, _accept_with(ran_and_form_ok, BY_LARGER_PROGRAM)),
             (larger_worked, _accept_with(always, BY_LAST_RESORT))]
    run = _rule(lambda task, profile: steps)
    run.steps = steps
    return run


def rule_e3b(calc="T.calc", small_program="S.reuse", small_worked="S.worked", larger_program="B.reuse",
             larger_worked="B.worked", tol=1e-3):
    """Arm E3b of test 7: as E3, but a NUMBER is accepted only when two ways agree.

    A form check cannot judge a number (every number has the form of a number), so for a question
    that wants a number the rule asks for agreement:
      1. the calculator, when it gives a value;
      2. the small model's program and the small model's worked answer give the same number;
      3. the larger model's program gives the same number as one of those two;
      4. the larger model's program gives the same number as the larger model's worked answer;
      5. last resort: the larger model's worked answer.
    For a question with lettered options the form check is strong (the value must name exactly one
    option), so the rule is E3: small program, larger program, then the larger model's worked answer.
    The answer form comes from the input profile (`answer_form`), never from the answer key.
    Same decisions and same cost as the source (replay_t7.py). Measured there on 840 test Tasks:
    85.2% right at 9.97 model seconds, against 72.0% at 9.78 s for the larger model's worked answer.
    Returns `run(task, probe) -> Trace`. `trace.reason` names the path that gave the answer.
    """
    def two_small_ways(result, trace):
        program = trace.step(small_program)
        if _usable(program) and _same_number(program.answer, result.get("answer"), tol):
            return Decision(True, program.answer, BY_TWO_SMALL_WAYS)
        return Decision(False, None, "the small model's two ways do not give the same number")

    def larger_and_small(result, trace):
        program, worked = trace.step(small_program), trace.step(small_worked)
        value = result.get("answer")
        if ran_and_form_ok(result, trace).accepted and (
                _same_number(value, program.answer if _usable(program) else None, tol)
                or _same_number(value, worked.answer, tol)):
            return Decision(True, value, BY_LARGER_AND_SMALL)
        return Decision(False, None, "the larger model's program agrees with no small-model way")

    def two_larger_ways(result, trace):
        program = trace.step(larger_program)
        if _usable(program) and _same_number(program.answer, result.get("answer"), tol):
            return Decision(True, program.answer, BY_TWO_LARGER_WAYS)
        return Decision(True, result.get("answer"), BY_LAST_RESORT)

    number_steps = [(calc, _accept_with(has_answer, BY_CALCULATOR)), (small_program, never),
                    (small_worked, two_small_ways), (larger_program, larger_and_small),
                    (larger_worked, two_larger_ways)]
    option_steps = [(calc, _accept_with(has_answer, BY_CALCULATOR)),
                    (small_program, _accept_with(ran_and_form_ok, BY_SMALL_OPTION)),
                    (larger_program, _accept_with(ran_and_form_ok, BY_LARGER_OPTION)),
                    (larger_worked, _accept_with(always, BY_LAST_RESORT))]
    run = _rule(lambda task, profile: option_steps if profile.get("answer_form") == "choice" else number_steps)
    run.number_steps, run.option_steps = number_steps, option_steps
    return run


def rule_with_reply_checker(checker, t=0.8, kind_of=None, calc="T.calc", small="S.worked", larger="B.worked"):
    """A cascade with the reply checker: keep the small model's answer when its reply looks right.

    The calculator, when it gives a value. Else the small model's worked answer: code reads the reply
    (`stepkit.reply`), and the answer is accepted when there is one and
    `checker.confidence(question, reply, kind)` is at least `t`. Else the larger model's worked answer.
    `kind_of(task)` names the kind of the Task for the checker (for example from
    `CheckedStore.kind_vote`); with None the checker uses its one model for all kinds.
    The probe must give the raw text of the small model's reply as "reply".
    Returns `run(task, probe) -> Trace`.
    """
    def make_steps(task, profile):
        question = task_text_of(task)
        kind = kind_of(task) if kind_of is not None else None

        def confident(result, trace):
            answer, reply = result.get("answer"), result.get("reply")
            if answer is None:
                return Decision(False, None, "the small model gave no answer")
            if reply is None:
                return Decision(False, None, "the probe gave no reply text to read")
            confidence = checker.confidence(question, reply, kind)
            if confidence >= t:
                return Decision(True, answer, f"reply checker: confidence {confidence:.3f}, at least {t:g}")
            return Decision(False, None, f"reply checker: confidence {confidence:.3f}, under {t:g}")

        return [(calc, _accept_with(has_answer, BY_CALCULATOR)), (small, confident),
                (larger, _accept_with(always, BY_LAST_RESORT))]

    return _rule(make_steps)


# ---------------------------------------------------------------------------
# 6. A table from kind to node
# ---------------------------------------------------------------------------

class KindTable:
    """For each kind of Task, the node that did best on recorded Tasks of that kind.

    `default_node` is used for a kind the table does not know, and for a Task that looks like nothing
    in the store: give `choose` the "top_similarity" of `CheckedStore.kind_vote` and the store's
    `familiarity_floor()`; when the similarity is under the floor (see `stepkit.profile.unfamiliar`)
    the default node is returned. A floor given to the table itself is used when `choose` gets none.
    """

    def __init__(self, default_node=None, floor=None):
        self.default_node = default_node
        self.floor = floor
        self.table = {}     # kind -> {"node", "accuracy", "model_s", "n"}

    def fit(self, records, kinds, candidates):
        """Pick, for each kind, the candidate node with the highest accuracy on the given records.

        `records`: record dictionaries with "item", "probe", "correct" and "model_s" (or a mapping
        {node: {Task id: record}}). `kinds`: {Task id: kind} for the Tasks to fit on; records of other
        Tasks are not read. `candidates`: node names; on equal accuracy the node with fewer model
        seconds wins, then the one named first. A node counts for a kind only when it has a record for
        every fit Task of that kind. Same rule as the source (replay_t7.py, table).
        """
        candidates = list(candidates)
        if hasattr(records, "items"):
            by = {node: {i: r for i, r in rows.items() if i in kinds} for node, rows in records.items()}
        else:
            by = {}
            for record in records:
                if record["item"] in kinds and record["probe"] in candidates:
                    by.setdefault(record["probe"], {})[record["item"]] = record
        tasks_of = {}
        for task_id, kind in kinds.items():
            tasks_of.setdefault(kind, []).append(task_id)
        self.table = {}
        for kind, tasks in tasks_of.items():
            best = None
            for node in candidates:
                have = by.get(node, {})
                if not all(task_id in have for task_id in tasks):
                    continue
                accuracy = float(np.mean([have[t]["correct"] for t in tasks]))
                seconds = float(np.mean([have[t].get("model_s", 0.0) for t in tasks]))
                if best is None or (accuracy, -seconds) > (best["accuracy"], -best["model_s"]):
                    best = {"node": node, "accuracy": accuracy, "model_s": seconds, "n": len(tasks)}
            if best is not None:
                self.table[kind] = best
        return self

    def choose(self, kind, top_similarity=None, floor=None):
        """The node for a Task of this kind.

        The default node is returned when the kind is not in the table, and when `top_similarity` is
        given and is under the floor (the `floor` given here, else the table's). Raises LookupError
        when the default node is needed and none was set.
        """
        floor = self.floor if floor is None else floor
        row = self.table.get(kind)
        gated = top_similarity is not None and floor is not None and unfamiliar(top_similarity, floor)
        if row is not None and not gated:
            return row["node"]
        if self.default_node is None:
            raise LookupError(f"no node for kind {kind!r} and no default node")
        return self.default_node
