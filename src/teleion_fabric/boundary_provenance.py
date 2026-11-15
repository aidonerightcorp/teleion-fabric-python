# Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md
"""Body-only boundary evidence and fail-closed output envelope diagnostics.

Default retention is body digests only. An optional caller-supplied CAS sink
receives raw body bytes and must return `{digest, size_bytes}`; no headers,
environment variables, filesystem paths, or credentials are recorded.
"""
import copy
import hashlib
import threading

from . import prose_tools as Prose
from . import settings as S


class BoundaryProvenance:
    """Thread-safe body-only digest tracker across provider and harness boundaries."""

    def __init__(self, attempt, model, sink=None, config_overrides=None):
        if type(attempt) is not str or not attempt or type(model) is not str or not model:
            raise ValueError("exact request identity required")
        if sink is not None and not callable(sink):
            raise ValueError("private body sink must be callable")
        selected = S.select(S.load("boundary"), config_overrides)
        self._schema = selected["schema_version"]["value"]
        self._required = list(selected["required_boundaries"]["value"])
        self._max_body_bytes = selected["max_body_bytes"]["value"]
        self._sink = sink
        self._lock = threading.RLock()
        self._data = {
            "schema": self._schema,
            "identity": {"attempt_id": attempt, "model": model, "task_id": None},
            "retention": "private_cas" if sink else "hash_only",
            "max_body_bytes": self._max_body_bytes,
            "boundaries": {},
            "link_status": "not_observed",
        }

    def bind(self, task_id, attempt_id):
        with self._lock:
            identity = self._data["identity"]
            if type(task_id) is not str or not task_id or attempt_id != identity["attempt_id"]:
                raise ValueError("boundary identity mismatch")
            if identity["task_id"] not in (None, task_id):
                raise ValueError("boundary task already bound")
            identity["task_id"] = task_id

    def capture(self, name, body, *, complete=True):
        if type(name) is not str or not name:
            raise ValueError("nonempty boundary name required")
        if type(body) is not bytes or type(complete) is not bool:
            raise TypeError("exact body bytes and completeness required")
        within_cap = len(body) <= self._max_body_bytes
        effective_complete = complete and within_cap
        clipped = body[: self._max_body_bytes] if not within_cap else body
        digest = hashlib.sha256(clipped).hexdigest()
        with self._lock:
            if name in self._data["boundaries"]:
                raise ValueError("boundary already captured")
            record = {
                "status": "complete" if effective_complete else "partial",
                "size_bytes": len(body),
                ("sha256" if effective_complete else "partial_sha256"): digest,
            }
            if not within_cap:
                record["truncated_at_cap"] = True
            self._data["boundaries"][name] = record
            if self._sink is not None and effective_complete:
                try:
                    ref = self._sink(body)
                    if (
                        type(ref) is not dict
                        or set(ref) != {"digest", "size_bytes"}
                        or type(ref["digest"]) is not str
                        or ref["digest"] != digest
                        or type(ref["size_bytes"]) is not int
                        or ref["size_bytes"] != len(body)
                    ):
                        raise ValueError("invalid private CAS reference")
                    record["cas_ref"] = dict(ref)
                except Exception as exc:
                    record["retention_error_type"] = type(exc).__name__
                    self._data["link_status"] = "capture_failed"
                    raise RuntimeError("private boundary capture failed") from None
            return copy.deepcopy(record)

    def unavailable(self, name, error_type):
        if type(name) is not str or not name or type(error_type) is not str or not error_type:
            raise ValueError("boundary name and error_type required")
        with self._lock:
            if name not in self._data["boundaries"]:
                self._data["boundaries"][name] = {"status": "unavailable", "error_type": error_type}

    def link_harness(self, stdout, text):
        if type(stdout) is not str or type(text) is not str:
            raise TypeError("harness stdout and text must be strings")
        self.capture("harness_stdout", stdout.encode("utf-8"))
        self.capture("harness_text", text.encode("utf-8"))
        with self._lock:
            boundaries = self._data["boundaries"]
            complete = self._data["identity"]["task_id"] is not None and all(
                boundaries.get(key, {}).get("status") == "complete"
                and "retention_error_type" not in boundaries[key]
                for key in self._required
            )
            if not complete:
                self._data["link_status"] = "incomplete"
            elif boundaries["native_content"]["sha256"] == boundaries["harness_text"]["sha256"]:
                self._data["link_status"] = "matched"
            else:
                self._data["link_status"] = "text_mismatch"

    def snapshot(self):
        with self._lock:
            return copy.deepcopy(self._data)


strict_json = Prose.strict_json
diagnose_json_boundary = Prose.diagnose_json_boundary
