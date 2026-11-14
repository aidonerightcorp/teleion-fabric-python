# Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md
"""The reply profile: code reads a model's reply and says how likely its answer is right. No model.

`reply_features` makes 15 cheap, exact signals from a question and a reply: is there an "Answer:"
line, could an answer of the wanted form be read, every equation the reply wrote ("12 * 3 = 36") is
computed again and the false ones are counted, does the final answer equal the last equation, its
size against the numbers of the question, the length of the reply, words of doubt. All of it runs in
time linear in the length of the reply.

`ReplyChecker` turns the signals into a confidence between 0 and 1, with one small model per kind of
Task. Fitting needs scikit-learn. Using a fitted checker needs none: the fitted numbers (means,
scales, weights for each kind) are saved as plain JSON and the confidence is computed in plain Python.

Copied logic, behaviour kept identical. Sources (under the notes folder):
  work-2026-11-12-next-tests/reply-profile/reply_profile.py   equations, features, NAMES, auc
  work-2026-11-12-next-tests/reply-profile/second_fit.py      one model per kind (here: ReplyChecker.fit)
  work-2026-11-12-next-tests/reply-profile/confirm.py         confidence
  work-2026-11-12-next-tests/t6-fine-tune/scoring.py          wants, parse_answer (here: reply_answer),
                                                              has_answer_line
Python 3 standard library; numpy and scikit-learn inside `ReplyChecker.fit` only.
"""
import ast
import json
import math
import re

# ---------------------------------------------------------------------------
# 1. Reading the answer out of a reply (the rule of the harness that made the training replies)
# ---------------------------------------------------------------------------

_NUMBER = re.compile(r"-?\d[\d,]*(?:\.\d+)?")
_OPTION = re.compile(r"\(?\b([A-H])\b\)?")
_OPTION_A = re.compile(r"\n\s*\(A\)")
_ANSWER_MARK = re.compile(r"answer\s*(?:is)?\s*[:=]", re.I)
# A line counts as an "Answer:" line when it starts with the word Answer (capital A) and a colon.
# Leading spaces and the marks * _ # > are allowed, so "**Answer:** 7" also counts.
_ANSWER_LINE = re.compile(r"^[ \t*_#>]*Answer\**[ \t]*:", re.M)


def wanted_form(question) -> str:
    """A Task with lettered options wants a letter ("choice"); any other Task here wants a "number"."""
    return "choice" if _OPTION_A.search(question) else "number"


def reply_answer(reply, form):
    """Read the answer from a reply: after the last "Answer:" mark when there is one, else at its end.

    `form` is "choice" (gives "(C)") or "number" (gives a float). None when no answer can be read.
    This is the rule that scored the replies the checker was fitted on. It is not the same rule as
    `stepkit.profile.parse_answer`, which the mixed benchmark used.
    """
    text = (reply or "").strip()
    marks = [m.end() for m in _ANSWER_MARK.finditer(text)]
    tail = text[marks[-1]:] if marks else text[-200:]
    tail = tail.replace("**", "").replace("$", "").strip()
    if form == "choice":
        m = _OPTION.search(tail[:40]) if marks else None
        if not m:
            found = re.findall(r"\(([A-H])\)", tail)
            return f"({found[-1]})" if found else None
        return f"({m.group(1)})"
    line = tail.split("\n")[0].split("=")[-1] if marks else tail  # "Answer: 3 + 4 = 7" means 7
    found = _NUMBER.findall(line)
    if not found:
        return None
    pick = found[0] if marks else found[-1]
    try:
        return float(pick.replace(",", ""))
    except ValueError:
        return None


def has_answer_line(reply) -> bool:
    """True when some line of the reply is an "Answer:" line."""
    return bool(_ANSWER_LINE.search(reply or ""))


# ---------------------------------------------------------------------------
# 2. The exact re-check of every equation in a reply
# ---------------------------------------------------------------------------

_RIGHT_NUMBER = re.compile(r"\s*(-?\$?\d[\d,]*(?:\.\d+)?%?)")
_LEFT_OK = set("0123456789.,$%()+-*/x×÷ ")
_DOUBT = re.compile(r"\b(approximately|approx|assume|assuming|unclear|cannot|can't|not enough|unsure|maybe|roughly|"
                    r"i think|estimate)\b", re.I)
_OPS = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b, ast.Mult: lambda a, b: a * b,
        ast.Div: lambda a, b: a / b}


def _number(text):
    t = text.replace("$", "").replace(",", "").strip()
    percent = t.endswith("%")
    v = float(t.rstrip("%"))
    return v / 100.0 if percent else v


def _compute(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_compute(node.left), _compute(node.right))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        v = _compute(node.operand)
        return -v if isinstance(node.op, ast.USub) else v
    raise ValueError("not arithmetic")


def _equations(reply):
    """(number checked, number false, result of the last one). An equation is "expression = number".

    Linear time: for every "=" the number on its right is read, and the arithmetic just left of it
    (at most 90 characters) is computed again.
    """
    n = bad = 0
    last = None
    text = reply or ""
    pos = text.find("=")
    while pos != -1:
        mt = _RIGHT_NUMBER.match(text, pos + 1)
        if mt:
            i = pos
            while i > 0 and pos - i < 90 and text[i - 1] in _LEFT_OK:
                i -= 1
            lhs = text[i:pos].replace("×", "*").replace("÷", "/").replace("$", "").replace(",", "")
            lhs = re.sub(r"(\d+(?:\.\d+)?)%", r"(\1/100)", lhs)
            lhs = re.sub(r"(?<=[\d\)])\s*x\s*(?=[\d\(])", "*", lhs).replace("x", " ").strip().lstrip("+*/ ").strip()
            if lhs and re.search(r"\d\s*[-+*/]\s*[\d\(-]", lhs) and lhs.count("(") == lhs.count(")"):
                try:
                    got, want = _compute(ast.parse(lhs, mode="eval").body), _number(mt.group(1))
                    n += 1
                    last = want
                    if not (abs(got - want) <= 1e-2 * max(1.0, abs(want))
                            or abs(got - want * 100) <= 1e-2 * max(1.0, abs(want * 100))):
                        bad += 1
                except Exception:
                    pass
        pos = text.find("=", pos + 1)
    return n, bad, last


def check_equations(reply) -> dict:
    """Compute every equation of a reply again. Returns {"checked", "false", "last"}.

    "checked" counts the equations of the form "arithmetic = number" that code could compute, "false"
    counts those whose two sides differ by more than 1% (a result written as a percent is allowed for),
    and "last" is the number on the right of the last one (None when there is none).
    Measured on 1,132 recorded replies of the small model: of 509 replies with an equation, 59 held a
    false one, and their final answer was right 30.5% of the time, against 51.8% when all held.
    """
    n, bad, last = _equations(reply)
    return {"checked": n, "false": bad, "last": last}


# ---------------------------------------------------------------------------
# 3. The 15 signals
# ---------------------------------------------------------------------------

# The names of the source, in the source's order, and a short key for each.
FEATURE_NAMES = ["has an Answer line", "an answer was read", "log length", "log lines", "log equations",
                 "some equation is false", "share of false equations", "answer equals the last equation",
                 "answer is a whole number", "log size of answer",
                 "answer size against the largest number in the question", "answer is a number of the question",
                 "words of doubt", "question has options", "log length of question"]
FEATURE_KEYS = ["has_answer_line", "answer_read", "log_length", "log_lines", "log_equations",
                "some_equation_false", "false_equation_share", "answer_equals_last_equation",
                "answer_is_whole_number", "log_answer_size", "answer_size_against_question", "answer_in_question",
                "doubt_words", "question_has_options", "log_question_length"]


def reply_vector(question, reply) -> "list[float]":
    """The 15 signals as a list of numbers, in the order of FEATURE_KEYS."""
    reply = reply or ""
    form = wanted_form(question)
    pred = reply_answer(reply, form)
    n_eq, bad_eq, last = _equations(reply)
    qnums = []
    for t in re.findall(r"\d[\d,]*(?:\.\d+)?", question):
        try:
            qnums.append(float(t.replace(",", "")))
        except ValueError:
            pass
    is_num = isinstance(pred, float)
    mx = max(qnums) if qnums else 1.0
    return [
        1.0 if has_answer_line(reply) else 0.0,
        1.0 if pred is not None else 0.0,
        math.log1p(len(reply)),
        math.log1p(reply.count("\n")),
        math.log1p(n_eq),
        1.0 if bad_eq > 0 else 0.0,
        bad_eq / n_eq if n_eq else 0.0,
        1.0 if (is_num and last is not None and abs(pred - last) <= 1e-3 * max(1.0, abs(last))) else 0.0,
        1.0 if (is_num and float(pred).is_integer()) else 0.0,
        math.log10(abs(pred) + 1.0) if is_num else 0.0,
        (math.log10((abs(pred) + 1.0) / (abs(mx) + 1.0)) if is_num else 0.0),
        1.0 if (is_num and any(abs(pred - q) <= 1e-9 for q in qnums)) else 0.0,
        float(len(_DOUBT.findall(reply))),
        1.0 if form == "choice" else 0.0,
        math.log1p(len(question)),
    ]


def reply_features(question, reply) -> dict:
    """The profile of a reply: 15 exact signals, by name. No model, linear time.

    has_answer_line, answer_read            is there an "Answer:" line; could an answer of the wanted form be read
    log_length, log_lines                   size of the reply (natural logarithm of 1 + the count)
    log_equations                           how many equations code could compute again
    some_equation_false, false_equation_share   the exact re-check of those equations
    answer_equals_last_equation             the final answer is the result of the last equation
    answer_is_whole_number, log_answer_size, answer_size_against_question, answer_in_question
                                            the final answer against the numbers of the question
    doubt_words                             words such as "approximately", "assume", "cannot"
    question_has_options, log_question_length   two facts about the question
    """
    return dict(zip(FEATURE_KEYS, reply_vector(question, reply)))


def auc(scores, right) -> float:
    """How well scores tell right answers from wrong ones: 0.5 is chance, 1.0 is perfect. Ties count half."""
    pairs = sorted(zip(scores, right), key=lambda pair: pair[0])
    n_right = sum(1 for _, flag in pairs if flag)
    n_wrong = len(pairs) - n_right
    if not n_right or not n_wrong:
        raise ValueError("auc needs right and wrong answers")
    rank_sum, i = 0.0, 0
    while i < len(pairs):
        j = i
        while j + 1 < len(pairs) and pairs[j + 1][0] == pairs[i][0]:
            j += 1
        mean_rank = (i + j) / 2.0 + 1
        rank_sum += mean_rank * sum(1 for k in range(i, j + 1) if pairs[k][1])
        i = j + 1
    return (rank_sum - n_right * (n_right + 1) / 2.0) / (n_right * n_wrong)


# ---------------------------------------------------------------------------
# 4. From the signals to a confidence
# ---------------------------------------------------------------------------

def _sigmoid(z):
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


def _score(model, vector):
    z = model["intercept"]
    for x, mean, scale, weight in zip(vector, model["mean"], model["scale"], model["weights"]):
        z += weight * (x - mean) / scale
    return _sigmoid(z)


class ReplyChecker:
    """A confidence that a reply's answer is right, from the reply profile. One small model per kind.

        checker = ReplyChecker.load(path)                        # plain JSON, no scikit-learn needed
        c = checker.confidence(question, reply, kind)            # between 0 and 1
        if c >= 0.8: keep the answer, else ask the next node

    A checker knows the replies of the node it was fitted on. Measured for the checker fitted on worked
    replies of the small model (AUC, 0.5 is chance): 0.892 on 1,132 held-out Tasks, 0.806 on 960 Tasks of
    another benchmark run with another prompt, and 0.727 on the larger model's replies, which it never
    saw (reply-profile/RESULTS.md). On tracking questions it does not work (0.397): the reply looks
    the same whether right or wrong.
    """

    FORMAT = "stepkit reply checker, version 1"

    def __init__(self):
        self.kinds = {}         # kind -> {"rows", "right_rate", "mean", "scale", "weights", "intercept"}
        self.rates = {}         # kind -> share right among the fitting rows of that kind
        self.overall_rate = None
        self.all_kinds = None   # one model fitted on the rows of every kind
        self.per_kind = True
        self.unknown_kind = "rate"
        self.fitted_on = {}

    # ---- fitting (needs numpy and scikit-learn) ----
    def fit(self, rows, per_kind=True, min_rows=40, note=""):
        """Fit the checker on recorded replies. Returns the checker.

        `rows`: dictionaries with "question", "reply", "right" (True or False) and "kind". Use replies
        of ONE node, in the form the checker will read later (worked answers with worked answers).
        `per_kind=True`: one model for each kind that has at least `min_rows` rows with both right
        and wrong answers; a kind with fewer rows gets only its share of right answers. One model for
        all kinds is fitted too; it is used when no kind is given, and for every kind when
        `per_kind=False`. Same settings as the source (second_fit.py).
        """
        import numpy as np
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler

        rows = list(rows)
        X = np.array([reply_vector(row["question"], row.get("reply")) for row in rows])
        y = np.array([bool(row["right"]) for row in rows])
        kinds = np.array([row.get("kind") for row in rows], dtype=object)

        def fitted(mask, strength):
            pipe = make_pipeline(StandardScaler(), LogisticRegression(C=strength, max_iter=2000)).fit(X[mask], y[mask])
            scaler, model = pipe.named_steps["standardscaler"], pipe.named_steps["logisticregression"]
            return {"rows": int(mask.sum()), "right_rate": float(y[mask].mean()),
                    "mean": [float(v) for v in scaler.mean_], "scale": [float(v) for v in scaler.scale_],
                    "weights": [float(v) for v in model.coef_[0]], "intercept": float(model.intercept_[0])}

        self.per_kind = bool(per_kind)
        self.kinds, self.rates = {}, {}
        self.overall_rate = float(y.mean())
        everything = np.ones(len(rows), dtype=bool)
        self.all_kinds = fitted(everything, 1.0) if y.min() != y.max() else None
        for kind in sorted({k for k in kinds if k is not None}):
            mask = kinds == kind
            self.rates[kind] = float(y[mask].mean())
            if per_kind and mask.sum() >= min_rows and y[mask].min() != y[mask].max():
                self.kinds[kind] = fitted(mask, 0.3)
        self.fitted_on = {"rows": len(rows), "right_rate": self.overall_rate, "min_rows": int(min_rows), "note": note}
        return self

    # ---- using a fitted checker (plain Python) ----
    def confidence_of(self, vector, kind=None) -> float:
        """The confidence for a ready list of the 15 signals (see `reply_vector`)."""
        if self.overall_rate is None:
            raise ValueError("the checker is not fitted: call fit(rows) or ReplyChecker.load(path)")
        if self.per_kind and kind in self.kinds:
            return _score(self.kinds[kind], vector)
        use_all = (not self.per_kind) or kind is None or self.unknown_kind == "all_kinds"
        if use_all and self.all_kinds is not None:
            return _score(self.all_kinds, vector)
        return self.rates.get(kind, self.overall_rate)

    def confidence(self, question, reply, kind=None) -> float:
        """How likely the answer of this reply is right, between 0 and 1.

        `kind` is the kind of the Task, for example from `CheckedStore.kind_vote`. A kind with its own
        model is scored by it. With `kind=None` the one model for all kinds is used. A kind the
        checker has no model for gets the share of right answers seen for that kind when fitting (the
        rule of the source); set `checker.unknown_kind = "all_kinds"` to use the one model instead.
        """
        return self.confidence_of(reply_vector(question, reply), kind)

    # ---- files (plain JSON) ----
    def to_dict(self) -> dict:
        return {"format": self.FORMAT, "features": list(FEATURE_KEYS), "per_kind": self.per_kind,
                "unknown_kind": self.unknown_kind, "overall_rate": self.overall_rate, "rates": self.rates,
                "kinds": self.kinds, "all_kinds": self.all_kinds, "fitted_on": self.fitted_on}

    def save(self, path):
        """Write the fitted numbers as plain JSON: for each kind its means, scales, weights and intercept."""
        with open(path, "w", encoding="utf-8") as out:
            json.dump(self.to_dict(), out, indent=1)
            out.write("\n")

    @classmethod
    def load(cls, path):
        """Read a checker written by `save`. Needs no scikit-learn."""
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        if data.get("features") != FEATURE_KEYS:
            raise ValueError("this file was made for another list of signals")
        checker = cls()
        checker.per_kind = bool(data.get("per_kind", True))
        checker.unknown_kind = data.get("unknown_kind", "rate")
        checker.overall_rate = data["overall_rate"]
        checker.rates = dict(data.get("rates") or {})
        checker.kinds = dict(data.get("kinds") or {})
        checker.all_kinds = data.get("all_kinds")
        checker.fitted_on = dict(data.get("fitted_on") or {})
        return checker
