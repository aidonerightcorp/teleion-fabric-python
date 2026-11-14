# Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md
"""The calculator: an exact tool for a Task that is one arithmetic expression. No model.

Copied logic, behaviour kept identical. Sources (under the notes folder):
  work-2026-11-09-real-benchmarks/bench.py           FUNCS, BIN, ev (here: evaluate), check_value
  work-2026-11-10-node-sizer/mixed/bench_mixed.py    ARITH, h_tool_arithmetic (here: calculate_detail)
Python 3 standard library only.
"""
import ast
import math
import re

# Functions an expression may call, and the operators it may use.
FUNCS = {"min": min, "max": max, "round": round, "abs": abs, "int": int, "float": float, "sum": sum,
         "ceil": math.ceil, "floor": math.floor}
BIN = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b, ast.Mult: lambda a, b: a * b,
       ast.Div: lambda a, b: a / b, ast.FloorDiv: lambda a, b: a // b, ast.Mod: lambda a, b: a % b}

# The whole Task must be made of digits, spaces, + - * / ( ) and the decimal point.
ARITH = re.compile(r"^[\d\s+\-*/().]+$")
_DIGIT_THEN_OPERATOR = re.compile(r"\d\s*[-+*/]")


def evaluate(node, env):
    """Compute one parsed expression safely. `env` holds the values of the names it may use.

    Allowed: numbers, names in `env`, + - * / // % and ** (small powers only), a sign, lists, and calls
    of the functions in FUNCS. Anything else raises ValueError.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.Name):
        if node.id in env:
            return env[node.id]
        raise ValueError(f"unknown name {node.id}")
    if isinstance(node, ast.BinOp):
        a, b = evaluate(node.left, env), evaluate(node.right, env)
        if isinstance(node.op, ast.Pow):
            if abs(b) > 12 or abs(a) > 1e6:
                raise ValueError("power too large")
            return a ** b
        if type(node.op) in BIN:
            return BIN[type(node.op)](a, b)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        v = evaluate(node.operand, env)
        return -v if isinstance(node.op, ast.USub) else v
    if isinstance(node, (ast.Tuple, ast.List)):
        return [evaluate(e, env) for e in node.elts]
    if isinstance(node, ast.Call) and not node.keywords:
        name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", None)
        if name in FUNCS:
            return FUNCS[name](*[evaluate(a, env) for a in node.args])
    raise ValueError(f"not allowed: {type(node).__name__}")


def check_value(v):
    """Return the value as a float. Raises ValueError unless it is a finite number of sensible size."""
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or abs(v) > 1e15:
        raise ValueError("value is not a finite number")
    return float(v)


def _expression(text):
    """The Task text without spaces around it and without a closing "=" sign."""
    return text.strip().rstrip("=").strip()


def is_arithmetic(text) -> bool:
    """True when the whole text is one arithmetic expression, such as "((8 - 3) * 2) =".

    This is the profile test only. It does not compute anything, so it is safe on any text.
    """
    if not isinstance(text, str):
        return False
    expr = _expression(text)
    return bool(expr and ARITH.match(expr) and _DIGIT_THEN_OPERATOR.search(expr))


def calculate_detail(text):
    """Compute the expression exactly. Returns (value, error): one of the two is None.

    Never raises for a string: a failure (division by zero, a broken expression) comes back as the error text.
    """
    if not is_arithmetic(text):
        return None, "not an arithmetic expression"
    try:
        return check_value(evaluate(ast.parse(_expression(text), mode="eval").body, {})), None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"[:160]


def calculate(text) -> "float | None":
    """The exact value of an arithmetic expression, or None when the text is not one or cannot be computed."""
    return calculate_detail(text)[0]
