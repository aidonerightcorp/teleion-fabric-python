# Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md
"""Portable record retention, task-text redaction, and data-use boundaries.

Every tunable threshold, field list, and write limit is resolved from
`RETENTION_SETTINGS` (`stepkit/data/retention-settings.json`). No service
credentials, network calls, or local filesystem paths are embedded.
"""
import datetime
import hashlib
from importlib.resources import files
import json
import math
import os
import re

import numpy as np

from .dimension import Resolver, Settings
from .record import task_text_of

WITHHELD = "[Task text withheld]"
ELLIPSIS = "..."
RUN_SCHEMA = "stepkit.node_record.v1"
DATA_USE_SUBSETS = {
    "open": {"open", "benchmark: no training"},
    "benchmark: no training": {"benchmark: no training"},
}
HERE = os.path.dirname(os.path.abspath(__file__))

RETENTION_SETTINGS = Settings.from_dict(
    json.loads(files("stepkit").joinpath("data/retention-settings.json").read_text(encoding="utf-8"))
)


class RecordConflictError(RuntimeError):
    """A compare-and-set version expectation or idempotency constraint failed."""

    def __init__(self, message, current_version=None):
        super().__init__(message)
        self.current_version = current_version


class RecordLimitError(RuntimeError):
    """A writer reached its configured `records.max_writes` limit."""


def _contract_error(message):
    from .omninode import ContractError

    return ContractError(message)


def setting(name, resolver=None, settings=None):
    """Resolve one setting from `RETENTION_SETTINGS` (or a caller-supplied Settings)."""
    return (resolver or Resolver()).value((settings or RETENTION_SETTINGS)[name])


def _whole(value, exact_limit, decimal_limit):
    """Normalize whole floats to integers within exact IEEE-754 bounds."""
    if isinstance(value, int) and not isinstance(value, bool) and abs(value) >= exact_limit:
        try:
            as_float = float(value)
        except OverflowError as exc:
            raise ValueError("JSON integers must fit IEEE-754") from exc
        if int(as_float) != value:
            raise ValueError("JSON integers must round-trip through IEEE-754")
        return as_float if abs(value) >= decimal_limit else value
    if isinstance(value, float) and value.is_integer() and abs(value) < decimal_limit:
        return int(value)
    if isinstance(value, dict):
        return {k: _whole(v, exact_limit, decimal_limit) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_whole(v, exact_limit, decimal_limit) for v in value]
    return value


def canonical_json(value, resolver=None) -> str:
    """Deterministic UTF-8 JSON string without NaN/Infinity."""
    exact_limit = setting("records.ieee754_exact_int_limit", resolver)
    decimal_limit = setting("records.decimal_int_limit", resolver)
    return json.dumps(
        _whole(value, exact_limit, decimal_limit),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def canonical_digest(value, resolver=None) -> str:
    """Hex digest of canonical JSON bytes."""
    return hashlib.sha256(canonical_json(value, resolver=resolver).encode("utf-8")).hexdigest()


def plain_json(value):
    """Convert rich values (numpy scalars/arrays, sets, custom records) into plain JSON types."""
    if isinstance(value, np.ndarray):
        return plain_json(value.tolist())
    if isinstance(value, np.generic):
        return plain_json(value.item())
    if hasattr(value, "to_dict"):
        return plain_json(value.to_dict())
    if isinstance(value, dict):
        return {str(key): plain_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain_json(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((plain_json(item) for item in value), key=lambda item: json.dumps(item, sort_keys=True, default=str))
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


def record_key(*parts, resolver=None) -> str:
    """Normalized record key bounded by `records.key_max_chars`."""
    raw = ":".join(str(part) for part in parts if part is not None and str(part) != "")
    text = re.sub(r":\s+", ":", raw.strip())
    text = re.sub(r"\s+", "_", text)
    text = re.sub(r"[^A-Za-z0-9_.:-]", "-", text)
    if not text or not text[0].isalnum():
        text = "k" + text
    key_max = setting("records.key_max_chars", resolver)
    if len(text) > key_max:
        digits = setting("records.digest_digits", resolver)
        prefix_len = key_max - 1 - digits
        text = text[:prefix_len] + "-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:digits]
    return text


def module_lineage(
    names=("omninode.py", "store.py", "record.py", "dimension.py", "assembler.py", "retention.py"),
    resolver=None,
) -> dict:
    """Short source digests for bundled stepkit modules."""
    digits = setting("records.digest_digits", resolver)
    out = {}
    for name in names:
        path = os.path.join(HERE, name)
        if os.path.isfile(path):
            with open(path, "rb") as handle:
                out[name] = hashlib.sha256(handle.read()).hexdigest()[:digits]
    return out


def utc_now() -> str:
    """Current UTC timestamp at second precision."""
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


def task_text_allowed(contract) -> bool:
    """True only when `records.task_text` is explicitly boolean True on the contract."""
    if contract is None:
        return False
    if hasattr(contract, "get") and not isinstance(contract, dict):
        found = contract.get("records.task_text")
        return bool(found is not None and found.suggested[0] is True)
    if isinstance(contract, dict):
        return contract.get("records.task_text") is True
    return False


def record_task_text_allowed(record) -> bool:
    """Effective run policy may narrow, never widen, declared task-text retention."""
    declared = task_text_allowed(getattr(record, "contract", None))
    if not hasattr(record, "effective_policy"):
        return declared
    effective = record.effective_policy
    if not isinstance(effective, dict):
        return False
    return bool(declared and effective.get("records.task_text", declared) is True)


def declared_data_use(contract, default_use="benchmark: no training") -> str:
    """Extract and validate declared `records.data_use` from a Contract or summary dict."""
    if contract is None:
        value = default_use
    elif hasattr(contract, "get") and not isinstance(contract, dict):
        found = contract.get("records.data_use")
        value = found.suggested[0] if found is not None else default_use
    elif isinstance(contract, dict):
        value = contract.get("records.data_use", default_use)
    else:
        raise _contract_error("malformed record contract for records.data_use")
    if not isinstance(value, str) or value not in DATA_USE_SUBSETS:
        raise _contract_error(f"invalid declared records.data_use {value!r}")
    return value


def record_data_use(record, requested_data_use=None, default_use="benchmark: no training") -> str:
    """Resolve effective `records.data_use` with monotonic narrowing and fail-closed override checks."""
    declared = declared_data_use(getattr(record, "contract", None), default_use=default_use)
    effective_use = declared
    if hasattr(record, "effective_policy"):
        effective = record.effective_policy
        if not isinstance(effective, dict):
            effective_use = "benchmark: no training"
        elif "records.data_use" in effective:
            candidate = effective["records.data_use"]
            if not isinstance(candidate, str) or candidate not in DATA_USE_SUBSETS.get(declared, set()):
                raise _contract_error(
                    f"effective policy records.data_use {candidate!r} widens declared {declared!r}"
                )
            effective_use = candidate
    if requested_data_use is not None:
        if not isinstance(requested_data_use, str) or requested_data_use not in DATA_USE_SUBSETS:
            raise _contract_error(f"invalid requested data_use {requested_data_use!r}")
        if requested_data_use not in DATA_USE_SUBSETS.get(effective_use, set()):
            raise _contract_error(
                f"requested data_use {requested_data_use!r} widens effective {effective_use!r}"
            )
        effective_use = requested_data_use
    return effective_use


def withhold_task_text(value, texts=(), fields=None, resolver=None):
    """Return a copy with named task-text fields and matching strings replaced by `WITHHELD`."""
    shortest = setting("records.withhold_min_chars", resolver)
    part_limit = setting("records.withhold_part_chars", resolver)
    field_names = set(setting("records.text_fields", resolver) if fields is None else fields)
    usable = [text.strip() for text in texts if isinstance(text, str) and len(text.strip()) >= shortest]

    def holds_text(item):
        return any(text in item or (len(item) >= part_limit and item.strip() in text) for text in usable)

    def walk(item):
        if isinstance(item, dict):
            return {
                key: (WITHHELD if key in field_names and item[key] not in (None, "", [], {}) else walk(part))
                for key, part in item.items()
            }
        if isinstance(item, list):
            return [walk(part) for part in item]
        if isinstance(item, str) and holds_text(item):
            return WITHHELD
        return item

    return walk(value)


def _redact_strings(item):
    if isinstance(item, str):
        return WITHHELD if item else item
    if isinstance(item, list):
        return [_redact_strings(part) for part in item]
    if isinstance(item, dict):
        return {key: _redact_strings(part) for key, part in item.items()}
    return item


def _withhold_unverified_echo_fields(body: dict) -> dict:
    """When retention is denied and no usable task text was supplied, scrub free-form string echoes."""
    out = dict(body)
    for key in ("answer", "reason"):
        if key in out:
            out[key] = _redact_strings(out[key])
    if isinstance(out.get("output_validation"), dict):
        validation = dict(out["output_validation"])
        if "raw_answer" in validation:
            validation["raw_answer"] = _redact_strings(validation["raw_answer"])
        out["output_validation"] = validation
    if isinstance(out.get("evidence"), dict):
        evidence = dict(out["evidence"])
        for key in ("answer", "raw_answer", "why"):
            if key in evidence:
                evidence[key] = _redact_strings(evidence[key])
        out["evidence"] = evidence
    if isinstance(out.get("steps"), list):
        steps = []
        for step in out["steps"]:
            if not isinstance(step, dict):
                steps.append(step)
                continue
            cleaned = dict(step)
            for key in ("answer", "reason"):
                if key in cleaned:
                    cleaned[key] = _redact_strings(cleaned[key])
            if isinstance(cleaned.get("output_profile"), dict):
                profile = dict(cleaned["output_profile"])
                for key in ("answer", "raw_answer", "why"):
                    if key in profile:
                        profile[key] = _redact_strings(profile[key])
                cleaned["output_profile"] = profile
            steps.append(cleaned)
        out["steps"] = steps
    return out


def _short(value, limit):
    text = json.dumps(plain_json(value), ensure_ascii=False)
    return text if len(text) <= limit else text[: limit - len(ELLIPSIS)] + ELLIPSIS


class MemoryRecordPort:
    """Deterministic in-memory record and submission port for offline qualification."""

    def __init__(self, clock=utc_now, resolver=None):
        self.clock = clock
        self.resolver = resolver or Resolver()
        self.records = {}
        self.results = {}
        self.calls = []
        self.writes = 0

    def _view(self, row):
        out = dict(row)
        out["value"] = json.loads(row["value"])
        out["tags"] = list(row["tags"])
        return out

    def get(self, store, key, version=None):
        self.calls.append(("get", store, key))
        rows = self.records.get((store, key))
        if not rows:
            return None
        if version is None:
            return self._view(rows[-1])
        return self._view(rows[version - 1]) if 1 <= version <= len(rows) else None

    def history(self, store, key):
        return [self._view(row) for row in self.records.get((store, key), [])]

    def list(self, store, prefix=""):
        self.calls.append(("list", store, prefix))
        return [
            self._view(rows[-1])
            for (name, key), rows in sorted(self.records.items())
            if name == store and key.startswith(prefix)
        ]

    def put(self, store, key, value, expected_version=0, tags=(), visibility="private"):
        self.calls.append(("put", store, key))
        rows = self.records.setdefault((store, key), [])
        head = len(rows)
        if (expected_version in (None, 0) and head) or (expected_version not in (None, 0) and expected_version != head):
            raise RecordConflictError(
                f"{store}/{key}: expected version {expected_version}, head is {head or None}",
                head or None,
            )
        row = {
            "store": store,
            "key": key,
            "version": head + 1,
            "value": canonical_json(plain_json(value), resolver=self.resolver),
            "tags": list(dict.fromkeys(tags)),
            "visibility_scope": visibility,
            "created_at": self.clock(),
        }
        rows.append(row)
        self.writes += 1
        return self._view(row)

    def submit(
        self,
        task_id,
        fencing_token,
        output,
        idempotency_key=None,
        ok=True,
        error=None,
        execution_report=None,
    ):
        self.calls.append(("submit", task_id, idempotency_key))
        done = self.results.get(task_id)
        if done is not None:
            if done["idempotency_key"] == idempotency_key:
                return dict(done["envelope"])
            raise RecordConflictError(f"Task {task_id!r} already has a submitted result")
        normalized_output = json.loads(canonical_json(plain_json(output), resolver=self.resolver))
        normalized_report = (
            json.loads(canonical_json(plain_json(execution_report), resolver=self.resolver))
            if execution_report is not None
            else None
        )
        envelope = {
            "task_id": task_id,
            "fencing_token": fencing_token,
            "ok": bool(ok),
            "submission_digest": canonical_digest(
                {
                    "task_id": task_id,
                    "fencing_token": fencing_token,
                    "ok": bool(ok),
                    "output": normalized_output,
                    "error": error,
                },
                resolver=self.resolver,
            ),
        }
        self.results[task_id] = {
            "idempotency_key": idempotency_key,
            "envelope": envelope,
            "output": normalized_output,
            "execution_report": normalized_report,
        }
        self.writes += 1
        return dict(envelope)


class NodeRecordSink:
    """Persist `NodeRecord` trees and queue execution reports under strict privacy boundaries."""

    def __init__(self, port, run, worker="kit-replay", store=None, resolver=None, when=None):
        self.port = port
        self.resolver = resolver or Resolver()
        self.run = record_key(run, resolver=self.resolver)
        self.store = store or setting("records.store", self.resolver)
        self.maker = dict(setting("records.maker", self.resolver), worker=worker)
        self.default_use = setting("records.data_use", self.resolver)
        self.max_writes = setting("records.max_writes", self.resolver)
        self.text_fields = setting("records.text_fields", self.resolver)
        self.summary_chars = setting("records.summary_chars", self.resolver)
        self.report_version = setting("records.report_schema_version", self.resolver)
        self.lineage = module_lineage(resolver=self.resolver)
        self.when = when or utc_now()
        self.written = []

    def key_of(self, record) -> str:
        return record_key(
            self.run,
            record.task_id if record.task_id is not None else "list",
            record.node_id,
            resolver=self.resolver,
        )

    def _task_context_info(self, task):
        min_chars = setting("records.withhold_min_chars", self.resolver)
        text = task_text_of(task) if task is not None else None
        usable = isinstance(text, str) and len(text.strip()) >= min_chars
        extras = [text] if usable else []
        if isinstance(task, dict):
            for field_name in self.text_fields:
                candidate = task.get(field_name)
                if isinstance(candidate, str) and len(candidate.strip()) >= min_chars and candidate not in extras:
                    extras.append(candidate)
        return text, usable, extras

    def value_of(self, record, task=None, data_use=None, child_keys=None) -> dict:
        """Build the sanitized persisted value for one `NodeRecord`."""
        effective_use = record_data_use(record, requested_data_use=data_use, default_use=self.default_use)
        body = record.to_dict()
        keys = child_keys if child_keys is not None else [self.key_of(child) for child in record.children]
        body["children"] = [
            {"node_id": child.node_id, "key": key}
            for child, key in zip(record.children, keys, strict=True)
        ]
        body = plain_json(body)
        if isinstance(body.get("effective_policy"), dict):
            body["effective_policy"] = dict(body["effective_policy"], **{"records.data_use": effective_use})
        allowed = record_task_text_allowed(record)
        text, usable_text, candidate_texts = self._task_context_info(task)
        if not allowed:
            body = withhold_task_text(body, candidate_texts, self.text_fields, self.resolver)
            if not usable_text:
                body = _withhold_unverified_echo_fields(body)
        stages = " > ".join(step.stage for step in record.steps) or "no stage of its own"
        return {
            "kind": "task_object",
            "schema": RUN_SCHEMA,
            "key": self.key_of(record),
            "title": f"Kit run {self.run}: Task {record.task_id}, node {record.node_id}",
            "l0_summary": (
                f"{record.role or 'node'} at depth {record.depth}: {stages}; answer "
                f"{_short(body['answer'], self.summary_chars)}; accepted {record.accepted}; "
                f"model seconds {record.cost_with_children.get('model_s', 0.0):.3f}"
            ),
            "run": self.run,
            "task_id": record.task_id,
            "node_id": record.node_id,
            "maker": self.maker,
            "data_use": effective_use,
            "task_text": text if allowed and usable_text else None,
            "lineage": dict(self.lineage, kit="stepkit"),
            "made_at": self.when,
            "record": body,
        }

    def tags_of(self, value) -> list:
        use = re.sub(r"[^a-z0-9]+", "-", str(value["data_use"]).lower()).strip("-")
        return ["kind:kit_run", "task_object", f"data-use:{use}", f"run:{self.run}"]

    def write(self, record, task=None, data_use=None) -> dict:
        """Persist `record` and all descendants (children first), enforcing `records.max_writes`."""
        child_keys = [self.write(child, task, data_use)["key"] for child in record.children]
        if len(self.written) >= self.max_writes:
            raise RecordLimitError(
                f"writer reached configured records.max_writes ({self.max_writes})"
            )
        value = self.value_of(record, task, data_use, child_keys)
        out = self.port.put(self.store, value["key"], value, expected_version=0, tags=self.tags_of(value))
        done = {"key": value["key"], "version": out["version"], "digest": canonical_digest(value, resolver=self.resolver)}
        self.written.append(done)
        return done

    def verify(self) -> list:
        """Read back every written record and compare canonical digests."""
        rows = []
        for done in self.written:
            read = self.port.get(self.store, done["key"], done["version"])
            digest = canonical_digest(read["value"], resolver=self.resolver) if read is not None else None
            rows.append(dict(done, read=digest, equal=digest == done["digest"]))
        return rows

    def execution_report(self, record, task=None, data_use=None) -> dict:
        """Build a privacy-bounded telemetry execution report for queue submission."""
        effective_use = record_data_use(record, requested_data_use=data_use, default_use=self.default_use)
        allowed = record_task_text_allowed(record)
        text, usable_text, candidate_texts = self._task_context_info(task)
        if not allowed and not usable_text:
            solution = WITHHELD
        else:
            content = {"answer": plain_json(record.answer), "reason": record.reason}
            if not allowed:
                content = withhold_task_text(content, candidate_texts, self.text_fields, self.resolver)
            solution = f"answer {_short(content['answer'], self.summary_chars)}: {content['reason']}"
        used = record.cost_with_children
        models = sorted(
            {
                str(step.settings.get("model"))
                for node in record.walk()
                for step in node.steps
                if step.cost.get("calls") and step.settings.get("model")
            }
        )
        tokens_in, tokens_out = int(used.get("tok_in", 0)), int(used.get("tok_out", 0))
        return {
            "version": self.report_version,
            "data_use": effective_use,
            "task_text_retained": bool(allowed and usable_text),
            "harness": {
                "name": self.maker["id"],
                "version": self.lineage.get("omninode.py", ""),
                "role": record.role or "node",
                "worker": self.maker["worker"],
            },
            "model": {
                "ids": models,
                "attempts": int(used.get("calls", 0)),
                "model_seconds": float(used.get("model_s", 0.0)),
            }
            if models
            else None,
            "summaries": {"problem": "", "solution": solution},
            "usage": {
                "input_tokens": tokens_in,
                "output_tokens": tokens_out,
                "total_tokens": tokens_in + tokens_out,
                "source": "the node record's cost",
            },
        }

    def submit(self, task_id, fencing_token, record, idempotency_key=None, task=None, data_use=None) -> dict:
        """Submit the functional task output alongside a sanitized execution report."""
        report = self.execution_report(record, task=task, data_use=data_use)
        output = {"answer": plain_json(record.answer), "accepted": bool(record.accepted), "reason": record.reason}
        return self.port.submit(
            task_id,
            fencing_token,
            output,
            idempotency_key=idempotency_key
            or record_key(self.run, task_id, record.node_id, resolver=self.resolver),
            execution_report=report,
        )
