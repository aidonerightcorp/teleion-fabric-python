# Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md
"""The assembler: a search that writes the arrangement of parts for a group of Tasks from recorded outcomes.

Generalized from the search of test 10 (work-2026-11-12-next-tests/t10-self-assembly/assemble.py, main),
with the same decisions and figures on its 960 Tasks when every dimension is at its first suggested value:

  parts          one connector: an answer or none, right or wrong, and the recorded calls on the part's path
  stages         `take(P)`: run P; if it answers, that is the answer. `agree(P)`: run P; if its answer equals
                 the answer of a part run before it in this arrangement, that is the answer; if not, go on.
                 A stage type is data (`StageKind`), registered by name, so a new type needs no change here.
  an arrangement the first parts (exact, free: the calculator), then up to `max_stages` stages, no part twice.
                 If no stage gives the answer, a named fallback rule decides (`assembler.fallback`, the same
                 names as the node's `fallback`): "last_answered" (test 10's rule) or "none".
  cost           the recorded model seconds of every call that ran. A call is paid once for a Task, also
                 when two parts of one arrangement use it (in test 10 every part is one call of its own).
  chooser        among the arrangements within `within_points` of the best accuracy on the fit Tasks and
                 inside the cap on mean model seconds: the lowest mean cost, then fewer stages, then the
                 order of enumeration.
  one price      each group takes the arrangement with the best "accuracy minus price times seconds"; the
                 price is the lowest one that keeps the mean over all fit Tasks inside one budget.
  named rules    what happens when nothing fits inside a cap (`assembler.when_nothing_fits`), when no price
                 keeps the budget (`assembler.when_over_budget`) and when a Task's group has no arrangement
                 (`assembler.when_no_group`) is data, and every time such a rule fires it is written to `events`.
  exact first    `compose`: exact parts first, then the arrangement that was assembled without them.
  admission      `admission`: new parameters replace stored ones only when they are at least as right,
                 within a stated margin, on Tasks they were not assembled on.

Every number of the search is a `Dimension` in `SETTINGS` and is read through a `Resolver`, which writes
the value down as a choice (see stepkit/dimension.py). Needs numpy.
"""
import itertools
import re
from dataclasses import dataclass

import numpy as np

from .dimension import CHOICES, JOINT, NUMBERS, Dimension, Resolver, Settings

PERCENT = 100.0     # a unit, not a setting: accuracy is written in points out of 100

SETTINGS = Settings(name="assembler", dimensions=[
    Dimension("assembler.max_stages", [4], [1, 2, 3, 4, 5], NUMBERS, {"min": 1, "max": 6},
              about="the largest number of stages of an arrangement, after its first parts"),
    Dimension("assembler.within_points", [1.0], [0.0, 0.5, 1.0, 2.0, 3.0], NUMBERS, {"min": 0.0, "max": 10.0},
              about="the chooser takes the cheapest arrangement within this many points of the best accuracy"),
    Dimension("assembler.cap_model_seconds", [10.0, None, 5.0], [None, 2.0, 3.0, 5.0, 10.0, 20.0], NUMBERS, {"min": 0.0},
              about="cap on the mean model seconds per Task of a group; None is no cap"),
    Dimension("assembler.budget_model_seconds", [10.0, 5.0, 3.0, 2.0], [1.0, 2.0, 3.0, 5.0, 10.0, 20.0], NUMBERS,
              {"min": 0.0}, about="one budget of mean model seconds per Task for all groups, kept by one price"),
    Dimension("assembler.price_search", [[0.0, 500.0, 50]], [[0.0, 100.0, 40], [0.0, 500.0, 50], [0.0, 1000.0, 60]], JOINT,
              {"lowest_price": {"min": 0.0}, "highest_price": {"min": 0.0, "max": 10000.0}, "halvings": {"min": 1, "max": 200}},
              ["lowest_price", "highest_price", "halvings"],
              about="the search for the one price: the range of prices (points per model second) and how often it is halved"),
    Dimension("assembler.tie_window", [1e-9], [0.0, 1e-12, 1e-9, 1e-6], NUMBERS, {"min": 0.0, "max": 1e-3},
              about="two scores or costs nearer than this count as equal"),
    Dimension("assembler.cost_decimals", [6], [3, 6, 9], NUMBERS, {"min": 0, "max": 12},
              about="decimals of the mean cost when the chooser orders arrangements by cost"),
    Dimension("assembler.min_group_tasks", [30], [10, 20, 30, 50, 100], NUMBERS, {"min": 1},
              about="a kind with fewer fit Tasks than this gets no arrangement of its own"),
    Dimension("assembler.number_equality", [[0.001, 0.001]], [[0.0, 0.0], [0.0001, 0.0001], [0.001, 0.001], [0.01, 0.01]],
              JOINT, {"relative": {"min": 0.0, "max": 0.1}, "absolute": {"min": 0.0, "max": 1.0}}, ["relative", "absolute"],
              about="two numbers are equal within this relative tolerance, and at least this absolute one"),
    Dimension("assembler.folds", [5], [2, 3, 5, 10], NUMBERS, {"min": 2, "max": 20},
              about="folds of the out-of-fold protocol"),
    Dimension("assembler.seed", [20261112], [20261112, 20261113, 20261114], CHOICES,
              about="the seed of the folds and of the resamples"),
    Dimension("assembler.resamples", [10000], [1000, 2000, 10000, 20000], NUMBERS, {"min": 100},
              about="resamples of the paired bootstrap over Tasks"),
    Dimension("assembler.interval_percentiles", [[2.5, 97.5]], [[5.0, 95.0], [2.5, 97.5], [0.5, 99.5]], JOINT,
              {"low": {"min": 0.0, "max": 50.0}, "high": {"min": 50.0, "max": 100.0}}, ["low", "high"],
              about="the two ends of the interval (2.5 and 97.5 give the 95% interval)"),
    Dimension("assembler.report_decimals", [3], [1, 2, 3, 4], NUMBERS, {"min": 0, "max": 6},
              about="decimals of a reported mean and of its interval"),
    Dimension("assembler.rows_per_block", [65536], [8192, 65536, 262144], NUMBERS, {"min": 1},
              about="arrangements read at a time when fit means are made (speed and memory only, no effect on a figure)"),
    Dimension("assembler.admission_margin_points", [1.0], [0.0, 0.5, 1.0, 2.0], NUMBERS, {"min": 0.0, "max": 10.0},
              about="admission gate: new parameters may be at most this many points under the stored ones"),
    Dimension("assembler.admission_min_tasks", [30], [10, 30, 50, 100], NUMBERS, {"min": 1},
              about="admission gate: fewer held-back Tasks than this cannot admit anything"),
    Dimension("assembler.fallback", ["last_answered", "none"], kind=CHOICES,
              about="the answer of a replayed arrangement when no stage gives one: the last part that answered "
                    "(test 10's rule), or none; the same names as the node's fallback"),
    Dimension("assembler.when_nothing_fits", ["cheapest", "refuse"], kind=CHOICES,
              about="when no arrangement is inside the cap: take the cheapest (test 10's rule), or refuse; "
                    "either way it is written to the events"),
    Dimension("assembler.when_over_budget", ["highest_price", "refuse"], kind=CHOICES,
              about="when no price keeps the budget: take the choice at the highest price (test 10's rule), or "
                    "refuse; either way it is written to the events with how far over the budget it is"),
    Dimension("assembler.when_no_group", ["first_group", "refuse"], kind=CHOICES,
              about="a Task whose group got no arrangement: take the first group's arrangement (test 10's rule), "
                    "or refuse; either way it is written to the events"),
])


class Refused(LookupError):
    """A named rule of the search refused to give a choice that would break a cap, a budget or a group."""


def _refuse(what):
    def refuse(*_args):
        raise Refused(what)
    return refuse


# rule name -> rule(done, right, last_has, last_right) -> right or wrong of every Task when no stage gave the answer
REPLAY_FALLBACKS = {"last_answered": lambda done, right, last_has, last_right: np.where(~done & last_has, last_right, right),
                    "none": lambda done, right, last_has, last_right: right}
# rule name -> rule(cost, tie) -> the arrangements that may be taken when none is inside the cap
NOTHING_FITS = {"cheapest": lambda cost, tie: cost <= cost.min() + tie,
                "refuse": _refuse("no arrangement is inside the cap")}
# rule name -> rule(chosen, price) -> (chosen, price) when not even the highest price keeps the budget
OVER_BUDGET = {"highest_price": lambda chosen, price: (chosen, price),
               "refuse": _refuse("no price keeps the mean cost inside the budget")}
# rule name -> rule(chosen by group key, first key) -> the arrangement for a Task whose group got none
NO_GROUP = {"first_group": lambda chosen, first_key: chosen[first_key],
            "refuse": _refuse("the Task's group got no arrangement")}


def pick_group(chosen, key, first_key, rule, events=None, task=None):
    """The arrangement for a Task whose group key is `key`, from {group key: arrangement}. When that group
    got none, the named rule `rule` decides (NO_GROUP) and the event is written to `events`."""
    if key in chosen:
        return chosen[key]
    if events is not None:
        events.append({"rule": "assembler.when_no_group", "taken": rule, "group": key, "first_group": first_key, "task": task})
    return NO_GROUP[rule](chosen, first_key)


# ---------------------------------------------------------------------------
# 1. Answers, stage types, outcomes
# ---------------------------------------------------------------------------

def answers_equal(relative, absolute):
    """The equality of two answers of test 10: numbers within the tolerance (relative, at least the
    absolute one), options equal as text. A missing answer is equal to nothing."""
    def same(x, y):
        if x is None or y is None:
            return False
        if isinstance(x, str) or isinstance(y, str):
            return isinstance(x, str) and isinstance(y, str) and x == y
        return abs(x - y) <= max(absolute, relative * max(abs(x), abs(y)))
    return same


@dataclass(frozen=True)
class StageKind:
    """A stage type, as data. A stage accepts its part's answer when the part answered, and, when the
    type says so, the answer equals an earlier answer and a named piece of the step's evidence is true."""
    name: str
    needs_agreement: bool = False
    needs_flag: str = ""

    def accepts(self, answered, agrees, flags):
        """True where the stage stops with its part's answer. Works on one Task and on arrays of Tasks."""
        ok = answered
        if self.needs_agreement:
            ok = ok & agrees
        if self.needs_flag:
            ok = ok & flags.get(self.needs_flag, False)
        return ok


STAGE_KINDS = {}


def register_stage_kind(kind):
    """Add a stage type under its name. A name cannot be given a second meaning."""
    if STAGE_KINDS.get(kind.name, kind) != kind:
        raise ValueError(f"stage type {kind.name!r} is already registered with another meaning")
    STAGE_KINDS[kind.name] = kind
    return kind


register_stage_kind(StageKind("take"))
register_stage_kind(StageKind("agree", needs_agreement=True))


def show(stages, bare=()):
    """An arrangement as one line, as test 10 writes it: "calc > take(B.reuse) > agree(S.direct)"."""
    return " > ".join(part if part in bare else f"{kind}({part})" for part, kind in stages)


_STAGE = re.compile(r"(?P<kind>\w+)\((?P<part>.+)\)")


def parse(line):
    """Read a line written by `show` back into stages: [(part, stage type)]. A bare name is a `take`."""
    stages = []
    for token in (piece.strip() for piece in line.split(" > ")):
        found = _STAGE.fullmatch(token)
        stages.append((found.group("part"), found.group("kind")) if found else (token, "take"))
    return stages


def compose(exact_parts, stages):
    """Exact parts first (each a `take`), then the arrangement that was assembled without them."""
    return [(part, "take") for part in exact_parts] + [tuple(stage) for stage in stages]


class Outcomes:
    """What every part did on a list of Tasks, as arrays over the Tasks. Made from recorded answers.

    answer[p]     the answers of part p (None where it did not answer)
    has[p]        p answered
    right[p]      that answer is right (the recorded flag; a search reads it on fit Tasks only)
    recorded[p]   there is a record of p for the Task
    flags[p]      {name: array}: named pieces of evidence of p's step (for stage types that need one)
    uses[p]       {call: array}: the recorded calls on p's path
    seconds       {call: array}: the model seconds of each recorded call
    kinds[p]      the stage types p may be used with, in the order of enumeration
    """

    def __init__(self, task_ids):
        self.ids = list(task_ids)
        self.n = len(self.ids)
        self.answer, self.has, self.right, self.recorded = {}, {}, {}, {}
        self.flags, self.uses, self.kinds, self.seconds = {}, {}, {}, {}

    def add(self, part, rows, kinds=("take", "agree")):
        """Add one part. `rows` holds one dictionary for each Task, in order: "answer" (None when the
        part did not answer), "right", "calls" ([(call name, model seconds)]: every recorded call on
        the part's path), "flags" ({name: yes or no}) and "recorded" (False: no record of the part)."""
        if len(rows) != self.n:
            raise ValueError(f"part {part!r}: {len(rows)} rows for {self.n} Tasks")
        self.answer[part] = [row.get("answer") for row in rows]
        self.has[part] = np.array([answer is not None for answer in self.answer[part]], bool)
        self.right[part] = np.array([bool(row.get("right")) for row in rows], bool) & self.has[part]
        self.recorded[part] = np.array([bool(row.get("recorded", True)) for row in rows], bool)
        uses, flags = {}, {}
        for j, row in enumerate(rows):
            for call, seconds in row.get("calls") or ():
                uses.setdefault(call, np.zeros(self.n, bool))[j] = True
                self.seconds.setdefault(call, np.zeros(self.n))[j] = float(seconds)
            for name, value in (row.get("flags") or {}).items():
                flags.setdefault(name, np.zeros(self.n, bool))[j] = bool(value)
        self.uses[part], self.flags[part], self.kinds[part] = uses, flags, tuple(kinds)
        return self

    def best_recorded(self, parts):
        """True where some part gave a right answer (the best recorded answer; not an arrangement)."""
        return np.any(np.stack([self.right[part] for part in parts]), axis=0)


# ---------------------------------------------------------------------------
# 2. The search and the chooser
# ---------------------------------------------------------------------------

class Assembler:
    """All arrangements of a part set replayed on recorded outcomes, and the choosers.

    outcomes    an `Outcomes` object
    parts       the parts of the grammar, in the order of enumeration
    first       parts that run first in every arrangement, each as a `take` (the calculator)
    equal       equal(a, b) for two answers; the default is `answers_equal` at the `number_equality` setting
    settings    the dimensions of the search (default `SETTINGS`); `resolver` gives their values and
                keeps the record of every value it gave in `resolver.choices`
    """

    def __init__(self, outcomes, parts, first=(), equal=None, settings=None, resolver=None):
        self.o, self.parts, self.first = outcomes, list(parts), list(first)
        self.settings = settings or SETTINGS
        self.resolver = resolver or Resolver()
        self.max_stages = self.ask("assembler.max_stages")
        self.within = self.ask("assembler.within_points")
        self.tie = self.ask("assembler.tie_window")
        self.cost_decimals = self.ask("assembler.cost_decimals")
        self.rows_per_block = self.ask("assembler.rows_per_block")
        self.fallback = REPLAY_FALLBACKS[self.ask("assembler.fallback")]
        self.events = []        # every time a named rule fired: which rule, what it took, and the numbers
        self.equal = equal or answers_equal(*self.ask("assembler.number_equality"))
        self._same, self._means = {}, {}
        self.G = self.grammar()
        self.n_stages = np.array([len(stages) for stages in self.G])
        self.R = self.S = None
        start = self._start()
        for part in self.parts:     # a part with no record on a Task is never reached: a first part answers there
            if not bool(np.all(start[0][~self.o.recorded[part]])):
                raise ValueError(f"part {part!r} has no record on a Task that no first part answers")

    def ask(self, name, context=None):
        """The value of one setting of the search, through the resolver."""
        return self.resolver.value(self.settings[name], context)

    # ---- the grammar ----
    def grammar(self):
        """Every arrangement: 1 to `max_stages` different parts in order, each with one of its stage
        types. Same order as test 10. An arrangement is a tuple of (part, stage type)."""
        options = {part: [(part, kind) for kind in self.o.kinds[part]] for part in self.parts}
        out = []
        for length in range(1, self.max_stages + 1):
            for chosen in itertools.permutations(self.parts, length):
                out.extend(itertools.product(*[options[part] for part in chosen]))
        return out

    def stages(self, index):
        """The whole arrangement with this index: the first parts, then its stages."""
        return compose(self.first, self.G[index])

    def show(self, index):
        return show(self.stages(index), bare=self.first)

    # ---- the replay ----
    def _equal(self, p, q):
        key = (p, q) if p <= q else (q, p)
        if key not in self._same:
            self._same[key] = np.array([self.equal(a, b) for a, b in zip(self.o.answer[p], self.o.answer[q])], bool)
        return self._same[key]

    def _step(self, state, part, kind, ran):
        """One stage on every Task that has no answer yet. Returns the new state; changes no array."""
        done, right, secs, paid, last_has, last_right = state
        o, active, paid = self.o, ~done, dict(paid)
        for call, used in o.uses[part].items():
            new = active & used
            if call in paid:
                new = new & ~paid[call]
                paid[call] = paid[call] | new
            else:
                paid[call] = new
            secs = secs + np.where(new, o.seconds[call], 0.0)
        answered = active & o.has[part]
        stage = STAGE_KINDS[kind]
        agrees = None
        if stage.needs_agreement:
            agrees = np.zeros(o.n, bool)
            for earlier in ran:
                agrees = agrees | self._equal(part, earlier)
        accepted = stage.accepts(answered, agrees, o.flags[part])
        right = np.where(accepted, o.right[part], right)
        last_right = np.where(answered, o.right[part], last_right)
        return done | accepted, right, secs, paid, last_has | answered, last_right

    def _start(self):
        n = self.o.n
        state = (np.zeros(n, bool), np.zeros(n, bool), np.zeros(n), {}, np.zeros(n, bool), np.zeros(n, bool))
        for position, part in enumerate(self.first):
            state = self._step(state, part, "take", self.first[:position])
        return state

    def _end(self, state):
        """Right or wrong of every Task: where no stage gave the answer, the fallback rule decides."""
        done, right, secs, _, last_has, last_right = state
        return self.fallback(done, right, last_has, last_right), secs

    def replay(self, stages):
        """One arrangement, written out in full (first parts included), on every Task.
        Returns (right or wrong, model seconds), one value for each Task."""
        n = self.o.n
        state = (np.zeros(n, bool), np.zeros(n, bool), np.zeros(n), {}, np.zeros(n, bool), np.zeros(n, bool))
        ran = []
        for part, kind in stages:
            state = self._step(state, part, kind, ran)
            ran.append(part)
        return self._end(state)

    def replay_all(self):
        """Replay every arrangement of the grammar. Fills R (right or wrong) and S (model seconds), one
        row for each arrangement and one column for each Task. An arrangement shares the work of its
        first stages with every arrangement that starts the same way."""
        index = {stages: position for position, stages in enumerate(self.G)}
        self.R = np.zeros((len(self.G), self.o.n), np.uint8)
        self.S = np.zeros((len(self.G), self.o.n), np.float32)

        def walk(prefix, state):
            ran = self.first + [part for part, _ in prefix]
            for part in self.parts:
                if part in ran:
                    continue
                for kind in self.o.kinds[part]:
                    stages = prefix + ((part, kind),)
                    after = self._step(state, part, kind, ran)
                    position = index[stages]
                    self.R[position], self.S[position] = self._end(after)
                    if len(stages) < self.max_stages:
                        walk(stages, after)

        walk((), self._start())
        self._means = {}
        return self

    # ---- the chooser of test 10 ----
    def fit_means(self, idx):
        """Accuracy (points) and mean model seconds of every arrangement on the Tasks idx. Kept for reuse."""
        key = np.asarray(idx).tobytes()
        if key not in self._means:
            blocks = range(0, len(self.G), self.rows_per_block)
            accuracy = np.concatenate([PERCENT * self.R[a:a + self.rows_per_block][:, idx].mean(axis=1) for a in blocks])
            cost = np.concatenate([self.S[a:a + self.rows_per_block][:, idx].mean(axis=1) for a in blocks])
            self._means[key] = (accuracy, cost)
        return self._means[key]

    def choose(self, idx, cap=None):
        """The arrangement for the fit Tasks idx: within `within_points` of the best, inside the cap, the
        cheapest (then fewer stages, then the order of enumeration). Returns its index."""
        accuracy, cost = self.fit_means(idx)
        ok = np.ones(len(accuracy), bool) if cap is None else cost <= cap
        if not ok.any():
            rule = self.ask("assembler.when_nothing_fits")
            self.events.append({"rule": "assembler.when_nothing_fits", "taken": rule, "cap": cap,
                                "cheapest_mean_cost": float(cost.min()), "fit_tasks": int(len(idx))})
            ok = NOTHING_FITS[rule](cost, self.tie)
        best = accuracy[ok].max()
        candidates = np.where(ok & (accuracy >= best - self.within))[0]
        order = np.lexsort((candidates, self.n_stages[candidates], np.round(cost[candidates], self.cost_decimals)))
        return int(candidates[order[0]])

    def priced(self, idx):
        """One group for `one_price`: (accuracy, cost, number of Tasks) of every arrangement on the Tasks idx."""
        accuracy, cost = self.fit_means(idx)
        return accuracy, cost, len(idx)

    def choose_with_price(self, groups, budget):
        """One arrangement for each group of fit Tasks, with one price for all groups (see `one_price`).
        Returns ([index for each group], price)."""
        lowest, highest, halvings = self.ask("assembler.price_search")
        return one_price([self.priced(idx) for idx in groups], budget, lowest, highest, halvings, self.tie,
                         self.ask("assembler.when_over_budget"), self.events)


def one_price(groups, budget, lowest, highest, halvings, tie, when_over="highest_price", events=None):
    """One price per model second for all groups, also for groups of different searches.

    `groups` holds (accuracy, cost, number of Tasks) for each group: two arrays over the arrangements of
    that group's search. Each group takes the arrangement with the best "accuracy minus price times
    cost" (on equal scores the cheaper one). The price is the lowest one, found by halving the range,
    that keeps the mean cost over all Tasks inside the budget. Returns ([index for each group], price).
    When not even the highest price keeps the budget, the named rule `when_over` decides (OVER_BUDGET),
    and the event, with how far over the budget the choice is, is written to `events`.
    """
    accuracies, costs = [accuracy for accuracy, _, _ in groups], [cost for _, cost, _ in groups]
    weight = np.array([tasks for _, _, tasks in groups], float)
    weight = weight / weight.sum()

    def pick(price):
        out = []
        for accuracy, cost in zip(accuracies, costs):
            score = accuracy - price * cost
            candidates = np.where(score >= score.max() - tie)[0]
            out.append(int(candidates[np.argmin(cost[candidates])]))
        return out

    def mean_cost(chosen):
        return float(sum(w * costs[i][a] for i, (w, a) in enumerate(zip(weight, chosen))))

    low, high = lowest, highest
    if mean_cost(pick(low)) <= budget:
        return pick(low), low
    for _ in range(halvings):
        middle = (low + high) / 2.0
        if mean_cost(pick(middle)) <= budget:
            high = middle
        else:
            low = middle
    chosen = pick(high)
    if mean_cost(chosen) <= budget:
        return chosen, high
    if events is not None:
        events.append({"rule": "assembler.when_over_budget", "taken": when_over, "budget": budget, "price": high,
                       "mean_cost": mean_cost(chosen), "over_by": mean_cost(chosen) - budget})
    return OVER_BUDGET[when_over](chosen, high)


# ---------------------------------------------------------------------------
# 3. Groups, folds, intervals, admission
# ---------------------------------------------------------------------------

def profile_groups(fit_idx, labels, min_tasks=None):
    """The groups of fit Tasks that get an arrangement of their own: [(key, idx)].

    `labels` is {label type: array over all Tasks}, for example {"form": ..., "kind": ...}; a key is
    "form: number" or "kind: date-choice". `min_tasks` is {label type: smallest group}: a smaller
    group gets none (test 10: a kind with fewer than 30 fit Tasks uses the arrangement of its form).
    """
    groups = []
    for label, values in labels.items():
        here = np.asarray(values)[fit_idx]
        for value in sorted(set(here.tolist())):
            idx = fit_idx[here == value]
            if len(idx) and len(idx) >= (min_tasks or {}).get(label, 0):
                groups.append((f"{label}: {value}", idx))
    return groups


def fold_of(strata, folds, seed):
    """The fold of every Task: stratified by `strata`, as test 10 does it. Returns an array of fold numbers."""
    strata = np.asarray(strata)
    generator = np.random.default_rng(seed)
    fold = np.zeros(len(strata), int)
    for label in sorted(set(strata.tolist())):
        idx = np.where(strata == label)[0]
        idx = idx[generator.permutation(len(idx))]
        fold[idx] = np.arange(len(idx)) % folds
    return fold


class Bootstrap:
    """The paired bootstrap over Tasks of test 10: one set of resamples for every figure of a run."""

    def __init__(self, n, resamples, seed, percentiles, decimals):
        self.index = np.random.default_rng(seed).integers(0, n, size=(resamples, n))
        self.low, self.high = percentiles
        self.decimals = decimals

    def interval(self, values):
        """[mean, lower end, upper end] of one value for each Task (for a comparison: the difference of
        two arms, Task by Task)."""
        values = np.asarray(values, dtype=float)
        means = values[self.index].mean(axis=1)
        return [round(float(values.mean()), self.decimals), round(float(np.percentile(means, self.low)), self.decimals),
                round(float(np.percentile(means, self.high)), self.decimals)]


def admission(right_new, right_old, margin_points, min_tasks):
    """The admission gate: may new parameters replace the stored ones for a profile?

    `right_new` and `right_old` are right or wrong of the two on the same Tasks, and none of these Tasks
    was used to assemble the new parameters. Admitted when there are at least `min_tasks` Tasks and the
    new accuracy is at least the stored one minus `margin_points`. Returns the record of the decision.
    """
    right_new, right_old = np.asarray(right_new, bool), np.asarray(right_old, bool)
    n = len(right_new)
    new = PERCENT * float(right_new.mean()) if n else None
    old = PERCENT * float(right_old.mean()) if n else None
    enough = n >= min_tasks
    admitted = bool(enough and new >= old - margin_points)
    why = ("too few held-back Tasks to judge" if not enough else
           "at least as right as the stored parameters, within the margin" if admitted else
           "less right than the stored parameters by more than the margin")
    return {"admitted": admitted, "why": why, "tasks": n, "new_right_pct": new, "stored_right_pct": old,
            "margin_points": margin_points, "min_tasks": min_tasks}
