# Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md
"""A shared guard for the daily caps of shared plans and quotas: reserve, settle, refuse.

Why (MUST-FOLLOW.md, firm rule 1, added November 12, 2026): shared plans and quotas (a login or plan that the owner's
other agents also use) are budgets: cap our use per day and stop on a limit message. Several tests call the same
plan at the same time; each one reserves a call here before it starts the tool, so that all of them together can
never pass the day's cap. A refused reservation means the tool is not started.

    guard = QuotaGuard()                                   # the shared caps file and ledger
    held = guard.reserve("codex-gpt-6-astra", who="t24b", purpose="builder round 1")     # raises Refused
    ... run the tool ...
    guard.settle(held, ran=True, exit_status=0, seconds=41.2, reply=reply, stderr=err, error_events=messages)

The files, side by side (the ledger and the lock are always next to the caps file):
    quota-caps.json            every cap and rule as a Dimension (stepkit/dimension.py: suggested values, the first
                               in force; a grid; hard limits). The coordinator edits it. It is read again, under the
                               lock, at every reservation, so a change applies to the next call.
    quota-ledger.jsonl         one append-only JSON-lines ledger for every route. Events: reserve, settle, refuse,
                               stop, clear_stop. Times and days come from `date`. It never holds a prompt, a reply
                               or a credential: digests, counts and short labels only.
    quota-ledger.jsonl.lock    the lock (fcntl.flock on a fresh open of this file, so it holds between processes
                               and between threads of one process). Every read, decision and append is done under it.

The rules (all data in the caps file):
    - a day is the Eastern calendar day (quota.day_timezone) at the moment of the event
    - used today = calls reserved today, less the ones released. A reservation that is never settled stays counted:
      a caller that died may have spent the call
    - quota.<route>.release_when: a settled reservation is given back only when the tool never started
    - quota.<route>.on_limit_message: a limit or quota message in any reply stops the route until the next Eastern
      day. The error channels (the tool's error events and standard error) are read with a broad pattern
      (stop_pattern_errors); the final reply with a narrow one (stop_pattern_reply: the plan's own limit sentences and
      codes), so that a model's answer that only says "429" or "quota" does not stop the route. Which channels are
      read is quota.<route>.scan_channels. The matched words of a limit message are written to the ledger
    - fail closed: a route with no cap, a route another program governs (read_only), a damaged ledger line, a caps
      file or clock that cannot be read: refused
    - nobody raises a cap through this module: a cap comes only from the caps file, read through a resolver with no
      evidence. A caller may add a lower cap of its own (own_cap)

Routes that another program governs (the local adapter for the owner's Antigravity plan counts its own calls) are
mirrored read-only: `status` shows their cap and the adapter's own count, `reserve` refuses them, `check_mirrors`
compares the mirrored caps with the adapter's source (read with ast, never imported).

    python3 -m stepkit.quota status                   every route today (JSON)
    python3 -m stepkit.quota check-mirrors            exit 1 when a mirrored cap differs from its source
    python3 -m stepkit.quota clear-stop --route R --who W --why TEXT     the coordinator ends a stop set by mistake

Python 3 standard library only, and stepkit.dimension.
"""
import argparse
import ast
import contextlib
import fcntl
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from .dimension import LimitError, Resolver, Settings

HERE = os.path.dirname(os.path.abspath(__file__))
NEXT_TESTS = os.path.normpath(os.path.join(HERE, "..", ".."))
DEFAULT_CAPS = os.path.join(NEXT_TESTS, "quota-caps.json")
LEDGER_NAME = "quota-ledger.jsonl"
LOCK_SUFFIX = ".lock"
SCHEMA = "quota-ledger/1"
FILE_MODE = stat.S_IRUSR | stat.S_IWUSR                  # the ledger and the lock: this user only
ZONEINFO = "/usr/share/zoneinfo"
DATE_FORMAT = "+%Y-%m-%dT%H:%M:%S%:z"
DATE_PATH = "/usr/bin:/bin"

RESERVE, SETTLE, REFUSE, STOP, CLEAR_STOP = "reserve", "settle", "refuse", "stop", "clear_stop"
CHANNELS = ("error_events", "stderr", "reply")
STOP_UNTIL_NEXT_DAY, STOP_UNTIL_CLEARED = "stop_until_next_day", "stop_until_cleared"
RELEASE_IF_NOT_STARTED, RELEASE_NEVER = "tool_not_started", "never"

# the settings of the caps file: one for the day, the others for each route (quota.<route>.<what>)
DAY_TIMEZONE = "quota.day_timezone"
CAP, PATTERN_ERRORS, PATTERN_REPLY = "calls_per_day", "stop_pattern_errors", "stop_pattern_reply"
SCAN, ON_LIMIT, RELEASE = "scan_channels", "on_limit_message", "release_when"

# the reasons of a refusal, as the ledger writes them
CAPS_UNREADABLE = "caps_file_unreadable"
CLOCK_UNREADABLE = "clock_unreadable"
LOCK_UNAVAILABLE = "lock_unavailable"
LEDGER_DAMAGED = "ledger_damaged"
UNKNOWN_ROUTE = "unknown_route"
READ_ONLY_ROUTE = "read_only_route"
ROUTE_STOPPED = "route_stopped"
DAILY_CAP = "daily_cap_reached"
OWN_CAP = "own_cap_reached"

CAPS_ERRORS = (OSError, ValueError, KeyError, TypeError, LimitError)


def setting(route, what):
    """The name of a route's setting in the caps file: quota.<route>.<what>."""
    return f"quota.{route}.{what}"


def routes_of(settings):
    """The routes that have a cap in the caps file, in the file's order."""
    prefix, suffix = "quota.", "." + CAP
    return [name[len(prefix):-len(suffix)] for name in settings.names() if name.startswith(prefix) and name.endswith(suffix)]


def value_of(settings, name):
    """The value in force of a setting of the caps file: its first suggested value, read through a resolver that has
    no evidence, so that no caller can put another value in its place."""
    return Resolver().value(settings[name])


def read_only(settings, route):
    """True when another program governs this route (the caps file mirrors it)."""
    info = (settings.extra.get("routes") or {}).get(route) or {}
    return bool(info.get("read_only") or settings[setting(route, CAP)].extra.get("read_only"))


def digest(text):
    """The sha256 of a text (UTF-8), or None for None."""
    return None if text is None else hashlib.sha256(text.encode("utf-8")).hexdigest()


def _label(text, what, empty_ok=False):
    """A short label for the ledger, on one line. Never pass a prompt or a reply here."""
    text = " ".join(str(text or "").split())
    if not text and not empty_ok:
        raise ValueError(f"{what} must name the caller (for example the test, like t24b)")
    return text


class DateClock:
    """The time, read with `date` in a named time zone (the workspace rule: times come from `date`).

    `epoch` (seconds since 1970-01-01 UTC) fixes the instant, which is still read through `date`: a test that crosses
    midnight goes through the same code as a live call. A zone the system does not know is an error, because `date`
    would fall back to UTC without a word."""

    def __init__(self, epoch=None):
        self.epoch = epoch

    def now(self, timezone):
        if not os.path.isfile(os.path.join(ZONEINFO, str(timezone))):
            raise ValueError(f"the time zone {timezone!r} is not in {ZONEINFO}")
        command = ["date", DATE_FORMAT] + ([f"--date=@{self.epoch}"] if self.epoch is not None else [])
        done = subprocess.run(command, capture_output=True, text=True, check=True,
                              env={"TZ": str(timezone), "LC_ALL": "C", "PATH": DATE_PATH})
        return datetime.fromisoformat(done.stdout.strip())


@dataclass(frozen=True)
class Reservation:
    """One reserved call. Give it back to `QuotaGuard.settle` when the call is over."""
    route: str
    id: str
    day: str
    who: str
    purpose: str
    t: str
    cap: int
    used_before: int
    caps_sha256: str


class Refused(RuntimeError):
    """A refused reservation: nothing is reserved and the tool must not start. The refusal is on the ledger, unless
    `facts["recorded"]` is False (the ledger itself could not be written)."""

    def __init__(self, route, reason, detail, facts=None):
        super().__init__(f"{route}: refused ({reason}): {detail}")
        self.route, self.reason, self.detail, self.facts = route, reason, detail, dict(facts or {})


def find_limit_message(settings, route, reply=None, stderr=None, error_events=()):
    """The first limit or quota message in the channels a route reads: {"channel", "match"}, or None.

    The error channels (error events, standard error) are read with the route's broad pattern, the final reply with its
    narrow pattern. The match is the pattern's own words (keep the patterns free of open wildcards: the match is
    written to the ledger)."""
    channels = value_of(settings, setting(route, SCAN))
    broad = re.compile(value_of(settings, setting(route, PATTERN_ERRORS)), re.IGNORECASE)
    narrow = re.compile(value_of(settings, setting(route, PATTERN_REPLY)), re.IGNORECASE)
    scanned = []
    if "error_events" in channels:
        scanned += [("error_events", broad, str(message)) for message in (error_events or ())]
    if "stderr" in channels and stderr:
        scanned.append(("stderr", broad, str(stderr)))
    if "reply" in channels and reply:
        scanned.append(("reply", narrow, str(reply)))
    for channel, pattern, text in scanned:
        found = pattern.search(text)
        if found:
            return {"channel": channel, "match": found.group(0)}
    return None


def _used(events, route, day, release_rule, who=None):
    """Calls of a route counted on a day (for one caller when `who` is given): reserved that day, less those released
    under the rule in force (a settlement that says the tool never started)."""
    held = {}
    for event in events:
        if (event.get("route") == route and event.get("event") == RESERVE and event.get("day") == day
                and (who is None or event.get("who") == who)):
            held[event.get("id")] = event
    if release_rule == RELEASE_IF_NOT_STARTED:
        for event in events:
            if event.get("event") == SETTLE and event.get("id") in held and event.get("ran") is False:
                held.pop(event.get("id"))
    return len(held)


def _active_stop(events, route, day):
    """The stop in force for a route on a day, or None. A stop "until the next day" holds on the day it was set; a stop
    "until cleared" holds until a clear_stop event; a clear_stop ends every stop before it."""
    active = None
    for event in events:
        if event.get("route") != route:
            continue
        if event.get("event") == STOP and (event.get("rule") != STOP_UNTIL_NEXT_DAY or event.get("day") == day):
            active = event
        elif event.get("event") == CLEAR_STOP:
            active = None
    return active


def _assigned_value(path, name):
    """The literal value given to a module-level name in a Python source file, read with ast (the file is not run)."""
    with open(path, encoding="utf-8") as handle:
        tree = ast.parse(handle.read(), filename=path)
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            return ast.literal_eval(node.value)
    return None


def check_mirrors(caps_path=None):
    """The differences between each mirrored cap of the caps file and the value in the governing program's source:
    [{"route", "mirrored", "in_source", "source"}]. An empty list: every mirror holds."""
    caps_path = os.path.abspath(caps_path or DEFAULT_CAPS)
    with open(caps_path, encoding="utf-8") as handle:
        settings = Settings.from_dict(json.load(handle))
    out = []
    for route in routes_of(settings):
        if not read_only(settings, route):
            continue
        mirror = ((settings.extra.get("routes") or {}).get(route) or {}).get("mirror_of") or {}
        source = os.path.join(os.path.dirname(caps_path), str(mirror.get("file", "")))
        found = _assigned_value(source, mirror.get("name")) if os.path.isfile(source) else None
        in_source = found.get(mirror.get("key")) if isinstance(found, dict) else None
        mirrored = value_of(settings, setting(route, CAP))
        if in_source != mirrored:
            out.append({"route": route, "mirrored": mirrored, "in_source": in_source, "source": source})
    return out


class QuotaGuard:
    """Reserve, settle and refuse the calls of shared plans, per route and per Eastern day, for all processes at once.

    caps_path   the caps file (default: the shared one); the ledger and its lock are the files next to it. Another
                path is for tests only.
    clock       what reads the time (default: `date`); tests give a DateClock with a fixed instant.
    """

    def __init__(self, caps_path=None, clock=None):
        self.caps_path = os.path.abspath(caps_path or DEFAULT_CAPS)
        self.ledger_path = os.path.join(os.path.dirname(self.caps_path), LEDGER_NAME)
        self.lock_path = self.ledger_path + LOCK_SUFFIX
        self.clock = clock or DateClock()

    # ---- files ------------------------------------------------------------------------------------------------

    @contextlib.contextmanager
    def _locked(self):
        """The lock: a new open of the lock file each time, so that flock excludes other threads too."""
        handle = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, FILE_MODE)
        try:
            fcntl.flock(handle, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
            os.close(handle)

    def _read_caps(self):
        """(Settings, sha256 of the file)."""
        with open(self.caps_path, "rb") as handle:
            raw = handle.read()
        return Settings.from_dict(json.loads(raw.decode("utf-8"))), hashlib.sha256(raw).hexdigest()

    def _read_ledger(self):
        """(events in order, numbers of the lines that cannot be read)."""
        events, damaged = [], []
        if not os.path.exists(self.ledger_path):
            return events, damaged
        with open(self.ledger_path, encoding="utf-8", errors="replace") as lines:
            for number, line in enumerate(lines, start=1):
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except ValueError:
                    damaged.append(number)
                    continue
                if isinstance(event, dict) and "event" in event and "route" in event:
                    events.append(event)
                else:
                    damaged.append(number)
        return events, damaged

    def _append(self, event):
        """Append one line and flush it to disk. A last line that a crash cut short is ended first, so this one stays
        whole (the cut line then reads as damaged, and reservations are refused until a person looks)."""
        handle = os.open(self.ledger_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, FILE_MODE)
        try:
            data = (json.dumps(event, sort_keys=True, default=str) + "\n").encode("utf-8")
            size = os.fstat(handle).st_size
            if size:
                with open(self.ledger_path, "rb") as reader:
                    reader.seek(size - 1)
                    if reader.read() != b"\n":
                        data = b"\n" + data
            while data:
                data = data[os.write(handle, data):]
            os.fsync(handle)
        finally:
            os.close(handle)

    def _stamp(self, timezone=None):
        """(time, day) from `date` in the zone, or in the system's zone when the caps file gave none; (None, None)
        when `date` cannot be read."""
        try:
            if timezone is not None:
                now = self.clock.now(timezone)
            else:
                done = subprocess.run(["date", DATE_FORMAT], capture_output=True, text=True, check=True,
                                      env={"LC_ALL": "C", "PATH": DATE_PATH})
                now = datetime.fromisoformat(done.stdout.strip())
        except (OSError, ValueError, subprocess.CalledProcessError):
            return None, None
        return now.isoformat(), now.date().isoformat()

    def _timezone_or_none(self):
        try:
            return value_of(self._read_caps()[0], DAY_TIMEZONE)
        except CAPS_ERRORS:
            return None

    def _refusal(self, route, reason, detail, who, purpose, facts=None, timezone=None, stamp=None):
        """Inside the lock: write a refuse event and return the Refused error."""
        t, day = stamp or self._stamp(timezone)
        facts = dict(facts or {})
        event = {"v": SCHEMA, "t": t, "day": day, "route": route, "event": REFUSE, "reason": reason, "detail": detail,
                 "who": who, "purpose": purpose, "pid": os.getpid()}
        event.update({key: item for key, item in facts.items() if key not in event})
        try:
            self._append(event)
            facts["recorded"] = True
        except OSError as error:
            facts["recorded"], facts["record_error"] = False, str(error)
        return Refused(route, reason, detail, facts)

    # ---- the three acts -----------------------------------------------------------------------------------------

    def reserve(self, route, who, purpose="", own_cap=None):
        """Reserve one call of a route for today, or raise Refused (recorded). `own_cap` adds the caller's own lower
        cap for the day, counted over its own reservations (`who`)."""
        who, purpose = _label(who, "who"), _label(purpose, "purpose", empty_ok=True)
        if own_cap is not None and (isinstance(own_cap, bool) or not isinstance(own_cap, int) or own_cap < 0):
            raise ValueError("own_cap must be a whole number, zero or more")
        try:
            lock = self._locked()
            lock.__enter__()
        except OSError as error:
            raise Refused(route, LOCK_UNAVAILABLE, f"the lock {self.lock_path} cannot be taken: {error}",
                          {"recorded": False}) from error
        try:
            return self._reserve_locked(route, who, purpose, own_cap)
        finally:
            lock.__exit__(None, None, None)

    def _reserve_locked(self, route, who, purpose, own_cap):
        try:
            settings, caps_sha256 = self._read_caps()
            timezone = value_of(settings, DAY_TIMEZONE)
        except CAPS_ERRORS as error:
            raise self._refusal(route, CAPS_UNREADABLE, f"{self.caps_path}: {error}", who, purpose) from error
        known = {"caps_sha256": caps_sha256}
        try:
            now = self.clock.now(timezone)
        except (OSError, ValueError, subprocess.CalledProcessError) as error:
            raise self._refusal(route, CLOCK_UNREADABLE, f"`date` in {timezone!r}: {error}", who, purpose, known,
                                stamp=(None, None)) from error
        t, day = now.isoformat(), now.date().isoformat()
        stamp = (t, day)
        events, damaged = self._read_ledger()
        if damaged:
            raise self._refusal(route, LEDGER_DAMAGED, f"lines {damaged} of {self.ledger_path} cannot be read; a person "
                                "must look (copy the file aside before any repair)", who, purpose, known, stamp=stamp)
        if setting(route, CAP) not in settings:
            raise self._refusal(route, UNKNOWN_ROUTE, f"no cap for this route in {self.caps_path} (routes with a cap: "
                                f"{routes_of(settings)})", who, purpose, known, stamp=stamp)
        try:
            if read_only(settings, route):
                governed = ((settings.extra.get("routes") or {}).get(route) or {}).get("managed_by", "another program")
                raise self._refusal(route, READ_ONLY_ROUTE, f"this route is governed by {governed}; call it there (it "
                                    "counts and caps its own calls)", who, purpose, known, stamp=stamp)
            cap = value_of(settings, setting(route, CAP))
            rule = value_of(settings, setting(route, RELEASE))
        except CAPS_ERRORS as error:
            raise self._refusal(route, CAPS_UNREADABLE, f"{self.caps_path}: {error}", who, purpose, known,
                                stamp=stamp) from error
        known["cap"] = cap
        stop = _active_stop(events, route, day)
        if stop is not None:
            raise self._refusal(route, ROUTE_STOPPED, f"stopped since {stop.get('t')} by a limit message "
                                f"({stop.get('channel')}: {stop.get('match')!r}); rule {stop.get('rule')}, until "
                                f"{stop.get('until')}", who, purpose, known, stamp=stamp)
        used = _used(events, route, day, rule)
        if used >= cap:
            raise self._refusal(route, DAILY_CAP, f"{used} of {cap} calls used on {day} (Eastern) by all our tests "
                                "together", who, purpose, dict(known, used=used), stamp=stamp)
        if own_cap is not None:
            own_used = _used(events, route, day, rule, who)
            if own_used >= own_cap:
                raise self._refusal(route, OWN_CAP, f"{who} used {own_used} of its own cap of {own_cap} on {day}", who,
                                    purpose, dict(known, used=used, own_cap=own_cap, own_used=own_used), stamp=stamp)
        held = Reservation(route, uuid.uuid4().hex, day, who, purpose, t, cap, used, caps_sha256)
        self._append({"v": SCHEMA, "t": t, "day": day, "route": route, "event": RESERVE, "id": held.id, "who": who,
                      "purpose": purpose, "pid": os.getpid(), "cap": cap, "own_cap": own_cap, "used_before": used,
                      "caps_sha256": caps_sha256})
        return held

    def settle(self, held, ran, exit_status=None, seconds=None, timed_out=False, reply=None, stderr=None,
               error_events=(), prompt_sha256=None, notes=None):
        """Close a reservation: one settle event (digests and counts only), and one stop event when a channel holds a
        limit or quota message. `ran` says whether the tool started. `notes` are counts and short labels (never text
        of a prompt or a reply). Returns {"t", "released", "limit_message", "stopped", "scan"}."""
        with self._locked():
            events, _damaged = self._read_ledger()
            mine = [event for event in events if event.get("id") == held.id and event.get("route") == held.route]
            if not any(event.get("event") == RESERVE for event in mine):
                raise ValueError(f"no reservation {held.id} of {held.route} in {self.ledger_path}")
            if any(event.get("event") == SETTLE for event in mine):
                raise ValueError(f"the reservation {held.id} is already settled")
            try:
                settings, caps_sha256 = self._read_caps()
                timezone = value_of(settings, DAY_TIMEZONE)
                rule = value_of(settings, setting(held.route, RELEASE))
                problem = None
            except CAPS_ERRORS as error:
                settings, caps_sha256, timezone, rule, problem = None, None, None, RELEASE_NEVER, str(error)
            t, day = self._stamp(timezone)
            limit, scan = None, "not read: the tool did not start"
            if ran and settings is not None:
                limit, scan = find_limit_message(settings, held.route, reply, stderr, error_events), "read"
            elif ran:
                scan = f"not read: the caps file cannot be read ({problem})"
            released = (not ran) and rule == RELEASE_IF_NOT_STARTED
            event = {"v": SCHEMA, "t": t, "day": day, "route": held.route, "event": SETTLE, "id": held.id,
                     "who": held.who, "ran": bool(ran), "released": released, "exit_status": exit_status,
                     "seconds": seconds, "timed_out": bool(timed_out), "reply_sha256": digest(reply),
                     "reply_chars": None if reply is None else len(reply), "prompt_sha256": prompt_sha256,
                     "limit_message": limit is not None, "scan": scan, "caps_sha256": caps_sha256,
                     "notes": dict(notes or {})}
            self._append(event)
            if limit is not None:
                on_limit = value_of(settings, setting(held.route, ON_LIMIT))
                if day is not None:
                    following = (datetime.fromisoformat(day) + timedelta(days=1)).date().isoformat()
                    until = f"{following} 00:00 {timezone}" if on_limit == STOP_UNTIL_NEXT_DAY else "a clear_stop event"
                else:
                    until = "unknown (the clock could not be read)"
                self._append({"v": SCHEMA, "t": t, "day": day, "route": held.route, "event": STOP, "rule": on_limit,
                              "reservation": held.id, "who": held.who, "channel": limit["channel"],
                              "match": limit["match"], "until": until})
            return {"t": t, "released": released, "limit_message": limit, "stopped": limit is not None, "scan": scan}

    def refuse(self, route, reason, detail, who="", purpose="", facts=None):
        """Record a refusal that a caller decided before reserving (for example: the tool is not installed) and return
        the Refused error for the caller to raise. Every refusal is on the ledger."""
        who, purpose = _label(who, "who", empty_ok=True), _label(purpose, "purpose", empty_ok=True)
        with self._locked():
            return self._refusal(route, reason, detail, who, purpose, facts, timezone=self._timezone_or_none())

    # ---- reading and the coordinator's act ----------------------------------------------------------------------

    def clear_stop(self, route, who, why):
        """End a stop before its time (one set by mistake): a clear_stop event with who and why. The coordinator's
        act, not a test's. Returns the stop that was in force, or None."""
        who, why = _label(who, "who"), _label(why, "why")
        with self._locked():
            settings, _sha = self._read_caps()
            timezone = value_of(settings, DAY_TIMEZONE)
            now = self.clock.now(timezone)
            events, _damaged = self._read_ledger()
            day = now.date().isoformat()
            active = _active_stop(events, route, day)
            self._append({"v": SCHEMA, "t": now.isoformat(), "day": day, "route": route, "event": CLEAR_STOP,
                          "who": who, "why": why, "cleared": None if active is None else active.get("t")})
            return active

    def status(self, route=None):
        """Every route today (or one): cap, used, remaining, pending reservations, use by caller, refusals, the stop in
        force; for a mirrored route, the governing program's own count."""
        with self._locked():
            settings, caps_sha256 = self._read_caps()
            timezone = value_of(settings, DAY_TIMEZONE)
            now = self.clock.now(timezone)
            events, damaged = self._read_ledger()
        day = now.date().isoformat()
        out = {"t": now.isoformat(), "day": day, "time_zone": timezone, "caps_file": self.caps_path,
               "caps_sha256": caps_sha256, "ledger": self.ledger_path, "damaged_lines": damaged, "routes": {}}
        for name in (routes_of(settings) if route is None else [route]):
            out["routes"][name] = (self._mirror(settings, name, day) if read_only(settings, name)
                                   else self._route(settings, events, name, day))
        return out

    @staticmethod
    def _route(settings, events, route, day):
        cap = value_of(settings, setting(route, CAP))
        rule = value_of(settings, setting(route, RELEASE))
        reserved = [event for event in events
                    if event.get("route") == route and event.get("event") == RESERVE and event.get("day") == day]
        settled = {event.get("id"): event for event in events if event.get("event") == SETTLE}
        by_who = {}
        for event in reserved:
            released = rule == RELEASE_IF_NOT_STARTED and settled.get(event.get("id"), {}).get("ran") is False
            if not released:
                by_who[event.get("who")] = by_who.get(event.get("who"), 0) + 1
        used = _used(events, route, day, rule)
        stop = _active_stop(events, route, day)
        return {"governed_by": "this guard", "cap": cap, "used": used, "remaining": max(cap - used, 0),
                "pending": [event.get("id") for event in reserved if event.get("id") not in settled], "by_who": by_who,
                "refused_today": sum(1 for event in events if event.get("route") == route
                                     and event.get("event") == REFUSE and event.get("day") == day),
                "stopped": None if stop is None else {key: stop.get(key) for key in ("t", "rule", "channel", "match", "until")}}

    def _mirror(self, settings, route, day):
        info = (settings.extra.get("routes") or {}).get(route) or {}
        mirror = info.get("mirror_of") or {}
        log = os.path.join(os.path.dirname(self.caps_path), str(mirror.get("log", "")))
        family, counts = str(mirror.get("key", "")), {"success": 0, "error": 0, "refused": 0}
        if os.path.isfile(log):
            with open(log, encoding="utf-8", errors="replace") as lines:
                for line in lines:
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    if not str(row.get("t", "")).startswith(day) or not str(row.get("model", "")).startswith(family):
                        continue
                    status = str(row.get("status", ""))
                    counts["success" if status == "SUCCESS" else "refused" if status.startswith("refused") else "error"] += 1
        cap = value_of(settings, setting(route, CAP))
        return {"governed_by": info.get("managed_by"), "read_only": True, "cap_mirrored": cap,
                "used_as_the_adapter_counts": counts["success"], "remaining_as_the_adapter_counts": max(cap - counts["success"], 0),
                "errors_today": counts["error"], "refused_today": counts["refused"], "log": log,
                "note": "the adapter counts its SUCCESS calls of the family on its own local day; it is the authority"}


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python3 -m stepkit.quota", description=__doc__.split("\n\n")[0])
    parser.add_argument("--caps", help="another caps file (tests only); the ledger is the file next to it")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="every route today, as JSON")
    sub.add_parser("check-mirrors", help="compare the mirrored caps with the governing program's source")
    clear = sub.add_parser("clear-stop", help="the coordinator ends a stop set by mistake (recorded with who and why)")
    clear.add_argument("--route", required=True)
    clear.add_argument("--who", required=True)
    clear.add_argument("--why", required=True)
    args = parser.parse_args(argv)
    if args.command == "check-mirrors":
        differences = check_mirrors(args.caps)
        print(json.dumps(differences, indent=1))
        return 1 if differences else 0
    guard = QuotaGuard(args.caps)
    if args.command == "status":
        print(json.dumps(guard.status(), indent=1))
        return 0
    print(json.dumps({"cleared": guard.clear_stop(args.route, args.who, args.why)}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
