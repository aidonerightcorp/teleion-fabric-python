# Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md
"""Where the source files and the recorded runs live, and how to import a source file by its path.

The kit was refactored from the benchmark folders named below. Most logic was copied into the kit, so
the kit runs without them. Two things still read these folders:
  - `stepkit.tools.tables` imports the large table tool file by path (it is not copied);
  - the tests and the example compare the kit with the original functions and replay the recorded runs.

Nothing here writes outside the kit: an import by path is made with bytecode writing switched off, so no
cache file appears next to a source file. Set the environment variable STEPKIT_NOTES to use another
copy of the notes folder.
"""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
NOTES = os.environ.get("STEPKIT_NOTES") or os.path.normpath(os.path.join(HERE, "..", "..", ".."))

BENCH_DIR = os.path.join(NOTES, "work-2026-11-09-real-benchmarks")
MIXED_DIR = os.path.join(NOTES, "work-2026-11-10-node-sizer", "mixed")
MIXED_RUN = os.path.join(MIXED_DIR, "runs", "mixed-v1")
NEXT_TESTS = os.path.join(NOTES, "work-2026-11-12-next-tests")
T3_DIR = os.path.join(NEXT_TESTS, "t3-lazy-split")
T4_DIR = os.path.join(NEXT_TESTS, "t4-whole-loop")
T7_DIR = os.path.join(NEXT_TESTS, "t7-toolsmith")
T7_RUN = os.path.join(T7_DIR, "runs", "t7-v1")
REPLY_DIR = os.path.join(NEXT_TESTS, "reply-profile")
CORPUS_DIR = os.path.join(NOTES, "work-2026-11-10-traces-and-training", "corpus")

# name -> path of each source file the kit was refactored from
SOURCE_FILES = {
    "bench": os.path.join(BENCH_DIR, "bench.py"),
    "bench_mixed": os.path.join(MIXED_DIR, "bench_mixed.py"),
    "fingerprint": os.path.join(MIXED_DIR, "fingerprint.py"),
    "sandbox": os.path.join(T7_DIR, "sandbox.py"),
    "toolsmith": os.path.join(T7_DIR, "toolsmith.py"),
    "lazy_split": os.path.join(T3_DIR, "lazy_split.py"),
    "wtq_tools": os.path.join(T4_DIR, "wtq_tools.py"),
    "reply_profile": os.path.join(REPLY_DIR, "reply_profile.py"),
    "scoring": os.path.join(NEXT_TESTS, "t6-fine-tune", "scoring.py"),
}

# The split rule of test 7 (toolsmith.py, load_items): inside each kind, by the order of the items file,
# Tasks 1 to 40 are the library, 41 to 60 are the fit Tasks, the rest are the test Tasks.
N_LIBRARY, N_FIT = 40, 60


def load_by_path(name, path=None):
    """Import one source file by its path and return the module. No bytecode file is written.

    The module gets a private name, so it cannot hide a module of the caller. A source file that
    imports its neighbours by plain name still works: it adds its own folder to the search path itself.
    """
    path = path or SOURCE_FILES[name]
    key = "stepkit_source_" + name
    if key in sys.modules:
        return sys.modules[key]
    if not os.path.isfile(path):
        raise ImportError(f"source file not found: {path}")
    before = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location(key, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[key] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            sys.modules.pop(key, None)
            raise
    finally:
        sys.dont_write_bytecode = before
    return module


def split_by_position(items, n_library=N_LIBRARY, n_fit=N_FIT):
    """Give each Task its place inside its kind and its split, by the order of the list.

    Returns new dictionaries with two more fields: "pos" (0 for the first Task of a kind) and "split"
    ("library", "fit" or "test"). Same rule as test 7 (toolsmith.py, load_items).
    """
    seen, out = {}, []
    for item in items:
        pos = seen.get(item["kind"], 0)
        seen[item["kind"]] = pos + 1
        split = "library" if pos < n_library else ("fit" if pos < n_fit else "test")
        out.append(dict(item, pos=pos, split=split))
    return out
