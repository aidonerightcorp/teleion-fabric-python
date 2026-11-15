# Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md
"""The ladder: the cheapest part first, in tiers, with a gate on every part.

A Task climbs an order of tiers. Each tier is a list of kit parts (`stepkit.omninode.Part`), and each part has a
gate: a check of that step's own output that says "stop here with this answer" or "go on". Every attempt is kept
with its result state, every tier with what it spent, and an answer of an exact part that passes its gate is never
followed by a model call (the invariant).

INTERNAL: this is the interface of external provider's cheapest-effective-tool ladder (Loop Engine,
external invariants and cheapest-tool ladder engines: tier specs, a gate per tier, the refusal of model spend
when tier 0 solves, telemetry, the eight result states) over the kit's measured parts instead of canned engines.
The external ladder bridge maps one to the other and runs that module's own checks over these records.

The file is `tier_ladder.py`, not `ladder.py`: the package already exports the function `stepkit.ladder`
(`decide.ladder`, the two-level ladder), and importing a submodule of the same name would replace that attribute.

Tiers, by what their parts spend (a kit part has a model label; None is a part that calls no model):
    L0  exact tools: the calculator, the six step tools, a query that code runs        no model
    L1  stored programs that run with no model (an admitted program for a kind)          no model
    L2  a route chosen by the profile (kind vote and kind table); it names one part      no model
    L3  table tools                                                                      no model
    L4  the small model's parts                                                          the small model
    L5  the larger model's parts                                                         the larger model
An order is a list of tiers; a tier id may come back (an assembled arrangement can go L4, L5, L4). The order is the
value of the dimension `ladder.tiers`, and it can differ per profile: a proven order is kept per profile in the
kit's `ProvenStore` (a `Parameters` set, so a Task Object), or an arrangement of the kit's assembler is converted
into one (`tiers_from_arrangement`). No new learner: the order per profile comes from the store and the assembler.

Gates (registered by name in GATES; the name is data):
    answered          the part gave an answer of the wanted form (an exact tool answers only what it computes)
    form              the part ran and its output has the wanted form (a program whose value names one option)
    agree             the part's answer equals the answer of a named earlier part (or of any earlier part); the
                      rung says which answer is kept, its own ("self") or the other one ("other"), and the kept
                      answer is compared relative to the other (the argument order of test 7's tolerance test)
    reply_confidence  the reply checker's confidence for the part's reply is at least `ladder.gate.reply_confidence`
    stage             a stage type of the assembler (take, agree, take_if_one_cell), for converted arrangements
    never             never stops: the answer is kept for a later comparison
    none              no gate: nothing checks this answer
When no gate passes, the rule `ladder.when_no_gate_passes` names the final answer; such an answer is never
"accepted".

The eight result states (the words of external provider's state machine), one step at a time; "invalidated" from any state:
    attempted       the part ran (the step was paid for)
    artifact_valid  its output is present and has the wanted form (the record keeps a sha256 of it)
    score_valid     the contract's output checks pass and a gate gave it a score
    accepted        its answer became the Task's answer through a passed gate, checked by something other than it
    paired          the order that made it was compared with a named baseline on the same Tasks
    selected        that order was the assembler's choice for its profile
    promoted        that order passed the admission gate on Tasks it was not made on
    invalidated     that order was rolled back
The first four come from the run. The last four belong to the order, and `mark` writes them onto the accepted
attempts that the order made, when the evidence exists.

The invariant (`ladder.invariant`): "exact_first" puts the reference exact parts (`ladder.exact_parts`) first with
the gate "answered" and records the repair; "refuse" refuses an order that does not start with them; "record_only"
runs the order as given (a replay of a recorded arm) and checks on the side whether an exact answer was followed by
model spend, running the free exact parts that the order skipped in a shadow session (not paid, not used for the
answer). In every mode a model attempt after an answer of any other part that calls no model (one outside
`ladder.exact_parts`, or with a gate that does not stop on an answer) is flagged as well (added after the independent
check of J2). A request that forces a tier (`ladder.force_tier`, external provider's force_direct_tier) is refused when an exact
part answers.

The ladder runs as an OmniNode: `children.rule = "ladder"` is registered in the node's CHILD_RULES when this module
is imported, so the contract holds (parts, models, permission to call a model, output checks), every setting is
asked from the node's resolver and recorded, and the ladder's own record is `NodeRecord.evidence["ladder"]`.

    store = store_of(test7_orders()["E3b"], "test 7, arm E3b")
    record = run(task, O.word_source(), store, values=TEST7_VALUES)
    ladder = record.evidence["ladder"]
    print(record.answer, ladder["final_tier"], ladder["final_state"], ladder["invariant"]["held"])

Every number of a setting is a Dimension (`SETTINGS`); tools_dev/find_bare_scalars.py checks this file.
Needs numpy (through the kit's store and assembler). Calls no model unless the source is a `LiveSource` and the
contract permits it.
"""
import hashlib
import json
import os
from dataclasses import asdict

from . import omninode as O
from .assembler import SETTINGS as SEARCH
from .assembler import STAGE_KINDS, answers_equal
from .decide import Decision, KindTable, Step, first_accepted
from .dimension import CALLER, CHOICES, JOINT, NUMBERS, STRUCTURED, Dimension, Settings, plain
from .record import Trace, add_costs, task_id_of, task_text_of
from .reply import ReplyChecker

HERE = os.path.dirname(os.path.abspath(__file__))
RECORD_FORMAT = "stepkit ladder record, version 1"

# the tiers, by what their parts spend; the tier of a part comes from its model label (`ladder.tier_of_model`)
TIERS = {"L0": "exact tools", "L1": "stored programs that run with no model", "L2": "a route chosen by the profile",
         "L3": "table tools", "L4": "the small model's parts", "L5": "the larger model's parts"}
# the eight result states, in order; the last one ends a chain from any state
STATES = ("attempted", "artifact_valid", "score_valid", "accepted", "paired", "selected", "promoted", "invalidated")
TERMINAL = STATES[-1]


# ---------------------------------------------------------------------------
# 1. Orders as data
# ---------------------------------------------------------------------------

def rung(part, gate, **more):
    """One part of a tier with its gate. More fields: "with" and "keep" for agree, "checker" and "kinds" for
    reply_confidence, "stage" for stage."""
    return dict(more, part=part, gate=gate)


def agree(part, others, keep):
    """A rung with the gate "agree": `others` are the parts it is compared with ("earlier": every earlier part),
    `keep` is "self" or "other"."""
    return {"part": part, "gate": "agree", "with": others if others == "earlier" else list(others), "keep": keep}


def tier(tier_id, *rungs):
    """One tier: its id and its parts, in order, each with its gate."""
    return {"tier": tier_id, "parts": [dict(item) for item in rungs]}


def route(rule, store, table, default, gate="none"):
    """A route (tier L2): the rule names one part for the Task (the kind vote of a named store, then the kind
    table), and that part runs with `gate`. A route is the last tier of an order."""
    return {"tier": "L2", "route": rule, "store": store, "table": plain(table), "default": default, "gate": gate}


L0_CALC = tier("L0", rung("calc", "answered"))
L0_TOOLS_CALC = tier("L0", rung("tools", "answered"), rung("calc", "answered"))
# test 7's arm E3 (form checks only, no kind label) and the fair baseline CL, over the kit's word parts
E3_ORDER = [L0_CALC, tier("L4", rung("S.reuse", "form")), tier("L5", rung("B.reuse", "form"), rung("B.worked", "none"))]
CL_ORDER = [L0_CALC, tier("L5", rung("B.worked", "none"))]


SETTINGS = Settings(name="ladder", dimensions=[
    Dimension("ladder.tiers", [E3_ORDER, CL_ORDER], kind=STRUCTURED,
              generator={"name": "stepkit.tier_ladder.tiers_from_arrangement",
                         "text": "any list of tiers, each {tier, parts: [{part, gate, ...}]}, the last one may be a route "
                                 "{tier: L2, route, store, table, default}; an arrangement of the assembler converts into one"},
              about="the order of the ladder for a profile: tiers in order, each a list of kit parts with a gate on each; "
                    "the value for a profile comes from the proven set stored for it, else this default (test 7's E3 over "
                    "the word parts, then calculator-then-larger)"),
    Dimension("ladder.order_from", ["tiers_else_arrangement", "tiers", "arrangement"], kind=CHOICES,
              about="where the order of a run comes from: the proven ladder order of the profile, else the proven "
                    "arrangement of the assembler (converted), else the node's own order; or only one of the two"),
    Dimension("ladder.invariant", ["exact_first", "refuse", "record_only"], kind=CHOICES,
              about="the invariant 'an exact answer that passes its gate is never followed by model spend': put the "
                    "reference exact parts first (a recorded repair), refuse an order that does not start with them, or "
                    "run the order as given and record every violation (for a replay of a recorded arm)"),
    Dimension("ladder.exact_parts", [["calc"], ["tools", "calc"], []], kind=CHOICES,
              about="the reference exact parts of the invariant, in the order they run first, each with the gate 'answered'"),
    Dimension("ladder.force_tier", [None, "L5", "L4", "L0"], kind=CHOICES,
              about="a request to go straight to one tier (external provider's force_direct_tier); None: no such request; a forced "
                    "model tier is refused when a reference exact part answers"),
    Dimension("ladder.when_no_gate_passes", ["last_part", "last_answered", "none"], kind=CHOICES,
              about="the final answer when no gate passes: the last part's own answer (the kit's first_accepted, test 7), "
                    "the last answer any part gave (the assembler, test 10), or none; such an answer is never accepted"),
    Dimension("ladder.form_rule", ["contract", "any"], kind=CHOICES,
              about="the answer form a part must give: the contract's output form (the node's rule), or any answer "
                    "(test 7's replay, which checks no form beyond the recorded one)"),
    Dimension("ladder.equality", ["relative_to_other", "answers_equal"], kind=CHOICES,
              about="when two answers agree: numbers only, |kept - other| <= tolerance * max(1, |other|) (test 7's step "
                    "rules), or the assembler's rule (numbers within its tolerance, texts equal)"),
    Dimension("ladder.number_tolerance", [1e-3], [0.0, 1e-4, 1e-3, 1e-2], NUMBERS, {"min": 0.0, "max": 0.1},
              about="the tolerance of the equality 'relative_to_other'"),
    SEARCH["assembler.number_equality"],
    Dimension("ladder.gate.reply_confidence", [0.9, 0.8, 0.7], [0.5, 0.6, 0.7, 0.8, 0.9, 0.95], NUMBERS,
              {"min": 0.0, "max": 1.0},
              about="the bar of the gate 'reply_confidence': a reply is kept when the reply checker's confidence is at least this"),
    Dimension("ladder.tier_of_model", [{"exact": "L0", "small": "L4", "larger": "L5"}], kind=JOINT,
              about="the tier of a part by the model it calls ('exact': none); a tier that holds a model part must be "
                    "one of the model tiers named here, and a part that calls no model may not sit in one"),
    Dimension("ladder.money_per_model_second", [0.0], [0.0], NUMBERS, {"min": 0.0},
              about="US dollars per model second; 0 for the local card (test 7 spent no money)"),
    Dimension("ladder.money_per_token", [0.0], [0.0], NUMBERS, {"min": 0.0},
              about="US dollars per token of a paid route; 0 for the local models"),
])


class LadderRefused(O.ContractError):
    """An order the ladder cannot run: an unknown part, gate or route, a tier whose label does not match what its
    parts spend, a route that is not the last tier, or a reference exact part that is not an exact part."""


class StateError(ValueError):
    """A result state out of order, or without the evidence it needs."""


# ---------------------------------------------------------------------------
# 2. The eight result states
# ---------------------------------------------------------------------------

# what a state needs before it is reached: the evidence external provider's state machine asks for, and the maker of an answer
NEEDS = {"artifact_valid": ("digest",), "score_valid": ("score",), "accepted": ("score", "bar", "verifier", "maker"),
         "paired": ("baseline",), "selected": ("rank",), "promoted": ("admission",), "invalidated": ("why",)}


def advance(chain, state, **evidence):
    """Add one state to a chain of states (a list of {"state", ...evidence}). One state at a time, in order;
    "invalidated" may follow any state and ends the chain. Raises StateError otherwise. Returns the chain."""
    if state not in STATES:
        raise StateError(f"no result state {state!r}; the states are {STATES}")
    last = chain[-1]["state"] if chain else None
    if last == TERMINAL:
        raise StateError("an invalidated result takes no further state")
    if state != TERMINAL:
        expected = STATES[0] if last is None else STATES[STATES.index(last) + 1]
        if state != expected:
            raise StateError(f"the state {state!r} cannot follow {last!r}: one state at a time, in order")
    missing = [key for key in NEEDS.get(state, ()) if evidence.get(key) is None]
    if missing:
        raise StateError(f"the state {state!r} needs {missing}")
    if state == "accepted":
        if evidence["score"] < evidence["bar"]:
            raise StateError(f"a score of {evidence['score']} is under the bar {evidence['bar']}")
        if evidence["verifier"] == evidence["maker"]:
            raise StateError("a part cannot be the checker of its own answer")
    if state == "selected" and evidence["rank"] != 1:
        raise StateError("only the first choice is selected")
    if state == "promoted" and not evidence["admission"].get("admitted"):
        raise StateError("the admission gate did not admit the order")
    chain.append(dict(plain(evidence), state=state))
    return chain


# ---------------------------------------------------------------------------
# 3. Gates: gate(rung, result, trace, run) -> judgement. Registered by name.
# ---------------------------------------------------------------------------

GATES = {}


def register_gate(name):
    """Register `function(rung, result, trace, run) -> judgement` as a gate under this name."""
    def register(function):
        GATES[name] = function
        return function
    return register


def _judged(passed, score, bar, why, keep=None, kept_from=None, verifier=None, checker=None):
    """A gate's judgement. `score` is None when the step gave nothing to score; `keep` is the answer kept when the
    gate passes and `kept_from` the part that gave it; `verifier` says in words what checked it and `checker` is a
    short id of the same ("agreement.S.worked", "admission.calc", "code.form")."""
    return {"passed": bool(passed), "score": score, "bar": bar, "why": why, "keep": keep, "kept_from": kept_from,
            "verifier": verifier, "checker": checker}


def _usable(answer, output):
    """An answer that is there, from a step that ran and whose output has the wanted form."""
    return answer is not None and bool(output.get("ok")) and bool(output.get("form_ok", True))


@register_gate("answered")
def _answered(rung, result, trace, run):
    part, answer = rung["part"], result.get("answer")
    if answer is None:
        return _judged(False, None, 1.0, result.get("why") or f"{part} gave no answer")
    return _judged(True, 1.0, 1.0, f"{part} gave an answer", answer, part, run.verifier_of(part), run.checker_of(part))


@register_gate("form")
def _form(rung, result, trace, run):
    part, answer = rung["part"], result.get("answer")
    if result.get("ok") and result.get("form_ok", answer is not None) and answer is not None:
        return _judged(True, 1.0, 1.0, f"{part} ran and its output has the wanted form", answer, part,
                       "code: the program ran and its value has the wanted form", "code.form")
    return _judged(False, None, 1.0, result.get("why") or f"{part} did not run, or its output has the wrong form")


@register_gate("agree")
def _agree(rung, result, trace, run):
    part, answer, named = rung["part"], result.get("answer"), rung.get("with", "earlier")
    if not _usable(answer, result):
        return _judged(False, None, 1.0, f"{part} gave no usable answer to compare")
    keep_own = rung.get("keep", "self") == "self"
    others = list(trace) if named == "earlier" else [trace.step(name) for name in named]
    for step in others:
        if step is None or not _usable(step.answer, step.output_profile):
            continue
        kept, compared = (answer, step.answer) if keep_own else (step.answer, answer)
        if run.equal(kept, compared):
            maker, checker = (part, step.node) if keep_own else (step.node, part)
            return _judged(True, 1.0, 1.0, f"{part} agrees with {step.node}; the answer of {maker} is kept", kept, maker,
                           f"{checker} (another way), compared by code", "agreement." + checker)
    names = "any earlier part" if named == "earlier" else ", ".join(named)
    return _judged(False, 0.0, 1.0, f"{part} agrees with none of: {names}")


@register_gate("reply_confidence")
def _reply_confidence(rung, result, trace, run):
    part, answer, reply = rung["part"], result.get("answer"), result.get("reply")
    bar = run.ask("ladder.gate.reply_confidence")
    if answer is None:
        return _judged(False, None, bar, f"{part} gave no answer")
    if reply is None:
        return _judged(False, None, bar, f"{part}: the source gave no reply text to read")
    kind = run.kind_of(rung.get("kinds"))
    confidence = run.checker(rung["checker"]).confidence(run.question, reply, kind)
    verifier = f"code: the reply checker {rung['checker']} (kind {kind})"
    if confidence >= bar:
        return _judged(True, confidence, bar, f"reply checker: confidence {confidence:.3f}, at least {bar:g}", answer, part,
                       verifier, "code.reply_checker")
    return _judged(False, confidence, bar, f"reply checker: confidence {confidence:.3f}, under {bar:g}", verifier=verifier,
                   checker="code.reply_checker")


@register_gate("stage")
def _stage(rung, result, trace, run):
    part, answer, kind = rung["part"], result.get("answer"), STAGE_KINDS[rung["stage"]]
    agreeing = None
    if kind.needs_agreement and answer is not None:
        agreeing = next((step for step in trace if run.equal(answer, step.answer)), None)
    passed = bool(kind.accepts(answer is not None, agreeing is not None, result.get("flags") or {}))
    if not passed:
        return _judged(False, None if answer is None else 0.0, 1.0, f"{rung['stage']}({part}) did not give the answer")
    if kind.needs_agreement:
        verifier, checker = f"{agreeing.node} (an earlier part), compared by code", "agreement." + agreeing.node
    elif kind.needs_flag:
        verifier, checker = f"code: the step's evidence {kind.needs_flag}", "code." + kind.needs_flag
    else:
        verifier, checker = run.verifier_of(part), run.checker_of(part)
    return _judged(True, 1.0, 1.0, f"{rung['stage']}({part}) gave the answer", answer, part, verifier, checker)


@register_gate("never")
def _never(rung, result, trace, run):
    return _judged(False, None, None, f"{rung['part']}: kept for a later comparison")


@register_gate("none")
def _none(rung, result, trace, run):
    return _judged(False, None, None, f"{rung['part']}: no gate checks this answer")


def _stops_on_answer(item):
    """True for a rung that stops the ladder whenever its part answers: the gate 'answered', or a stage type that
    asks for nothing more than an answer (take)."""
    if item["gate"] == "answered":
        return True
    if item["gate"] == "stage":
        kind = STAGE_KINDS[item["stage"]]
        return not kind.needs_agreement and not kind.needs_flag
    return False


# ---------------------------------------------------------------------------
# 4. Rules looked up by the name a setting gives
# ---------------------------------------------------------------------------

def _relative_to_other(run):
    tolerance = run.ask("ladder.number_tolerance")

    def same(kept, other):
        return (kept is not None and other is not None and not isinstance(kept, str) and not isinstance(other, str)
                and abs(kept - other) <= tolerance * max(1.0, abs(other)))
    return same


# rule name -> make(run) -> equal(kept, other)
EQUALITY_RULES = {"relative_to_other": _relative_to_other,
                  "answers_equal": lambda run: answers_equal(*run.ask("assembler.number_equality"))}


def _last_answered(answers):
    return next((index for index in reversed(range(len(answers))) if answers[index] is not None), None)


# rule name -> rule(answers of the attempts, in order) -> the position of the attempt whose answer is final, or None
WHEN_NO_GATE = {"last_part": lambda answers: len(answers) - 1 if answers else None, "last_answered": _last_answered,
                "none": lambda answers: None}
# rule name -> form(node): the answer form a part must give
FORM_RULES = {"contract": lambda node: node.ask("output.form"), "any": lambda node: "any"}

ROUTES = {}


def register_route(name):
    """Register `function(block, run) -> (part, evidence)` as a route rule under this name."""
    def register(function):
        ROUTES[name] = function
        return function
    return register


@register_route("kind_table")
def _kind_table(block, run):
    """The kind vote of the named store (the kit's `CheckedStore.kind_vote`), then the part that the kind table
    names for that kind (the kit's `KindTable.choose`; the default part for a kind the table does not hold)."""
    vote = run.vote(block["store"])
    table = KindTable(default_node=block.get("default"))
    table.table = {kind: dict(row) for kind, row in block["table"].items()}
    part = table.choose(vote["kind"])
    return part, {"rule": "kind_table", "store": block["store"], "kind": vote["kind"], "share": vote["share"],
                  "top_similarity": vote["top_similarity"], "votes": vote["votes"],
                  "row": block["table"].get(vote["kind"]), "default_used": vote["kind"] not in block["table"]}


def _proven_tiers(node, source):
    if node.resolver.evidence_dimension("ladder.tiers") is not None:
        return node.ask("ladder.tiers"), "the proven ladder order of the profile"
    return None


def _proven_arrangement(node, source):
    if node.resolver.evidence_dimension("arrangement") is not None:
        stages = node.ask("arrangement")
        if stages:
            return (tiers_from_arrangement(stages, source, node.ask("ladder.tier_of_model")),
                    "the proven arrangement of the profile (the assembler's), converted into tiers")
    return None


def _own_order(node, source):
    return node.ask("ladder.tiers"), "the ladder order of the node's parameters"


# rule name -> the sources of an order, tried in turn; the last one always gives one
ORDER_SOURCES = {"tiers_else_arrangement": (_proven_tiers, _proven_arrangement, _own_order),
                 "tiers": (_proven_tiers, _own_order), "arrangement": (_proven_arrangement, _own_order)}


def order_of(node, source):
    """The order of this run and where it came from: (order, how)."""
    for find in ORDER_SOURCES[node.ask("ladder.order_from")]:
        found = find(node, source)
        if found is not None:
            return found
    raise LadderRefused("no source of an order gave one")


# ---------------------------------------------------------------------------
# 5. Orders: conversion from an arrangement, and the check before a run
# ---------------------------------------------------------------------------

def tier_of_part(part, source, tier_of_model):
    """The tier of a part by the model it calls."""
    model = source.parts[part].model
    return tier_of_model["exact" if model is None else model]


def tiers_from_arrangement(stages, source, tier_of_model):
    """An arrangement of the kit's assembler ([[part, stage type], ...], first parts included) as a ladder order:
    each stage becomes a rung with the gate "stage", and stages next to each other in the same tier share a tier."""
    blocks = []
    for part, kind in stages:
        tier_id = tier_of_part(part, source, tier_of_model)
        item = {"part": part, "gate": "stage", "stage": kind}
        if blocks and blocks[-1]["tier"] == tier_id:
            blocks[-1]["parts"].append(item)
        else:
            blocks.append({"tier": tier_id, "parts": [item]})
    return blocks


def rungs_of(order):
    """The rungs of an order in the order they run (a route adds its part only when it runs)."""
    return [item for block in order if "route" not in block for item in block["parts"]]


def model_tiers(tier_of_model):
    return {tier_id for key, tier_id in tier_of_model.items() if key != "exact"}


def check_order(order, source, exact_parts, mode, tier_of_model):
    """Check an order before a run and apply the invariant. Returns (order to run, events, refusal).

    Configuration errors raise LadderRefused: an unknown part, gate, stage type or route, a tier whose label does
    not match what its parts spend, a route that is not the last tier, a reference exact part that is not an exact
    part of the source. An order that does not start with the reference exact parts (each with a gate that stops on
    an answer) is repaired ("exact_first": they are put first, and taken out of later tiers), refused ("refuse":
    the refusal is returned, nothing runs) or run as given ("record_only"); every such step is an event.
    """
    spends_model = model_tiers(tier_of_model)
    for position, block in enumerate(order):
        if "route" in block:
            if block["route"] not in ROUTES:
                raise LadderRefused(f"no route rule named {block['route']!r}; registered: {sorted(ROUTES)}")
            if position != len(order) - 1:
                raise LadderRefused("a route must be the last tier of an order")
            continue
        for item in block["parts"]:
            part = item["part"]
            if part not in source.parts:
                raise LadderRefused(f"no part {part!r} in the source; it has {sorted(source.parts)}")
            if item["gate"] not in GATES:
                raise LadderRefused(f"no gate named {item['gate']!r}; registered: {sorted(GATES)}")
            if item["gate"] == "stage" and item.get("stage") not in STAGE_KINDS:
                raise LadderRefused(f"no stage type {item.get('stage')!r}")
            calls_model = source.parts[part].model is not None
            if calls_model != (block["tier"] in spends_model):
                raise LadderRefused(f"tier {block['tier']} holds the part {part!r}, which "
                                    f"{'calls a model' if calls_model else 'calls no model'}")
    for part in exact_parts:
        if part not in source.parts or source.parts[part].model is not None:
            raise LadderRefused(f"the reference exact part {part!r} is not a part of the source that calls no model")
    head = rungs_of(order)[:len(exact_parts)]
    if [item["part"] for item in head] == list(exact_parts) and all(_stops_on_answer(item) for item in head):
        return order, [], None
    what = (f"the order does not start with the reference exact parts {list(exact_parts)}, each with a gate that "
            f"stops on an answer")
    if mode == "record_only":
        return order, [{"rule": "ladder.invariant", "taken": "record_only",
                        "what": what + "; it runs as given and the invariant is checked on the side"}], None
    if mode == "refuse":
        return None, [], {"code": "exact_parts_not_first", "what_happened": what + ": the order is refused",
                          "next_action": "put the reference exact parts first, each with the gate 'answered'"}
    rest = []
    for block in order:
        if "route" in block:
            rest.append(block)
            continue
        kept = [item for item in block["parts"] if item["part"] not in exact_parts]
        if kept:
            rest.append(dict(block, parts=kept))
    repaired = [tier(tier_of_model["exact"], *[rung(part, "answered") for part in exact_parts])] + rest
    return repaired, [{"rule": "ladder.invariant", "taken": "exact_first", "what": what + "; they were put first",
                       "order_given": order}], None


# ---------------------------------------------------------------------------
# 6. One run
# ---------------------------------------------------------------------------

_CHECKERS = {}      # reply checkers by path: a cache of files that are only read


def _digest(value):
    """sha256 of the value as sorted JSON (not Fabric's canonical form)."""
    return "sha256:" + hashlib.sha256(json.dumps(plain(value), sort_keys=True, default=str).encode("utf-8")).hexdigest()


class _Run:
    """What the gates and routes of one run read: the node (for settings), the Task, the source, the stores."""

    def __init__(self, node, task, profile, source, store):
        self.node, self.task, self.profile, self.source, self.store = node, task, profile, source, store
        self.question = task_text_of(task)
        self.equal = EQUALITY_RULES[node.ask("ladder.equality")](self)
        self._votes = {}

    def ask(self, name):
        return self.node.ask(name)

    def is_exact(self, part):
        return self.source.parts[part].model is None

    def verifier_of(self, part):
        """What checks an answer that a part gave in the wanted form."""
        if self.is_exact(part):
            return f"admission of the exact part {part} (checked on held-out Tasks before use)"
        return "code: the output has the wanted form"

    def checker_of(self, part):
        """The short id of what `verifier_of` names."""
        return "admission." + part if self.is_exact(part) else "code.form"

    def stored(self, name):
        exemplars = getattr(self.store, "exemplars", None) or {}
        if name not in exemplars:
            raise LadderRefused(f"no store named {name!r} was given to the run (give it in ProvenStore.exemplars)")
        return exemplars[name]

    def vote(self, name):
        """The kind vote of a named store for this Task: with the Task's vector when it has one and the measure
        allows it, else with the built-in text similarity. Made once per run and store."""
        if name not in self._votes:
            stored = self.stored(name)
            vector = (self.task.get("vector") if isinstance(self.task, dict)
                      and self.ask("retrieval.measure") in ("auto", "vector") else None)
            how = {"vector": vector} if vector is not None else {"text": self.question}
            self._votes[name] = stored.kind_vote(k=self.ask("retrieval.neighbours"), exclude=[task_id_of(self.task)], **how)
        return self._votes[name]

    def kind_of(self, name):
        return None if name is None else self.vote(name)["kind"]

    def checker(self, path):
        full = path if os.path.isabs(path) else os.path.join(HERE, path)
        if full not in _CHECKERS:
            _CHECKERS[full] = ReplyChecker.load(full)
        return _CHECKERS[full]

    def session(self, form, seed):
        return self.source.session(self.task, form=form, seed=seed, profile=self.profile, checks=self.ask("output.checks"))


def _attempt(number, tier_id, item, step, judged, run):
    """The record of one answer attempt, before its states are written."""
    part, output = item["part"], step.output_profile
    raw = step.answer if step.answer is not None else output.get("raw_answer")
    present = raw is not None and bool(output.get("present", True)) and bool(output.get("ok")) and bool(output.get("form_ok"))
    return {"number": number, "role": "answer", "tier": tier_id, "part": part, "model": run.source.parts[part].model,
            "gate": {key: value for key, value in item.items() if key != "part"}, "gate_passed": bool(judged.get("passed")),
            "score": judged.get("score"), "bar": judged.get("bar"), "verifier": judged.get("verifier"),
            "checker": judged.get("checker"), "answer": step.answer, "raw_answer": None if step.answer is not None else raw,
            "digest": _digest(raw) if present else None, "artifact": present,
            "checks_ok": all((output.get("checks") or {}).values()), "cost": dict(step.cost),
            "why": judged.get("why") or step.reason, "states": [], "state": None}


def _route_attempt(number, info):
    chain = advance([], "attempted", maker="route", tier=info["tier"])
    advance(chain, "artifact_valid", digest=_digest(info["chosen"]))
    return {"number": number, "role": "route", "tier": info["tier"], "part": None, "model": None,
            "gate": {"route": info["evidence"]["rule"]}, "gate_passed": False, "score": None, "bar": None, "verifier": None,
            "checker": None, "answer": None, "chosen": info["chosen"], "reused": info["reused"], "evidence": info["evidence"],
            "digest": chain[-1]["digest"], "artifact": True, "checks_ok": True, "cost": add_costs([]),
            "why": f"the route names the part {info['chosen']}" + (", which already ran" if info["reused"] else ""),
            "states": chain, "state": chain[-1]["state"]}


def _write_states(attempt, final, accepted):
    """The run's states of one answer attempt: attempted, then as far as its evidence goes."""
    chain = advance([], "attempted", maker=attempt["part"], tier=attempt["tier"])
    if attempt["artifact"]:
        advance(chain, "artifact_valid", digest=attempt["digest"])
        if attempt["checks_ok"] and attempt["score"] is not None:
            advance(chain, "score_valid", score=attempt["score"])
            if (final and accepted and attempt["bar"] is not None and attempt["score"] >= attempt["bar"]
                    and attempt["verifier"] not in (None, attempt["part"])):
                advance(chain, "accepted", score=attempt["score"], bar=attempt["bar"], verifier=attempt["verifier"],
                        maker=attempt["part"])
    attempt["states"], attempt["state"] = chain, chain[-1]["state"]


def _shadow(run, part, form, seed):
    """A reference exact part run on the side: free, not paid as model time, not used for the answer."""
    result = run.session(form, seed)(part)
    return {"role": "shadow", "part": part, "answer": result.get("answer"), "answered": result.get("answer") is not None,
            "cost": dict(result.get("cost") or add_costs([]))}


def _exact_answers_before_model(attempts):
    """Every attempt of a part that calls no model which gave an answer and was followed by a model attempt, whatever
    the part's gate and whether or not the part is a reference exact part (added after the independent check of J2,
    notes/coordination-2026-11-12/check-j2.md, its case (b); with `ladder.exact_parts = []` it is the only rule)."""
    answers = [a for a in attempts if a["role"] == "answer"]
    out = []
    for attempt in answers:
        if attempt["model"] is None and attempt["answer"] is not None:
            later = [a["number"] for a in answers if a["model"] is not None and a["number"] > attempt["number"]]
            if later:
                out.append({"number": attempt["number"], "part": attempt["part"], "gate": attempt["gate"].get("gate"),
                            "model_attempts_after": later})
    return out


def _invariant(attempts, run, exact_parts, mode, form, seed, total):
    """Did an exact answer that passed its gate come before model spend? The reference exact parts are judged by
    the gate 'answered' (an answer of the wanted form): from the attempt when the order ran the part, else in a
    shadow session, in order, until one answers. Also flagged: a model attempt after an answer of any other part
    that calls no model (`exact_answers_before_model`). The invariant holds when neither happened."""
    passed_by, shadows = None, []
    for part in exact_parts:
        attempt = next((a for a in attempts if a["role"] == "answer" and a["part"] == part), None)
        if attempt is not None:
            answered = attempt["answer"] is not None
        else:
            shadows.append(_shadow(run, part, form, seed))
            answered = shadows[-1]["answered"]
        if answered:
            passed_by = part
            break
    model_attempts = [a["number"] for a in attempts if a["role"] == "answer" and a["model"] is not None]
    spent = bool(model_attempts) or total["calls"] > 0 or total["model_s"] > 0 or total["tok_in"] + total["tok_out"] > 0
    before_model = _exact_answers_before_model(attempts)
    return {"mode": mode, "exact_parts": list(exact_parts), "exact_passed_by": passed_by, "model_spent": spent,
            "model_attempts": model_attempts, "exact_answers_before_model": before_model,
            "held": not (passed_by is not None and spent) and not before_model, "shadow": shadows}


def price(cost, money_per_second, money_per_token):
    """US dollars of one cost: model seconds and tokens at the two prices of the settings."""
    return cost["model_s"] * money_per_second + (cost["tok_in"] + cost["tok_out"]) * money_per_token


def telemetry_of(attempts):
    """What each tier spent in one run: attempts, gate passes, calls, tokens, model seconds, tool time, money."""
    by_tier, total = {}, dict(add_costs([]), attempts=0, gate_passed=0, money_usd=0.0)
    for attempt in attempts:
        row = by_tier.setdefault(attempt["tier"], dict(add_costs([]), attempts=0, gate_passed=0, money_usd=0.0))
        for into in (row, total):
            into["attempts"] += 1
            into["gate_passed"] += int(bool(attempt["gate_passed"]))
            into["money_usd"] += attempt["money_usd"]
            for key, value in attempt["cost"].items():
                into[key] += value
    return {"by_tier": by_tier, "total": total}


def _refused_record(task, how, given, events, refusal, mode, exact_parts, shadows):
    return {"format": RECORD_FORMAT, "task_id": task_id_of(task), "order_from": how, "order_given": given,
            "order_run": None, "events": events, "mode": mode, "refusal": refusal, "attempts": [], "answer": None,
            "answer_from": None, "stopped_at": None, "accepted": False, "reason": "refused: " + refusal["what_happened"],
            "final_tier": None, "final_state": None,
            "invariant": {"mode": mode, "exact_parts": list(exact_parts), "exact_passed_by": next(
                (s["part"] for s in shadows if s["answered"]), None), "model_spent": False, "model_attempts": [],
                "exact_answers_before_model": [], "held": True, "shadow": list(shadows)},
            "telemetry": telemetry_of([])}


def _run_ladder(node, task, source, store, seed):
    """The child rule "ladder" of an OmniNode: one Task climbs the order of its profile. Returns the NodeRecord;
    the ladder's own record is its evidence["ladder"]."""
    profile = node.profile
    source = O.source_for(source, profile)
    run = _Run(node, task, profile, source, store)
    mode, exact = node.ask("ladder.invariant"), list(node.ask("ladder.exact_parts"))
    tier_of_model = node.ask("ladder.tier_of_model")
    form = FORM_RULES[node.ask("ladder.form_rule")](node)
    given, how = order_of(node, source)
    order, events, refusal = check_order(given, source, exact, mode, tier_of_model)
    if refusal is not None:
        node.spent = add_costs([])
        return node.record(task, [], None, False, "refused: " + refusal["what_happened"],
                           {"ladder": _refused_record(task, how, given, events, refusal, mode, exact, [])})
    force = node.ask("ladder.force_tier")
    if force is not None:
        if force not in TIERS:
            raise LadderRefused(f"no tier {force!r}; the tiers are {sorted(TIERS)}")
        shadows = []
        if force in model_tiers(tier_of_model):
            for part in exact:
                shadows.append(_shadow(run, part, form, seed))
                if shadows[-1]["answered"]:
                    refusal = {"code": "refuse_unnecessary_frontier_spend_when_tier0_solves",
                               "what_happened": f"a forced tier {force} was refused: the exact part {part} answers",
                               "next_action": "let the ladder start with its exact parts instead of forcing a tier"}
                    node.spent = add_costs([])
                    return node.record(task, [], None, False, "refused: " + refusal["what_happened"],
                                       {"ladder": _refused_record(task, how, given, events, refusal, mode, exact, shadows)})
        order = [block for block in order if block.get("tier") == force]
        if not order:
            raise LadderRefused(f"the order has no tier {force!r} to go to")
        events.append({"rule": "ladder.force_tier", "taken": force, "what": f"only the tiers {force} run"})

    rungs, route_info = [], None
    for block in order:
        if "route" not in block:
            rungs += [(block["tier"], dict(item)) for item in block["parts"]]
            continue
        chosen, evidence = ROUTES[block["route"]](block, run)
        if chosen not in source.parts:
            raise LadderRefused(f"the route named the part {chosen!r}, which is not in the source")
        reused = chosen in [item["part"] for _, item in rungs]
        route_info = {"after": len(rungs), "tier": block["tier"], "chosen": chosen, "evidence": evidence, "reused": reused}
        if not reused:
            rungs.append((tier_of_part(chosen, source, tier_of_model), {"part": chosen, "gate": block.get("gate", "none")}))
    node.check_resources([(item["part"], "take") for _, item in rungs], source)

    judgements, rule = {}, node.ask("ladder.when_no_gate_passes")

    def accept_of(position, item):
        last = position == len(rungs) - 1

        def accept(result, trace):
            judged = GATES[item["gate"]](item, result, trace, run)
            judgements[position] = judged
            if judged["passed"]:
                return Decision(True, judged["keep"], judged["why"])
            if last:
                answers = [step.answer for step in trace] + [result.get("answer")]
                index = WHEN_NO_GATE[rule](answers)
                judged["fallback"] = {"rule": rule, "answer_from": index}
                return Decision(True, None if index is None else answers[index],
                                f"no gate passed ({judged['why']}): the rule {rule!r} gives the answer")
            return Decision(False, None, judged["why"])
        return accept

    steps = [Step(item["part"], accept_of(position, item)) for position, (_, item) in enumerate(rungs)]
    session = run.session(form, seed)
    trace = first_accepted(task, steps, session, input_profile=profile, seed=seed) if steps else Trace(task_id_of(task))

    by_position = [_attempt(position, rungs[position][0], rungs[position][1], step, judgements.get(position, {}), run)
                   for position, step in enumerate(trace)]
    stop = len(by_position) - 1
    judged = judgements.get(stop, {}) if by_position else {}
    accepted = bool(judged.get("passed"))
    if accepted:
        final = max(p for p in range(stop + 1) if rungs[p][1]["part"] == judged["kept_from"])
        if final != stop:      # an agreement kept an earlier answer: that attempt carries the score and its checker
            by_position[final].update(score=judged["score"], bar=judged["bar"], verifier=judged["verifier"],
                                      checker=judged["checker"], confirmed_by=stop)
    else:
        final = (judged.get("fallback") or {}).get("answer_from")
    for position, attempt in enumerate(by_position):
        _write_states(attempt, position == final, accepted)

    attempts, reached_route = [], False
    if route_info is not None:
        before = route_info["after"]
        reached_route = len(by_position) > before or (
            route_info["reused"] and len(by_position) == before and not judgements.get(before - 1, {}).get("passed"))
    for position, attempt in enumerate(by_position):
        if reached_route and position == route_info["after"]:
            attempts.append(_route_attempt(len(attempts) + 1, route_info))
        attempt["number"] = len(attempts) + 1
        attempts.append(attempt)
    if reached_route and route_info["after"] >= len(by_position):
        attempts.append(_route_attempt(len(attempts) + 1, route_info))
    per_second, per_token = node.ask("ladder.money_per_model_second"), node.ask("ladder.money_per_token")
    for attempt in attempts:
        attempt["money_usd"] = price(attempt["cost"], per_second, per_token)
        if "confirmed_by" in attempt:
            attempt["confirmed_by"] = by_position[attempt["confirmed_by"]]["number"]

    total = trace.total_cost()
    final_attempt = by_position[final] if final is not None else None
    record = {"format": RECORD_FORMAT, "task_id": task_id_of(task), "profile_key": (node.configured or {}).get("key"),
              "order_from": how, "order_given": given if events else None, "order_run": order, "events": events,
              "mode": mode, "form": form, "refusal": None, "attempts": attempts, "answer": trace.answer,
              "answer_from": final_attempt["number"] if final_attempt is not None else None,
              "stopped_at": by_position[stop]["number"] if by_position else None, "accepted": accepted,
              "reason": trace.reason, "final_tier": final_attempt["tier"] if final_attempt is not None else None,
              "final_state": final_attempt["state"] if final_attempt is not None else None,
              "invariant": _invariant(attempts, run, exact, mode, form, seed, total),
              "telemetry": telemetry_of(attempts)}
    node.spent = total
    done = [O.NodeStep(**asdict(step), stage=f"{tier_id} {item['gate']}({item['part']})",
                       settings=node.part_settings(item["part"], source)) for step, (tier_id, item) in zip(trace, rungs)]
    return node.record(task, done, trace.answer, accepted, trace.reason, {"ladder": record})


O.CHILD_RULES["ladder"] = _run_ladder


# ---------------------------------------------------------------------------
# 7. Nodes, runs, stores, and the states of an order
# ---------------------------------------------------------------------------

def parameters(values=None, by=CALLER) -> O.Parameters:
    """The node's parameters with the ladder's settings and the child rule "ladder"; `values` sets some of them."""
    out = O.PARAMETERS.merged(O.Parameters(list(SETTINGS), "ladder")).with_({"children.rule": "ladder"}, by="stepkit.tier_ladder")
    return out.with_(values or {}, by=by)


def node(profile, values=None, contract_values=None, by=CALLER) -> O.OmniNode:
    """An OmniNode that runs the ladder for a Task of this profile."""
    return O.OmniNode(O.contract_for(profile, contract_values), parameters(values, by))


def run(task, source, store=None, values=None, contract_values=None, profile=None, by=CALLER) -> O.NodeRecord:
    """One Task through the ladder: a node for its profile, configured from the store when one is given."""
    return replay([task], source, store, values, contract_values, by, [profile] if profile is not None else None)[0]


def replay(tasks, source, store=None, values=None, contract_values=None, by=CALLER, profiles=None) -> list:
    """Every Task through the ladder, one node for each Task (the parameters are made once). Returns NodeRecords."""
    params, out = parameters(values, by), []
    for position, task in enumerate(tasks):
        profile = profiles[position] if profiles is not None else O.profile_of(task)
        ladder = O.OmniNode(O.contract_for(profile, contract_values), params)
        if store is not None:
            ladder.configure(task, store, profile)
        out.append(ladder.run(task, source, store, profile=profile))
    return out


def proven(order, by) -> O.Parameters:
    """A ladder order as a proven parameter set (a Task Object) that a ProvenStore keeps for a profile."""
    return O.Parameters([SETTINGS["ladder.tiers"].narrowed(order, by)], "ladder order")


def store_of(orders, by, exemplars=None) -> O.ProvenStore:
    """A ProvenStore with one proven order per profile key ("form: number", "work: text", ...)."""
    store = O.ProvenStore(exemplars)
    for key, order in orders.items():
        store.put(key, proven(order, by))
    return store


def ladder_of(record) -> dict:
    """The ladder's record of a NodeRecord (or the ladder record itself)."""
    return record.evidence["ladder"] if hasattr(record, "evidence") else record


def mark(records, state, **evidence) -> int:
    """Write a state of the order (paired, selected, promoted or invalidated) onto the records it made: onto the
    accepted attempt of each record, and for "invalidated" onto every answer attempt. Returns how many got it."""
    if state not in STATES[STATES.index("paired"):]:
        raise StateError(f"{state!r} is not a state of an order; those are {STATES[STATES.index('paired'):]}")
    count = 0
    for record in records:
        ladder = ladder_of(record)
        targets = [a for a in ladder["attempts"] if a["role"] == "answer" and (
            state == TERMINAL or (ladder["accepted"] and a["number"] == ladder["answer_from"]))]
        for attempt in targets:
            advance(attempt["states"], state, **evidence)
            attempt["state"] = state
            count += 1
        if ladder["answer_from"] is not None:
            final = next(a for a in ladder["attempts"] if a["number"] == ladder["answer_from"])
            ladder["final_state"] = final["state"]
    return count


def telemetry(records) -> dict:
    """Over many records: per tier the attempts, gate passes, calls, tokens, model seconds, tool time and money;
    the tier and the state of the final answers; the invariant; refusals. Reads no answer key."""
    by_tier, final_tier, final_state, held, broken, refused, accepted = {}, {}, {}, 0, [], 0, 0
    for record in records:
        ladder = ladder_of(record)
        for tier_id, row in ladder["telemetry"]["by_tier"].items():
            into = by_tier.setdefault(tier_id, {})
            for key, value in row.items():
                into[key] = into.get(key, 0) + value
        final_tier[str(ladder["final_tier"])] = final_tier.get(str(ladder["final_tier"]), 0) + 1
        final_state[str(ladder["final_state"])] = final_state.get(str(ladder["final_state"]), 0) + 1
        held += int(ladder["invariant"]["held"])
        if not ladder["invariant"]["held"]:
            broken.append(ladder["task_id"])
        refused += int(ladder["refusal"] is not None)
        accepted += int(ladder["accepted"])
    return {"tasks": len(records), "by_tier": by_tier, "final_tier": final_tier, "final_state": final_state,
            "accepted": accepted, "invariant_held": held, "invariant_broken": broken, "refused": refused}


# ---------------------------------------------------------------------------
# 8. Test 7's arms as ladder orders, over the kit's word parts (`omninode.word_parts`)
# ---------------------------------------------------------------------------

WORD_CHECKER = os.path.join("data", "reply_checker_small_model.json")
# the settings under which test 7's arms replay: no form check beyond the recorded one, its equality, its last resort
TEST7_VALUES = {"ladder.form_rule": "any", "ladder.equality": "relative_to_other", "ladder.when_no_gate_passes": "last_part"}
E3B_NUMBER = [tier("L4", rung("S.reuse", "never"), agree("S.worked", ["S.reuse"], "other")),
              tier("L5", agree("B.reuse", ["S.reuse", "S.worked"], "self"), agree("B.worked", ["B.reuse"], "other"))]
E3B_CHOICE = [tier("L4", rung("S.reuse", "form")), tier("L5", rung("B.reuse", "form"), rung("B.worked", "none"))]


def test7_orders():
    """Test 7's arms as orders by profile key. E3b and E6 differ by the answer form (two ways must agree on a
    number; a program must name one option). E1 and E2 need a fitted kind table: see `kind_table_order`."""
    return {"E0": {"work: text": [tier("L5", rung("B.worked", "none"))]},
            "CL": {"work: text": list(CL_ORDER)},
            "E3": {"work: text": list(E3_ORDER)},
            "E3b": {"form: number": [L0_CALC] + E3B_NUMBER, "form: choice": [L0_CALC] + E3B_CHOICE},
            "E6": {"form: number": [L0_TOOLS_CALC] + E3B_NUMBER, "form: choice": [L0_TOOLS_CALC] + E3B_CHOICE}}


# the reference exact parts of each arm: its own exact tier (E0, E1 and E2 have none of their own: the calculator)
TEST7_EXACT = {"E6": ["tools", "calc"]}


def kind_table_order(rows, store, default, rename=None):
    """A route by kind as an order: the kind vote of the named store, then the part that a fitted
    `KindTable.table` ({kind: {"node", ...}}) names. `rename` maps recorded node names to part names
    (the recorded calculator "T.calc" is the part "calc")."""
    rename = rename or {}
    table = {kind: dict(row, node=rename.get(row["node"], row["node"])) for kind, row in rows.items()}
    return [route("kind_table", store, table, rename.get(default, default))]


def reply_cascade_order(checker=WORD_CHECKER, kinds="library"):
    """The kit's cascade with the reply checker as an order: the calculator; the small model's worked answer, kept
    when the checker's confidence is at least the gate's bar (kind from the named store); else the larger model's."""
    return [L0_CALC, tier("L4", rung("S.worked", "reply_confidence", checker=checker, kinds=kinds)),
            tier("L5", rung("B.worked", "none"))]


# external provider's "unverified cheap only" baseline over the word parts: the calculator, then the small model's worked
# answer with no gate and no escalation
UNVERIFIED_CHEAP_ORDER = [L0_CALC, tier("L4", rung("S.worked", "none"))]
