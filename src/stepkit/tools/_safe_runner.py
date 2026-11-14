# Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md
# COPY, NOT THE ORIGINAL. This file is a whole copy of
#   notes/work-2026-11-12-next-tests/t7-toolsmith/sandbox.py
# taken on November 12, 2026. Nothing below the marker line is changed, so its behaviour is the same.
# Do not edit this copy: change the original, copy it again, and run tests/test_programs.py, which
# compares the text below the marker with the original and runs the original's own test file on it.
# Use it through stepkit.tools.programs (extract, check, run).
# ---- copy starts below this line ----
"""Safe runner for short Python programs written by the model, for a benchmark.

Public functions (a fixed contract with the benchmark runner):
    extract_code(reply)               -> the program text found in a model reply
    check_program(code)               -> None when the program is allowed, else a one-line reason
    run_program(code, timeout_s=3.0)  -> result dictionary; never raises

Safety comes in layers:
  1. A whitelist check of the syntax tree: simple statements only, and only the public methods
     of plain values.  No name or attribute may start with an underscore, so the usual escape
     routes cannot even be written down.
  2. The program runs with no builtins except a short list of provided names.
  3. It runs in a fresh child process: empty environment, empty temporary folder, limits on CPU
     time, memory, file size, open files and new processes, and a wall-clock timeout.
  4. Where the Linux kernel supports it (Landlock), the child also gives up all file, TCP and
     signal access before the program starts.
Python 3 standard library only.
"""
import ast, json, math, os, re, shutil, signal, subprocess, sys, tempfile, textwrap, time, warnings
from datetime import date, datetime, timedelta

__all__ = ["extract_code", "check_program", "run_program"]

PROVIDED = ("date timedelta datetime ceil floor sqrt abs round min max sum len sorted reversed range "
            "int float str bool list dict set tuple enumerate zip any all divmod").split()
BANNED_NAMES = frozenset(
    "eval exec compile open input getattr setattr delattr globals locals vars dir type object super "
    "memoryview bytearray bytes breakpoint exit quit help __import__".split())
BANNED_ATTRS = frozenset("format format_map mro gi_frame f_globals f_builtins func_globals".split())
# The only attribute names a program may read: public methods and fields of the plain values it
# can hold.  Frame, code and generator attributes are not in this set, so they are refused too.
_VALUE_TYPES = (str, int, float, bool, list, dict, set, frozenset, tuple, range,
                date, datetime, timedelta, time.struct_time)
ALLOWED_ATTRS = frozenset(
    ({name for kind in _VALUE_TYPES for name in dir(kind) if not name.startswith("_")}
     | {"timedelta", "datetime", "ceil", "floor", "sqrt", "week"})   # math.sqrt, datetime.timedelta
    - BANNED_ATTRS - {"encode", "to_bytes", "from_bytes"})
_ALLOWED_NODES = (
    ast.Module, ast.Expr, ast.Assign, ast.AugAssign, ast.AnnAssign, ast.For, ast.If, ast.Pass,
    ast.Break, ast.Continue, ast.Assert, ast.Name, ast.Load, ast.Store, ast.Constant, ast.Tuple,
    ast.List, ast.Dict, ast.Set, ast.Starred, ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare,
    ast.IfExp, ast.NamedExpr, ast.Call, ast.keyword, ast.Attribute, ast.Subscript, ast.Slice,
    ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp, ast.comprehension, ast.JoinedStr,
    ast.FormattedValue, ast.operator, ast.unaryop, ast.boolop, ast.cmpop)
_PLAIN_WORDS = {"Import": "import", "ImportFrom": "import", "FunctionDef": "function definition",
                "AsyncFunctionDef": "function definition", "ClassDef": "class definition",
                "Delete": "del"}
_IMPORTABLE = {"datetime": {"date", "timedelta", "datetime"}, "math": {"ceil", "floor", "sqrt"}}
_FENCE = re.compile(r"```([^\n`]*)\n(.*?)(?:```|\Z)", re.S)
_PRINT_LINE = re.compile(r"^(\s*)print\s*\(.*\)\s*(#.*)?$")
_RESULT_TYPES = ("number", "date", "string", "list", "dict", "bool", "none")
_FILENAME = "<model program>"
MAX_CODE_CHARS = 20000
TEMP_PREFIX = "t7-safe-run-"
# A program with an odd escape such as "\d" makes the parser print a warning; keep that quiet.
warnings.filterwarnings("ignore", category=SyntaxWarning, module=re.escape(_FILENAME))


def _one_line(text, line=None):
    """Squeeze any text into one line of at most 200 characters; name the program line if known."""
    return " ".join(str(text).split())[:185] + (f" (line {line})" if line else "")


def _import_replacement(line):
    """Lines to put in place of a harmless import line, or None when the line must stay.

    Only names the runner already provides count as harmless.  `import x as y` becomes the
    plain assignment `y = x`; an import without `as` is simply dropped.
    """
    text = line.split("#", 1)[0].strip()
    found = re.fullmatch(r"from\s+(\w+)\s+import\s+(.+)", text)
    if found:
        allowed, items = _IMPORTABLE.get(found.group(1)), found.group(2).strip("() ")
        if allowed is None:
            return None
        if items == "*":
            return []
    else:
        found = re.fullmatch(r"import\s+(.+)", text)
        if not found:
            return None
        allowed, items = set(_IMPORTABLE), found.group(1)
    lines = []
    for item in items.split(","):
        words = item.split()
        if len(words) == 3 and words[1] == "as" and words[0] in allowed and words[2].isidentifier():
            lines.append(f"{words[2]} = {words[0]}")
        elif words and not (len(words) == 1 and words[0] in allowed):
            return None
    return lines


def extract_code(reply: str) -> str:
    """Return the program inside a model reply.

    Takes the first code fence (marked python or unmarked) when there is one, else the whole
    reply.  Drops import lines for names the runner already provides and print-only lines.
    """
    text = reply if isinstance(reply, str) else ("" if reply is None else str(reply))
    for fence in _FENCE.finditer(text):
        if fence.group(1).strip().lower() in ("", "python", "py", "python3"):
            text = fence.group(2)
            break
    kept = []
    for line in textwrap.dedent(text).strip().splitlines():
        replacement = _import_replacement(line) if line.startswith(("import ", "from ")) else None
        shown = _PRINT_LINE.match(line)
        if replacement is not None:
            kept.extend(replacement)
        elif shown and shown.group(1):
            kept.append(shown.group(1) + "pass")       # inside a block: keep the block valid
        elif not shown:
            kept.append(line)
    return "\n".join(kept).strip()


def _literal_number(node):
    """The value of a plain number literal (a leading sign is fine), else None."""
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        node = node.operand
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return node.value
    return None


def _is_text_or_list(node):
    """True when the node is written as a string, list or tuple."""
    if isinstance(node, ast.Constant):
        return isinstance(node.value, (str, bytes))
    return isinstance(node, (ast.JoinedStr, ast.List, ast.Tuple, ast.ListComp))


def _node_problem(node):
    """Why this syntax tree node is not allowed, or None when it is fine."""
    kind = type(node).__name__
    if not isinstance(node, _ALLOWED_NODES):
        return f"{_PLAIN_WORDS.get(kind, kind.lower())} is not allowed"
    if isinstance(node, ast.Name):
        if node.id in BANNED_NAMES or (node.id.startswith("_") and node.id != "_"):
            return f"name '{node.id}' is not allowed"
    elif isinstance(node, ast.Attribute):
        if not isinstance(node.ctx, ast.Load):
            return "setting an attribute is not allowed"
        if node.attr.startswith("_") or node.attr not in ALLOWED_ATTRS:
            return f"attribute '{node.attr}' is not allowed"
    elif isinstance(node, ast.Call):
        if not isinstance(node.func, (ast.Name, ast.Attribute)):
            return "only named functions and methods may be called"
        if any(word.arg is None for word in node.keywords):
            return "'**' in a call is not allowed"
    elif isinstance(node, ast.Constant):
        if not isinstance(node.value, (int, float, complex, str, type(None))):
            return "this kind of literal is not allowed"
    elif isinstance(node, ast.comprehension) and node.is_async:
        return "async is not allowed"
    elif isinstance(node, (ast.BinOp, ast.AugAssign)):
        left, right = (node.left, node.right) if isinstance(node, ast.BinOp) else (None, node.value)
        if isinstance(node.op, ast.MatMult):
            return "the @ operator is not allowed"
        if isinstance(node.op, ast.Pow):
            power = _literal_number(right)
            if power is None or abs(power) > 6:
                return "'**' needs a literal exponent of at most 6"
        if isinstance(node.op, ast.Mult):
            for text, count in ((left, right), (right, left)):
                if text is not None and _is_text_or_list(text):
                    times = _literal_number(count) if count is not None else None
                    if type(times) is not int or times > 1000:
                        return "repeating text or a list needs a literal count of at most 1000"
    return None


def check_program(code: str) -> "str | None":
    """Static whitelist check.  Returns None when allowed, else a short one-line reason."""
    try:
        if not isinstance(code, str):
            return "program is not text"
        if len(code) > MAX_CODE_CHARS:
            return "program is too long"
        try:
            tree = ast.parse(code, filename=_FILENAME)
        except SyntaxError as error:
            return _one_line(f"syntax error: {error.msg}", error.lineno)
        for node in ast.walk(tree):
            problem = _node_problem(node)
            if problem:
                return _one_line(problem, getattr(node, "lineno", None))
        return None
    except Exception as error:      # never raise: a program that breaks the check is not allowed
        return _one_line(f"check failed: {type(error).__name__}: {error}")


# The child process runs this text.  It reads the program from standard input, locks itself
# down, runs the program with only the provided names, and prints one JSON line.
_RUNNER = r'''
import sys, os, math, time, builtins, resource, datetime as dt
from _json import encode_basestring_ascii as quote
code = sys.stdin.buffer.read().decode("utf-8")
cpu_seconds, names = int(sys.argv[1]), sys.argv[2].split()
loaded = {"time": time}              # modules that date methods ask for by name while they run
if "strptime" in code:
    import _strptime                 # load now: nothing can be opened once the limits are set
    loaded["_strptime"] = _strptime
time.localtime()                     # same reason: this reads the time zone file once

def loaded_only(name, *rest):
    """The only import hook: strftime, today and strptime look up a loaded module by name."""
    if name not in loaded:
        raise ImportError("import is not allowed: %s" % (name,))
    return loaded[name]

def kernel_lock():
    """Best effort (Linux Landlock): from now on no file, TCP or signal action is possible."""
    import ctypes
    libc, num = ctypes.CDLL(None, use_errno=True), ctypes.c_long
    version = libc.syscall(num(444), None, num(0), num(1))      # which rule version exists
    if version < 1:
        return
    files = (1 << (13 if version < 2 else 14 if version < 3 else 15 if version < 5 else 16)) - 1
    fields = [files] + ([3] if version >= 4 else []) + ([3] if version >= 6 else [])
    rules = b"".join(field.to_bytes(8, sys.byteorder) for field in fields)
    handle = libc.syscall(num(444), rules, num(len(rules)), num(0))   # a rule set that allows nothing
    if handle >= 0:
        libc.prctl(num(38), num(1), num(0), num(0), num(0))     # no new privileges (needed first)
        libc.syscall(num(446), num(handle), num(0))             # apply the rule set to this process
        os.close(handle)

def convert(value, depth=0):
    """Turn the answer into a JSON-safe value and a type word."""
    if depth > 20:
        raise ValueError("answer is nested too deep")
    if value is None: return None, "none"
    if isinstance(value, bool): return value, "bool"
    if isinstance(value, dt.date):                               # covers datetime too
        return "%02d/%02d/%04d" % (value.month, value.day, value.year), "date"
    if isinstance(value, int): return int(value), "number"
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("answer is not a finite number")
        return float(value), "number"
    if isinstance(value, str): return value.strip(), "string"
    if isinstance(value, (list, tuple, set, frozenset)):
        items = [convert(item, depth + 1)[0] for item in value]
        if isinstance(value, (set, frozenset)):
            items.sort(key=lambda item: (str(item), type(item).__name__))
        return items, "list"
    if isinstance(value, dict):
        return {key if isinstance(key, str) else str(key): convert(item, depth + 1)[0]
                for key, item in value.items()}, "dict"
    return str(value), "string"

def to_json(value):
    """A small JSON writer for converted answers (loading the json module would cost 10 ms)."""
    if value is None or value is True or value is False:
        return {None: "null", True: "true", False: "false"}[value]
    if isinstance(value, (int, float)): return repr(value)
    if isinstance(value, str): return quote(value)
    if isinstance(value, list): return "[" + ",".join(map(to_json, value)) + "]"
    return "{" + ",".join(quote(key) + ":" + to_json(item) for key, item in value.items()) + "}"

def describe(error):
    """One line about a failure, with the program line where it happened."""
    line, trace = None, error.__traceback__
    while trace is not None:
        if trace.tb_frame.f_code.co_filename == "<program>":
            line = trace.tb_lineno
        trace = trace.tb_next
    line = error.lineno if isinstance(error, SyntaxError) else line
    text = " ".join((type(error).__name__ + ": " + str(error)).split())[:160].rstrip(": ")
    return text + (" (line %s)" % line if line else "")

def finish(result):
    """Print the one result line and stop at once."""
    text = to_json(result)
    if len(text) > 200000:
        text = to_json({"ok": False, "error": "answer is too large"})
    sys.stdout.write("\n" + text + "\n")
    sys.stdout.flush()
    os._exit(0)

class ModuleStyleDate:               # lets `datetime.date(2021, 4, 30)` work as in the module
    def __get__(self, obj, cls=None):
        return dt.date if obj is None else dt.datetime.date.__get__(obj, cls)

class datetime(dt.datetime):         # the provided `datetime`: the usual class, usable like the module too
    __slots__ = ()
    date = ModuleStyleDate()
    timedelta = dt.timedelta
datetime.datetime = datetime

pool = dict(vars(builtins), date=dt.date, timedelta=dt.timedelta, datetime=datetime,
            ceil=math.ceil, floor=math.floor, sqrt=math.sqrt)
tiny_math = type(sys.implementation)(ceil=math.ceil, floor=math.floor, sqrt=math.sqrt)
space = {"__builtins__": {"__import__": loaded_only}, "math": tiny_math}
space.update((name, pool[name]) for name in names)
try:
    try:
        kernel_lock()
    except Exception:
        pass
    memory = 512 * 1024 * 1024       # limits: CPU seconds, address space, file size, core dump, open files
    for name, soft, hard in (("CPU", cpu_seconds, cpu_seconds + 1), ("AS", memory, memory),
                             ("FSIZE", 0, 0), ("CORE", 0, 0), ("NOFILE", 0, 0)):
        resource.setrlimit(getattr(resource, "RLIMIT_" + name), (soft, hard))
    try:
        resource.setrlimit(resource.RLIMIT_NPROC, (0, 0))        # no new process or thread
    except Exception:
        pass
    exec(compile(code, "<program>", "exec", dont_inherit=True), space)
    if "answer" not in space:
        finish({"ok": False, "error": "no answer variable"})
    answer, kind = convert(space["answer"])
    finish({"ok": True, "answer": answer, "answer_type": kind})
except BaseException as error:
    if isinstance(error, MemoryError):
        space.clear()                                            # free memory for the report
    try:
        message = describe(error)
    except BaseException:
        message = type(error).__name__
    finish({"ok": False, "error": message})
'''


def _fail(message):
    return {"ok": False, "error": _one_line(message), "answer": None, "answer_type": "none"}


def _kill(proc):
    """Kill the child and everything in its process group, then collect it."""
    for action in (lambda: os.killpg(proc.pid, signal.SIGKILL), proc.kill,
                   lambda: proc.communicate(timeout=5)):
        try:
            action()
        except Exception:
            pass


def _run_child(code, timeout_s):
    """Run checked code in the locked-down child and return the result fields."""
    try:
        timeout_s = float(timeout_s)
    except (TypeError, ValueError):
        timeout_s = 3.0
    if not 0.05 <= timeout_s <= 600:                # also catches a not-a-number value
        timeout_s = 3.0
    command = [sys.executable or "/usr/bin/python3", "-I", "-S", "-B", "-c", _RUNNER,
               str(max(1, math.ceil(timeout_s))), " ".join(PROVIDED)]
    folder = tempfile.mkdtemp(prefix=TEMP_PREFIX)
    proc = None
    try:
        proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, env={}, cwd=folder, close_fds=True,
                                start_new_session=True)
        try:
            output, _ = proc.communicate(code.encode("utf-8"), timeout=timeout_s + 1.0)
        except subprocess.TimeoutExpired:
            _kill(proc)
            return _fail(f"time limit: no result after {timeout_s + 1.0:g} seconds")
        lines = output.decode("utf-8", "replace").strip().splitlines()
        try:
            data = json.loads(lines[-1]) if lines else None
        except ValueError:
            data = None
        if not isinstance(data, dict) or "ok" not in data:
            if proc.returncode in (-signal.SIGXCPU, -signal.SIGKILL):
                return _fail("time limit: the CPU seconds were used up")
            return _fail(f"the child process ended without a result (exit code {proc.returncode})")
        if data["ok"] is True and data.get("answer_type") in _RESULT_TYPES:
            return {"ok": True, "error": None, "answer": data.get("answer"),
                    "answer_type": data["answer_type"]}
        return _fail(data.get("error") or "unknown error")
    finally:
        if proc is not None and proc.poll() is None:
            _kill(proc)
        shutil.rmtree(folder, ignore_errors=True)


def run_program(code: str, timeout_s: float = 3.0) -> dict:
    """Check the program, run it in a locked-down child process, and return the result.

    Returns {"ok", "error", "answer", "answer_type", "ms"}.  Never raises.
    """
    started = time.perf_counter()
    try:
        reason = check_program(code)
        result = _fail(reason) if reason is not None else _run_child(code, timeout_s)
    except Exception as error:
        result = _fail(f"runner error: {type(error).__name__}: {error}")
    result["ms"] = round((time.perf_counter() - started) * 1000.0, 3)
    return result
