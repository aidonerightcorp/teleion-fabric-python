# Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md
"""Reading and comparing answers: numbers, lettered options, right or wrong.

Copied logic, behaviour kept identical. Sources (under the notes folder):
  work-2026-11-09-real-benchmarks/bench.py           NUM, to_number, same
  work-2026-11-10-node-sizer/mixed/bench_mixed.py    CHOICE, answer_kind, parse_answer, right
  work-2026-11-10-node-sizer/mixed/chooser.py        same_answer
  work-2026-11-12-next-tests/t7-toolsmith/sandbox.py the value types of a program result (see plain_value)
Python 3 standard library only.
"""
import re
from datetime import date

# A number as a model writes it: optional sign, optional $ sign, digits with commas, optional decimals.
NUM = re.compile(r"-?\$?\d[\d,]*(?:\.\d+)?")
# A lettered option named in a reply, such as "(C)".
CHOICE = re.compile(r"\(([A-Z])\)")
# The start of a list of lettered options inside a Task text.
OPTION_A = re.compile(r"\n\s*\(A\)")


def to_number(text):
    """The LAST number written in the text, as a float. None when there is none."""
    found = NUM.findall(text or "")
    if not found:
        return None
    try:
        return float(found[-1].replace(",", "").replace("$", ""))
    except ValueError:
        return None


def same(a, b):
    """True when two numbers are equal within 0.1% of the second one (or 0.001 for small numbers)."""
    return a is not None and b is not None and abs(a - b) <= 1e-3 * max(1.0, abs(b))


def same_answer(a, b, tol=1e-3):
    """True when two answers are equal: strings must be the same, numbers within the tolerance.

    A missing answer (None) is equal to nothing, not even to another missing answer.
    """
    if a is None or b is None:
        return False
    if isinstance(a, str) or isinstance(b, str):
        return a == b
    return abs(a - b) <= tol * max(1.0, abs(b))


def answer_kind(question):
    """The benchmark rule: a Task with lettered options wants a letter; any other Task wants a number."""
    return "choice" if OPTION_A.search(question) else "number"


def parse_answer(text, kind):
    """Read an answer out of a model reply. kind "choice" gives "(C)"; any other kind gives a float."""
    text = text or ""
    if kind == "choice":
        found = CHOICE.search(text) or re.match(r"\s*([A-Z])\b", text)
        return f"({found.group(1)})" if found else None
    return to_number(text)


def right(pred, gold, tol=1e-3):
    """Compare an answer with the answer key. A missing answer is wrong."""
    if pred is None:
        return False
    if isinstance(gold, str) or isinstance(pred, str):
        return pred == gold
    return abs(pred - gold) <= tol * max(1.0, abs(gold))


def plain_value(value):
    """Turn a Python value into (value, type word), with the type words of the safe program runner.

    Type words: "number", "date", "string", "list", "dict", "bool", "none". A date becomes the text
    MM/DD/YYYY, a string is stripped, and any other object becomes its text. This follows `convert`
    inside the runner, so a plain value and a program result are treated the same way.
    """
    if value is None:
        return None, "none"
    if isinstance(value, bool):
        return value, "bool"
    if isinstance(value, date):  # covers datetime too
        return "%02d/%02d/%04d" % (value.month, value.day, value.year), "date"
    if isinstance(value, int):
        return int(value), "number"
    if isinstance(value, float):
        return float(value), "number"
    if isinstance(value, str):
        return value.strip(), "string"
    if isinstance(value, (list, tuple, set, frozenset)):
        return list(value), "list"
    if isinstance(value, dict):
        return value, "dict"
    return str(value), "string"

