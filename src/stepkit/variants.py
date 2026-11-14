# Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md
"""Variants of library Tasks, and an admission gate for model-written programs that scores them (test 25).

A program that a model writes for one kind of Task is admitted only when it is right on the kind's library Tasks
and silent on the other kinds' library Tasks (test 7b's gate) and, since November 13, 2026, also right on copies of
the library Tasks that each change one thing a program must not depend on. Every family of copies is data
(`FAMILIES`), every setting is a `Dimension` (`SETTINGS`), and every copy is checked by code before it is used; a
copy that fails its check is dropped and counted, never scored.

Families (each copy is made from one Task by code, never by a model):
  renamed_people  every person name replaced by a new name: test 24's `Renamer` and name detector, unchanged
                  (`work-2026-11-12-next-tests/t24-live-fabric/builder.py`, imported by path). Check: the names
                  mapped back give the original text exactly; options and key unchanged.
  more_objects    a tracking Task rebuilt with 5 and with 7 people, objects and swaps, in the wording of the public
                  five- and seven-object files: the Task's people, objects and swaps are kept; each added person
                  (the files' own names Dave, Eve, Fred, Gertrude) starts with an object of the same template taken
                  from the library's own words and takes part in one added swap. Key: the swaps simulated by code.
  bystander       a tracking Task with one added person who takes part in no swap and is the asked person.
  date_forms      every date in a date Task's story written in another form with the same value ("4/19/1969" to
                  "April 19, 1969", "19 April 1969", ...). The question sentence and the options keep their form:
                  the question names the answer form and the runner matches answers to options in that form.
                  Check: every new date read back gives the same value, the old text comes back exactly, and the
                  question sentence and options are byte-equal.
  date_phrases    a fixed table of phrases with the same meaning, used only right before a date ("Yesterday was" to
                  "The day before today was"). Same check, with the dates unchanged.

Why: notes/coordination-2026-11-12/check-t7c.md (a program with its examples' names written in passed the gate),
check-t24-gate.md (renamed copies do not catch a program that reads only three people) and FABRIC.md section 5
("Add": admission must test structural variants, such as bystanders). Plan and results:
notes/work-2026-11-12-next-tests/t25-variant-gate/.

    admitted, record, why = gate(program, "tracking-choice", library, others)
    copies, skipped = make_copies("date_forms", date_library, context_for(library + others))

Programs run in test 7b's locked-down runner (`t7-toolsmith/kind_tool.py`, `sandbox.py`, imported by path).
Python 3 standard library only, plus the files named above.
"""
import calendar
import datetime
import hashlib
import json
import os
import random
import re
from collections import Counter
from dataclasses import dataclass, field
from fractions import Fraction

from . import _sources as S
from .dimension import CHOICES, MULTI, NUMBERS, ORDERED, STRUCTURED, Dimension, Resolver, Settings

T24_BUILDER = os.path.join(S.NEXT_TESTS, "t24-live-fabric", "builder.py")
DATE_KNOWN_FAULTS = os.path.join(S.MIXED_DIR, "data", "bbh_date_understanding", "known-faults-2026-11-13.json")
KIND_TOOL = os.path.join(S.T7_DIR, "kind_tool.py")
TRACKING, DATES, COUNTING = "tracking-choice", "date-choice", "object-counting"

# ---- settings: every value that can change a figure is a Dimension ----
PHRASES = [      # (written once; a test checks that each pair says the same thing about the same date)
    {"from": "Today is ", "to": "The date today is ", "reason": "'today is X' says that the date today is X"},
    {"from": "today is in fact ", "to": "the date today is in fact ", "reason": "the same, with 'in fact'"},
    {"from": "today is ", "to": "the date today is ", "reason": "the same, inside a sentence"},
    {"from": "Yesterday was ", "to": "The day before today was ", "reason": "yesterday is the day before today"},
    {"from": "yesterday was ", "to": "the day before today was ", "reason": "the same, inside a sentence"},
    {"from": "Yesterday, ", "to": "The day before today, ", "reason": "the same, before a date set off by commas"},
    {"from": "Tomorrow is ", "to": "The day after today is ", "reason": "tomorrow is the day after today"},
    {"from": "tomorrow is ", "to": "the day after today is ", "reason": "the same, inside a sentence"},
    {"from": "tomorrow, ", "to": "the day after today, ", "reason": "the same, before a date set off by commas"},
]
DATE_FORMS = ["month_d_y", "d_month_y", "mdy_numeric", "ordinal_of", "mon_d_y"]

SETTINGS = Settings(name="variants", dimensions=[
    Dimension("variants.families", [{TRACKING: ["renamed_people", "more_objects", "bystander"],
                                     DATES: ["renamed_people", "date_forms", "date_phrases"],
                                     COUNTING: ["renamed_people"]}],
              [{TRACKING: ["renamed_people", "more_objects", "bystander"], DATES: ["renamed_people", "date_forms"],
                COUNTING: ["renamed_people"]},
               {TRACKING: ["renamed_people"], DATES: ["renamed_people"], COUNTING: ["renamed_people"]},
               {TRACKING: [], DATES: [], COUNTING: []}], STRUCTURED,
              generator={"text": "for each kind, any list of the names in variants.FAMILIES that apply to that kind"},
              about="the families of copies a program of each kind must also pass; a kind not named has no family"),
    Dimension("variants.share", ["the library gate's share"], ["the library gate's share", 0.8, 0.9, 0.95, 1.0], ORDERED,
              {"min": 0.0, "max": 1.0},
              about="a family's bar: this share of its copies, rounded up; by default the library gate's own share "
                    "(kind_tool.ADMIT of the library size of test 7, 36 of 40)"),
    Dimension("variants.bar_counts", ["right"], ["right", "not wrong"], CHOICES,
              about="what a family's bar counts: right answers (as the library gate and test 24), or answers that are "
                    "not wrong (a silent copy then counts)"),
    Dimension("variants.bar_base", ["every copy"], ["every copy", "copies of originals it gets right"], CHOICES,
              about="what a family's share is taken of: every copy (as planned), or only the copies whose original "
                    "library Task the program gets right, so the bar measures what the change costs and not the "
                    "program's accuracy, which the library gate judges (added after test 25's first record: PLAN.md)"),
    Dimension("variants.run_when", ["library gate passed"], ["library gate passed", "always"], CHOICES,
              about="families run only when the library gate passes (as test 24), or always (a described run)"),
    Dimension("variants.other_kinds_answers", [0], [0, 1, 2, 5], NUMBERS, {"min": 0},
              about="answers of the right form a program may give on the other kinds' Tasks and on their copies"),
    Dimension("variants.rename_rule", ["shuffle-per-task"], ["shuffle-per-task", "written-order"], CHOICES,
              about="how a renamed copy takes its new names from builder.NEW_NAMES (test 24's t24.rename_rule)"),
    Dimension("variants.rename_seed", [20261112], [20261112, 20261113, 20261114], CHOICES,
              about="the seed of the rename shuffle (test 24's t24.rename_seed)"),
    Dimension("variants.more_objects_sizes", [[5, 7]], [[5, 7], [5], [7], [4, 5, 6, 7]], CHOICES,
              about="the numbers of people of the more_objects copies: those of the public five- and seven-object files"),
    Dimension("variants.added_names", [["Dave", "Eve", "Fred", "Gertrude"]],
              [["Dave", "Eve", "Fred", "Gertrude"], ["Dave", "Eve", "Fred", "Gertrude", "Harry", "Irene"]], CHOICES,
              about="the names of added people, in order: the public five- and seven-object files' own"),
    Dimension("variants.swap_seed", [20261113], [20261113, 20261114, 20261115], CHOICES,
              about="the seed of the added objects, swap partners and swap places of more_objects and bystander copies"),
    Dimension("variants.date_forms", [DATE_FORMS], DATE_FORMS + ["iso"], MULTI,
              about="the forms a date may be written in by a date_forms copy (iso: year-month-day with dashes)"),
    Dimension("variants.date_form_rule", ["shuffle-per-task"], ["shuffle-per-task", "listed-order"], CHOICES,
              about="which form a Task's dates take: the first, in a seeded order for the Task or in the listed order, "
                    "that differs from every date's own form and text"),
    Dimension("variants.date_form_seed", [20261113], [20261113, 20261114, 20261115], CHOICES,
              about="the seed of the date form order"),
    Dimension("variants.listed_ids", [10], [5, 10, 50], NUMBERS, {"min": 0},
              about="how many ids of wrong and of silent copies a record lists for each set (a record's length only)"),
    Dimension("variants.exclude_known_faults", [[]], [[], [DATE_KNOWN_FAULTS]], CHOICES,
              about="known-faults files whose listed Tasks the kit gate leaves out of the library of their kind and out of "
                    "the copies made from it (a listed Task among the other kinds stays: a silence check reads no key); "
                    "[] leaves nothing out, the default, so test 24's gate is unchanged (added at the coordinator's "
                    "request on November 13; the date file lists Task date-choice:180, whose key is wrong)"),
    Dimension("variants.date_phrases", [PHRASES], kind=STRUCTURED,
              generator={"text": "any list of {from, to, reason}: two phrases with the same meaning before a date"},
              about="the phrase pairs of date_phrases copies, used only right before a date"),
])


def setting(name, resolver=None):
    """The value of one setting, through a resolver (which writes the choice and its reason)."""
    return (resolver or Resolver()).value(SETTINGS[name])


# ---- shared parts ----

def _load(name, path):
    return S.load_by_path(name, path)


def builder():
    """Test 24's builder module (its name detector, `Renamer` and `NEW_NAMES`), imported by path, unchanged."""
    return _load("t24_builder", T24_BUILDER)


def kind_tool():
    """Test 7b's module: `score_on` (the locked-down runner on a list of Tasks), `ADMIT`, `sandbox`."""
    return _load("t7_kind_tool", KIND_TOOL)


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path):
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def words_of(texts):
    return {word.lower() for text in texts for word in re.findall(r"[A-Za-z]+", text)}


OPTION_LINE = re.compile(r"^\s*\(([A-Z])\)\s*(.+?)\s*$", re.M)      # toolsmith's option rule


def split_options(question):
    """(text before the options, the options part with its line break, or "")."""
    at = question.find("\nOptions:")
    return (question, "") if at < 0 else (question[:at], question[at:])


# ---- tracking Tasks: read, write, simulate ----

LEADS = ("First", "Then", "Finally")      # the words that start the swap sentences of the files
SWAP_SENTENCE = re.compile(r"(?:First|Then|Finally), (?P<a>[A-Z][a-z]+) and (?P<b>[A-Z][a-z]+)(?P<tail>.+)")


@dataclass
class Tracking:
    """A tracking Task in the wording of the public three-, five- and seven-object files."""
    people: list
    objects: list
    swaps: list
    asked: str
    intro: str        # " are playing a game. At the start of the game, they are each holding a ball: "
    give: str         # " has a "
    progress: str     # "\nAs the game progresses, pairs of players trade balls. "
    swap_tail: str    # " swap balls"
    end_head: str     # "At the end of the game, "
    end_tail: str     # " has the"

    def render(self):
        names = ", ".join(self.people[:-1]) + ", and " + self.people[-1]
        setup = ", ".join(p + self.give + o for p, o in zip(self.people[:-1], self.objects[:-1]))
        setup += ", and " + self.people[-1] + self.give + self.objects[-1] + "."
        first, then, last = LEADS
        leads = [first] + [then] * (len(self.swaps) - len(LEADS) + 1) + [last]
        moves = " ".join(f"{lead}, {a} and {b}{self.swap_tail}." for lead, (a, b) in zip(leads, self.swaps))
        letters = [chr(ord("A") + i) for i in range(len(self.objects))]
        options = "\n".join(f"({letter}) {o}" for letter, o in zip(letters, self.objects))
        return (names + self.intro + setup + self.progress + moves + " " + self.end_head + self.asked + self.end_tail
                + "\nOptions:\n" + options)

    def final(self):
        """{person: object at the end}, by simulating the swaps."""
        holds = dict(zip(self.people, self.objects))
        for a, b in self.swaps:
            holds[a], holds[b] = holds[b], holds[a]
        return holds

    def key(self):
        """The answer key: the letter of the asked person's object at the end."""
        return "(" + chr(ord("A") + self.objects.index(self.final()[self.asked])) + ")"

    def template(self):
        return self.intro


def read_tracking(question):
    """The Tracking of a Task, or None when its wording is not the files' wording (checked: writing the Tracking back
    must give the Task's text exactly)."""
    body, opts = split_options(question)
    options = [text for _, text in OPTION_LINE.findall(opts)]
    if "\n" not in body or " are " not in body or not options:
        return None
    first, second = body.split("\n", 1)
    names, rest = first.split(" are ", 1)
    people = names.replace(", and ", ", ").split(", ")
    if len(people) != len(options) or not all(re.fullmatch(r"[A-Z][a-z]+", p) for p in people):
        return None
    colon = rest.find(": ")
    if colon < 0:
        return None
    cut = colon + len(": ")
    intro, setup = " are " + rest[:cut], rest[cut:]
    at = setup.find(options[0], len(people[0]))
    if not setup.startswith(people[0]) or at < 0:
        return None
    give = setup[len(people[0]):at]
    lead = second.find("First, ")
    end_at = second.rfind(". ")
    if lead < 0 or end_at < lead:
        return None
    progress, moves, end = "\n" + second[:lead], second[lead:end_at + 1], second[end_at + len(". "):]
    swaps, tail = [], None
    for sentence in moves[:-1].split(". "):
        m = SWAP_SENTENCE.fullmatch(sentence)
        if m is None or m["a"] not in people or m["b"] not in people or tail not in (None, m["tail"]):
            return None
        swaps.append((m["a"], m["b"]))
        tail = m["tail"]
    asked = [p for p in people if re.search(rf"\b{p}\b", end)]
    if len(asked) != 1 or len(swaps) < len(LEADS) - 1:
        return None
    head, _, end_tail = end.partition(asked[0])
    t = Tracking(people, options, swaps, asked[0], intro, give, progress, tail, head, end_tail)
    return t if t.render() == question else None


def tracking_pools(tasks):
    """{template: the objects of that template in the given Tasks, in order of first use}: added objects come only
    from the library's own words."""
    pools = {}
    for task in tasks:
        t = read_tracking(task["question"]) if task.get("kind", TRACKING) == TRACKING else None
        if t is not None:
            pool = pools.setdefault(t.template(), [])
            pool.extend(o for o in t.objects if o not in pool)
    return pools


def _rng(seed, *parts):
    return random.Random(":".join(str(part) for part in (seed,) + parts))     # a string seed hashes the same every run


def more_objects_copy(task, size, pools, names, seed, family="more_objects"):
    """(the copy with `size` people, None) or (None, why). Each added person starts with an object of the same
    template that the Task does not use and takes part in one added swap, with a partner and at a place drawn by the
    seeded rule; the asked person is the Task's. Key by simulation."""
    t = read_tracking(task["question"])
    if t is None:
        return None, "not in the tracking files' wording"
    if size <= len(t.people):
        return None, f"already has {len(t.people)} people"
    rng = _rng(seed, task["id"], family, size)
    added = [n for n in names if n not in t.people][:size - len(t.people)]
    free = [o for o in pools.get(t.template(), []) if o not in t.objects]
    if len(added) < size - len(t.people) or len(free) < len(added):
        return None, "too few added names or library objects of this template"
    objects = rng.sample(free, len(added))
    people, swaps = t.people + added, list(t.swaps)
    for person in added:
        partner = rng.choice([p for p in people if p != person])
        pair = rng.choice([(person, partner), (partner, person)])
        swaps.insert(rng.randrange(len(swaps) + 1), pair)
    c = Tracking(people, t.objects + objects, swaps, t.asked, t.intro, t.give, t.progress, t.swap_tail, t.end_head,
                 t.end_tail)
    return _tracking_copy(task, c, family, f"{size}", {"added_people": added, "added_objects": objects,
                                                        "asked_in_a_swap": any(c.asked in s for s in c.swaps)})


def bystander_copy(task, pools, names, seed):
    """(the copy, None) or (None, why): one added person with an object of the same template, in no swap, asked."""
    t = read_tracking(task["question"])
    if t is None:
        return None, "not in the tracking files' wording"
    added = [n for n in names if n not in t.people][:1]
    free = [o for o in pools.get(t.template(), []) if o not in t.objects]
    if not added or not free:
        return None, "no added name or library object of this template left"
    obj = _rng(seed, task["id"], "bystander").choice(free)
    c = Tracking(t.people + added, t.objects + [obj], list(t.swaps), added[0], t.intro, t.give, t.progress, t.swap_tail,
                 t.end_head, t.end_tail)
    return _tracking_copy(task, c, "bystander", "", {"added_people": added, "added_objects": [obj],
                                                      "asked_in_a_swap": False})


def _tracking_copy(task, c, family, tag, detail):
    text = c.render()
    back = read_tracking(text)
    if back is None or back.key() != c.key():          # the copy reads back as itself (no hidden change)
        return None, "failed its check: the copy does not read back"
    copy = dict(task, id=f"{task['id']}#{family}{tag}", question=text, gold=c.key(),
                variant=dict(detail, family=family, people=len(c.people), swaps=len(c.swaps), key_by="simulation"))
    return copy, None


# ---- dates: find every date in a story, write it in another form, read it back ----

MONTHS = "January February March April May June July August September October November December".split()
MONTH_ABBR = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
MONTH_OF = {**{name.lower(): i for i, name in enumerate(MONTHS, 1)}, **{a.lower(): i for i, a in enumerate(MONTH_ABBR, 1)},
            "sept": MONTHS.index("September") + 1}
ORDINAL_SUFFIX = ("st nd rd th th th th th th th th th th th th th th th th th st nd rd th th th th th th th st").split()
_MON = "|".join(sorted(MONTHS + MONTH_ABBR + ["Sept"], key=len, reverse=True))
_DATE_PATTERNS = [       # (form, kind, pattern), tried in this order; a later match may not overlap an earlier one
    ("iso", "ymd", r"(?<![\d-])(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})(?![\d-])"),
    ("mdy_numeric", "ymd", r"(?<![\d/.])(?P<m>\d{1,2})/(?P<d>\d{1,2})/(?P<y>\d{4})(?![\d/])"),
    ("month_name_first", "ymd", rf"\b(?P<mon>{_MON})(?P<dot>\.)?\s(?P<d>\d{{1,2}})(?P<suf>st|nd|rd|th)?,?\s(?P<y>\d{{4}})\b"),
    ("day_first", "ymd", rf"\b(?P<the>the\s)?(?P<d>\d{{1,2}})(?P<suf>st|nd|rd|th)?\s(?P<of>of\s)?(?P<mon>{_MON})\b(?P<dot>\.)?,?\s(?P<y>\d{{4}})\b"),
    ("mdy_numeric", "md", r"(?<![\d/.:])(?P<m>\d{1,2})/(?P<d>\d{1,2})(?=[.,;:!?)](?!\d)|$)"),   # ends a phrase: not "1/2 of"
    ("month_name_first", "md", rf"\b(?P<mon>{_MON})(?P<dot>\.)?\s(?P<d>\d{{1,2}})(?P<suf>st|nd|rd|th)?\b(?![\d/])"),
    ("day_first", "md", rf"\b(?P<the>the\s)?(?P<d>\d{{1,2}})(?P<suf>st|nd|rd|th)?\s(?P<of>of\s)?(?P<mon>{_MON})\b(?P<dot>\.)?"),
    ("month_year", "ym", rf"\b(?P<mon>{_MON})(?P<dot>\.)?\s(?P<y>\d{{4}})\b"),
]
_DATE_RES = [(form, kind, re.compile(pattern)) for form, kind, pattern in _DATE_PATTERNS]
OWN_ORDER = re.compile(r"day before the month|dd/mm|month after the day", re.I)    # a Task that sets its own order


@dataclass
class DateMention:
    start: int
    end: int
    kind: str            # "ymd", "md" (no year) or "ym" (month and year)
    value: tuple         # (year, month, day), (month, day) or (year, month)
    form: str            # one of DATE_FORMS, "iso", "month_year_full" or "month_year_abbr"
    text: str
    extra: dict = field(default_factory=dict)


def _form_of(form, kind, groups):
    if form == "month_name_first":
        mon = groups["mon"]
        return "month_d_y" if mon in MONTHS else "mon_d_y"
    if form == "day_first":
        return "ordinal_of" if groups.get("of") else "d_month_y"
    if form == "month_year":
        return "month_year_full" if groups["mon"] in MONTHS else "month_year_abbr"
    return form


def _valid(kind, value):
    try:
        if kind == "ymd":
            datetime.date(*value)
        elif kind == "md":
            month, day = value
            if not (1 <= month < len(calendar.month_name) and 1 <= day <= calendar.mdays[month]):
                return False
        else:
            datetime.date(value[0], value[1], 1)
    except (ValueError, TypeError, IndexError):
        return False
    return True


def date_mentions(story):
    """Every date of a story, read strictly: [DateMention], in order. Not a date: a month alone, an impossible date
    (left as written), a number without a month."""
    taken, found = [], []
    for form, kind, pattern in _DATE_RES:
        for m in pattern.finditer(story):
            start, end = m.span()
            g = m.groupdict()
            if g.get("the") and not g.get("of"):          # "the" belongs to a date only in "the 1st of May"
                start += len(g["the"])
            if any(start < b and a < end for a, b in taken):
                continue
            month = int(g["m"]) if g.get("m") else MONTH_OF.get((g.get("mon") or "").lower())
            value = {"ymd": (int(g["y"]) if g.get("y") else 0, month, int(g["d"]) if g.get("d") else 0),
                     "md": (month, int(g["d"]) if g.get("d") else 0),
                     "ym": (int(g["y"]) if g.get("y") else 0, month)}[kind]
            if not _valid(kind, value):
                continue
            taken.append((start, end))
            found.append(DateMention(start, end, kind, value, _form_of(form, kind, g), story[start:end],
                                     {"dot": bool(g.get("dot")), "suffix": bool(g.get("suf"))}))
    return sorted(found, key=lambda mention: mention.start)


def write_date(mention, form):
    """A mention's value written in a form. A date without a year has no year-month-day form: it takes month_d_y."""
    if mention.kind == "ym":
        year, month = mention.value
        return f"{MONTH_ABBR[month - 1] if form == 'month_year_abbr' else MONTHS[month - 1]} {year}"
    if mention.kind == "md":
        month, day = mention.value
        form = "month_d_y" if form == "iso" else form
        return {"month_d_y": f"{MONTHS[month - 1]} {day}", "d_month_y": f"{day} {MONTHS[month - 1]}",
                "mdy_numeric": f"{month}/{day}", "mon_d_y": f"{MONTH_ABBR[month - 1]} {day}",
                "ordinal_of": f"the {day}{ORDINAL_SUFFIX[day - 1]} of {MONTHS[month - 1]}"}[form]
    year, month, day = mention.value
    return {"month_d_y": f"{MONTHS[month - 1]} {day}, {year}", "d_month_y": f"{day} {MONTHS[month - 1]} {year}",
            "mdy_numeric": f"{month}/{day}/{year}", "mon_d_y": f"{MONTH_ABBR[month - 1]} {day}, {year}",
            "ordinal_of": f"the {day}{ORDINAL_SUFFIX[day - 1]} of {MONTHS[month - 1]}, {year}",
            "iso": f"{year:04d}-{month:02d}-{day:02d}"}[form]


def story_of(question):
    """(story, rest): the story is the text before the question sentence ("What is the date ..."; else the last
    sentence that ends with a question mark); rest is the question sentence and the options, never changed."""
    body, _ = split_options(question)
    at = body.rfind("What is the date")
    if at < 0:
        mark = body.rfind("?")
        if mark < 0:
            return question, ""
        stop = body.rfind(". ", 0, mark)
        line = body.rfind("\n", 0, mark)
        at = stop + len(". ") if stop > line else (line + len("\n") if line >= 0 else 0)
    return question[:at], question[at:]


def _apply(text, changes):
    """Replace (start, end, new) spans, right to left. Returns the new text and each change's new span."""
    out, spans = text, []
    for start, end, new in sorted(changes, reverse=True):
        out = out[:start] + new + out[end:]
    shift = 0
    for start, end, new in sorted(changes):
        spans.append((start + shift, start + shift + len(new)))
        shift += len(new) - (end - start)
    return out, spans


def _check_date_copy(task, story, rest, new_story, spans, olds):
    """The checks every date copy must pass: the old text comes back exactly, the story's dates read back with the
    same values in the same order, the question sentence and options are byte-equal."""
    back, _ = _apply(new_story, [(a, b, old) for (a, b), old in zip(spans, olds)])
    before = [(m.kind, m.value) for m in date_mentions(story)]
    after = [(m.kind, m.value) for m in date_mentions(new_story)]
    problems = []
    if back != story:
        problems.append("the old text does not come back")
    if before != after:
        problems.append("the dates do not read back with the same values")
    if (new_story + rest)[len(new_story):] != task["question"][len(story):]:
        problems.append("the question sentence or options changed")
    return problems


def date_forms_copy(task, forms, rule, seed):
    """(the copy, None) or (None, why): every date of the story in one form that differs from each date's own form
    and text. Dates of a Task that sets its own numeric order keep their form only when they are numbers."""
    story, rest = story_of(task["question"])
    mentions = date_mentions(story)
    own_order = bool(OWN_ORDER.search(story))
    if own_order:
        mentions = [m for m in mentions if m.form != "mdy_numeric"]
    days = [m for m in mentions if m.kind != "ym"]
    if not days and not mentions:
        return None, "no date in the story" + (" that is not a number in the Task's own order" if own_order else "")
    order = list(forms)
    if rule == "shuffle-per-task":
        _rng(seed, task["id"], "date_forms").shuffle(order)
    elif rule != "listed-order":
        raise ValueError(f"unknown date form rule {rule!r}")
    target = next((f for f in order if all(f != m.form and write_date(m, f) != m.text for m in days)), None)
    if days and target is None:
        return None, "no other form for every date of the story"
    changes = []
    for m in mentions:
        if m.kind == "ym":
            new = write_date(m, "month_year_abbr" if m.form == "month_year_full" else "month_year_full")
        else:
            new = write_date(m, target)
        if new != m.text:
            changes.append((m.start, m.end, new))
    if not changes:
        return None, "no date of the story can be written another way"
    new_story, spans = _apply(story, changes)
    olds = [story[a:b] for a, b, _ in sorted(changes)]
    problems = _check_date_copy(task, story, rest, new_story, spans, olds)
    if problems:
        return None, "failed its check: " + "; ".join(problems)
    rewrites = [{"old": old, "new": new_story[a:b]} for old, (a, b) in zip(olds, spans)]
    return dict(task, id=f"{task['id']}#date_forms", question=new_story + rest,
                variant={"family": "date_forms", "form": target, "rewrites": rewrites,
                         "kept_as_numbers_in_own_order": own_order}), None


def date_phrases_copy(task, phrases):
    """(the copy, None) or (None, why): each phrase of the table that stands right before a date of the story (and
    starts a word) replaced by its pair; the longest phrase wins at one place."""
    story, rest = story_of(task["question"])
    starts = {m.start for m in date_mentions(story)}
    changes, used = [], []
    for phrase in sorted(phrases, key=lambda p: len(p["from"]), reverse=True):
        for m in re.finditer(re.escape(phrase["from"]), story):
            a, b = m.span()
            if b in starts and (a == 0 or not story[a - 1].isalnum()) and not any(a < y and x < b for x, y, _ in changes):
                changes.append((a, b, phrase["to"]))
                used.append(phrase["from"])
    if not changes:
        return None, "no phrase of the table right before a date"
    new_story, spans = _apply(story, changes)
    olds = [story[a:b] for a, b, _ in sorted(changes)]
    problems = _check_date_copy(task, story, rest, new_story, spans, olds)
    if problems:
        return None, "failed its check: " + "; ".join(problems)
    rewrites = [{"old": old, "new": new_story[a:b]} for old, (a, b) in zip(olds, spans)]
    return dict(task, id=f"{task['id']}#date_phrases", question=new_story + rest,
                variant={"family": "date_phrases", "rewrites": rewrites}), None


# ---- renamed people: test 24's renamer, unchanged ----

def renamed_copy(task, renamer):
    """(the copy, None) or (None, why), by test 24's `Renamer.variant`; checked here: the names mapped back give the
    original text exactly, and options and key are unchanged."""
    copy, why = renamer.variant(task)
    if copy is None:
        return None, why
    back = copy["question"]
    for old, new in copy["renamed"].items():
        back = re.sub(rf"\b{new}\b", old, back)
    if back != task["question"] or copy["gold"] != task["gold"]:
        return None, "failed its check: the names do not map back"
    return dict(copy, id=f"{task['id']}#renamed_people", variant={"family": "renamed_people", "renamed": copy["renamed"]}), None


# ---- the families, as data ----

@dataclass
class Family:
    name: str
    kinds: tuple          # the kinds whose Tasks it copies; ("any",) for every kind
    about: str
    make: object          # make(task, context) -> ([copies], [why each copy that could not be made was not])

    def applies(self, task):
        return "any" in self.kinds or task.get("kind") in self.kinds


class Context:
    """What the makers share for one gate: the settings (through a resolver), the renamer (its new names may occur in
    none of the Tasks given), the tracking object pools (the library's own words)."""

    def __init__(self, tasks, resolver=None, renamer=None, extra_texts=()):
        self.resolver = resolver or Resolver()
        self.tasks = list(tasks)
        self._renamer, self.extra_texts = renamer, list(extra_texts)
        self.pools = tracking_pools(self.tasks)

    def value(self, name):
        return self.resolver.value(SETTINGS[name])

    def renamer(self):
        if self._renamer is None:
            B = builder()
            taken = words_of([t["question"] for t in self.tasks] + self.extra_texts)
            pool = [name for name in B.NEW_NAMES if name.lower() not in taken]
            self._renamer = B.Renamer(pool, self.value("variants.rename_rule"), self.value("variants.rename_seed"),
                                      left_out=[name for name in B.NEW_NAMES if name not in pool])
        return self._renamer


def context_for(tasks, resolver=None, renamer=None, extra_texts=()):
    return Context(tasks, resolver, renamer, extra_texts)


def _one(made):
    copy, why = made
    return ([copy], []) if copy is not None else ([], [why])


def _make_more(task, ctx):
    out, whys = [], []
    for size in ctx.value("variants.more_objects_sizes"):
        copies, reasons = _one(more_objects_copy(task, size, ctx.pools, ctx.value("variants.added_names"),
                                                 ctx.value("variants.swap_seed")))
        out += copies
        whys += reasons
    return out, whys


FAMILIES = {f.name: f for f in [
    Family("renamed_people", ("any",), "every person name replaced by a new name (test 24's Renamer)",
           lambda task, ctx: _one(renamed_copy(task, ctx.renamer()))),
    Family("more_objects", (TRACKING,), "the tracking Task with 5 and with 7 people, objects and swaps; key by simulation",
           _make_more),
    Family("bystander", (TRACKING,), "one added person in no swap is the asked person; key by simulation",
           lambda task, ctx: _one(bystander_copy(task, ctx.pools, ctx.value("variants.added_names"),
                                                 ctx.value("variants.swap_seed")))),
    Family("date_forms", (DATES,), "every date of the story written in another form with the same value",
           lambda task, ctx: _one(date_forms_copy(task, ctx.value("variants.date_forms"),
                                                  ctx.value("variants.date_form_rule"), ctx.value("variants.date_form_seed")))),
    Family("date_phrases", (DATES,), "phrases right before a date replaced by phrases with the same meaning",
           lambda task, ctx: _one(date_phrases_copy(task, ctx.value("variants.date_phrases")))),
]}


def make_copies(family, tasks, ctx):
    """(copies, skipped): the family's copies of the Tasks it applies to, and {why: count} for the others (a Task of
    a kind the family does not copy is counted under "not a kind this family copies")."""
    fam, copies, skipped = FAMILIES[family], [], Counter()
    for task in tasks:
        if not fam.applies(task):
            skipped["not a kind this family copies"] += 1
            continue
        made, whys = fam.make(task, ctx)
        copies += made
        for why in whys:
            skipped[why] += 1
    return copies, dict(skipped)


# ---- the gate ----

def _share(ctx, kt):
    value = ctx.value("variants.share")
    return Fraction(kt.ADMIT, S.N_LIBRARY) if value == "the library gate's share" else Fraction(str(value))


def _bar(share, n):
    return -(-share.numerator * n // share.denominator)          # share of n, rounded up, in whole numbers


def _score(runner, program, tasks, listed):
    """Scores in the runner. "right_ids" lists every right Task (for the paired bar; a record drops it)."""
    if not tasks:
        return {"tasks": 0, "right": 0, "answered": 0, "wrong": 0, "wrong_ids": [], "silent_ids": [], "right_ids": []}
    n_form, n_right, rows = runner(program, tasks)
    return {"tasks": len(tasks), "right": n_right, "answered": n_form, "wrong": n_form - n_right,
            "wrong_ids": [r["item"] for r in rows if r["form_ok"] and not r["correct"]][:listed],
            "silent_ids": [r["item"] for r in rows if not r["form_ok"]][:listed],
            "right_ids": [r["item"] for r in rows if r["correct"]], "wrong_all": [r["item"] for r in rows if r["form_ok"] and not r["correct"]]}


def _public(score):
    return {key: value for key, value in score.items() if key not in ("right_ids", "wrong_all")}


def original_id(copy):
    return copy["id"].split("#")[0]


def family_check(program, family, library, others, ctx, runner=None, library_right_ids=None, run_it=True):
    """One family's bar for a program. The copies of the kind's library Tasks: at least the share
    (`variants.share`) of them right, or not wrong (`variants.bar_counts`), counted over every copy or, with
    `variants.bar_base` = "copies of originals it gets right", over the copies whose original library Task the program
    gets right (`library_right_ids`): then the bar measures only what the change costs. The copies of the other kinds'
    Tasks: at most `variants.other_kinds_answers` answers of the right form. Returns the record entry; a family with no
    copy of the kind's Tasks does not apply and keeps the gate as it was."""
    kt = kind_tool()
    runner = runner or kt.score_on
    share, allowed = _share(ctx, kt), ctx.value("variants.other_kinds_answers")
    counts, base, listed = ctx.value("variants.bar_counts"), ctx.value("variants.bar_base"), ctx.value("variants.listed_ids")
    made, skipped = make_copies(family, library, ctx)
    other_made, other_skipped = make_copies(family, others, ctx)
    entry = {"copies": len(made), "skipped": skipped, "other_kinds_copies": len(other_made), "other_kinds_skipped": other_skipped,
             "failed_check": sum(n for why, n in list(skipped.items()) + list(other_skipped.items()) if why.startswith("failed its check"))}
    if not made:
        return dict(entry, applies=False, ran=False, passed=True,
                    why=f"no {family} copy of the {len(library)} library Tasks: the gate is as it was")
    if not run_it:
        return dict(entry, applies=True, ran=False, passed=None, why="not run: the library gate refused the program first")
    own = _score(runner, program, made, listed)
    oth = _score(runner, program, other_made, listed)
    right_originals = set(library_right_ids or [])
    bases = {"every copy": made, "copies of originals it gets right": [c for c in made if original_id(c) in right_originals]}
    if base not in bases:
        raise ValueError(f"unknown bar base {base!r}")
    figures = {}
    for name, counted in bases.items():            # both bases are written; the setting chooses the one that decides
        ids = {c["id"] for c in counted}
        right, wrong = set(own["right_ids"]) & ids, set(own["wrong_all"]) & ids
        count = len(right) if counts == "right" else len(ids) - len(wrong)
        need = _bar(share, len(counted))
        figures[name] = {"copies": len(counted), "count": count, "bar": need,
                         "passed": bool(count >= need and oth["answered"] <= allowed)}
    chosen = figures[base]
    return dict(entry, applies=True, ran=True, counted=counts, base=base, base_copies=chosen["copies"], count=chosen["count"],
                bar=chosen["bar"], own=_public(own), other_kinds=_public(oth), passed=chosen["passed"], bases=figures,
                example={"task": made[0]["id"], "variant": made[0].get("variant")},
                why=f"{counts} on {chosen['count']} of {chosen['copies']} copies (bar {chosen['bar']}; base: {base}); answers "
                    f"of the right form on {oth['answered']} of {len(other_made)} copies of the other kinds (bar {allowed})")


def gate(program, kind, library, others, runner=None, resolver=None, renamer=None, extra_texts=(), ctx=None):
    """Test 7b's gate, then every family of `variants.families` for the kind (`family_check`). Returns (admitted,
    record, why).

    library    the kind's library Tasks; others: the other kinds' library Tasks
    runner     score_on(program, tasks) -> (answered in the right form, right, rows); default test 7b's runner
    renamer    a ready Renamer (test 24 passes its own); default one whose new names occur in no Task given
    """
    kt = kind_tool()
    runner = runner or kt.score_on
    ctx = ctx or Context(list(library) + list(others), resolver, renamer, extra_texts)
    allowed, listed = ctx.value("variants.other_kinds_answers"), ctx.value("variants.listed_ids")
    fault_files = ctx.value("variants.exclude_known_faults")
    faults = known_fault_ids(fault_files) if fault_files else set()
    left_out = [task["id"] for task in library if task["id"] in faults]
    library = [task for task in library if task["id"] not in faults]
    problem = kt.sandbox.check_program(program)
    lib = _score(runner, program, library if problem is None else [], listed)
    oth = _score(runner, program, others if problem is None else [], listed)
    lib_bar = _bar(Fraction(kt.ADMIT, S.N_LIBRARY), len(library))     # test 7b's own bar: 36 of 40
    lib_ok = bool(problem is None and lib["right"] >= lib_bar and oth["answered"] <= allowed)
    record = {"kind": kind, "program_sha256": sha256_text(program), "check_problem": problem,
              "library": dict(_public(lib), bar=lib_bar, passed=bool(problem is None and lib["right"] >= lib_bar)),
              "other_kinds": dict(_public(oth), bar=allowed, passed=oth["answered"] <= allowed), "families": {}}
    if fault_files:
        record["known_faults"] = {"files": [{"path": path, "sha256": sha256_file(path)} for path in fault_files],
                                  "left_out_of_the_library": left_out}
    families = (ctx.value("variants.families") or {}).get(kind, [])
    run_all = ctx.value("variants.run_when") == "always"
    admitted, refused_by = lib_ok, [] if lib_ok else ["library gate"]
    for name in families:
        entry = family_check(program, name, library, others, ctx, runner, lib["right_ids"],
                             run_it=problem is None and (lib_ok or run_all))
        if entry["applies"] and entry["passed"] is False:
            admitted = False
            refused_by.append(name)
        record["families"][name] = entry
    record.update(admitted=bool(admitted), refused_by=refused_by, choices=list(ctx.resolver.choices),
                  files={"builder.py": sha256_file(T24_BUILDER), "kind_tool.py": sha256_file(KIND_TOOL),
                         "sandbox.py": sha256_file(os.path.join(S.T7_DIR, "sandbox.py"))})
    if admitted:
        why = (f"right on at least {lib_bar} of {len(library)} library Tasks, silent on the other kinds, and on the bar of "
               f"every family ({', '.join(families) or 'none'})")
    else:
        why = "refused by " + ", ".join(refused_by)
    return bool(admitted), record, why


def known_fault_ids(paths):
    """The Task ids listed in known-faults files ({"faults": [{"task_id": ...}, ...]}), as a set."""
    ids = set()
    for path in paths:
        with open(path, encoding="utf-8") as handle:
            ids.update(fault["task_id"] for fault in json.load(handle)["faults"])
    return ids


def describe():
    """The families and settings, as plain data for a record."""
    return {"families": {name: {"kinds": list(f.kinds), "about": f.about} for name, f in FAMILIES.items()},
            "settings": SETTINGS.to_dict()}


__all__ = ["SETTINGS", "FAMILIES", "PHRASES", "DATE_FORMS", "Tracking", "read_tracking", "tracking_pools",
           "more_objects_copy", "bystander_copy", "date_mentions", "write_date", "story_of", "date_forms_copy",
           "date_phrases_copy", "renamed_copy", "Context", "context_for", "make_copies", "family_check", "gate",
           "describe", "original_id", "known_fault_ids", "DATE_KNOWN_FAULTS"]
