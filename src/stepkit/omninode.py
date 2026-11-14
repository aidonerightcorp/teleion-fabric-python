# Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md
"""One OmniNode for every Task: a contract and parameters, and nothing else.

Every node is the same class. What makes one node differ from another is data:

    Contract     what the node must do and what it may use: the input, the form of the output and the
                 checks it must pass, the budget (model seconds, tokens, child nodes, depth), the
                 resources (parts, stores, models, cartridges) and the permissions.
    Parameters   everything a node can set: the arrangement of stages, the price of a model second, how
                 stored work is found and when a Task counts as unfamiliar, the settings and the weights
                 of a model part, the fallback and stop rules, and when and how child nodes start.

Both are `Settings`: sets of `Dimension` objects (stepkit/dimension.py). No number of a setting is written
bare, and no value is read directly: the node asks its `Resolver`, which writes every value down as a
choice with where it came from (set by the caller, suggested default, chosen by a strategy from evidence,
exploration). Control flow is data too: the run loop is the kit's `first_accepted` over the stages of the
arrangement; stage types, fallback rules, stop rules, child rules, the rules for a used-up budget and the
paths of parts are registered by name and named in the data.

The contract is enforced while the node runs: the input form is checked before it starts; every step's
answer is put to the contract's output checks, and a failed check fails the step; a parent holds its
budget (model seconds, tokens, child nodes, depth; per kind of work where `budget.by_kind` names one) as
a running limit and stops, or starts the remaining children with free parts only, when a limit is
reached. A cost is known only when a call ends, so a stage that starts with budget left may end over it;
the record shows that. Every run starts from a new `RunContext`: nothing of one run carries over to the next.

    node = OmniNode(contract, parameters)
    node.configure(task, store)        # nearest proven parameters for the Task's profile; the default when unfamiliar
    record = node.run(task, source)    # stages in order, a decision from each step's data, one record per step
    child = node.spawn(node.derive({"output.form": "values"}))     # a child node with a derived contract

A parts source gives the answers: `ReplaySource` reads recorded answers (no model call) and `LiveSource`
wraps the kit's live probe (the only way a model is called; a contract must permit it). The search that
writes parameters from records is `stepkit.assembler.Assembler`.

Sources (under the notes folder):
  work-2026-11-12-next-tests/t10-self-assembly/assemble.py   when a part answers, the stages, the fallback
  work-2026-11-12-next-tests/t7-toolsmith/                   the word Tasks, their records, the step tools
Needs numpy (through the kit's store and the assembler).
"""
import json
import os
from collections import Counter
from dataclasses import asdict, dataclass, field

from . import _sources as S
from .assembler import SETTINGS as SEARCH
from .assembler import STAGE_KINDS, Outcomes, StageKind, answers_equal, register_stage_kind, show
from .decide import Decision, MissingRecord, RecordedProbes, Step, first_accepted
from .dimension import CHOICES, NUMBERS, Dimension, Resolver, Settings, plain
from .profile import text_profile, unfamiliar
from .record import StepRecord, add_costs, task_id_of, task_text_of
from .store import CheckedStore


class ContractError(RuntimeError):
    """A node was asked to do what its contract does not give or permit."""


# ---------------------------------------------------------------------------
# 1. The dimensions of a contract and of a parameter set
# ---------------------------------------------------------------------------

class Contract(Settings):
    """What a node must do and what it may use. Every entry is a Dimension; see `CONTRACT`."""


class Parameters(Settings):
    """Everything a node can set. Every entry is a Dimension; see `PARAMETERS`. A parameter set may hold
    only some dimensions (a set proven for a profile holds the arrangement and the price)."""

    def to_task_object(self, profile, evidence=None) -> dict:
        """This parameter set as a Task Object that a store can keep."""
        return {"kind": "task_object", "type": "omninode.parameters", "id": "omninode.parameters/" + str(profile),
                "profile": profile, "parameters": self.to_dict(), "evidence": plain(evidence or {})}

    @classmethod
    def from_task_object(cls, data) -> "Parameters":
        return cls.from_dict(data["parameters"])


CONTRACT = Contract(name="contract", dimensions=[
    Dimension("input.form", ["text", "table", "batch"], kind=CHOICES,
              about="what the node is given: one Task with a text, one Task with a table, or a list of Tasks"),
    Dimension("output.form", ["number", "choice", "text", "values", "query_result", "any"], kind=CHOICES,
              about="the form an answer must have; a part answers only when its output has this form"),
    Dimension("output.checks", [[]], kind=CHOICES,
              about="names of the checks that every step's answer is put to; a failed check fails the step"),
    Dimension("budget.model_seconds", [None], [None, 1.0, 2.0, 3.0, 5.0, 10.0, 20.0, 60.0], NUMBERS, {"min": 0.0},
              about="model seconds the node and every node under it may use, held as a running limit; None is no limit"),
    Dimension("budget.tokens", [None], [None, 500, 1000, 2000, 4000, 8000], NUMBERS, {"min": 0},
              about="tokens the node and every node under it may use, held as a running limit; None is no limit"),
    Dimension("budget.by_kind", [None], kind=CHOICES,
              about="model seconds per Task for each kind of work, {kind: seconds}, held as a running limit over the "
                    "Tasks of that kind; None is no limit per kind"),
    Dimension("budget.when_used_up", ["stop", "free_parts"], kind=CHOICES,
              about="when a running limit is reached: start no further child (its Task gets no answer), or start "
                    "the remaining children with the fallback arrangement, which may hold only parts that call no model"),
    Dimension("budget.nodes", [0], [0, 1, 2, 3, 5, 10, 100, 1000, 10000], NUMBERS, {"min": 0, "max": 100000},
              about="child nodes the node may start"),
    Dimension("budget.depth", [0], [0, 1, 2, 3], NUMBERS, {"min": 0, "max": 8}, about="levels of child nodes under the node"),
    Dimension("resources.parts", [None], kind=CHOICES, about="names of the parts the node may use; None is every part of its source"),
    Dimension("resources.models", [None], kind=CHOICES, about="labels of the models the node may call; None is every model"),
    Dimension("resources.stores", [[]], kind=CHOICES, about="names of the stores the node may read"),
    Dimension("resources.cartridges", [[]], kind=CHOICES, about="weight cartridges the node may load"),
    Dimension("permissions.spawn", [False, True], kind=CHOICES, about="may the node start child nodes"),
    Dimension("permissions.live", [False, True], kind=CHOICES, about="may the node use a source that calls a model"),
    Dimension("records.task_text", [False, True], kind=CHOICES,
              about="may the Task's text be written into a record of this node; false: a writer withholds it "
                    "(stepkit.fabric.NodeRecordSink)"),
    Dimension("records.data_use", ["benchmark: no training", "open"], kind=CHOICES,
              about="what the records of this node may be used for: the restrictive tag for Tasks made from benchmark "
                    "items and whenever the source is not stated; open only when a caller says so"),
])

# The settings of a model part (the first six), of its harness (two) and of its weights (two).
PART_SETTINGS = ("model", "prompt_form", "examples", "context_length", "temperature", "samples",
                 "harness_tools", "harness_instruction", "cartridge_id", "mask_id")

PARAMETERS = Parameters(name="parameters", dimensions=[
    Dimension("arrangement", [[]], kind=CHOICES, generator={"name": "stepkit.assembler.Assembler.grammar"},
              about="the stages in order, each [part, stage type]; the grid is the grammar of the assembler"),
    Dimension("price_per_model_second", [0.0], [0.0, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0], NUMBERS, {"min": 0.0, "max": 10000.0},
              about="points of accuracy that one model second is worth; shared by a node and its children"),
    Dimension("fallback", ["last_answered", "none"], kind=CHOICES, about="the answer when no stage gives one"),
    Dimension("stop_rules", [["budget_model_seconds", "budget_tokens"], []], kind=CHOICES,
              about="names of the rules that end a run before its last stage"),
    SEARCH["assembler.number_equality"],
    Dimension("retrieval.neighbours", [5], [1, 3, 5, 7, 9, 15], NUMBERS, {"min": 1, "max": 100},
              about="how many of the nearest stored Tasks name the kind of a Task"),
    Dimension("retrieval.measure", ["auto", "vector", "text"], kind=CHOICES,
              about="how similar stored work is found: text vectors, the built-in text similarity, or vectors when the Task has one"),
    Dimension("retrieval.unfamiliar_q", [None], [None, 0.02, 0.05, 0.15], NUMBERS, {"min": 0.0, "max": 0.5},
              about="a Task under the store's familiarity floor at this quantile takes the default parameters; None is no such rule"),
    Dimension("retrieval.keys", [["kind", "form", "work"]], [["kind", "form", "work"], ["form", "work"], ["work"]], CHOICES,
              about="the labels of a profile under which proven parameters are looked for, in order"),
    Dimension("retrieval.when_no_match", ["default_set", "refuse"], kind=CHOICES,
              about="when no proven set matches the profile: the set stored as the default for the kind of work, "
                    "else the node's own parameters; or refuse"),
    Dimension("children.rule", ["none", "one_per_task", "steps"], kind=CHOICES, about="when and how the node starts child nodes"),
    Dimension("children.steps", [[]], kind=CHOICES, about="for the rule \"steps\": the typed steps, each a child node"),
    Dimension("children.budget", ["price", "left"], kind=CHOICES,
              about="a child's own limits of model seconds and tokens: none (the shared price keeps the budget), or "
                    "what the parent has left of them (of its kind of work too)"),
    Dimension("children.fallback_arrangement", [[]], kind=CHOICES,
              about="for the rule \"free_parts\": the arrangement of a child started after a running limit is reached; "
                    "only parts that call no model; empty: the child is not started"),
    Dimension("children.answer", ["first_accepted_else_last", "none"], kind=CHOICES, about="how the children's answers become the node's answer"),
    Dimension("part.model", [None], kind=CHOICES, about="the model of a model part"),
    Dimension("part.prompt_form", [None, "direct", "worked", "program", "reuse"], kind=CHOICES, about="the form of the prompt"),
    Dimension("part.examples", [None], [None, 0, 3, 5], NUMBERS, {"min": 0, "max": 50}, about="examples shown in the prompt"),
    Dimension("part.context_length", [None], [None, 2048, 4096, 8192], NUMBERS, {"min": 256}, about="context length in tokens"),
    Dimension("part.temperature", [None], [None, 0.0, 0.2, 0.5, 0.8, 1.0], NUMBERS, {"min": 0.0, "max": 2.0}, about="sampling temperature"),
    Dimension("part.samples", [None], [None, 1, 3, 5], NUMBERS, {"min": 1, "max": 50}, about="number of samples of one call"),
    Dimension("part.harness_tools", [[]], kind=CHOICES, about="tools of the harness around the model"),
    Dimension("part.harness_instruction", [None], kind=CHOICES, about="instruction text of the harness"),
    Dimension("part.cartridge_id", [None], kind=CHOICES, about="the weight cartridge loaded for the part"),
    Dimension("part.mask_id", [None], kind=CHOICES, about="the weight mask applied for the part"),
])


def assembled(stages, price=None) -> Parameters:
    """The parameter set that an assembler writes for a profile: the arrangement, and the price when
    one was used. Only these dimensions are in the set; a node keeps its own values for the others."""
    out = Parameters([PARAMETERS["arrangement"].narrowed([list(stage) for stage in stages], "the assembler")], "assembled")
    if price is not None:
        out.add(PARAMETERS["price_per_model_second"].narrowed(float(price), "the assembler"))
    return out


# ---------------------------------------------------------------------------
# 2. Control flow as data: everything below is looked up by a name that the data gives
# ---------------------------------------------------------------------------

def _plain_number(answer):
    return answer is not None and not isinstance(answer, bool) and isinstance(answer, (int, float))


# output form -> has_form(answer): does a part's output count as an answer of that form
FORMS = {
    "number": _plain_number,
    "choice": lambda answer: isinstance(answer, str) and answer.startswith("("),
    "text": lambda answer: _plain_number(answer) or (isinstance(answer, str) and bool(answer.strip())),
    "any": lambda answer: answer is not None,
}
# output form -> make(node) -> equal(a, b): when two answers of that form are the same (for `agree`)
EQUALITY = {form: (lambda node: answers_equal(*node.ask("assembler.number_equality"))) for form in FORMS}
# check name -> check(answer, profile) -> yes or no
CHECKS = {}
# kind of work -> how a Task of that kind is recognized and profiled: functions (task, profile) that add to the profile
PROFILERS = []
# condition name -> condition(results of the calls made so far on a part's path) -> make the next call or not
CALL_CONDITIONS = {"always": lambda ran: True}
# rule name -> rule(evidence, answer, profile) -> yes or no: evidence of a step that code derives
EVIDENCE_RULES = {}


def _last_ran(ran):
    return ran[-1] if ran else None


def _final_only(ran):
    return ran[-1] if ran and ran[-1]["final"] else None


# rule name -> which call on a part's path carries the part's answer
PART_ANSWERS = {"last_ran": _last_ran, "final_only": _final_only}


def _last_answered(answers):
    for answer in reversed(answers):
        if answer is not None:
            return answer, "the answer of the last part that answered is used"
    return None, "no part answered"


# rule name -> rule(answers of the steps, in order) -> (answer, reason) when no stage gives the answer
FALLBACKS = {"last_answered": _last_answered, "none": lambda answers: (None, "no answer is given")}


def _seconds_used_up(node, spent):
    limit = node.ask("budget.model_seconds")
    return "the budget of model seconds is used up" if limit is not None and spent["model_s"] >= limit else None


def _tokens_used_up(node, spent):
    limit = node.ask("budget.tokens")
    return "the budget of tokens is used up" if limit is not None and spent["tok_in"] + spent["tok_out"] >= limit else None


# rule name -> rule(node, cost so far) -> a reason to stop now, or None
STOP_RULES = {"budget_model_seconds": _seconds_used_up, "budget_tokens": _tokens_used_up}
# rule name -> rule(records of the children so far) -> start this child or not
CONDITIONS = {"always": lambda records: True, "no_child_accepted": lambda records: not any(r.accepted for r in records)}


def _first_accepted_else_last(records):
    for record in records:
        if record.accepted:
            return record.answer, True, f"the answer of child {record.node_id} ({record.role})"
    if records:
        return records[-1].answer, False, f"no child accepted: the answer of the last child {records[-1].node_id}"
    return None, False, "no child ran"


# rule name -> rule(records of the children) -> (answer, accepted, reason)
ANSWER_RULES = {"first_accepted_else_last": _first_accepted_else_last, "none": lambda records: (None, False, "no single answer")}


def _smallest(*values):
    known = [value for value in values if value is not None]
    return max(min(known), 0) if known else None


# rule name -> rule(what the parent has left) -> the child's own limits
CHILD_BUDGETS = {"price": lambda left: {"budget.model_seconds": None, "budget.tokens": None},
                 "left": lambda left: {"budget.model_seconds": _smallest(left["model_seconds"], left["kind_model_seconds"]),
                                       "budget.tokens": _smallest(left["tokens"])}}
# form of input -> test(task, profile): is this Task an input of that form
INPUT_FORMS = {"text": lambda task, profile: not isinstance(task, list) and profile.get("work") == "text",
               "table": lambda task, profile: not isinstance(task, list) and profile.get("work") == "table",
               "batch": lambda task, profile: isinstance(task, list)}
# the running limits of a parent, in the order they are tested: (name, reached(what is left))
LIMITS = [("child nodes", lambda left: left["nodes"] <= 0),
          ("depth", lambda left: left["depth"] <= 0),
          ("model seconds", lambda left: left["model_seconds"] is not None and left["model_seconds"] <= 0),
          ("tokens", lambda left: left["tokens"] is not None and left["tokens"] <= 0),
          ("model seconds of this kind of work", lambda left: left["kind_model_seconds"] is not None and left["kind_model_seconds"] <= 0)]
# limits after which no child can be started at all, whatever the rule for a used-up budget says
STRUCTURAL_LIMITS = ("child nodes", "depth")


def limit_reached(left):
    """The name of the first running limit that is reached, or None."""
    return next((name for name, reached in LIMITS if reached(left)), None)


def profile_of(task) -> dict:
    """The profile of a Task, by code: the kit's text profile of its text, the kind of work ("text"
    unless a registered profiler says otherwise) and the form of the answer it wants."""
    text = task_text_of(task)
    profile = text_profile(text) if isinstance(text, str) else {}
    profile["work"] = "text"
    for add in PROFILERS:
        add(task, profile)
    return profile


def source_for(source, profile):
    """One parts source, or the source of the Task's kind of work when a mapping {work: source} is given."""
    return source[profile.get("work")] if isinstance(source, dict) else source


# ---------------------------------------------------------------------------
# 3. Parts and their sources
# ---------------------------------------------------------------------------

@dataclass
class Part:
    """One part: one connector (an answer or none) and a cost. Its path is data.

    calls     the recorded or live calls on its path, in order: {"call": name, "when": condition name,
              "if_recorded": True}; a name may hold a field of the evidence of the call before it
    answer    which call carries the part's answer (a name in PART_ANSWERS)
    kinds     the stage types the part may be used with, in the order a search tries them
    model     label of the model it calls; None for an exact tool
    info      the settings the part was recorded with (model, prompt form, examples)
    value     for an exact tool that code computes: value(task) -> answer or None; no call
    evidence  names of evidence rules that code derives for the step (EVIDENCE_RULES)
    """
    name: str
    calls: list = field(default_factory=list)
    answer: str = "last_ran"
    kinds: tuple = ("take", "agree")
    model: str = None
    info: dict = field(default_factory=dict)
    value: object = None
    evidence: tuple = ()


class Session:
    """One node run on one Task. It has the call of the kit's probes, so `first_accepted` can use it.

    A call that was already made in this run is not made, and not paid, again: its result is known.
    A part answers when its call ran, its output has the wanted form of the call, and the output has
    the form that the node's contract asks for. An output that does not answer is kept in the step's
    output profile as "raw_answer" and the step's answer is None.
    """

    def __init__(self, source, task, form, seed, profile, checks=()):
        self.source, self.task, self.form, self.seed, self.profile = source, task, form, seed, profile or {}
        self.checks = list(checks)      # the contract's output checks: a failed check fails the step
        self.made = {}

    def has(self, call):
        return call in self.made or self.source.has(call, self.task)

    def _call(self, call, fresh):
        if call not in self.made:
            result = dict(self.source.probe(call, self.task, seed=self.seed))
            evidence = dict(result.get("output_profile") or {})
            evidence.update(self.source.evidence(call, self.task))
            result["evidence"] = evidence
            self.made[call] = result
            fresh.append(call)
        return self.made[call]

    def __call__(self, part_name, task=None, step_input=None, seed=None):
        if part_name not in self.source.parts:
            raise KeyError(f"unknown part {part_name!r}; this source has: {sorted(self.source.parts)}")
        part, fresh, ran = self.source.parts[part_name], [], []
        for step in part.calls:
            call = step["call"].format(**(ran[-1]["evidence"] if ran else {}))
            if not CALL_CONDITIONS[step.get("when", "always")](ran) or (step.get("if_recorded") and not self.has(call)):
                continue
            ran.append(dict(self._call(call, fresh), final=step is part.calls[-1]))
        if part.value is not None:
            value = part.value(self.task)
            ran.append({"answer": value, "ok": value is not None, "evidence": {}, "final": True})
        chosen = PART_ANSWERS[part.answer](ran) or {}
        answer = chosen.get("answer")
        ok = bool(chosen.get("ok", answer is not None)) and bool(chosen)
        form_ok = bool(chosen.get("form_ok", True)) and FORMS[self.form](answer)
        answered = ok and form_ok
        evidence = {key: value for key, value in (chosen.get("evidence") or {}).items()
                    if key not in ("answer", "present", "ok", "form_ok", "why")}
        for rule in part.evidence:
            evidence[rule] = bool(EVIDENCE_RULES[rule](evidence, answer if answered else None, self.profile))
        checks = {name: bool(CHECKS[name](answer, self.profile)) for name in self.checks} if answered else {}
        failed = [name for name, passed in checks.items() if not passed]
        answered = answered and not failed
        why = ("the answer failed the check " + ", ".join(failed)) if failed else chosen.get("why")
        output = dict(evidence, present=answer is not None, ok=ok, form_ok=form_ok, answered=answered,
                      answer=answer if answered else None, raw_answer=None if answered else answer,
                      why=why, calls=list(fresh), checks=checks)
        return {"answer": answer if answered else None, "ok": ok, "form_ok": form_ok, "why": why,
                "cost": add_costs(self.made[call]["cost"] for call in fresh),
                "correct": chosen.get("correct") if answered else None, "reply": chosen.get("reply"),
                "output_profile": output, "flags": {key: value for key, value in evidence.items() if isinstance(value, bool)},
                "calls": [(call, self.made[call]["cost"]["model_s"]) for call in fresh]}


class PartsSource:
    """Where a node's parts get their answers: one interface, two sources (`ReplaySource`, `LiveSource`).

    probe    a probe of the kit: probe(call name, task, seed=...) -> result dictionary
    parts    {name: Part}
    """
    live = None

    def __init__(self, probe, parts):
        self.probe, self.parts = probe, dict(parts)

    def session(self, task, form="any", seed=None, profile=None, checks=()) -> Session:
        return Session(self, task, form, seed, profile, checks)

    def has(self, call, task) -> bool:
        raise NotImplementedError

    def evidence(self, call, task) -> dict:
        """Evidence of a call's output beyond the probe's result (a replay reads it from the record)."""
        return {}


class ReplaySource(PartsSource):
    """Recorded answers: the kit's `RecordedProbes`. No model call; a missing record is an error."""
    live = False

    def has(self, call, task):
        return self.probe.has(call, task)

    def evidence(self, call, task):
        record = self.probe.records.get(call, {}).get(task_id_of(task)) or {}
        return dict(record.get("evidence") or {})


class LiveSource(PartsSource):
    """Real calls: the kit's `LiveProbes`. A node uses it only when its contract permits a live source."""
    live = True

    def has(self, call, task):
        return call in self.probe.nodes()


def outcomes_of(source, tasks, parts, form_of, right_of=None) -> Outcomes:
    """What every part does on every Task, as the `Outcomes` that an assembler searches.

    Each part runs in a session of its own, so every call on its path is listed. Right or wrong is the
    recorded flag of the answer; `right_of(answer, task)` scores a part that has no recorded flag (an
    exact tool that code computes). A part with no record for a Task is marked so.
    """
    out = Outcomes([task_id_of(task) for task in tasks])
    profiles = [profile_of(task) for task in tasks]
    for name in parts:
        rows = []
        for task, profile in zip(tasks, profiles):
            try:
                result = source.session(task, form=form_of(profile), profile=profile)(name)
            except MissingRecord:
                rows.append({"recorded": False})
                continue
            right = result["correct"]
            if right is None and result["answer"] is not None and right_of is not None:
                right = right_of(result["answer"], task)
            rows.append({"answer": result["answer"], "right": bool(right), "calls": result["calls"], "flags": result["flags"]})
        out.add(name, rows, source.parts[name].kinds)
    return out


# ---------------------------------------------------------------------------
# 4. Records: one for each step, one for each node
# ---------------------------------------------------------------------------

@dataclass
class NodeStep(StepRecord):
    """The kit's step record, with the stage it was and the settings of the part as the node resolved
    them (settings that no part reads yet are carried here too)."""
    stage: str = ""
    settings: dict = field(default_factory=dict)


@dataclass
class NodeRecord:
    """The record of one node: its contract and parameters, how it configured itself, every step,
    the answer and why, every value its resolver gave, its cost and budget, and its children."""
    node_id: str
    parent_id: object
    depth: int
    role: str
    task_id: object
    contract: dict
    parameters: dict
    configured: dict
    profile: dict
    steps: list
    answer: object
    accepted: bool
    reason: str
    evidence: dict
    output_checks: dict
    cost: dict
    cost_with_children: dict
    budget: dict
    choices: list
    children: list = field(default_factory=list)

    def to_dict(self) -> dict:
        out = {name: getattr(self, name) for name in self.__dataclass_fields__ if name not in ("steps", "children")}
        out["steps"] = [step.to_dict() for step in self.steps]
        out["children"] = [child.to_dict() for child in self.children]
        return out

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)

    def walk(self):
        """This record and every record under it, parents first."""
        yield self
        for child in self.children:
            yield from child.walk()

    def tree(self) -> list:
        """The tree of nodes as lines of text, one node on each line."""
        lines = []
        for record in self.walk():
            stages = " > ".join(step.stage for step in record.steps) or "(no stage of its own)"
            lines.append(f"{'    ' * record.depth}{record.node_id} [{record.role or 'node'}] depth {record.depth}: {stages} | "
                         f"answer {record.answer!r} | {record.reason} | model seconds {record.cost_with_children['model_s']:.3f}")
        return lines


# ---------------------------------------------------------------------------
# 5. The store of proven parameter sets
# ---------------------------------------------------------------------------

class ProvenStore:
    """Proven parameter sets by profile, and the stored Tasks that say which profile a Task is nearest to.

    A parameter set is kept as a Task Object in a `CheckedStore` of the kit, under its profile key
    ("kind: date-choice", "form: number", "work: table", "default: text"); an entry that is not admitted
    is never given. `exemplars` is {kind of work: CheckedStore of stored Tasks with their kind}: the
    nearest stored Tasks name the kind of a new Task, and the store's own familiarity floor says when
    a Task looks like nothing stored.
    """

    def __init__(self, exemplars=None):
        self.exemplars = dict(exemplars or {})
        self.sets = CheckedStore()
        self._read = {}

    def put(self, key, parameters, evidence=None, admitted=True):
        """Keep a parameter set for a profile key. `admitted` False keeps it without ever giving it."""
        self.sets.add(key, key, parameters.to_task_object(key, evidence), kind=key, checked=admitted)
        self._read.pop(key, None)
        return self

    def admit(self, key, parameters, gate) -> bool:
        """Put new parameters under a key only when the admission gate let them in. `gate` is the record
        of `stepkit.assembler.admission`, made on Tasks the parameters were not assembled on; it is kept
        with the set. A refused set is not stored, and the set that was stored stays."""
        if gate["admitted"]:
            self.put(key, parameters, {"admission": gate})
        return bool(gate["admitted"])

    def get(self, key):
        """The admitted parameter set under this key, or None."""
        if key not in self._read:
            entry = self.sets.get(key)
            self._read[key] = Parameters.from_task_object(entry["payload"]) if entry is not None and entry["checked"] else None
        return self._read[key]

    def nearest(self, task, profile, neighbours, measure, unfamiliar_q, keys) -> dict:
        """The proven parameter set nearest to the Task's profile. Returns what was found and how:
        {"parameters", "key", "tried", "kind", "top_similarity", "floor", "unfamiliar"}, and "measure" (vector or
        text) when stored Tasks were compared. With `measure` "auto" the Task's vector is used when it has one and
        the stored Tasks have vectors; otherwise the text.

        The kind of the Task is named by its nearest stored Tasks. The keys are tried in the order of
        `keys`; the first one with an admitted set wins. When the Task is under the familiarity floor,
        or no key has a set, the set under "default: <kind of work>" is given (None when there is none).
        """
        labels = {"form": profile.get("answer_form"), "work": profile.get("work")}
        found = {"kind": None, "top_similarity": None, "floor": None, "unfamiliar": False}
        stored = self.exemplars.get(profile.get("work"))
        if stored is not None and len(stored):
            vector = task.get("vector") if isinstance(task, dict) and measure in ("auto", "vector") else None
            if vector is not None and measure == "auto" and not stored.has_vectors():
                vector = None       # the rule of "auto": the stored Tasks hold no vector, so their text is compared
            how = {"vector": vector} if vector is not None else {"text": task_text_of(task)}
            found["measure"] = "vector" if vector is not None else "text"
            vote = stored.kind_vote(k=neighbours, exclude=[task_id_of(task)], **how)
            labels["kind"] = vote["kind"]
            found.update(kind=vote["kind"], top_similarity=vote["top_similarity"])
            if unfamiliar_q is not None:
                found["floor"] = stored.familiarity_floor(q=unfamiliar_q, by="vector" if vector is not None else "text")
                found["unfamiliar"] = bool(unfamiliar(vote["top_similarity"], found["floor"]))
        tried = [f"{label}: {labels[label]}" for label in keys if labels.get(label) is not None]
        default = f"default: {profile.get('work')}"
        key = default if found["unfamiliar"] else next((k for k in tried if self.get(k) is not None), default)
        return dict(found, tried=tried, key=key if self.get(key) is not None else None, parameters=self.get(key))

    def save(self, path):
        self.sets.save(path)

    @classmethod
    def load(cls, path, exemplars=None) -> "ProvenStore":
        store = cls(exemplars)
        store.sets = CheckedStore.load(path)
        return store


# ---------------------------------------------------------------------------
# 6. The node
# ---------------------------------------------------------------------------

@dataclass
class RunContext:
    """The state of one run of a node: on one Task, or on one list of Tasks. Every run starts from a new
    context, so nothing of one run carries over to the next: not the profile, not the parameters a store
    proved for another Task, not the child nodes, the cost or the record of choices."""
    task_id: object
    profile: dict
    resolver: Resolver
    configured: dict = field(default_factory=lambda: {"parameters": "the node's own"})
    children: list = field(default_factory=list)
    spent: dict = field(default_factory=lambda: add_costs([]))
    kinds: dict = field(default_factory=dict)            # kind of work -> Tasks of that kind in this run
    used_by_kind: dict = field(default_factory=dict)     # kind of work -> model seconds used so far
    not_started: list = field(default_factory=list)      # Tasks or steps that a running limit stopped, and why


def _refuse_no_match(node, found):
    raise ContractError(f"node {node.node_id}: no proven parameters match the profile (keys tried: {found.get('tried')})")


# rule name -> rule(node, what the store found) when no proven set matches the profile
NO_MATCH = {"default_set": lambda node, found: None, "refuse": _refuse_no_match}


class OmniNode:
    """One node. It is fully described by its contract and its parameters.

    The state of a run (profile, configuration, child nodes, cost, record of choices) is a `RunContext`.
    `configure(task, store)` prepares the context for that Task; `run(task, ...)` takes it, or starts a new
    one, so the order of calls on different Tasks does not matter. `resolver`, `children`, `profile`,
    `configured` and `spent` read the current (or last) run's context. The resolver given to the node is
    the base: every run works on a fork of it (the same evidence and strategies, an empty record).
    """

    def __init__(self, contract, parameters, node_id="n", parent=None, role="", resolver=None):
        self.contract, self.parameters = contract, parameters
        self.node_id, self.parent, self.role = node_id, parent, role
        self.depth = parent.depth + 1 if parent is not None else 0
        self.base_resolver = resolver or Resolver()
        self._prepared, self._given_profile = {}, None
        self.current = RunContext(None, {}, self.base_resolver.fork())

    # ---- the current run's state, by name (setters kept for code written before the run contexts) ----
    @property
    def resolver(self):
        return self.current.resolver

    @resolver.setter
    def resolver(self, value):
        """A new base resolver; the current run uses it too."""
        self.base_resolver = self.current.resolver = value

    @property
    def children(self):
        return self.current.children

    @children.setter
    def children(self, value):
        self.current.children = value

    @property
    def configured(self):
        return self.current.configured

    @configured.setter
    def configured(self, value):
        self.current.configured = value

    @property
    def spent(self):
        return self.current.spent

    @spent.setter
    def spent(self, value):
        self.current.spent = value

    @property
    def profile(self):
        """The profile of the current run's Task; before a run, a profile given for the next one."""
        return self.current.profile if self.current.task_id is not None else self._given_profile

    @profile.setter
    def profile(self, value):
        """Give the profile of the Task of the next `configure` or `run` (used once)."""
        self._given_profile = value

    def _new_context(self, task, profile=None):
        given = profile if profile is not None else self._given_profile
        self._given_profile = None
        if isinstance(task, list):
            return RunContext(None, {}, self.base_resolver.fork())
        return RunContext(task_id_of(task), dict(given) if given is not None else profile_of(task), self.base_resolver.fork())

    # ---- settings: never read directly ----
    def dimension(self, name):
        found = self.parameters.get(name) or self.contract.get(name) or self.resolver.evidence_dimension(name)
        if found is None:
            raise KeyError(f"node {self.node_id}: no dimension named {name!r} in its parameters, contract or evidence")
        return found

    def ask(self, name):
        """The value of one setting of this node, through its resolver (the choice is recorded)."""
        return self.resolver.value(self.dimension(name), {"profile": self.profile})

    def part_settings(self, part, source) -> dict:
        """The settings of one part as this node resolves them: its own dimension "part.<part>.<setting>"
        when the parameters hold one, else the shared one, for which the part's recorded setting is evidence."""
        recorded = {"part." + name: {"value": value, "source": "the recorded setting of this part"}
                    for name, value in source.parts[part].info.items()}
        out = {}
        for name in PART_SETTINGS:
            own = f"part.{part}.{name}"
            if own in self.parameters or self.resolver.evidence_dimension(own) is not None:
                out[name] = self.ask(own)
            else:
                out[name] = self.resolver.value(self.dimension("part." + name), {"evidence": recorded}, as_name=own)
        return out

    # ---- the running limits ----
    def used(self) -> dict:
        """The cost of this node and of every node under it, so far."""
        return add_costs([self.spent] + [child.used() for child in self.children])

    def left(self, kind=None) -> dict:
        """What is left now of this node's running limits: model seconds and tokens of the node and every
        node under it, child nodes, depth, and the model seconds of one kind of work when the contract
        names a limit for it (seconds per Task times the Tasks of that kind in this run). None: no limit."""
        used = self.used()
        seconds, tokens = self.ask("budget.model_seconds"), self.ask("budget.tokens")
        out = {"model_seconds": None if seconds is None else seconds - used["model_s"],
               "tokens": None if tokens is None else tokens - used["tok_in"] - used["tok_out"],
               "nodes": self.ask("budget.nodes") - len(self.children), "depth": self.ask("budget.depth"),
               "kind_model_seconds": None}
        by_kind = self.ask("budget.by_kind")
        if by_kind and kind in by_kind:
            out["kind_model_seconds"] = (by_kind[kind] * self.current.kinds.get(kind, 1)
                                         - self.current.used_by_kind.get(kind, 0))
        return out

    def left_model_seconds(self):
        """What is left of the budget of model seconds (never under 0), or None when there is no limit."""
        return _smallest(self.left()["model_seconds"])

    # ---- configure ----
    def configure(self, task, store, profile=None) -> dict:
        """Prepare the run of this Task: take the nearest proven parameters for its profile from the store,
        or apply the rule "retrieval.when_no_match" when none matches. Returns the record of how."""
        ctx = self.current = self._new_context(task, profile)
        found = store.nearest(task, ctx.profile, self.ask("retrieval.neighbours"), self.ask("retrieval.measure"),
                              self.ask("retrieval.unfamiliar_q"), self.ask("retrieval.keys"))
        proven = found.pop("parameters")
        if proven is not None:
            ctx.resolver.add_evidence(proven, f"the parameters admitted for the profile {found['key']!r}")
        else:
            NO_MATCH[self.ask("retrieval.when_no_match")](self, found)
        ctx.configured = dict(found, parameters="admitted" if proven is not None else "the node's own")
        self._prepared[ctx.task_id] = ctx
        return ctx.configured

    # ---- child nodes ----
    def derive(self, values=None, kind=None) -> Contract:
        """The contract of a child: this node's contract one level less deep, with no child nodes, no
        right to start any and no limit per kind, and with its own limits of model seconds and tokens by the
        rule "children.budget" (`kind`: the child's kind of work). `values` sets what the step needs."""
        depth = self.ask("budget.depth")
        if depth <= 0:
            raise ContractError(f"node {self.node_id}: the depth limit of its contract is reached, it can derive no child")
        own = CHILD_BUDGETS[self.ask("children.budget")](self.left(kind))
        derived = self.contract.with_({"budget.depth": depth - 1, **own}, by=f"derived by node {self.node_id}")
        for name in ("budget.nodes", "permissions.spawn", "budget.by_kind"):
            derived.add(CONTRACT[name])
        return derived.with_(values or {}, by=f"derived by node {self.node_id}")

    def spawn(self, contract, parameters=None, role="") -> "OmniNode":
        """Start a child node. The limits of this node's contract are enforced: the permission to
        spawn, the depth, the number of child nodes, and that the child is given no more than this node has."""
        if not self.ask("permissions.spawn"):
            raise ContractError(f"node {self.node_id}: its contract does not permit child nodes")
        depth, nodes = self.ask("budget.depth"), self.ask("budget.nodes")
        if depth <= 0:
            raise ContractError(f"node {self.node_id}: the depth limit of its contract is reached")
        if len(self.children) >= nodes:
            raise ContractError(f"node {self.node_id}: its contract allows {nodes} child nodes and all are started")
        child = OmniNode(contract, self.parameters if parameters is None else parameters,
                         f"{self.node_id}.{len(self.children) + 1}", self, role)
        if child.ask("budget.depth") >= depth or child.ask("budget.nodes") > nodes - len(self.children) - 1:
            raise ContractError(f"node {self.node_id}: a child's contract may not be deeper or wider than what is left")
        if child.ask("permissions.live") and not self.ask("permissions.live"):
            raise ContractError(f"node {self.node_id}: a child may not get a live source that the parent does not have")
        mine, theirs = self.ask("resources.parts"), child.ask("resources.parts")
        if mine is not None and (theirs is None or not set(theirs) <= set(mine)):
            raise ContractError(f"node {self.node_id}: a child may only get parts that the parent has")
        price = {"value": self.ask("price_per_model_second"), "source": f"the price of the parent node {self.node_id}",
                 "by": "caller"}
        child.base_resolver.evidence["price_per_model_second"] = price
        child.current.resolver.evidence["price_per_model_second"] = price
        self.children.append(child)
        return child

    def child_parameters(self, values=None) -> Parameters:
        """The parameters of a child that runs stages of its own: this node's, without its child rule."""
        return self.parameters.merged(Parameters([PARAMETERS["children.rule"]])).with_(values or {}, by=f"node {self.node_id}")

    # ---- run ----
    def run(self, task, source, store=None, seed=None, profile=None) -> NodeRecord:
        """Do the Task (or the list of Tasks) by the rule "children.rule": the node's own stages, one
        child for each Task, or a child for each typed step. The run takes the context that `configure`
        prepared for this Task, or a new one. The contract's input form is checked first. Returns the record."""
        ready = self._prepared.pop(None if isinstance(task, list) else task_id_of(task), None)
        ctx = ready or self._new_context(task, profile)
        if ready is not None and (profile is not None or self._given_profile is not None):
            ctx.profile = dict(profile if profile is not None else self._given_profile)
            self._given_profile = None
        self.current = ctx
        form = self.ask("input.form")
        if not INPUT_FORMS[form](task, ctx.profile):
            raise ContractError(f"node {self.node_id}: its contract takes input of the form {form!r}; this is not one "
                                f"(kind of work: {ctx.profile.get('work')!r}, a list of Tasks: {isinstance(task, list)})")
        return CHILD_RULES[self.ask("children.rule")](self, task, source, store, seed)

    def check_resources(self, arrangement, source):
        if source.live and not self.ask("permissions.live"):
            raise ContractError(f"node {self.node_id}: its contract does not permit a source that calls a model")
        parts, models = self.ask("resources.parts"), self.ask("resources.models")
        for part, kind in arrangement:
            if part not in source.parts or kind not in STAGE_KINDS:
                raise ContractError(f"node {self.node_id}: no part {part!r} in the source, or no stage type {kind!r}")
            if parts is not None and part not in parts:
                raise ContractError(f"node {self.node_id}: its contract does not give the part {part!r}")
            if models is not None and source.parts[part].model is not None and source.parts[part].model not in models:
                raise ContractError(f"node {self.node_id}: its contract does not give the model of the part {part!r}")

    def record(self, task, steps, answer, accepted, reason, evidence, children=()) -> NodeRecord:
        """Write the record of this node. The checks of the contract are put to the answer and recorded."""
        checks = {name: bool(CHECKS[name](answer, self.profile or {})) for name in self.ask("output.checks")}
        used, price, left = self.used(), self.ask("price_per_model_second"), self.left()
        budget = {"model_seconds": self.ask("budget.model_seconds"), "model_seconds_used": used["model_s"],
                  "model_seconds_left": left["model_seconds"], "tokens": self.ask("budget.tokens"),
                  "tokens_used": used["tok_in"] + used["tok_out"], "nodes": self.ask("budget.nodes"),
                  "nodes_started": len(self.children), "depth": self.ask("budget.depth"),
                  "by_kind": self.ask("budget.by_kind"), "used_by_kind": dict(self.current.used_by_kind),
                  "not_started": list(self.current.not_started),
                  "price_per_model_second": price, "priced_cost": price * used["model_s"]}
        return NodeRecord(self.node_id, self.parent.node_id if self.parent is not None else None, self.depth, self.role,
                          task_id_of(task) if not isinstance(task, list) else None, self.contract.summary(),
                          dict(self.parameters.summary(), **plain(self.parameters.extra)), dict(self.configured),
                          dict(self.profile or {}), list(steps), answer, bool(accepted), reason, dict(evidence or {}), checks,
                          dict(self.spent), used, budget, list(self.resolver.choices), list(children))


def _run_own_stages(node, task, source, store, seed):
    """The node's own stages, in order. The loop is the kit's `first_accepted`; every stage is data.
    A step whose answer fails a check of the contract is a failed step. A stop rule that is already met
    before the first stage (a limit of 0) starts no stage."""
    profile = node.profile
    source = source_for(source, profile)
    form = node.ask("output.form")
    arrangement = [tuple(stage) for stage in node.ask("arrangement")]
    if not arrangement:
        raise ContractError(f"node {node.node_id}: its parameters hold no arrangement")
    node.check_resources(arrangement, source)
    equal, fallback = EQUALITY[form](node), FALLBACKS[node.ask("fallback")]
    stops = [STOP_RULES[name] for name in node.ask("stop_rules")]
    before = next((why for why in (rule(node, add_costs([])) for rule in stops) if why), None)
    if before:
        node.spent = add_costs([])
        return node.record(task, [], None, False, before + " before the first stage: no stage was started", {})
    ended = {}

    def accept_of(position, part, kind_name):
        kind, last = STAGE_KINDS[kind_name], position == len(arrangement) - 1

        def accept(result, trace):
            answer = result.get("answer")
            agrees = kind.needs_agreement and any(equal(answer, step.answer) for step in trace)
            if kind.accepts(answer is not None, agrees, result.get("flags") or {}):
                ended["accepted"] = True
                return Decision(True, answer, f"{kind_name}({part}) gave the answer")
            spent = add_costs([trace.total_cost(), result.get("cost")])
            stopped = next((why for why in (rule(node, spent) for rule in stops) if why), None)
            if stopped or last:
                kept, how = fallback([step.answer for step in trace] + [answer])
                return Decision(True, kept, (stopped or "no stage gave the answer") + ": " + how)
            return Decision(False, None, f"{kind_name}({part}) did not give the answer")
        return accept

    session = source.session(task, form=form, seed=seed, profile=profile, checks=node.ask("output.checks"))
    steps = [Step(part, accept_of(position, part, kind)) for position, (part, kind) in enumerate(arrangement)]
    trace = first_accepted(task, steps, session, input_profile=profile, seed=seed)
    done = [NodeStep(**asdict(step), stage=f"{kind}({part})", settings=node.part_settings(part, source))
            for step, (part, kind) in zip(trace, arrangement)]
    node.spent = trace.total_cost()
    return node.record(task, done, trace.answer, ended.get("accepted", False), trace.reason,
                       done[-1].output_profile if done else {})


def _not_started(node, task, profile, position, why):
    """The record of a Task that a running limit stopped: no node was started for it."""
    nothing = add_costs([])
    return NodeRecord(f"{node.node_id}.not-started-{position}", node.node_id, node.depth + 1, "not started",
                      task_id_of(task), {}, {}, {}, dict(profile), [], None, False,
                      f"not started: the running limit of {why} is reached", {}, {}, nothing, nothing, {}, [])


def _stop(node, task, profile, kind, reached, source):
    node.current.not_started.append({"task": task_id_of(task), "why": reached})
    return None


def _free_parts(node, task, profile, kind, reached, source):
    """Start the child with the fallback arrangement, which may hold only parts that call no model."""
    arrangement = [list(stage) for stage in node.ask("children.fallback_arrangement")]
    if reached in STRUCTURAL_LIMITS or not arrangement:
        return _stop(node, task, profile, kind, reached, source)
    parts = source_for(source, profile).parts
    if any(parts[part].model is not None for part, _ in arrangement):
        raise ContractError(f"node {node.node_id}: the fallback arrangement may hold only parts that call no model")
    child = node.spawn(node.derive({"input.form": kind, "output.form": profile["answer_form"], "budget.model_seconds": None,
                                    "budget.tokens": None}, kind),
                       node.child_parameters({"arrangement": arrangement}), f"task, free parts only ({reached} used up)")
    child.profile = profile
    return child


# rule name -> rule(node, task, profile, kind, reached limit, source) -> a child to start, or None (not started)
USED_UP = {"stop": _stop, "free_parts": _free_parts}


def _run_one_child_per_task(node, tasks, source, store, seed):
    """A list of Tasks: one child for each Task, with a contract derived from the Task's profile. The
    child configures itself from the store and runs its own stages. Before each child the parent tests
    its running limits; when one is reached, the rule "budget.when_used_up" decides. The parent keeps the
    tree and the cost; a Task that was not started gets a record that says why."""
    ctx = node.current
    profiles = [profile_of(task) for task in tasks]
    ctx.kinds = dict(Counter(profile["work"] for profile in profiles))
    records = []
    for position, (task, profile) in enumerate(zip(tasks, profiles), 1):
        kind = profile["work"]
        reached = limit_reached(node.left(kind))
        if reached is None:
            child = node.spawn(node.derive({"input.form": kind, "output.form": profile["answer_form"]}, kind),
                               node.child_parameters(), "task")
            child.profile = profile
            if store is not None:
                child.configure(task, store)
        else:
            child = USED_UP[node.ask("budget.when_used_up")](node, task, profile, kind, reached, source)
            if child is None:
                records.append(_not_started(node, task, profile, position, reached))
                continue
        record = child.run(task, source, store, seed)
        ctx.used_by_kind[kind] = ctx.used_by_kind.get(kind, 0) + record.cost_with_children["model_s"]
        records.append(record)
    started = len(records) - len(ctx.not_started)
    return node.record(tasks, [], None, False, f"{started} child nodes for {len(tasks)} Tasks, one for each Task "
                       f"that a running limit did not stop", {}, records)


def _run_typed_steps(node, task, source, store, seed):
    """One Task done by child nodes, one for each typed step of "children.steps". A step is data:
    {"name", "when" (a name in CONDITIONS), "contract" (values for the derived contract), "parameters"
    (values for the child's parameters)}. Before each step the running limits are tested; a reached limit
    starts no further step. The rule "children.answer" turns their answers into the node's, and the
    node's own output checks are put to that answer: a failed check leaves the node with no answer."""
    ctx = node.current
    kind = node.profile.get("work")
    ctx.kinds = {kind: 1}
    records = []
    for step in node.ask("children.steps"):
        if not CONDITIONS[step.get("when", "always")](records):
            continue
        reached = limit_reached(node.left(kind))
        if reached is not None:
            ctx.not_started.append({"step": step.get("name", ""), "why": reached})
            break
        child = node.spawn(node.derive(step.get("contract"), kind), node.child_parameters(step.get("parameters")),
                           step.get("name", ""))
        child.profile = node.profile
        record = child.run(task, source, store, seed)
        ctx.used_by_kind[kind] = ctx.used_by_kind.get(kind, 0) + record.cost_with_children["model_s"]
        records.append(record)
    answer, accepted, reason = ANSWER_RULES[node.ask("children.answer")](records)
    failed = [name for name in node.ask("output.checks") if answer is not None and not CHECKS[name](answer, node.profile)]
    if failed:
        answer, accepted, reason = None, False, reason + "; the answer failed the check " + ", ".join(failed)
    return node.record(task, [], answer, accepted, reason, records[-1].evidence if records else {}, records)


# rule name -> how a node does its Task
CHILD_RULES = {"none": _run_own_stages, "one_per_task": _run_one_child_per_task, "steps": _run_typed_steps}


def contract_for(profile, values=None) -> Contract:
    """The contract of a node for one Task with this profile: its kind of work is the form of the
    input, the answer form it wants is the form of the output. `values` sets the rest."""
    return CONTRACT.with_({"input.form": profile["work"], "output.form": profile["answer_form"]},
                          by="contract_for: the Task's profile").with_(values or {})


# ---------------------------------------------------------------------------
# 7. The word Tasks of test 7 and of the mixed benchmark, as parts
# ---------------------------------------------------------------------------

WORD_MODELS = {"S": "small", "B": "larger"}
WORD_WAYS = ("direct", "worked", "program", "reuse")
WORD_ITEMS = os.path.join(S.MIXED_RUN, "items.jsonl")
WORD_VECTORS = os.path.join(S.MIXED_RUN, "vectors.json")
WORD_RECORDS = (os.path.join(S.MIXED_RUN, "records.jsonl"), os.path.join(S.T7_RUN, "records.jsonl"))


def word_parts(tools=None) -> dict:
    """The parts of test 10: the calculator, eight model parts (two models, four ways), and, when
    `tools(task)` is given, the step tools as one exact part that is silent unless sure."""
    examples = S.load_by_path("toolsmith").NEIGHBOURS
    parts = {"calc": Part("calc", [{"call": "T.calc"}], kinds=("take",), info={"prompt_form": None})}
    for letter, label in WORD_MODELS.items():
        for way in WORD_WAYS:
            name = f"{letter}.{way}"
            info = {"model": label, "prompt_form": way}
            if way == "reuse":
                info["examples"] = examples
            parts[name] = Part(name, [{"call": name}], model=label, info=info)
    if tools is not None:
        parts["tools"] = Part("tools", kinds=("take",), value=tools, info={"prompt_form": None})
    return parts


def read_jsonl(path):
    with open(path, encoding="utf-8") as lines:
        return [json.loads(line) for line in lines if line.strip()]


def word_tasks():
    """The 1,200 Tasks of the mixed benchmark with their place, split (library, fit, test) and recorded
    text vector. The answer key stays in "gold": a node never reads it."""
    with open(WORD_VECTORS, encoding="utf-8") as handle:
        vectors = json.load(handle)
    return [dict(item, vector=vectors.get(item["id"])) for item in S.split_by_position(read_jsonl(WORD_ITEMS))]


def word_source(tools=None) -> ReplaySource:
    """A replay of the word Tasks: the records of the mixed benchmark and of test 7."""
    records = [record for path in WORD_RECORDS for record in read_jsonl(path)]
    return ReplaySource(RecordedProbes.from_records(records), word_parts(tools))


def library_store(tasks, without_kind=None) -> CheckedStore:
    """The library Tasks as stored Tasks that name the kind of a new Task (their vectors, their kinds)."""
    store = CheckedStore()
    for task in tasks:
        if task["split"] == "library" and task["kind"] != without_kind:
            store.add(task["id"], task["question"], None, kind=task["kind"], checked=False, vector=task["vector"])
    return store


def step_tool_answers(tasks) -> dict:
    """{Task id: answer or None} of the six step tools of test 7's joint arm, computed by their own code
    (no model, network blocked while they load). The value is in the answer form of the question."""
    toolsmith = S.load_by_path("toolsmith")
    found = S.load_by_path("ag_tools", os.path.join(S.T7_DIR, "ag_tools.py")).outcomes(toolsmith, tasks)
    return {task_id: answer for task_id, (_, answer) in found.items()}


# ---------------------------------------------------------------------------
# 8. The table Tasks of test 4, as parts. Added after the freeze of the assembler (t13-omninode/runs/
#    t13-v1/assembler.frozen.json, 20:21:18 Eastern): only this adapter and the stage take_if_one_cell
#    are new for tables; the search and the chooser are the frozen ones.
# ---------------------------------------------------------------------------

TABLE_RUNS = ("fit-v1", "test-v1")
TABLE_ITEMS = os.path.join(S.T4_DIR, "data", "items.jsonl")
TABLE_MODELS = {"S": "small", "L": "larger"}
# the order in which test 4's runner made the queries of a Task (probes.py, run_task)
QUERY_CALLS = ("sql.S", "repair.S", "sql.L", "repair.L")
QUERY_KINDS = ("take", "agree", "take_if_one_cell")
ONE_CELL = "one_cell_passes_check"

register_stage_kind(StageKind("take_if_one_cell", needs_flag=ONE_CELL))


def table_replay():
    """Test 4's replay.py, imported by path: its arms, its check and its equality of two answers.
    Nothing is written in its folder."""
    return S.load_by_path("t4_replay", os.path.join(S.T4_DIR, "replay.py"))


def table_check(answer, profile):
    """Test 4's simple check of an answer (replay.py, check): not empty, not a refusal, and a number
    when the question asks a count. It reads the question's features from the profile."""
    return bool(table_replay().check(answer, {"question_features": profile.get("question_features") or {}}))


def table_same(a, b):
    """Test 4's equality of two answers: the official match in both directions (replay.py, same)."""
    return bool(table_replay().same(a, b))


def table_right(answer, task):
    """The official scoring rule of the dataset, as test 4's runner applied it: the answer key is read
    only after the node has answered."""
    return bool(table_replay().W.wtq_match(list(answer or []), task["gold"]))


def _profile_table_task(task, profile):
    """A Task with a table is table work. Its answer is a list of values. The features of the question
    are made by code (the tool of test 4); the table's own profile is the one test 4 recorded."""
    if isinstance(task, dict) and "table_file" in task:
        profile["work"] = "table"
        profile["answer_form"] = "values"
        profile["question_features"] = table_replay().W.question_features(task["question"])
        profile["table"] = dict(task.get("table_profile") or {})


def _non_empty_list(answer):
    return isinstance(answer, list) and len(answer) > 0


def _failed_or_empty(ran):
    return (not ran[-1]["evidence"].get("ran")) or bool(ran[-1]["evidence"].get("empty"))


PROFILERS.append(_profile_table_task)
FORMS.update({"values": _non_empty_list, "query_result": _non_empty_list})
EQUALITY.update({"values": lambda node: table_same, "query_result": lambda node: table_same})
CHECKS["table_answer_check"] = lambda answer, profile: table_check(answer, profile)
CALL_CONDITIONS.update({"query_failed_or_empty": _failed_or_empty,
                        "several_cells": lambda ran: bool(ran[-1]["evidence"].get("several_cells"))})
EVIDENCE_RULES[ONE_CELL] = lambda evidence, answer, profile: bool(
    evidence.get("ran") and not evidence.get("empty") and evidence.get("one_cell") and table_check(answer, profile))


def table_config():
    """The settings test 4 recorded its probes with (runs/test-v1/config.json; the fit run has the same)."""
    with open(os.path.join(S.T4_DIR, "runs", TABLE_RUNS[-1], "config.json"), encoding="utf-8") as handle:
        return json.load(handle)


def table_parts() -> dict:
    """The 14 parts of the table Tasks: every probe test 4 recorded.

    read.<M>.table          model M reads the whole table
    sql.<M>                 model M writes one query; code runs it; the answer is the first column of the
                            result (test 4's plain query pipeline)
    sqlr.<M>                the same, with test 4's repair step when the query failed or was empty
    read.<R>.of.<query>     the query part runs; when its result has several cells, model R reads that result
    S is the small model and L the larger one. The four query parts may also be used with the stage
    take_if_one_cell: the answer of a query whose result is one cell that passes test 4's check.
    """
    config = table_config()
    common = {"temperature": config["temperature"]}
    parts = {}
    for m, label in TABLE_MODELS.items():
        parts[f"read.{m}.table"] = Part(f"read.{m}.table", [{"call": f"read.{m}.table"}], model=label,
                                        info=dict(common, model=label, prompt_form="read_table", harness_instruction="read"))
    paths = {}
    for repaired in (False, True):
        for m, label in TABLE_MODELS.items():
            name = f"{'sqlr' if repaired else 'sql'}.{m}"
            calls = [{"call": f"sql.{m}"}]
            if repaired:
                calls.append({"call": f"repair.{m}", "when": "query_failed_or_empty", "if_recorded": True})
            paths[name] = calls
            parts[name] = Part(name, calls, kinds=QUERY_KINDS, model=label, evidence=(ONE_CELL,),
                               info=dict(common, model=label, prompt_form="query_with_repair" if repaired else "query",
                                         harness_tools=["sqlite_read_only"], harness_instruction="sql_system, sql"
                                         + (", repair" if repaired else "")))
    for query, calls in paths.items():
        for r, label in TABLE_MODELS.items():
            name = f"read.{r}.of.{query}"
            parts[name] = Part(name, calls + [{"call": f"read.{r}.result#{{result_slot}}", "when": "several_cells", "if_recorded": True}],
                               answer="final_only", model=label,
                               info=dict(common, model=label, prompt_form="read_query_result", harness_instruction="read"))
    return parts


def table_tasks() -> list:
    """The 419 table Tasks of test 4 (150 fit, 269 test) in the order of its items file, with the table
    profile and question features its runner recorded. The answer key stays in "gold"."""
    recorded = {}
    for run in TABLE_RUNS:
        for row in read_jsonl(os.path.join(S.T4_DIR, "runs", run, "records.jsonl")):
            recorded[row["id"]] = row
    out = []
    for item in read_jsonl(TABLE_ITEMS):
        row = recorded[item["id"]]
        out.append({"id": item["id"], "question": item["question"], "gold": item["answers"], "split": item["split"],
                    "table_file": item["table_file"], "table_profile": row["table_profile"]})
    return out


def table_probe_records() -> dict:
    """{call: {Task id: record}} from test 4's records, in the form of the kit's RecordedProbes.

    A query call gets its evidence by code: it ran, its result was empty, one cell or several cells, and
    the place of its result. The reader of a query result is kept under "read.<R>.result#<place>", where
    the place is the position (1 to 4, in the order sql.S, repair.S, sql.L, repair.L) of the first query
    that gave that result; so a result that two queries gave is read, and paid, once, as in test 4.
    """
    by = {}
    for run in TABLE_RUNS:
        for row in read_jsonl(os.path.join(S.T4_DIR, "runs", run, "records.jsonl")):
            place_of, places = {}, {}
            for position, key in enumerate(QUERY_CALLS, 1):
                probe = row["probes"].get(key)
                if probe is not None:
                    place_of.setdefault(probe["result_digest"], position)
                    places[key] = place_of[probe["result_digest"]]
            for key, probe in row["probes"].items():
                name, evidence = key, {}
                if key in places:
                    shape = probe["result_profile"]
                    ran, empty, one = bool(shape["ok"]), bool(shape["empty"]), bool(shape["single_cell"])
                    evidence = {"ran": ran, "empty": empty, "one_cell": one, "several_cells": ran and not empty and not one,
                                "n_cells": shape["n_cells"], "result_slot": places[key]}
                elif ".result." in key:
                    reader, digest = key.split(".")[1], key.split(".result.")[1]
                    name = f"read.{reader}.result#{place_of[digest]}"
                answer = list(probe.get("answer") or [])
                by.setdefault(name, {})[row["id"]] = {
                    "probe": name, "item": row["id"], "pred": answer or None, "correct": bool(probe["right"]),
                    "model_s": probe.get("model_s", 0.0), "calls": probe.get("calls", 0), "tok_in": probe.get("tok_in", 0),
                    "tok_out": probe.get("tok_out", 0), "evidence": evidence, "recorded_as": key}
    return by


def table_source() -> ReplaySource:
    """A replay of the table Tasks: test 4's records of every probe."""
    return ReplaySource(RecordedProbes(table_probe_records()), table_parts())


# ---------------------------------------------------------------------------
# 9. Which dimensions of the catalog of November 12 the node's settings are mapped to: a hand-written name table
#    (notes/work-2026-11-12-omninode-universal/catalog/dimensions.json); the node reads no catalog dimension
# ---------------------------------------------------------------------------

DECIDES, ENFORCED, BUILT_OFF, CARRIED = ("decides in a replay today", "a limit that is checked",
                                         "built and tested; off in every figure of test 13", "stored and carried into the records only")
# the node's dimension -> (the catalog's dimension, what the node does with it today)
CATALOG_NAMES = {
    "input.form": ("contract.input.type", ENFORCED),
    "output.form": ("contract.output.form", DECIDES),
    "output.checks": ("check.method", DECIDES),
    "budget.model_seconds": ("contract.budget.model_seconds", ENFORCED),
    "budget.tokens": ("contract.budget.tokens", ENFORCED),
    "budget.nodes": ("contract.budget.children", ENFORCED),
    "budget.depth": ("contract.budget.depth", ENFORCED),
    "resources.models": ("contract.resources.models", ENFORCED),
    "resources.stores": ("contract.resources.stores", CARRIED),
    "resources.cartridges": ("weights.cartridge", CARRIED),
    "permissions.spawn": ("contract.permissions", ENFORCED),
    "permissions.live": ("contract.permissions", ENFORCED),
    "arrangement": ("portfolio.order", DECIDES),
    "price_per_model_second": ("economics.price", DECIDES),
    "fallback": ("portfolio.fallback_default", DECIDES),
    "stop_rules": ("portfolio.stop_rule", ENFORCED),
    "retrieval.neighbours": ("profile.similarity.k", DECIDES),
    "retrieval.measure": ("profile.similarity.metric", DECIDES),
    "retrieval.unfamiliar_q": ("profile.unfamiliar.threshold", BUILT_OFF),
    "retrieval.keys": ("profile.granularity", DECIDES),
    "children.rule": ("structure.split.when", DECIDES),
    "children.steps": ("structure.split.decomposer", DECIDES),
    "children.answer": ("structure.merge", DECIDES),
    "part.model": ("model.choice", CARRIED),
    "part.prompt_form": ("model.prompt.form", CARRIED),
    "part.examples": ("model.prompt.examples", CARRIED),
    "part.context_length": ("model.context.length", CARRIED),
    "part.temperature": ("model.decoding.temperature", CARRIED),
    "part.samples": ("model.decoding.samples", CARRIED),
    "part.harness_tools": ("harness.tools_offered", CARRIED),
    "part.harness_instruction": ("harness.instruction_at_step", CARRIED),
    "part.cartridge_id": ("weights.cartridge", CARRIED),
    "part.mask_id": ("weights.mask.level", CARRIED),
    "resolver.strategy": ("strategy.resolve", DECIDES),
    "resolver.exploration_seed": ("strategy.exploration", CARRIED),
    "assembler.within_points": ("strategy.selection_rule", DECIDES),
    "assembler.admission_margin_points": ("learning.admission", BUILT_OFF),
}


def catalog_use(catalog) -> dict:
    """For each dimension of the catalog: the node's dimensions mapped to it by hand, and what they do today.
    `catalog` is the Settings of `stepkit.dimension.load_catalog`. A catalog name that the mapping names
    but the catalog lacks is listed under "not_in_catalog"."""
    use = {dimension.name: [] for dimension in catalog}
    missing = []
    for mine, (theirs, status) in CATALOG_NAMES.items():
        if theirs in use:
            use[theirs].append({"node_dimension": mine, "status": status})
        else:
            missing.append([mine, theirs])
    ranked = (DECIDES, ENFORCED, BUILT_OFF, CARRIED)
    best = {name: min((ranked.index(entry["status"]) for entry in entries), default=None) for name, entries in use.items()}
    return {"catalog_dimensions": len(use),
            "used": {status: sorted(name for name, rank in best.items() if rank is not None and ranked[rank] == status) for status in ranked},
            "not_used": sorted(name for name, rank in best.items() if rank is None),
            "by_catalog_dimension": {name: entries for name, entries in use.items() if entries},
            "not_in_catalog": missing}
