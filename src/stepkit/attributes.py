# Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md
"""Attributes: claims with evidence about Task Objects, an append-only ledger, and the views recomputed from it.

FABRIC.md, section 3 (November 12, 2026): an attribute is a claim with evidence, never a free field. Each
`AttributeRecord` says which object and version it is about; the attribute's name, type and family (from
`CATALOG`); the value; the scope where it holds (a profile region, a model, an environment, a date); the
method that made it (exact code, a measured run, a model's judgment, a person); the evidence (record ids and
their count); the interval; the maker and the checker with their lineage; a status (proposed, measured,
checked, checked with corrections, stale, retired) and the time. A `Ledger` appends records and never edits
one: a change of status is a new record that names the records it supersedes. A record's id is the address
of its content. A check is a new record that names the records it checks (`checks`), with the checker and a
"checked" status; a checked record must name a checker who is not its maker (a worker never approves its
own work; this compares the two ids, so it catches only the plain case).

    ledger = Ledger("ledger.jsonl")
    evidence = ledger.evidence(task_ids, "the records of test 7")      # a set of record ids, stored once
    ledger.append(AttributeRecord("part:B.reuse", "success", 0.84, scope={"region": "kind: date-choice"},
                                  method=MEASURED, evidence=evidence, interval=[0.71, 0.93]))
    tree = RegionTree.from_labels(fit_positions, [("form", forms), ("kind", kinds)])    # all > form > kind
    estimates = shrink(tree, right)        # right: objects x Tasks, 0 or 1. Every region's estimate is
                                           # shrunk toward its parent regions by empirical Bayes
    scores = estimates.scores("kind: date-choice")      # lower ends of the Beta intervals, in points
    index = choose(scores, costs, n_stages, cap, within, tie, decimals)      # test 10's rule on any score

The views, all recomputed from records: `success_counts` and `beta_interval` (success by region with a
Beta interval); `shrink` (a region's estimate shrunk toward its parent regions, empirical Bayes);
`mean_by_region` (cost by region); `relations` (duplicates by the same outputs, complements by low error
overlap); `replay_credit` (credit by swapping a part of a recorded chain); `RegionEstimates.table` (a
predictor of success from the profile). Repositories as Task Objects: `repository_records` builds the
repository, file and test levels of test 8's records (work-2026-11-12-harder-localization).

How a region is shrunk (setting "attributes.shrinkage.parent" at its default): the prior mean of a region
is its parent's estimate made WITHOUT the region's own Tasks, and that estimate is itself shrunk toward the
grandparent made without the parent's Tasks; the root has the prior "attributes.prior" (Jeffreys). So no
Task counts twice in a prior mean (the strength of a parent is fitted on all its Tasks, its children's
included). The strength of the prior (its weight in Tasks) is chosen for each region by empirical
Bayes: the value of the grid of "attributes.shrinkage.strength" with the largest beta-binomial marginal
likelihood of the region's counts, over all its objects. With fewer objects than
"attributes.shrinkage.min_objects", one strength is shared by the regions of a level.

Every setting is a Dimension in `SETTINGS`, read through a Resolver that writes down each value.
Needs numpy and scipy (scipy.special: betaln, betaincinv, ndtri). Git is used read-only, only by
`git_files` and `git_sizes`.
"""
import hashlib
import json
import math
import os
import subprocess
from collections import Counter
from dataclasses import asdict, dataclass, field

import numpy as np
from scipy import special

from . import _sources as S
from .assembler import PERCENT
from .dimension import CHOICES, JOINT, NUMBERS, Dimension, Resolver, Settings, plain

EXACT, MEASURED, JUDGED, PERSON = "exact code", "measured run", "model judgment", "person"
NO_PART = "(the stage left out)"        # the alternative of `replay_credit` that puts no part in a stage
METHODS = (EXACT, MEASURED, JUDGED, PERSON)
STATUSES = ("proposed", "measured", "checked", "checked with corrections", "stale", "retired")
CHECKED = ("checked", "checked with corrections")       # the statuses that only a checker who is not the maker may give
ADDED_FIELDS = ("checks",)      # fields added after the first ledgers were written: left out of a record's content
                                # (its address) and of its line while empty, so the ids of older records stay valid
FAMILIES = ("identity and structure", "description", "evidence of quality", "cost", "relations",
            "life cycle and rules", "use", "learned predictors")

SETTINGS = Settings(name="attributes", dimensions=[
    Dimension("attributes.prior", [[0.5, 0.5], [1.0, 1.0]], kind=JOINT, limits={"alpha": {"min": 0.0}, "beta": {"min": 0.0}},
              members=["alpha", "beta"],
              about="the Beta prior of a region that has no parent: Jeffreys (0.5, 0.5) or uniform (1, 1)"),
    Dimension("attributes.interval_percentiles", [[2.5, 97.5]], [[5.0, 95.0], [2.5, 97.5], [0.5, 99.5]], JOINT,
              {"low": {"min": 0.0, "max": 50.0}, "high": {"min": 50.0, "max": 100.0}}, ["low", "high"],
              about="the two ends of an interval, in percent: 2.5 and 97.5 give the equal-tailed 95% interval"),
    Dimension("attributes.shrinkage.strength", [None],
              [None, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 64.0, 128.0, 256.0, 512.0, 1024.0, 2048.0, 4096.0],
              NUMBERS, {"min": 0.0},
              about="the weight of a region's prior, in Tasks; None: chosen for each region by empirical Bayes "
                    "(the largest beta-binomial marginal likelihood) from the numbers of the grid"),
    Dimension("attributes.shrinkage.min_objects", [30], [1, 2, 10, 30, 100, 1000000], NUMBERS, {"min": 1},
              about="with at least this many objects every region gets its own strength; with fewer, one strength "
                    "is shared by the regions of a level"),
    Dimension("attributes.shrinkage.parent", ["without_own_tasks", "with_own_tasks"], kind=CHOICES,
              about="the prior mean of a region: its parent's estimate made without the region's own Tasks (no Task "
                    "counts twice), or the parent's estimate with them"),
    Dimension("attributes.score", ["lower_end", "mean"], kind=CHOICES,
              about="what a chooser ranks objects by: the lower end of each one's interval, or its mean"),
    Dimension("attributes.duplicates.min_agreement", [0.95], [0.9, 0.95, 0.99, 1.0], NUMBERS, {"min": 0.0, "max": 1.0},
              about="two parts duplicate each other when the lower end of the interval of their agreement (the share "
                    "of Tasks with the same output) is at least this"),
    Dimension("attributes.complements.max_overlap", [0.5], [0.25, 0.5, 0.75], NUMBERS, {"min": 0.0, "max": 1.0},
              about="two parts complement each other when the upper end of the interval of their error overlap (the "
                    "share of the smaller error set that the other part also misses) is at most this"),
    Dimension("attributes.locator.top", [10], [1, 3, 5, 10], NUMBERS, {"min": 1},
              about="a locator finds an issue's file when the file is among its first this many files"),
    Dimension("attributes.id_length", [20], [16, 20, 32, 64], NUMBERS, {"min": 8, "max": 64},
              about="hex digits of the content address that is a record's id"),
])


# ---------------------------------------------------------------------------
# 1. The catalog, the record and the ledger
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AttributeType:
    """One entry of the catalog: the name of an attribute, its family, the type of its value, its unit."""
    name: str
    family: str
    type: str
    unit: str = ""
    about: str = ""


def _catalog(*entries):
    for entry in entries:
        if entry.family not in FAMILIES:
            raise ValueError(f"attribute {entry.name!r}: unknown family {entry.family!r}")
    return {entry.name: entry for entry in entries}


CATALOG = _catalog(
    AttributeType("identity", "identity and structure", "address", "", "the content address, version and lineage of the object"),
    AttributeType("structure.files", "identity and structure", "counts", "files", "file counts of a repository snapshot or of its tests"),
    AttributeType("structure.bytes", "identity and structure", "numbers", "bytes", "sizes of files"),
    AttributeType("structure.change", "identity and structure", "counts", "lines", "lines added and removed in this file by an issue's fix"),
    AttributeType("evidence.set", "identity and structure", "list", "record ids", "a list of record ids that other records give as their evidence"),
    AttributeType("description.text", "description", "text", "", "what the object does, in words"),
    AttributeType("description.applies_to", "description", "list", "regions", "the profile regions where the object is meant to work"),
    AttributeType("profile.region", "description", "label", "", "the region of a Task at one level of the profile"),
    AttributeType("success", "evidence of quality", "rate", "share of Tasks right", "success in a region, raw counts with a Beta interval"),
    AttributeType("success.shrunk", "evidence of quality", "rate", "share of Tasks right",
                  "success in a region shrunk toward its parent regions by empirical Bayes, with its Beta interval"),
    AttributeType("locator.found", "evidence of quality", "table", "rank", "which locator found the issue's file, and at which rank"),
    AttributeType("locator.hit_rate", "evidence of quality", "rate", "share of issues", "share of issues whose file a locator found in its first files"),
    AttributeType("cost.model_seconds", "cost", "mean", "model seconds per Task", "mean model seconds in a region, with an interval"),
    AttributeType("cost.seconds", "cost", "mean", "seconds per issue", "mean wall seconds of a locator, with an interval"),
    AttributeType("duplicates", "relations", "relation", "share of Tasks", "agreement of two parts: the same output on the same Tasks"),
    AttributeType("complements", "relations", "relation", "share of errors", "error overlap of two parts, and what a perfect choice between them would add"),
    AttributeType("tested_by_name", "relations", "relation", "files", "test files named after this file"),
    AttributeType("life_cycle", "life cycle and rules", "status", "", "candidate, admitted, small live share, default, deprecated or retired, with its rules"),
    AttributeType("data_use", "life cycle and rules", "tags", "", "what records of or about the object may be used for"),
    AttributeType("use.calls", "use", "count", "calls", "recorded calls of the object"),
    AttributeType("credit.replay", "use", "number", "points", "how much of a chain's success the object earned, by replays that swap it"),
    AttributeType("shrinkage.strength", "learned predictors", "number", "Tasks", "the weight of a region's prior, chosen by empirical Bayes"),
    AttributeType("comparison", "evidence of quality", "difference", "",
                  "a difference between two arms or two runs on the same work, with its interval and its verdict"),
    AttributeType("predictor.region_table", "learned predictors", "function", "share of Tasks right",
                  "success predicted from the profile: shrunk estimates by region, the most specific region first"),
)


def _plain(value):
    """A value as plain JSON data: numpy values become numbers and lists; a number that JSON cannot hold becomes None."""
    if isinstance(value, np.ndarray):
        return _plain(value.tolist())
    if isinstance(value, np.generic):
        return _plain(value.item())
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return plain(value)


@dataclass
class AttributeRecord:
    """One claim with evidence. The type and the family come from `CATALOG`; an attribute that is not in the
    catalog yet (a proposed one) gives both. `id` is set by the ledger: the address of the content."""
    object_id: str
    name: str
    value: object
    object_version: str = ""
    scope: dict = field(default_factory=dict)       # region, model, environment, date, and what else limits the claim
    method: str = EXACT
    evidence: dict = field(default_factory=dict)    # {"ids": [...], "count": n} or {"set": record id, "count": n}
    interval: object = None                         # [low, high], with its level in scope["interval_percentiles"]
    maker: dict = field(default_factory=dict)       # {"id": ..., "lineage": ...}
    checker: dict = field(default_factory=dict)     # empty when no independent checker looked at it
    status: str = "measured"
    time: str = ""
    type: str = ""
    family: str = ""
    supersedes: list = field(default_factory=list)  # ids of earlier records this one replaces; they stay in the ledger
    checks: list = field(default_factory=list)      # ids of the records this record checks (a check is a record too)
    id: str = ""

    def __post_init__(self):
        known = CATALOG.get(self.name)
        if known is not None:
            self.type, self.family = self.type or known.type, self.family or known.family
        if not self.type or self.family not in FAMILIES:
            raise ValueError(f"attribute {self.name!r} is not in the catalog: give its type and one of the families {FAMILIES}")
        if self.method not in METHODS:
            raise ValueError(f"method {self.method!r}: one of {METHODS}")
        if self.status not in STATUSES:
            raise ValueError(f"status {self.status!r}: one of {STATUSES}")
        self.value, self.scope, self.evidence = _plain(self.value), _plain(self.scope), _plain(self.evidence)
        self.interval, self.maker, self.checker = _plain(self.interval), _plain(self.maker), _plain(self.checker)
        self.supersedes = [str(record_id) for record_id in self.supersedes]
        self.checks = [str(record_id) for record_id in self.checks]
        if self.status in CHECKED or self.checks:
            checker, maker = (self.checker or {}).get("id"), (self.maker or {}).get("id")
            if not checker:
                raise ValueError(f"a record with status {self.status!r} or that checks other records names its checker")
            if checker == maker:
                raise ValueError(f"the checker {checker!r} is the maker: a worker never approves its own work")

    def _without_empty_added_fields(self, out) -> dict:
        for name in ADDED_FIELDS:
            if not out.get(name):
                out.pop(name, None)
        return out

    def content(self) -> dict:
        """Everything but the id: what the id is the address of. A field of ADDED_FIELDS is left out while it is
        empty, so a record written before the field existed keeps its address."""
        out = asdict(self)
        out.pop("id")
        return self._without_empty_added_fields(out)

    def to_dict(self) -> dict:
        return self._without_empty_added_fields(asdict(self))

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)

    @classmethod
    def from_dict(cls, data) -> "AttributeRecord":
        return cls(**data)


def read_records(path) -> list:
    """The records of a ledger file, in order."""
    with open(path, encoding="utf-8") as lines:
        return [AttributeRecord.from_dict(json.loads(line)) for line in lines if line.strip()]


def now() -> str:
    """The time now, read with the `date` command (ISO 8601, seconds)."""
    return subprocess.run(["date", "--iso-8601=seconds"], capture_output=True, text=True, check=True).stdout.strip()


class Ledger:
    """Attribute records, appended and never edited, in memory and in a JSON-lines file when a path is given.

    `append` gives the record its id (the address of its content) and writes one line; the same content
    twice is one line. Nothing is ever rewritten: `supersede` appends a new record that names the old ones,
    which stay. Reading a file checks every id against its content, so an edited line is found.
    """

    def __init__(self, path=None, resolver=None, when=None):
        self.path = path
        self.resolver = resolver or Resolver()
        self.id_length = self.resolver.value(SETTINGS["attributes.id_length"])
        self.when = when if when is not None else now()
        self.records, self._by_id, self._superseded = [], {}, set()
        if path is not None and os.path.isfile(path):
            for record in read_records(path):
                found = record.id
                if self.address(record) != found:
                    raise ValueError(f"ledger {path}: the record {found} does not match its content (was a line edited?)")
                self._keep(record)

    def tick(self):
        """Read the time again; records appended from now on without a time get it."""
        self.when = now()
        return self.when

    def address(self, record) -> str:
        text = json.dumps(record.content(), sort_keys=True)
        return "a-" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:self.id_length]

    def _keep(self, record):
        self.records.append(record)
        self._by_id[record.id] = record
        self._superseded.update(record.supersedes)

    def append(self, record) -> AttributeRecord:
        """Add one record (its time is the ledger's time when it has none). Returns the record kept."""
        if not record.time and record.name != "evidence.set":
            record.time = self.when
        address = self.address(record)
        if record.id and record.id != address:
            raise ValueError(f"record id {record.id} does not match its content")
        record.id = address
        if address in self._by_id:
            return self._by_id[address]
        missing = [old for old in record.supersedes if old not in self._by_id]
        if missing:
            raise KeyError(f"cannot supersede records that are not in the ledger: {missing}")
        unknown = [checked for checked in record.checks if checked not in self._by_id]
        if unknown:
            raise KeyError(f"cannot check records that are not in the ledger: {unknown}")
        if self.path is not None:
            with open(self.path, "a", encoding="utf-8") as out:
                out.write(record.to_json() + "\n")
        self._keep(record)
        return record

    def extend(self, records) -> list:
        return [self.append(record) for record in records]

    def supersede(self, old_ids, record) -> AttributeRecord:
        """Append `record` as the replacement of the records `old_ids` (for example a new status). They stay."""
        record.supersedes = [str(old) for old in old_ids]
        return self.append(record)

    def get(self, record_id):
        return self._by_id.get(record_id)

    def checked_by(self, record_id) -> list:
        """The records that check this record (their `checks` names it), in the order they were appended."""
        return [record for record in self.records if record_id in record.checks]

    def is_current(self, record) -> bool:
        return record.id not in self._superseded

    def find(self, object_id=None, name=None, status=None, current=False, **scope) -> list:
        """The records that match every condition given, in the order they were appended. A keyword that is
        not a field names an entry of the record's scope."""
        out = []
        for record in self.records:
            if object_id is not None and record.object_id != object_id or name is not None and record.name != name:
                continue
            if status is not None and record.status != status or current and not self.is_current(record):
                continue
            if all(record.scope.get(key) == value for key, value in scope.items()):
                out.append(record)
        return out

    def evidence(self, ids, source, maker=None) -> dict:
        """Evidence that cites many record ids: the list is stored once, as an "evidence.set" record, and the
        evidence names that record. Returns {"set": id, "count": n, "source": source}."""
        ids = [str(item) for item in ids]
        stored = self.append(AttributeRecord("evidence-set", "evidence.set", ids, method=EXACT,
                                             evidence={"count": len(ids), "source": source}, maker=maker or {}))
        return {"set": stored.id, "count": len(ids), "source": source}

    def evidence_ids(self, evidence) -> list:
        """The record ids an evidence dictionary cites (resolving a stored set)."""
        if "set" in evidence:
            return list(self._by_id[evidence["set"]].value)
        return list(evidence.get("ids", []))

    def __len__(self):
        return len(self.records)

    def __iter__(self):
        return iter(self.records)


# ---------------------------------------------------------------------------
# 2. Beta posteriors and the empirical Bayes strength
# ---------------------------------------------------------------------------

def beta_quantile(alpha, beta, percent):
    """The quantile of Beta(alpha, beta) at `percent` (0 to 100), element by element."""
    return special.betaincinv(np.asarray(alpha, float), np.asarray(beta, float), np.asarray(percent, float) / PERCENT)


def beta_interval(alpha, beta, percentiles):
    """[low end, high end] of the equal-tailed interval of Beta(alpha, beta) at the two percentiles."""
    low, high = percentiles
    return beta_quantile(alpha, beta, low), beta_quantile(alpha, beta, high)


def success_counts(right, positions):
    """Successes of every object (a row of `right`, 0 or 1 per Task) on the Tasks `positions`, and their number."""
    positions = np.asarray(positions, dtype=np.intp)
    return np.asarray(right)[:, positions].sum(axis=1).astype(float), len(positions)


def log_marginal(successes, trials, prior_mean, strength):
    """Beta-binomial log likelihood of `successes` of `trials` when the rate has a Beta prior with this mean
    and strength (alpha = strength * mean). The binomial coefficient is left out: it does not depend on the
    prior, so the comparison of strengths is the same."""
    a, b = strength * prior_mean, strength * (1 - prior_mean)
    return special.betaln(successes + a, trials - successes + b) - special.betaln(a, b)


def strength_by_marginal_likelihood(groups, grid):
    """Empirical Bayes: the strength of the grid under which the counts are most likely.

    `groups` is a list of (successes, trials, prior_mean): one for each region that shares the strength
    (arrays over the objects, or numbers). Returns (strength, {strength: total log likelihood}). On equal
    totals the first strength of the grid wins.
    """
    totals = {}
    for strength in grid:
        totals[strength] = float(sum(np.sum(log_marginal(successes, trials, prior_mean, strength))
                                     for successes, trials, prior_mean in groups))
    best = max(grid, key=lambda strength: (totals[strength], -grid.index(strength)))
    return best, totals


# ---------------------------------------------------------------------------
# 3. Regions and shrinkage
# ---------------------------------------------------------------------------

@dataclass
class Region:
    """One profile region: its key ("form: number"), the label and value it stands for, its depth, its
    parent's key and the positions of its Tasks."""
    key: str
    label: str
    value: object
    depth: int
    parent: object
    members: np.ndarray


class RegionTree:
    """Regions of the profile, from the root ("all") to the most specific level, each with one parent."""

    def __init__(self, regions):
        self.regions = {region.key: region for region in regions}
        self.root = regions[0].key
        self.labels = []
        for region in regions:
            if region.label not in self.labels:
                self.labels.append(region.label)

    @classmethod
    def from_labels(cls, positions, levels, root="all"):
        """The tree of the Tasks `positions`. `levels` is [(label, values over all Tasks)], from the general
        level to the specific one, for example [("form", forms), ("kind", kinds)]. A region of a level holds
        the Tasks with one value; its parent is the region of the level above that holds most of its Tasks
        (on equal counts, the first in order)."""
        positions = np.asarray(positions, dtype=np.intp)
        regions = [Region(root, root, None, 0, None, positions)]
        above = regions[:]
        for depth, (label, values) in enumerate(levels, start=1):
            values = np.asarray(values)[positions]
            here = []
            for value in sorted(set(values.tolist()), key=str):
                members = positions[values == value]
                shared = [int(np.isin(members, region.members).sum()) for region in above]
                parent = above[int(np.argmax(shared))].key
                here.append(Region(f"{label}: {value}", label, value, depth, parent, members))
            regions.extend(here)
            above = here
        return cls(regions)

    def __getitem__(self, key) -> Region:
        return self.regions[key]

    def __contains__(self, key):
        return key in self.regions

    def keys(self):
        return list(self.regions)

    def at(self, depth):
        return [key for key, region in self.regions.items() if region.depth == depth]

    def depths(self):
        return sorted({region.depth for region in self.regions.values()})

    def path(self, key):
        """The key, its parent, ..., the root."""
        out = [key]
        while self.regions[out[-1]].parent is not None:
            out.append(self.regions[out[-1]].parent)
        return out

    def lookup(self, values):
        """The most specific region that a Task with these label values falls in: {label: value} is tried
        from the specific level to the general one; the root when no region matches."""
        for label in reversed(self.labels):
            if label in values:
                key = f"{label}: {values[label]}"
                if key in self.regions:
                    return key
        return self.root


class RegionEstimates:
    """Beta posteriors of many objects in every region of a tree: `alpha[key]` and `beta[key]` are arrays with
    one entry for each object (a row of the counts). Also kept: the region's own counts, its prior mean, its
    strength and the log likelihood of each strength that empirical Bayes compared."""

    def __init__(self, tree, settings, resolver):
        self.tree, self.settings, self.resolver = tree, settings, resolver
        self.successes, self.trials, self.alpha, self.beta = {}, {}, {}, {}
        self.prior_mean, self.strength, self.likelihood = {}, {}, {}
        self.percentiles = resolver.value(settings["attributes.interval_percentiles"])

    def mean(self, key):
        return self.alpha[key] / (self.alpha[key] + self.beta[key])

    def raw(self, key):
        """The region's own share right (no prior); None where it has no Task."""
        trials = self.trials[key]
        return self.successes[key] / trials if trials else None

    def interval(self, key, percentiles=None):
        return beta_interval(self.alpha[key], self.beta[key], percentiles or self.percentiles)

    def lower(self, key, percent=None):
        return beta_quantile(self.alpha[key], self.beta[key], self.percentiles[0] if percent is None else percent)

    def scores(self, key, how=None):
        """What a chooser ranks the objects of a region by, in points: the lower end of each interval, or the
        mean (setting "attributes.score")."""
        how = how or self.resolver.value(self.settings["attributes.score"])
        return PERCENT * (self.lower(key) if how == "lower_end" else self.mean(key))

    def summary(self, key, index) -> dict:
        """One object in one region, as plain data for a record."""
        low, high = (float(end[index]) for end in self.interval(key))
        prior = self.prior_mean.get(key)
        return {"region": key, "successes": float(self.successes[key][index]), "trials": int(self.trials[key]),
                "raw": None if not self.trials[key] else float(self.successes[key][index] / self.trials[key]),
                "mean": float(self.mean(key)[index]), "interval": [low, high], "percentiles": list(self.percentiles),
                "prior_mean": None if prior is None else float(prior[index]), "strength": self.strength.get(key)}

    def table(self, index) -> dict:
        """The shrunk estimate of one object in every region: a predictor of success from the profile. Give
        a Task's labels to `tree.lookup` to find its region."""
        return {key: float(self.mean(key)[index]) for key in self.tree.keys()}


def _counter(right):
    """counts(positions) -> successes of every object, kept for reuse; `right` is objects x Tasks (0 or 1)."""
    right = np.asarray(right)
    kept = {}

    def counts(positions):
        positions = np.asarray(positions, dtype=np.intp)
        key = positions.tobytes()
        if key not in kept:
            kept[key] = right[:, positions].sum(axis=1).astype(float)
        return kept[key]
    return counts, right.shape[0]


def shrink(tree, right, settings=None, resolver=None) -> RegionEstimates:
    """Shrunk Beta posteriors of every object (a row of `right`) in every region of `tree`.

    The root gets the prior "attributes.prior". Every other region r gets Beta(s + k m, n - s + k (1 - m)):
    s of n are its own counts, m is its prior mean and k its strength. With the default parent rule, m is
    the parent's estimate made without r's Tasks (itself shrunk toward the grandparent made without the
    parent's Tasks), so no Task counts twice. The strength is the grid value with the largest beta-binomial
    marginal likelihood of r's counts over all objects, or one shared value for a level when there are
    fewer objects than "attributes.shrinkage.min_objects". A fixed number for "attributes.shrinkage.strength"
    is used for every region instead.
    """
    settings = settings or SETTINGS
    resolver = resolver or Resolver()

    def ask(name):
        return resolver.value(settings[name])

    alpha0, beta0 = ask("attributes.prior")
    fixed = ask("attributes.shrinkage.strength")
    grid = [value for value in settings["attributes.shrinkage.strength"].grid if value is not None] if fixed is None else [fixed]
    own_objects = ask("attributes.shrinkage.min_objects")
    parent_rule = ask("attributes.shrinkage.parent")
    counts, objects = _counter(right)
    out = RegionEstimates(tree, settings, resolver)

    def estimate(key, without):
        """Mean of region `key` over its Tasks that are not in `without`, shrunk toward its parent made
        without them and without the region's own Tasks."""
        region = tree[key]
        positions = np.setdiff1d(region.members, without)
        successes, trials = counts(positions), len(positions)
        if region.parent is None:
            return (successes + alpha0) / (trials + alpha0 + beta0)
        prior = estimate(region.parent, np.union1d(without, region.members))
        strength = out.strength[key]
        return (successes + strength * prior) / (trials + strength)

    for depth in tree.depths():
        keys = tree.at(depth)
        for key in keys:
            region = tree[key]
            out.successes[key], out.trials[key] = counts(region.members), len(region.members)
            if region.parent is None:
                out.prior_mean[key] = None
            elif parent_rule == "without_own_tasks":
                out.prior_mean[key] = estimate(region.parent, region.members)
            else:
                out.prior_mean[key] = out.mean(region.parent)
        if depth == tree[tree.root].depth:
            for key in keys:
                out.alpha[key] = out.successes[key] + alpha0
                out.beta[key] = out.trials[key] - out.successes[key] + beta0
            continue
        if objects >= own_objects or fixed is not None:
            for key in keys:
                out.strength[key], out.likelihood[key] = strength_by_marginal_likelihood(
                    [(out.successes[key], out.trials[key], out.prior_mean[key])], grid)
        else:
            shared, totals = strength_by_marginal_likelihood(
                [(out.successes[key], out.trials[key], out.prior_mean[key]) for key in keys], grid)
            for key in keys:
                out.strength[key], out.likelihood[key] = shared, totals
        for key in keys:
            strength, prior = out.strength[key], out.prior_mean[key]
            out.alpha[key] = out.successes[key] + strength * prior
            out.beta[key] = out.trials[key] - out.successes[key] + strength * (1 - prior)
    return out


def raw_estimates(tree, right, settings=None, resolver=None) -> RegionEstimates:
    """The same view with no shrinkage: every region has the root's prior (Jeffreys by default)."""
    settings = settings or SETTINGS
    resolver = resolver or Resolver()
    alpha0, beta0 = resolver.value(settings["attributes.prior"])
    counts, _ = _counter(right)
    out = RegionEstimates(tree, settings, resolver)
    for key in tree.keys():
        members = tree[key].members
        out.successes[key], out.trials[key] = counts(members), len(members)
        out.alpha[key] = out.successes[key] + alpha0
        out.beta[key] = out.trials[key] - out.successes[key] + beta0
        out.prior_mean[key] = None
    return out


# ---------------------------------------------------------------------------
# 4. Cost by region, and the chooser
# ---------------------------------------------------------------------------

def mean_by_region(values, positions):
    """Mean of every object (a row of `values`, one number per Task) on the Tasks `positions`, computed as
    the assembler computes a fit mean (so a cost here equals `Assembler.fit_means`)."""
    return np.asarray(values)[:, np.asarray(positions, dtype=np.intp)].mean(axis=1)


def mean_interval(values, percentiles):
    """[mean, low, high] of one list of numbers: a normal interval of the mean at the two percentiles."""
    values = np.asarray(values, dtype=float)
    mean = float(values.mean()) if len(values) else None
    if len(values) <= 1:
        return [mean, None, None]
    half = float(values.std(ddof=1) / math.sqrt(len(values)))
    low, high = (float(special.ndtri(end / PERCENT)) for end in percentiles)
    return [mean, mean + low * half, mean + high * half]


def choose(scores, costs, n_stages, cap, within, tie, decimals):
    """Test 10's rule on any score: inside the cap on cost, within `within` points of the best score, the
    lowest cost (rounded to `decimals`), then fewer stages, then the order of enumeration. With raw accuracy
    as the score it is `Assembler.choose`. Returns the index of the chosen object."""
    scores, costs, n_stages = np.asarray(scores, float), np.asarray(costs), np.asarray(n_stages)
    ok = np.ones(len(scores), bool) if cap is None else costs <= cap
    if not ok.any():
        ok = costs <= costs.min() + tie
    best = scores[ok].max()
    candidates = np.where(ok & (scores >= best - within))[0]
    order = np.lexsort((candidates, n_stages[candidates], np.round(costs[candidates], decimals)))
    return int(candidates[order[0]])


# ---------------------------------------------------------------------------
# 5. Relations and credit
# ---------------------------------------------------------------------------

def relations(outcomes, parts, positions, equal, settings=None, resolver=None) -> list:
    """Duplicates and complements of every pair of parts on the Tasks `positions` (the kit's `Outcomes`).

    agreement   share of the Tasks where both have a record on which they give the same output (both the
                same answer, or both no answer), with its Beta interval; "duplicates" when the lower end is
                at least "attributes.duplicates.min_agreement"
    overlap     of the Tasks where either is wrong (no answer counts as wrong), the share of the smaller error
                set that the other part also gets wrong, with its Beta interval; "complements" when the upper
                end is at most "attributes.complements.max_overlap"
    gain        share right when a perfect choice takes the right one of the two, minus the better part's share
    """
    settings = settings or SETTINGS
    resolver = resolver or Resolver()
    alpha0, beta0 = resolver.value(settings["attributes.prior"])
    percentiles = resolver.value(settings["attributes.interval_percentiles"])
    min_agreement = resolver.value(settings["attributes.duplicates.min_agreement"])
    max_overlap = resolver.value(settings["attributes.complements.max_overlap"])
    positions = np.asarray(positions, dtype=np.intp)
    out = []
    for i, p in enumerate(parts):
        for q in parts[i + 1:]:
            both = (outcomes.recorded[p] & outcomes.recorded[q])[positions]
            has_p, has_q = outcomes.has[p][positions], outcomes.has[q][positions]
            equal_answers = np.array([equal(outcomes.answer[p][j], outcomes.answer[q][j]) for j in positions], bool)
            same = both & ((has_p & has_q & equal_answers) | (~has_p & ~has_q))
            n_both, n_same = int(both.sum()), int(same.sum())
            agree_low, agree_high = beta_interval(n_same + alpha0, n_both - n_same + beta0, percentiles)
            wrong_p, wrong_q = both & ~outcomes.right[p][positions], both & ~outcomes.right[q][positions]
            smaller, shared = int(min(wrong_p.sum(), wrong_q.sum())), int((wrong_p & wrong_q).sum())
            over_low, over_high = beta_interval(shared + alpha0, smaller - shared + beta0, percentiles)
            right_p, right_q = (~wrong_p)[both], (~wrong_q)[both]
            gain = float((right_p | right_q).mean() - max(right_p.mean(), right_q.mean())) if n_both else None
            out.append({"parts": [p, q], "tasks": n_both,
                        "agreement": n_same / n_both if n_both else None, "agreement_interval": [float(agree_low), float(agree_high)],
                        "duplicates": bool(n_both and agree_low >= min_agreement),
                        "errors": [int(wrong_p.sum()), int(wrong_q.sum())], "shared_errors": shared,
                        "overlap": shared / smaller if smaller else None, "overlap_interval": [float(over_low), float(over_high)],
                        "complements": bool(smaller and over_high <= max_overlap), "gain": gain,
                        "min_agreement": min_agreement, "max_overlap": max_overlap, "percentiles": list(percentiles)})
    return out


def replay_credit(replay, stages, positions, alternatives, kinds_of=None, bootstrap=None) -> list:
    """Credit of each part of a recorded chain, by replays that swap it (FABRIC.md section 3, point 6).

    `replay(stages)` gives (right, seconds) over all Tasks, for example `Assembler.replay`; `stages` is the
    whole chain [(part, stage type)], first parts included. For each stage, on the Tasks `positions`:
      removal      the chain's share right minus the share with this stage left out, in points
      swaps        {alternative: the chain's share minus the share with the alternative in this stage}
      credit       the chain minus its best alternative, where leaving the stage out (NO_PART) is one of the
                   alternatives: how much more the part earns than anything else that could stand there. A part
                   that never answers gets 0, even when every part swapped in would do worse
    `alternatives` are the parts that may take its place (parts already in the chain are skipped);
    `kinds_of(part)` gives the stage types a part may have. On equal shares, leaving the stage out is the
    best alternative, then the order of `alternatives`. With a `bootstrap` (the kit's Bootstrap over these
    Tasks) the removal and the credit get intervals.
    """
    positions = np.asarray(positions, dtype=np.intp)
    stages = [tuple(stage) for stage in stages]
    base_right, base_seconds = replay(stages)
    base = PERCENT * float(base_right[positions].mean())
    in_chain = {part for part, _ in stages}
    out = []
    for i, (part, kind) in enumerate(stages):
        removed_right, removed_seconds = replay(stages[:i] + stages[i + 1:])
        entry = {"part": part, "stage": kind, "position": i, "chain_right_pct": base,
                 "removal_points": base - PERCENT * float(removed_right[positions].mean()),
                 "removal_seconds": float((base_seconds - removed_seconds)[positions].mean()), "swaps": {}}
        best = (NO_PART, removed_right)
        for other in alternatives:
            if other in in_chain or kinds_of is not None and kind not in kinds_of(other):
                continue
            swapped_right, _ = replay(stages[:i] + [(other, kind)] + stages[i + 1:])
            entry["swaps"][other] = base - PERCENT * float(swapped_right[positions].mean())
            if swapped_right[positions].mean() > best[1][positions].mean():
                best = (other, swapped_right)
        entry["best_alternative"] = best[0]
        entry["credit_points"] = base - PERCENT * float(best[1][positions].mean())
        if bootstrap is not None:
            entry["removal_interval"] = bootstrap.interval(PERCENT * (base_right[positions].astype(float)
                                                                     - removed_right[positions].astype(float)))[1:]
            entry["credit_interval"] = bootstrap.interval(PERCENT * (base_right[positions].astype(float)
                                                                    - best[1][positions].astype(float)))[1:]
        out.append(entry)
    return out


# ---------------------------------------------------------------------------
# 6. Repositories as Task Objects: the records of test 8
# ---------------------------------------------------------------------------

T8_DIR = os.path.join(S.NOTES, "work-2026-11-12-harder-localization")
T8_ISSUES = os.path.join(T8_DIR, "data", "issues.jsonl")
T8_RECORDS = os.path.join(T8_DIR, "runs", "swe-lite-v1", "stage1-records.jsonl")
T8_REPOS = os.path.join(T8_DIR, "data", "repos")
LOCATORS = {"F1": "BM25 over files (the notebook's tokenizer)", "F2": "the legacy locator",
            "F3": "the v6 locator", "F4": "the fusion of the BM25 and v6 lists"}
TEST_FOLDERS = ("tests", "test", "testing")


def read_jsonl(path) -> list:
    with open(path, encoding="utf-8") as lines:
        return [json.loads(line) for line in lines if line.strip()]


def test8_issues(path=T8_ISSUES) -> list:
    """The 300 issues of test 8 in their fixed order, with their answer keys (the target file)."""
    return sorted(read_jsonl(path), key=lambda issue: issue["order"])


def test8_records(path=T8_RECORDS) -> dict:
    """The stage-1 records of test 8: {(arm, instance id): record}."""
    return {(record["arm"], record["instance_id"]): record for record in read_jsonl(path)}


def record_id(record) -> str:
    """The id of one stage-1 record of test 8: its arm and its issue."""
    return f"t8-stage1:{record['arm']}/{record['instance_id']}"


def is_test_path(path) -> bool:
    """The notebook's test rule (test 8, build_dataset.is_test_path): a name that starts with test_ or ends
    with _test.py, or a folder named tests, test or testing on the path."""
    parts = path.strip("/").split("/")
    name = parts[-1]
    return name.startswith("test_") or name.endswith("_test.py") or any(part in TEST_FOLDERS for part in parts[:-1])


def found_at(record, top):
    """True when the record's target file is among the first `top` files (status ok and a rank)."""
    rank = record.get("target_rank") if record is not None and record.get("status") == "ok" else None
    return rank is not None and rank <= top


def git_dir_of(repo, root=T8_REPOS):
    """The bare clone of a repository ("django/django" -> data/repos/django__django.git)."""
    return os.path.join(root, repo.replace("/", "__") + ".git")


def git_files(git_dir, commit) -> list:
    """[(path, bytes)] of every file of a commit, read from the bare clone (read only: git ls-tree)."""
    listed = subprocess.run(["git", "--git-dir", git_dir, "ls-tree", "-r", "-l", commit],
                            capture_output=True, text=True, check=True).stdout
    out = []
    for line in listed.splitlines():
        meta, path = line.split("\t", 1)
        _mode, kind, _object, size = meta.split()
        if kind == "blob":
            out.append((path, int(size)))
    return out


def git_sizes(git_dir, specs) -> dict:
    """{"commit:path": bytes or None} for many files at once (read only: git cat-file --batch-check)."""
    if not specs:
        return {}
    answer = subprocess.run(["git", "--git-dir", git_dir, "cat-file", "--batch-check=%(objectsize)"],
                            input="\n".join(specs) + "\n", capture_output=True, text=True, check=True).stdout.splitlines()
    return {spec: (int(line) if line.isdigit() else None) for spec, line in zip(specs, answer)}


def repository_records(issues, records, ledger, maker=None, settings=None, resolver=None, git_root=None) -> dict:
    """Repositories, their files and their tests as Task Objects, from test 8's issues and stage-1 records.

    Appended to `ledger`, one record per claim:
      repository  structure.files (Python files, outside tests, tests: over every snapshot of the issues),
                  structure.bytes (sizes at the repository's first snapshot of the fixed order, from git),
                  locator.hit_rate for each locator with its Beta interval (which locator finds this
                  repository's files), data_use
      file        (the target file of each issue, at the issue's base commit) structure.bytes (from git),
                  structure.change (lines of the fix), locator.found (the rank each locator gave it),
                  tested_by_name (test files named test_<name>.py in the repository's first snapshot)
      tests       structure.files and structure.bytes of the test files at the first snapshot
      locator     cost.seconds (mean wall seconds per issue, with an interval), description.text
    Without `git_root` (or without git) the sizes and the names of test files are left out.
    Returns {"repositories": [...], "files": n, "records": n appended}.
    """
    settings = settings or SETTINGS
    resolver = resolver or Resolver()
    alpha0, beta0 = resolver.value(settings["attributes.prior"])
    percentiles = resolver.value(settings["attributes.interval_percentiles"])
    top = resolver.value(settings["attributes.locator.top"])
    maker = maker or {"id": "stepkit.attributes.repository_records", "lineage": "test 8 stage-1 records and answer keys"}
    before = len(ledger)
    arms = sorted({arm for arm, _ in records if arm in LOCATORS})
    by_repo = {}
    for issue in issues:
        by_repo.setdefault(issue["repo"], []).append(issue)
    for arm in arms:
        ledger.append(AttributeRecord("locator:" + arm, "description.text", LOCATORS[arm], method=PERSON,
                                      evidence={"ids": ["work-2026-11-12-harder-localization/PLAN.md"], "count": 1},
                                      maker=maker, scope={"environment": "test 8 sandbox, read-only tree, no network"}))
        seconds = [records[(arm, issue["instance_id"])]["seconds"] for issue in issues if (arm, issue["instance_id"]) in records]
        mean, low, high = mean_interval(seconds, percentiles)
        ledger.append(AttributeRecord("locator:" + arm, "cost.seconds", mean, interval=[low, high], method=MEASURED,
                                      evidence=ledger.evidence([record_id(records[(arm, issue["instance_id"])]) for issue in issues
                                                                if (arm, issue["instance_id"]) in records], "test 8 stage 1"),
                                      scope={"region": "all", "percentiles": percentiles,
                                             "environment": "6 processes in parallel on a loaded machine"}, maker=maker))
    for repo, own in by_repo.items():
        object_id = "repository:" + repo
        first = own[0]
        snapshot_counts = {name: [issue[field_name] for issue in own] for name, field_name in
                           (("python_files", "n_py_files"), ("outside_tests", "n_non_test_py_files"))}
        snapshot_counts["tests"] = [issue["n_py_files"] - issue["n_non_test_py_files"] for issue in own]
        ledger.append(AttributeRecord(object_id, "structure.files",
                                      {name: {"min": min(values), "median": float(np.median(values)), "max": max(values)}
                                       for name, values in snapshot_counts.items()},
                                      object_version=f"{len(own)} snapshots", method=EXACT, maker=maker,
                                      evidence=ledger.evidence([f"t8-issues:{issue['instance_id']}" for issue in own],
                                                               "test 8 issues and answer keys"),
                                      scope={"snapshots": len(own), "test_rule": "name test_*.py or *_test.py, or a folder tests, test or testing"}))
        ledger.append(AttributeRecord(object_id, "data_use", ["public benchmark issues (SWE-bench Lite, test split)",
                                                              "evaluation records: keep out of training sets"],
                                      method=PERSON, maker=maker, evidence={"ids": ["t8-dataset-summary"], "count": 1}))
        for arm in arms:
            hits = [found_at(records.get((arm, issue["instance_id"])), top) for issue in own]
            successes, trials = sum(hits), len(hits)
            low, high = beta_interval(successes + alpha0, trials - successes + beta0, percentiles)
            ledger.append(AttributeRecord(object_id, "locator.hit_rate", successes / trials, method=MEASURED, maker=maker,
                                          interval=[float(low), float(high)],
                                          evidence=ledger.evidence([record_id(records[(arm, issue["instance_id"])]) for issue in own
                                                                    if (arm, issue["instance_id"]) in records], "test 8 stage 1"),
                                          scope={"region": "repository: " + repo, "locator": arm, "top": top, "found": successes,
                                                 "issues": trials, "percentiles": percentiles}))
        listing, sizes = [], {}
        git_dir = git_dir_of(repo, git_root) if git_root else None
        if git_dir and os.path.isdir(git_dir):
            listing = git_files(git_dir, first["base_commit"])
            sizes = git_sizes(git_dir, [f"{issue['base_commit']}:{issue['target_files'][0]}" for issue in own])
            python = [(path, size) for path, size in listing if path.endswith(".py")]
            tests = [(path, size) for path, size in python if is_test_path(path)]
            ledger.append(AttributeRecord(object_id, "structure.bytes",
                                          {"python_files": len(python), "python_bytes": sum(size for _, size in python),
                                           "median_python_file_bytes": float(np.median([size for _, size in python])) if python else None,
                                           "all_files": len(listing), "all_bytes": sum(size for _, size in listing)},
                                          object_version=first["base_commit"], method=EXACT, maker=maker,
                                          evidence={"ids": [f"git:{repo}@{first['base_commit']}"], "count": 1},
                                          scope={"snapshot": first["base_commit"], "issue": first["instance_id"]}))
            ledger.append(AttributeRecord("tests:" + repo, "structure.files",
                                          {"test_files": len(tests), "test_bytes": sum(size for _, size in tests),
                                           "share_of_python_files": len(tests) / len(python) if python else None},
                                          object_version=first["base_commit"], method=EXACT, maker=maker,
                                          evidence={"ids": [f"git:{repo}@{first['base_commit']}"], "count": 1},
                                          scope={"snapshot": first["base_commit"], "repository": repo}))
        test_names = {}
        for path, _ in listing:
            if path.endswith(".py") and is_test_path(path):
                test_names.setdefault(os.path.basename(path), []).append(path)
        for issue in own:
            target = issue["target_files"][0]
            file_id = f"file:{repo}:{target}"
            found = {arm: (records[(arm, issue["instance_id"])].get("target_rank") if (arm, issue["instance_id"]) in records else None)
                     for arm in arms}
            ledger.append(AttributeRecord(file_id, "locator.found", found, object_version=issue["base_commit"], method=MEASURED,
                                          maker=maker, evidence={"ids": [record_id(records[(arm, issue["instance_id"])]) for arm in arms
                                                                         if (arm, issue["instance_id"]) in records], "count": len(arms)},
                                          scope={"issue": issue["instance_id"], "repository": repo, "top": top,
                                                 "found_in_top": sorted(arm for arm, rank in found.items() if rank is not None and rank <= top)}))
            detail = issue.get("key_detail", {}).get(target, {})
            ledger.append(AttributeRecord(file_id, "structure.change", {"added": detail.get("added_lines"), "removed": detail.get("removed_lines")},
                                          object_version=issue["base_commit"], method=EXACT, maker=maker,
                                          evidence={"ids": [f"t8-issues:{issue['instance_id']}"], "count": 1},
                                          scope={"issue": issue["instance_id"], "repository": repo}))
            size = sizes.get(f"{issue['base_commit']}:{target}")
            if size is not None:
                ledger.append(AttributeRecord(file_id, "structure.bytes", {"bytes": size}, object_version=issue["base_commit"],
                                              method=EXACT, maker=maker, evidence={"ids": [f"git:{repo}@{issue['base_commit']}"], "count": 1},
                                              scope={"issue": issue["instance_id"], "repository": repo}))
            if listing:
                stem = os.path.basename(target)
                named = sorted(test_names.get("test_" + stem, []))
                ledger.append(AttributeRecord(file_id, "tested_by_name", named, object_version=first["base_commit"], method=EXACT,
                                              maker=maker, evidence={"ids": [f"git:{repo}@{first['base_commit']}"], "count": 1},
                                              scope={"snapshot": first["base_commit"], "rule": "a test file named test_<file name>",
                                                     "issue": issue["instance_id"]}))
    return {"repositories": list(by_repo), "files": len(issues), "records": len(ledger) - before}


def call_counts(records, key="probe") -> Counter:
    """Recorded calls by part: how often each part ran (the "use.calls" attribute)."""
    return Counter(record[key] for record in records)
