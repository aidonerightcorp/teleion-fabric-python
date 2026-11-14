# Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md
"""Profiles: cheap measurements of a step's input and of its output. No model, no network.

Before a step, `text_profile` measures the real input, so a decider can pick the node from it.
After a step, `output_profile` puts the output into the answer form of the question and says whether
that worked, `agreement` compares the answers of several ways, and `grounded_numbers` checks that a
calculation uses only numbers from the problem or from earlier values.

Copied logic, behaviour kept identical. Sources (under the notes folder):
  work-2026-11-10-node-sizer/mixed/fingerprint.py        profile_of (the "profile" level): shape measurements
  work-2026-11-10-node-sizer/mixed/bench_mixed.py        answer_kind (lettered options want a letter)
  work-2026-11-12-next-tests/t7-toolsmith/toolsmith.py   to_final (here: output_profile)
  work-2026-11-12-next-tests/t3-lazy-split/lazy_split.py numbers_in_text, literals, and the number check
                                                         of parse_and_check (here: grounded_numbers)
  work-2026-11-10-node-sizer/mixed/chooser.py            same_answer (the equality used by agreement)
Python 3 standard library, and numpy for one function of `shape_vector` (the same logarithm as the source).
"""
import ast
import math
import re

import numpy as np

from ._answers import OPTION_A, answer_kind, parse_answer, plain_value, right, same, same_answer, to_number
from .tools.calculator import is_arithmetic
from .tools.options import PLAIN_NUMBER, match

__all__ = ["text_profile", "answer_form", "question_word", "shape_vector", "PROFILE_NAMES", "output_profile",
           "agreement", "grounded_numbers", "numbers_in_text", "literals", "unfamiliar",
           # the benchmark's own reading and scoring of answers (defined in _answers.py)
           "answer_kind", "parse_answer", "right", "same", "same_answer", "to_number"]

# ---------------------------------------------------------------------------
# 1. The profile of an input text
# ---------------------------------------------------------------------------

NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
_WORD = re.compile(r"[A-Za-z']+")
_OPTION_LINE = re.compile(r"\n\s*\([A-Z]\)")
_SENTENCE_END = re.compile(r"[.?!](?:\s|$)")
_SENTENCE_SPLIT = re.compile(r"(?<=[.?!])\s+")
_COUNT_CUE = re.compile(r"\bhow\s+(many|much|long|far|old|tall|fast|often|big|heavy|wide|high|deep)\b", re.I)
_QUESTION_WORD = re.compile(r"\b(what|which|who|whom|whose|when|where|why|how)\b", re.I)
_LEADING_QUESTION_WORD = re.compile(r"\s*(what|which|who|whom|whose|when|where|why|how)\b", re.I)
_DIGIT = re.compile(r"\d")
# Question words that ask for a name, a place or a reason, never for a number.
_TEXT_WORDS = frozenset(["who", "whom", "whose", "where", "why"])

# The 13 shape measurements of the source's "profile" level, in the source's order (see shape_vector).
PROFILE_NAMES = ["log_words", "numbers", "distinct_numbers", "digit_share", "operator_share", "options", "lines",
                 "sentences", "commas", "capital_words", "word_length", "ends_with_equals", "question_mark"]


def question_word(text):
    """The question word of the last sentence that ends with a question mark, in lower case.

    A counting cue wins over any other word in that sentence: "how many", "how much", "how long",
    "how far", "how old" and so on. Else the first of what, which, who, whom, whose, when, where, why,
    how. A text with no question mark counts only when it starts with a question word. None when
    there is no question word.
    """
    if "?" not in text:
        lead = _LEADING_QUESTION_WORD.match(text)
        if not lead:
            return None
        cue = _COUNT_CUE.match(text.lstrip())
        return ("how " + cue.group(1).lower()) if cue else lead.group(1).lower()
    asked = [part for part in _SENTENCE_SPLIT.split(text) if "?" in part]
    last = asked[-1] if asked else text
    cue = _COUNT_CUE.search(last)
    if cue:
        return "how " + cue.group(1).lower()
    word = _QUESTION_WORD.search(last)
    return word.group(1).lower() if word else None


def _has_table(text):
    """True when at least two lines look like table rows (cells divided by | or by tabs)."""
    if "|" not in text and "\t" not in text:
        return False
    return sum(1 for line in text.split("\n") if "|" in line or "\t" in line) >= 2


def _form(text, arithmetic, qword):
    if OPTION_A.search(text):
        return "choice"
    if arithmetic or (qword is not None and qword.startswith("how ")):
        return "number"
    if qword in _TEXT_WORDS:
        return "text"
    return "number" if _DIGIT.search(text) else "text"


def answer_form(text) -> str:
    """The form of the answer a Task wants, read from its text: "choice", "number" or "text".

    "choice": the text has lettered options, starting with (A) on its own line. This is the rule of the
    mixed benchmark, unchanged. "number": the text is an arithmetic expression, or asks how many or how
    much, or holds digits and does not ask who, whose, where or why. "text": anything else.
    On the 1,200 Tasks of the mixed benchmark this gives the same result as the benchmark's own rule
    (choice or number). "text" is a careful guess for Tasks outside that benchmark.
    """
    return _form(text, is_arithmetic(text), question_word(text))


def text_profile(text) -> dict:
    """Cheap shape measurements of one input text. Takes well under 1 ms. No model.

    Counts: chars, words, sentences, lines, n_numbers, distinct_numbers, commas, capital_words, n_options.
    Shares of all characters: digit_share, operator_share (the characters + - * / = ( )).
    word_length is the mean length of a word. Yes or no: has_options, is_arithmetic_expression (the
    calculator can answer it), ends_with_equals, question_mark, has_table. question_word and
    answer_form are described at their own functions.
    """
    words = _WORD.findall(text)
    nums = NUMBER.findall(text)
    n = max(1, len(text))
    n_options = len(_OPTION_LINE.findall(text))
    arithmetic = is_arithmetic(text)
    qword = question_word(text)
    return {
        "chars": len(text),
        "words": len(words),
        "sentences": len(_SENTENCE_END.findall(text)),
        "lines": text.count("\n") + 1,
        "n_numbers": len(nums),
        "distinct_numbers": len(set(nums)),
        "digit_share": sum(c.isdigit() for c in text) / n,
        "operator_share": sum(c in "+-*/=()" for c in text) / n,
        "commas": text.count(","),
        "capital_words": sum(w[0].isupper() for w in words),
        "word_length": (sum(len(w) for w in words) / len(words)) if words else 0.0,
        "ends_with_equals": text.rstrip().endswith("="),
        "question_mark": "?" in text,
        "has_options": n_options > 0,
        "n_options": n_options,
        "is_arithmetic_expression": arithmetic,
        "question_word": qword,
        "has_table": _has_table(text),
        "answer_form": _form(text, arithmetic, qword),
    }


def shape_vector(text_or_profile) -> "list[float]":
    """The 13 numbers of the source's "profile" level, in the order of PROFILE_NAMES.

    Give a text or a dictionary made by `text_profile`. Two Tasks with near vectors have a similar
    shape. To compare, scale each number by its spread over the stored Tasks first, as the source does.
    """
    p = text_profile(text_or_profile) if isinstance(text_or_profile, str) else text_or_profile
    return [float(np.log1p(p["words"])), p["n_numbers"], p["distinct_numbers"], p["digit_share"], p["operator_share"],
            p["n_options"], p["lines"], p["sentences"], p["commas"], p["capital_words"], p["word_length"],
            float(p["ends_with_equals"]), float(p["question_mark"])]


# ---------------------------------------------------------------------------
# 2. The profile of an output
# ---------------------------------------------------------------------------

def _is_program_result(value):
    """True for a result dictionary of the safe program runner."""
    return isinstance(value, dict) and "ok" in value and ("answer_type" in value or "error" in value)


def output_profile(question, value, value_type=None, form=None) -> dict:
    """Put a step's output into the answer form of the question. Returns {present, form_ok, answer, why}.

    `value` is a result dictionary of the safe program runner, or a plain Python value (a number, a
    text, a date). `value_type` is a type word of the runner; leave it None to read it from the value.
    `form` is the wanted form; leave it None to read it from the question with `answer_form`.

    present   there is a value at all (the program ran and set an answer)
    form_ok   the value could be put into the wanted form
    answer    the value in that form: a float for "number", "(C)" for "choice" (the ONE option the
              value names), the plain value for "text"; None when form_ok is False
    why       None when form_ok is True, else a short reason

    A value that fails here needs no model to be judged: try the next node.
    """
    if value_type is None and _is_program_result(value):
        if not value.get("ok"):
            return {"present": False, "form_ok": False, "answer": None,
                    "why": "the program did not run: " + str(value.get("error"))[:120]}
        ans, typ = value.get("answer"), value.get("answer_type")
    elif value_type is None:
        ans, typ = plain_value(value)
        if typ == "number" and not math.isfinite(ans):
            return {"present": False, "form_ok": False, "answer": None, "why": "the answer is not a finite number"}
    else:
        ans, typ = value, value_type
    if ans is None:
        typ = "none"
    present = typ != "none"
    form = form or answer_form(question)
    if form == "number":
        if typ == "number":
            return {"present": present, "form_ok": True, "answer": float(ans), "why": None}
        if typ == "string" and PLAIN_NUMBER.fullmatch(ans or ""):
            number = to_number(ans)
            if number is not None:
                return {"present": present, "form_ok": True, "answer": number, "why": None}
        return {"present": present, "form_ok": False, "answer": None, "why": "the answer is not a number"}
    if form == "choice":
        letter, why = match(ans, typ, question)
        return {"present": present, "form_ok": letter is not None,
                "answer": f"({letter})" if letter is not None else None, "why": why}
    if typ in ("number", "date") or (typ == "string" and ans):
        return {"present": present, "form_ok": True, "answer": ans, "why": None}
    return {"present": present, "form_ok": False, "answer": None, "why": "the answer is not one plain value"}


def agreement(answers, tol=1e-3, equal=None) -> dict:
    """Group equal answers of several ways of solving one Task.

    Two numbers are equal within the relative tolerance `tol`; two strings must be the same. A missing
    answer (None) is in no group. Give `equal(a, b)` to use another rule of equality.
    Returns:
      n            how many answers were given, missing ones included
      n_present    how many are not None
      groups       [{"answer": first answer of the group, "count": ..., "members": [positions]}],
                   largest group first; groups of the same size keep the order in which they appeared
      top_answer   the answer of the largest group (None when every answer is missing)
      top_share    size of the largest group divided by n, so a missing answer lowers it
      all_agree    True when no answer is missing and all are in one group
    Agreement is a confidence signal, not a check against an answer key.
    """
    answers = list(answers)
    if equal is None:
        def equal(a, b):
            return same_answer(a, b, tol)
    groups = []
    for position, answer in enumerate(answers):
        if answer is None:
            continue
        for group in groups:
            if equal(group["answer"], answer):
                group["count"] += 1
                group["members"].append(position)
                break
        else:
            groups.append({"answer": answer, "count": 1, "members": [position]})
    groups.sort(key=lambda group: -group["count"])
    n = len(answers)
    n_present = sum(1 for answer in answers if answer is not None)
    top = groups[0] if groups else None
    return {"n": n, "n_present": n_present, "groups": groups,
            "top_answer": top["answer"] if top else None,
            "top_share": (top["count"] / n) if top else 0.0,
            "all_agree": bool(n and n_present == n and len(groups) == 1)}


# ---------------------------------------------------------------------------
# 3. Numbers a calculation may use
# ---------------------------------------------------------------------------

# Numbers that a word of the problem stands for. "half" allows 0.5 and 2; "year" allows 12, 52 and 365.
WORD_NUM = {
    "zero": [0], "one": [1], "two": [2], "three": [3], "four": [4], "five": [5], "six": [6], "seven": [7],
    "eight": [8], "nine": [9], "ten": [10], "eleven": [11], "twelve": [12], "thirteen": [13], "fourteen": [14],
    "fifteen": [15], "sixteen": [16], "seventeen": [17], "eighteen": [18], "nineteen": [19], "twenty": [20],
    "thirty": [30], "forty": [40], "fifty": [50], "sixty": [60], "seventy": [70], "eighty": [80], "ninety": [90],
    "hundred": [100], "thousand": [1000], "million": [1000000],
    "half": [0.5, 2], "halves": [0.5, 2], "third": [3], "thirds": [3], "quarter": [0.25, 4], "quarters": [0.25, 4],
    "fourth": [4], "fifth": [5], "tenth": [10],
    "double": [2], "doubles": [2], "doubled": [2], "twice": [2], "pair": [2], "pairs": [2], "couple": [2], "both": [2],
    "triple": [3], "triples": [3], "tripled": [3], "thrice": [3], "dozen": [12], "dozens": [12],
    "percent": [100], "week": [7], "weeks": [7], "weekly": [7], "day": [24], "days": [24], "daily": [24, 7, 30, 365],
    "hour": [60], "hours": [60], "minute": [60], "minutes": [60], "year": [12, 52, 365], "years": [12, 52, 365],
    "month": [30, 4, 12], "months": [30, 4, 12], "monthly": [12], "yearly": [12, 52], "annual": [12, 52],
    "decade": [10], "century": [100], "feet": [12, 3], "foot": [12, 3], "yard": [3, 36], "yards": [3, 36],
    "pound": [16], "pounds": [16], "gallon": [4], "gallons": [4], "dollar": [100], "dollars": [100], "cents": [100],
    "kilometer": [1000], "kilometers": [1000], "kilogram": [1000], "kilograms": [1000], "meter": [100], "meters": [100],
    "average": [2, 3, 4, 5], "mean": [2, 3, 4, 5],
}
ALWAYS = [0.0, 1.0, 2.0, 10.0, 100.0]


def numbers_in_text(q):
    """The numbers a step may use: those written in the problem (digits or words) and a few fixed constants.

    When the problem speaks of percent, each number p also allows p/100, 1 - p/100 and 1 + p/100.
    """
    nums = set(ALWAYS)
    for m in re.findall(r"\d[\d,]*(?:\.\d+)?", q):
        try:
            nums.add(float(m.replace(",", "")))
        except ValueError:
            pass
    for a, b in re.findall(r"(\d+)\s*/\s*(\d+)", q):  # fractions such as 3/4
        nums.add(float(a))
        nums.add(float(b))
        if float(b):
            nums.add(float(a) / float(b))
    low = q.lower()
    for w in re.findall(r"[a-z]+", low):
        for v in WORD_NUM.get(w, ()):
            nums.add(float(v))
    if "%" in q or "percent" in low:
        for p in list(nums):
            nums.update({p / 100.0, 1 - p / 100.0, 1 + p / 100.0})
    return nums


def literals(tree):
    """Every number written in a parsed expression or program."""
    return [float(n.value) for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) and not isinstance(n.value, bool)]


def grounded_numbers(expression, problem_text, known_values=()) -> dict:
    """Check that every number written in a calculation comes from the problem or from earlier values.

    `expression` is one expression ("12 * 0.2") or a short program of assignment lines.
    `problem_text` is the text of the problem; a set of numbers made by `numbers_in_text` is taken as
    it is, which saves the scan when many steps of one problem are checked.
    `known_values` are values already calculated (a list, or a dictionary of name -> value): a model
    may write such a value as a number.
    Returns {"ok", "not_grounded", "error"}: `not_grounded` lists the numbers that came from nowhere,
    which often means the model worked something out in its head. `error` is set, and ok is False,
    when the text cannot be parsed.
    """
    try:
        try:
            tree = ast.parse(expression.strip(), mode="eval")
        except SyntaxError:
            tree = ast.parse(expression)
    except Exception as e:
        return {"ok": False, "not_grounded": [], "error": f"{type(e).__name__}: {e}"[:160]}
    allowed = problem_text if isinstance(problem_text, (set, frozenset)) else numbers_in_text(problem_text)
    values = known_values.values() if hasattr(known_values, "values") else known_values
    ok_numbers = list(allowed) + [float(v) for v in values]
    bad = [x for x in literals(tree) if not any(abs(x - a) <= 1e-6 * max(1.0, abs(a)) for a in ok_numbers)]
    return {"ok": not bad, "not_grounded": bad, "error": None}


# ---------------------------------------------------------------------------
# 4. Is this Task like anything in the store?
# ---------------------------------------------------------------------------

def unfamiliar(top_similarity, floor) -> bool:
    """True when the nearest stored Task is less similar than the floor, or when there is none.

    What it is for: a table or a chooser that was fitted on stored Tasks knows nothing about a Task that
    looks like none of them. In the mixed benchmark, when every record of one kind was taken out of the
    store, the chooser lost 16.5 and 18.0 points on two of the six kinds against one fixed node for all
    Tasks; a gate "nothing stored looks like this, so use the default node" brought it back to the
    default node's score on every kind and cost nothing on the kinds the store knows (mixed-v1
    COMPARISONS-1-to-7.md). So when this returns True, do not trust a choice made from neighbours: use
    the default node (see `stepkit.decide.KindTable`).

    `floor` is the store's own `CheckedStore.familiarity_floor()`: it is read from how similar the
    stored Tasks are to each other, so it fits the measure of similarity and the store. A fixed number
    does not: 0.2 never fires with text vectors (the nearest entry was never under 0.55 in the mixed
    benchmark) and fires on every arithmetic expression with the built-in text similarity.
    `top_similarity` is the "top_similarity" of `CheckedStore.kind_vote`, made with the same measure.
    """
    return top_similarity is None or top_similarity < floor
