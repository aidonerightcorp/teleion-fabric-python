# Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md
"""Running programs that the model wrote: a safe runner for short Python, and an arithmetic-only runner.

Two runners, for two kinds of program:
  run(code)             a short Python program in a locked-down child process (dates, lists, loops).
                        The runner is a whole, unchanged copy of the source below (see _safe_runner.py).
  run_arithmetic(text)  assignment lines with arithmetic only, computed in this process by the
                        calculator's evaluator. Nothing else can run, so it needs no child process.

Sources (under the notes folder):
  work-2026-11-12-next-tests/t7-toolsmith/sandbox.py   extract_code, check_program, run_program
  work-2026-11-09-real-benchmarks/bench.py             strip_code, run_program (here: run_arithmetic)
Python 3 standard library only.
"""
import ast
import re

from . import _safe_runner
from .calculator import BIN, check_value, evaluate

_FENCED = re.compile(r"```(?:python)?\s*\n?(.*?)```", flags=re.S)
_ASSIGNMENT_LINE = re.compile(r"^\s*[A-Za-z_]\w*\s*(?:[-+*/]?=)[^=]")


def extract(reply) -> str:
    """The program inside a model reply: the first code fence when there is one, else the whole reply.

    Import lines for names the runner already provides, and print-only lines, are dropped.
    """
    return _safe_runner.extract_code(reply)


def check(code) -> "str | None":
    """Static check of a program. None when it is allowed, else one short line with the reason."""
    return _safe_runner.check_program(code)


def run(code, timeout_s=3.0) -> dict:
    """Check a program and run it in a locked-down child process. Never raises.

    Returns {"ok", "error", "answer", "answer_type", "ms"}. The program must set the variable `answer`.
    "answer_type" is one of "number", "date", "string", "list", "dict", "bool", "none".
    Give this dictionary to `stepkit.profile.output_profile` to get the answer form of the question.
    """
    return _safe_runner.run_program(code, timeout_s)


def strip_code(text):
    """The text inside the first code fence of a reply, or the whole reply when there is no fence."""
    found = _FENCED.findall(text)
    return (found[0] if found else text).strip()


def run_arithmetic(text):
    """Run an assignment-only arithmetic program. Returns (value, error): one of the two is None.

    The program is a list of lines such as `total = 6 * (2 * 5)`. The value of the name `answer` is the
    result. Lines that print, import or comment are skipped. Any failure is a returned error, never a crash.
    """
    code = strip_code(text).replace("$", "")
    lines = [ln for ln in code.splitlines()
             if ln.strip() and not ln.strip().startswith(("print", "import", "from", "#"))]
    if "```" not in text:
        lines = [ln for ln in lines if _ASSIGNMENT_LINE.match(ln)]
    try:
        tree = ast.parse("\n".join(lines[:60]))
        env = {}
        for st in tree.body:
            if isinstance(st, ast.Assign) and len(st.targets) == 1 and isinstance(st.targets[0], ast.Name):
                env[st.targets[0].id] = evaluate(st.value, env)
            elif isinstance(st, ast.AugAssign) and isinstance(st.target, ast.Name) and type(st.op) in BIN:
                env[st.target.id] = BIN[type(st.op)](env[st.target.id], evaluate(st.value, env))
            elif isinstance(st, ast.Expr):
                continue
            else:
                raise ValueError(f"statement not allowed: {type(st).__name__}")
        if "answer" not in env:
            raise ValueError("no answer line")
        return check_value(env["answer"]), None
    except Exception as e:  # any failure is a recorded miss, never a crash
        return None, f"{type(e).__name__}: {e}"[:160]
