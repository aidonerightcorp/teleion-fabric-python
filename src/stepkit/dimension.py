# Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md
"""Dimensions: every setting of a node, a contract or a search is an object, never a bare value.

The owner's rule of November 12, 2026: no scalar setting and no implicit state machine. A setting is a
`Dimension`: a name, a few suggested values in order of preference (the first is the default), the full
grid of values that may be tried, the type of the grid (ordered numbers, a set of choices, ordered
values, a set of members of which a value takes several, a joint grid over several settings, or a
structure that is only described) and hard limits that no search may cross. A `Settings` object is a
named set of dimensions. All of it is plain data, to and from JSON, and a field that this version does
not know is kept and written back.

The catalog of setting dimensions of November 12 (notes/work-2026-11-12-omninode-universal/catalog/
dimensions.json) is read as it is: `load_catalog(path)` gives a `Settings` with one Dimension for each
entry, and `Dimension.to_catalog()` gives the entry back unchanged.

A value is never read directly. Code asks a `Resolver` for the value of a dimension in a context (the
Task's profile, the contract, the store of evidence), and the resolver writes every value it gives as a
choice: the dimension, the value and where it came from: "set by the caller" (and by whom: `with_` and
`narrowed` mark a value with who set it), "suggested default", "chosen by strategy X from evidence", or
"exploration". The strategy that resolves values is itself a dimension with a grid of strategies.

    cap = Dimension("cap_model_seconds", [10.0, None, 5.0], [None, 2.0, 5.0, 10.0], NUMBERS, {"min": 0.0})
    resolver = Resolver()
    resolver.value(cap)            # 10.0, and resolver.choices holds the dimension, the value and "suggested default"
    Resolver(evidence={"cap_model_seconds": {"value": 5.0, "source": "the plan"}}).value(cap)     # 5.0, from evidence

Python 3 standard library only.
"""
import json
import random
from dataclasses import dataclass, field

NUMBERS, CHOICES, JOINT = "numbers", "choices", "joint"
ORDERED, MULTI, STRUCTURED = "ordered", "multi", "structured"
GRID_TYPES = (NUMBERS, CHOICES, JOINT, ORDERED, MULTI, STRUCTURED)
# the catalog's word for a grid type -> the grid type here, and back
FROM_CATALOG = {"set": CHOICES, "ordered": ORDERED, "multi": MULTI, "joint": JOINT, "structured": STRUCTURED}
TO_CATALOG = {CHOICES: "set", ORDERED: "ordered", NUMBERS: "ordered", MULTI: "multi", JOINT: "joint", STRUCTURED: "structured"}
# the fields of a catalog entry that are kept as they are (in `extra`); "decides" is the dimension's `about`
CATALOG_KEPT = ("layer", "joint_with", "sized_by", "resolve_when", "try_cost", "evidence")
# the three reasons a resolver can give for a value
# where a value came from, as the record says it
BY_DEFAULT, BY_CALLER, BY_EXPLORATION = "suggested default", "set by the caller", "exploration"
BY_EVIDENCE = "chosen by strategy {strategy} from evidence"
CALLER = "the caller"        # who set a value when nobody is named


def by_evidence(strategy_name, source):
    """The reason for a value that a strategy took from evidence."""
    return BY_EVIDENCE.format(strategy=strategy_name) + ": " + str(source)


def by_caller(who=None):
    """The reason for a value that a caller set; `who` names the caller when it is known."""
    return BY_CALLER if who in (None, "", CALLER) else BY_CALLER + ": " + str(who)


class LimitError(ValueError):
    """A value outside the hard limits of its dimension. No search and no evidence may cross them."""


def plain(value):
    """A value as plain JSON data: a tuple becomes a list; a Dimension or Settings becomes its dictionary."""
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, dict):
        return {str(key): plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    return value


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _inside(value, limits):
    """True when one plain value is inside a limits dictionary: "min" and "max" for a number, "never"
    and "only" for a choice. A missing limit allows everything."""
    if value in limits.get("never", ()):
        return False
    if "only" in limits and value not in limits["only"]:
        return False
    if not _is_number(value):
        return True
    lowest, highest = limits.get("min"), limits.get("max")
    return (lowest is None or value >= lowest) and (highest is None or value <= highest)


def _order(values):
    """Numbers in rising order; None (no limit, or switched off) comes first."""
    return sorted(values, key=lambda value: (value is not None, value if value is not None else False))


def _key(value):
    return json.dumps(plain(value), sort_keys=True, default=str)


def _members_of(values):
    """The member names of a joint grid whose values are dictionaries: their keys, in order of first use."""
    names = []
    for value in values:
        for name in (value if isinstance(value, dict) else ()):
            if name not in names:
                names.append(name)
    return names


@dataclass
class Dimension:
    """One setting.

    name        the name code asks for
    suggested   a few values in order of preference; the first one is the default
    grid        every value that may be tried (the suggested values when left out)
    kind        NUMBERS (ordered numbers; None means no limit or switched off), CHOICES (a set of
                choices; a choice may be a name, a yes or no, or a list), ORDERED (values in the order
                the grid gives; numbers and names may be mixed), MULTI (the grid lists members and a
                value is a list of different members), JOINT (a value has one entry for each member
                dimension: a list in the order of `members`, or a dictionary member -> entry),
                STRUCTURED (a value is any plain structure; the grid is described by `generator`)
    limits      hard limits: {"min", "max"} for numbers, {"never", "only"} for choices (for MULTI they
                hold for each member), for a joint grid one such dictionary for each member name, and
                "rules": rules in words that code cannot check (the catalog's hard limits)
    members     the member names of a joint grid, in the order of the entries (read from the keys of
                dictionary values when not given)
    generator   when the grid is too large to list: the rule that makes it (a name and its settings,
                or "text": the catalog's description of the grid)
    about       one line that says what the setting does
    extra       fields this version does not know: kept and written back
    """
    name: str
    suggested: list
    grid: list = None
    kind: str = CHOICES
    limits: dict = field(default_factory=dict)
    members: list = field(default_factory=list)
    generator: dict = field(default_factory=dict)
    about: str = ""
    extra: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.kind not in GRID_TYPES:
            raise ValueError(f"dimension {self.name!r}: the grid type must be one of {GRID_TYPES}")
        self.suggested = [plain(value) for value in self.suggested]
        if not self.suggested:
            raise ValueError(f"dimension {self.name!r} needs at least one suggested value")
        if self.kind == MULTI:      # the grid lists members; the suggested values are lists of members
            listed = self.grid if self.grid is not None else [m for value in self.suggested for m in value]
            grid = []
            for member in (plain(member) for member in listed):
                if member not in grid:
                    grid.append(member)
        else:
            grid = [plain(value) for value in (self.grid if self.grid is not None else self.suggested)]
            grid = grid + [value for value in self.suggested if value not in grid]
        self.grid = _order(grid) if self.kind == NUMBERS else grid
        self.limits, self.members = plain(self.limits), list(self.members)
        if self.kind == JOINT and not self.members:
            self.members = _members_of(self.suggested)
            if not self.members:
                raise ValueError(f"dimension {self.name!r}: a joint grid names its member dimensions")
        for value in (self.suggested if self.kind == MULTI else self.grid):
            if not self.allows(value):
                raise LimitError(f"dimension {self.name!r}: the value {value!r} is outside its own limits or has the wrong form")
        if self.kind == MULTI and not all(_inside(member, self.limits) for member in self.grid):
            raise LimitError(f"dimension {self.name!r}: a member of the grid is outside its own limits")

    def allows(self, value) -> bool:
        """True when the value has the form of this dimension and is inside its hard limits."""
        value = plain(value)
        if self.kind == NUMBERS:
            return value is None and None in (self.grid or self.suggested) or _is_number(value) and _inside(value, self.limits)
        if self.kind == JOINT:
            if isinstance(value, dict):
                return (set(value) <= set(self.members)
                        and all(_inside(item, self.limits.get(member, {})) for member, item in value.items()))
            return (isinstance(value, list) and len(value) == len(self.members)
                    and all(_inside(item, self.limits.get(member, {})) for member, item in zip(self.members, value)))
        if self.kind == MULTI:
            return (isinstance(value, list) and len({_key(member) for member in value}) == len(value)
                    and all(_inside(member, self.limits) for member in value))
        return _inside(value, self.limits)

    def candidates(self) -> list:
        """The values a search may try. The grid; for MULTI the suggested lists and every list one member
        away from the first; for a grid that is only described (STRUCTURED, or a grid given as text),
        the suggested values and what the grid holds."""
        if self.kind != MULTI:
            return [value for value in self.grid if self.allows(value)]
        out, first = [list(value) for value in self.suggested], list(self.suggested[0])
        for member in self.grid:
            other = [m for m in first if m != member] if member in first else first + [member]
            if other not in out:
                out.append(other)
        return [value for value in out if self.allows(value)]

    def narrowed(self, value, by=CALLER) -> "Dimension":
        """The same dimension with this value as its first suggested value (so it is the default), marked
        as set by `by`: a resolver then writes "set by the caller" (with who) as the reason for it.

        A value that is not on the grid is added to the grid. A value outside the hard limits is an error.
        """
        value = plain(value)
        if not self.allows(value):
            raise LimitError(f"dimension {self.name!r}: the value {value!r} is outside the hard limits {self.limits}")
        return Dimension(self.name, [value] + [other for other in self.suggested if other != value], list(self.grid),
                         self.kind, dict(self.limits), list(self.members), dict(self.generator), self.about,
                         dict(self.extra, set_by=by))

    def to_dict(self) -> dict:
        out = {"name": self.name, "kind": self.kind, "suggested": plain(self.suggested), "grid": plain(self.grid),
               "limits": plain(self.limits), "about": self.about}
        if self.members:
            out["members"] = list(self.members)
        if self.generator:
            out["generator"] = plain(self.generator)
        out.update(plain(self.extra))
        return out

    @classmethod
    def from_dict(cls, data) -> "Dimension":
        data = dict(data)
        known = {key: data.pop(key) for key in ("name", "suggested", "grid", "kind", "limits", "members", "generator", "about")
                 if key in data}
        return cls(**known, extra=data)

    @classmethod
    def from_catalog(cls, entry) -> "Dimension":
        """One entry of the catalog of setting dimensions, read as it is. A grid given as text becomes the
        generator; the catalog's hard limits (rules in words) are kept under limits["rules"]; "decides"
        is the `about` line; layer, joint_with, sized_by, resolve_when, try_cost and evidence are kept."""
        grid = entry.get("grid")
        generator = {"text": grid} if isinstance(grid, str) else {}
        rules = list(entry.get("limits") or [])
        extra = {key: value for key, value in entry.items()
                 if key not in ("name", "grid_type", "suggested", "grid", "limits", "decides")}
        return cls(entry["name"], entry["suggested"], None if isinstance(grid, str) else grid, FROM_CATALOG[entry["grid_type"]],
                   {"rules": rules} if rules else {}, generator=generator, about=entry.get("decides", ""), extra=extra)

    def to_catalog(self) -> dict:
        """This dimension as an entry of the catalog (the inverse of `from_catalog`). A limit that code
        checks is written as a short rule in words, so nothing is lost."""
        rules = list(self.limits.get("rules", [])) + [f"{key} {json.dumps(value)}" for key, value in self.limits.items()
                                                       if key != "rules"]
        out = {"name": self.name, "layer": self.extra.get("layer", self.name.split(".")[0]), "decides": self.about,
               "grid_type": TO_CATALOG[self.kind], "suggested": plain(self.suggested),
               "grid": self.generator["text"] if "text" in self.generator else plain(self.grid),
               "joint_with": self.extra.get("joint_with", []), "limits": rules, "sized_by": self.extra.get("sized_by", ""),
               "resolve_when": self.extra.get("resolve_when", ""), "try_cost": self.extra.get("try_cost", ""),
               "evidence": self.extra.get("evidence", [])}
        out.update({key: value for key, value in plain(self.extra).items() if key not in out})
        return out


def is_dimension_data(data) -> bool:
    """True when a dictionary has the form of a Dimension written by `to_dict`."""
    return isinstance(data, dict) and "name" in data and "suggested" in data and data.get("kind") in GRID_TYPES


class Settings:
    """A named set of dimensions. Plain data; a field it does not know is kept in `extra` and written back."""

    def __init__(self, dimensions=(), name="", extra=None):
        self.name = name
        self._dimensions = {}
        for dimension in dimensions:
            self.add(dimension)
        self.extra = dict(extra or {})

    def add(self, dimension):
        self._dimensions[dimension.name] = dimension
        return self

    def __getitem__(self, name) -> Dimension:
        return self._dimensions[name]

    def __contains__(self, name):
        return name in self._dimensions

    def __iter__(self):
        return iter(self._dimensions.values())

    def __len__(self):
        return len(self._dimensions)

    def get(self, name, default=None):
        return self._dimensions.get(name, default)

    def names(self):
        return list(self._dimensions)

    def with_(self, values=None, by=CALLER, **more) -> "Settings":
        """A copy in which each named dimension has the given value as its default, marked as set by `by`
        (the record then says "set by the caller" and names `by`). A name that is not a dimension of this
        set becomes a new dimension with that one value (a new field stays open)."""
        out = type(self)(self._dimensions.values(), self.name, self.extra)
        for name, value in {**(values or {}), **more}.items():
            known = out.get(name)
            out.add(known.narrowed(value, by) if known is not None else Dimension(name, [value], extra={"set_by": by}))
        return out

    def merged(self, other) -> "Settings":
        """A copy with the dimensions and extra fields of another set added; the other set wins on a shared name."""
        out = type(self)(self._dimensions.values(), self.name, self.extra)
        for dimension in other:
            out.add(dimension)
        out.extra.update(other.extra)
        return out

    def summary(self) -> dict:
        """{name: first suggested value}, for a record or a display. Code that needs a value asks a Resolver."""
        return {name: plain(dimension.suggested[0]) for name, dimension in self._dimensions.items()}

    def to_dict(self) -> dict:
        out = {"name": self.name, "dimensions": {name: dimension.to_dict() for name, dimension in self._dimensions.items()}}
        out.update(plain(self.extra))
        return out

    @classmethod
    def from_dict(cls, data) -> "Settings":
        data = dict(data or {})
        name = data.pop("name", "")
        dimensions = [Dimension.from_dict(item) for item in (data.pop("dimensions", None) or {}).values()]
        return cls(dimensions, name, data)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, default=str)

    @classmethod
    def from_json(cls, text) -> "Settings":
        return cls.from_dict(json.loads(text))


def load_catalog(path) -> Settings:
    """The catalog of setting dimensions (a JSON list of entries) as a Settings, read as it is. The file
    is only read. `Dimension.to_catalog()` gives each entry back."""
    with open(path, encoding="utf-8") as handle:
        entries = json.load(handle)
    return Settings([Dimension.from_catalog(entry) for entry in entries], "catalog", {"source": str(path)})


# ---------------------------------------------------------------------------
# Strategies: how a value is found. Registered by name; the name is data.
# ---------------------------------------------------------------------------

STRATEGIES = {}


def strategy(name):
    """Register `function(dimension, context, resolver) -> (value, why)` as a strategy with this name."""
    def register(function):
        STRATEGIES[name] = function
        return function
    return register


def _first_value(dimension):
    """The first suggested value, and whether a caller set it or it is the suggested default."""
    set_by = dimension.extra.get("set_by")
    return dimension.suggested[0], (by_caller(set_by) if set_by else BY_DEFAULT)


def _evidence_reason(found, strategy_name):
    """Evidence that a caller gave as a setting ("by": "caller") is a caller's value; any other is evidence."""
    source = found.get("source", "evidence given by the caller")
    return by_caller(source) if found.get("by") == "caller" else by_evidence(strategy_name, source)


@strategy("suggested")
def _suggested(dimension, context, resolver):
    return _first_value(dimension)


@strategy("evidence")
def _from_evidence(dimension, context, resolver):
    """The value that the evidence names for this dimension; else the value a caller set, else the
    suggested default."""
    found = (context.get("evidence") or {}).get(dimension.name)
    if found is None:
        found = resolver.evidence.get(dimension.name)
    if found is None:
        return _first_value(dimension)
    if "dimension" in found:        # the evidence is a dimension of a stored set: its first suggested value
        value = found["dimension"].suggested[0]
    else:
        value = found["value"] if "value" in found else found["values"][0]
    return value, _evidence_reason(found, "evidence")


@strategy("explore")
def _explore(dimension, context, resolver):
    """Another value that a search may try than the default, drawn with the resolver's seeded generator."""
    others = [value for value in dimension.candidates() if value != dimension.suggested[0]]
    if not others:
        return _first_value(dimension)
    return resolver.generator().choice(others), BY_EXPLORATION


STRATEGY = Dimension("resolver.strategy", ["evidence", "suggested", "explore"], kind=CHOICES,
                     about="how a value is found: from evidence when there is some, else the suggested default; "
                           "the suggested default only; or another value of the grid, as an exploration")
EXPLORATION_SEED = Dimension("resolver.exploration_seed", [20261112], [20261112, 20261113, 20261114], CHOICES,
                             about="the seed of the generator that draws exploration values")


class Resolver:
    """Gives the value of a dimension in a context and writes every value it gives as a choice.

    evidence    {dimension name: {"value": ..., "source": ...}}: what a store, a plan or a parent node
                says about a setting. A context given to `value` may hold more under "evidence".
    strategy    the strategy dimension (default `STRATEGY`); `strategies` may name another strategy for
                single dimensions, as data: {dimension name: strategy name}.
    choices     the record: [{"dimension", "value", "why"}], each different choice once, in order.
    """

    def __init__(self, evidence=None, strategy=None, strategies=None, seed=None):
        self.evidence = dict(evidence or {})
        self.strategy = strategy or STRATEGY
        self.strategies = dict(strategies or {})
        self.seed = seed or EXPLORATION_SEED
        self.choices = []
        self._written = set()
        self._generator = None

    def fork(self) -> "Resolver":
        """A new resolver with the same evidence, strategies and seed and an empty record (one run's resolver)."""
        return Resolver(dict(self.evidence), self.strategy, dict(self.strategies), self.seed)

    def add_evidence(self, settings, source):
        """Take every dimension of a stored set of settings as evidence, with the source that is written
        to the record. The first suggested value of such a dimension is what the evidence says."""
        for dimension in settings:
            self.evidence[dimension.name] = {"dimension": dimension, "source": source}
        return self

    def evidence_dimension(self, name):
        """The dimension that the evidence holds under this name, or None."""
        return (self.evidence.get(name) or {}).get("dimension")

    def generator(self):
        if self._generator is None:
            self._generator = random.Random(self._resolve(self.seed, {}, "evidence"))
        return self._generator

    def _write(self, name, value, why):
        key = (name, json.dumps(plain(value), sort_keys=True, default=str), why)
        if key not in self._written:
            self._written.add(key)
            self.choices.append({"dimension": name, "value": plain(value), "why": why})

    def _resolve(self, dimension, context, strategy_name, as_name=None):
        if strategy_name not in STRATEGIES:
            raise KeyError(f"no strategy named {strategy_name!r}; registered: {sorted(STRATEGIES)}")
        value, why = STRATEGIES[strategy_name](dimension, context, self)
        value = plain(value)
        if not dimension.allows(value):
            raise LimitError(f"dimension {dimension.name!r}: the value {value!r} ({why}) is outside the hard limits "
                             f"{dimension.limits}")
        self._write(as_name or dimension.name, value, why)
        return value

    def value(self, dimension, context=None, as_name=None):
        """The value of the dimension in this context. The choice is written to `choices`, under the
        dimension's name or under `as_name` (for one template dimension used for several parts)."""
        context = context or {}
        named = self.strategies.get(dimension.name)
        return self._resolve(dimension, context, named or self._resolve(self.strategy, context, "evidence"), as_name)

    def values(self, dimension, context=None) -> list:
        """Every suggested value, in order, for code that tries each of them (a protocol with several
        caps or budgets). Evidence may name the list under "values". Each one is written as a choice."""
        context = context or {}
        found = (context.get("evidence") or {}).get(dimension.name) or self.evidence.get(dimension.name)
        if found is not None and "values" in found:
            listed, why = [plain(value) for value in found["values"]], _evidence_reason(found, "values")
        else:
            listed, why = list(dimension.suggested), _first_value(dimension)[1] + ", one of the suggested values"
        for position, value in enumerate(listed):
            if not dimension.allows(value):
                raise LimitError(f"dimension {dimension.name!r}: the value {value!r} is outside the hard limits {dimension.limits}")
            self._write(dimension.name, value, f"{why} ({position + 1} of {len(listed)})")
        return listed
