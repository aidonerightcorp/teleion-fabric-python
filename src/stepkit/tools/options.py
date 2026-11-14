# Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md
"""Lettered options: read them from a question, and find the one option a value names.

Copied logic, behaviour kept identical. Source (under the notes folder):
  work-2026-11-12-next-tests/t7-toolsmith/toolsmith.py   OPT, PLAIN_NUMBER, norm, as_date, and the
                                                          option branch of to_final (here: match)
Python 3 standard library only.
"""
import re

from .._answers import plain_value, to_number

# One option line, such as "(B) 05/02/2000".
OPT = re.compile(r"^\s*\(([A-Z])\)\s*(.+?)\s*$", re.M)
# A text that is one plain number, with an optional $ sign and an optional % sign.
PLAIN_NUMBER = re.compile(r"\s*-?\$?\d[\d,]*(?:\.\d+)?\s*%?\s*")
_LETTER_ONLY = re.compile(r"\(?([A-Z])\)?")
_DATE = re.compile(r"\s*(\d{1,2})/(\d{1,2})/(\d{4})\s*")


def norm(s):
    """A text in a form that is easy to compare: lower case, single spaces, no leading article, no final dot."""
    s = re.sub(r"\s+", " ", str(s).strip().lower())
    s = re.sub(r"^(the|a|an)\s+", "", s)
    return re.sub(r"[\s\.]+$", "", s)


def as_date(s):
    """(year, month, day) of a text in the form MM/DD/YYYY, else None."""
    m = _DATE.fullmatch(str(s))
    return (int(m.group(3)), int(m.group(1)), int(m.group(2))) if m else None


def parse_options(question) -> "list[tuple[str, str]]":
    """The lettered options of a question, in order: [("A", "05/02/2020"), ("B", "05/02/2000"), ...]."""
    return OPT.findall(question)


def match(value, value_type, question):
    """Find the ONE option that a value names. Returns (letter or None, why).

    `value_type` is a type word of the safe program runner ("date", "string", "number", ...). Give None
    to have it read from the Python value. The rules, in order:
      - a string that is an option letter itself ("C" or "(C)") names that option;
      - a date is compared with options that are dates;
      - a number is compared with options that are plain numbers;
      - any other text is compared after `norm`; when nothing is equal, an option that contains the
        text, or is contained in it, counts.
    Exactly one option must fit: with none or with several the letter is None and `why` says which.
    """
    if value_type is None:
        value, value_type = plain_value(value)
    ans, typ = value, value_type
    if typ not in ("date", "string", "number"):
        return None, "the answer does not name one option"
    opts = OPT.findall(question)
    if typ == "string":  # the value names an option letter itself
        mt = _LETTER_ONLY.fullmatch((ans or "").strip())
        if mt and mt.group(1) in [letter for letter, _ in opts]:
            return mt.group(1), None
    a_date = as_date(ans) if typ in ("date", "string") else None
    hits = []
    for letter, text in opts:
        o_date = as_date(text)
        if a_date and o_date:
            if a_date == o_date:
                hits.append(letter)
        elif typ == "number":
            if PLAIN_NUMBER.fullmatch(text):
                v = to_number(text)
                if v is not None and abs(v - float(ans)) <= 1e-6 * max(1.0, abs(v)):
                    hits.append(letter)
        elif norm(ans) == norm(text):
            hits.append(letter)
    if not hits and typ == "string" and not a_date:
        na = norm(ans)
        hits = [letter for letter, text in opts if na and (na in norm(text) or norm(text) in na)]
    if len(hits) == 1:
        return hits[0], None
    return None, ("no option matched" if not hits else "more than one option matched")
