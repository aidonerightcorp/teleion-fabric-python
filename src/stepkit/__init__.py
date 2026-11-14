# Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md
"""stepkit: reusable parts for doing a Task in small steps, each step profiled, decided and recorded.

    profile   measurements of a step's input and of its output (no model)
    reply     the reply profile: code reads a model's reply and gives a confidence that it is right
    tools     exact tools: calculator, safe program runners, lettered options, tables
    store     checked results found by similarity, with a familiarity floor that calibrates itself
    decide    which node to try and whether to accept its output; ready-made rules; works on live
              calls and on replays
    live      the live probe: the only part that calls a model (the local model server)
    record    the record of every step, with its cost

Importing this package calls no model and no network. Only `LiveProbes`, when a model node is
called, contacts the local model server. See README.md for a usage example and MEASURED.md for what
each part costs and what was measured with it.
"""
from . import decide, live, profile, record, reply, store, tools
from .decide import (Decision, KindTable, LiveProbes, MissingRecord, RecordedProbes, Step, first_accepted, ladder,
                     rule_e3, rule_e3b, rule_with_reply_checker)
from .profile import agreement, answer_form, grounded_numbers, output_profile, text_profile, unfamiliar
from .record import StepRecord, Trace
from .reply import ReplyChecker, check_equations, reply_features
from .store import CheckedStore

__all__ = ["decide", "live", "profile", "record", "reply", "store", "tools", "Decision", "KindTable", "LiveProbes",
           "MissingRecord", "RecordedProbes", "Step", "first_accepted", "ladder", "rule_e3", "rule_e3b",
           "rule_with_reply_checker", "agreement", "answer_form", "grounded_numbers", "output_profile", "text_profile",
           "unfamiliar", "StepRecord", "Trace", "ReplyChecker", "check_equations", "reply_features", "CheckedStore"]
