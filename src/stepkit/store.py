# Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md
"""A store of checked results, searched by similarity. No model is needed to search it.

An entry is a Task text with a payload (for example a program that gave the right answer), a kind, and
a flag that says whether the payload was checked. Two questions can be asked:
  nearest(...)     the most similar entries, to reuse their payloads (checked entries only, by default)
  kind_vote(...)   the kind that the most similar entries name, with how similar the nearest one is

Similarity is the cosine of text vectors when the caller gives vectors. Without vectors it is a
built-in text similarity that needs no model: the cosine of word and word-pair counts (the "words"
level of the source fingerprint, counted exactly and not through a fixed number of buckets).

Sources (under the notes folder):
  work-2026-11-12-next-tests/t7-toolsmith/toolsmith.py   load_vectors, load_library, neighbours
  work-2026-11-12-next-tests/t7-toolsmith/replay_t7.py   predicted_kind (here: kind_vote)
  work-2026-11-10-node-sizer/mixed/fingerprint.py        the "words" level
Needs numpy.

How the kind vote treats entries with the same similarity is the setting "store.tie_break" (added November 12,
2026, 23:15, J1): in the order they were added (the rule of every recorded figure), by key (the same vote
whatever the order of loading), or in the order they were added but with no vote at all when the most similar
entry has similarity 0 (with the text measure: no entry shares a word with the Task). `nearest` keeps the order
entries were added.
"""
import json
import math
import re
from collections import Counter

import numpy as np

from ._sources import N_LIBRARY
from .dimension import CHOICES, Dimension, Resolver, Settings

_TOKEN = re.compile(r"\b\w\w+\b")  # a word of two or more letters or digits, as the source's vectorizer reads it

SETTINGS = Settings(name="store", dimensions=[
    Dimension("store.tie_break", ["load_order", "by_key", "no_vote_when_all_zero"], kind=CHOICES,
              about="the kind vote among entries with the same similarity: the order they were added (every recorded "
                    "figure), their keys (a store votes the same however it was loaded), or the order they were added "
                    "with no vote at all when the most similar entry has similarity 0 (kind None)"),
])


def text_terms(text):
    """The words and word pairs of a text with their weights, scaled so the weights have length 1."""
    tokens = _TOKEN.findall(text.lower())
    counts = Counter(tokens)
    counts.update(a + " " + b for a, b in zip(tokens, tokens[1:]))
    length = math.sqrt(sum(c * c for c in counts.values()))
    return {term: c / length for term, c in counts.items()} if length else {}


def text_similarity(a, b):
    """Cosine of the word and word-pair counts of two texts: 1 for the same words, 0 for no shared word."""
    ta, tb = text_terms(a), text_terms(b)
    if len(tb) < len(ta):
        ta, tb = tb, ta
    return float(sum(w * tb.get(term, 0.0) for term, w in ta.items()))


def _unit(vector):
    a = np.asarray(vector, dtype=np.float32)
    return a / max(float(np.linalg.norm(a)), 1e-9)


class _Load:
    """Makes `load` work in both ways: `CheckedStore.load(path)` gives a new store, and
    `store.load(path)` adds the entries of the file to that store (an entry with the same key is replaced)."""

    def __get__(self, store, cls):
        def load(path):
            """Read a file written by `save`. Returns the store."""
            return (cls() if store is None else store)._read(path)
        return load


class CheckedStore:
    """Entries with a text, a payload and a kind, found by similarity."""

    def __init__(self, resolver=None):
        self.resolver = resolver or Resolver()      # gives the store's settings (SETTINGS) and writes them down
        self._tie_break = None
        self._entries = []     # dictionaries: key, text, payload, kind, checked, vector (unit length or None)
        self._position = {}    # key -> index in _entries
        self._terms = []       # word and word-pair weights of each entry
        self._text_index = None    # the indexes below are made on first use and dropped by add()
        self._vector_index = None
        self._masks = None
        self._floors = {}

    def __len__(self):
        return len(self._entries)

    def __contains__(self, key):
        return key in self._position

    def keys(self):
        return [entry["key"] for entry in self._entries]

    def has_vectors(self) -> bool:
        """True when at least one entry has a text vector."""
        return any(entry["vector"] is not None for entry in self._entries)

    @property
    def tie_break(self):
        """The rule "store.tie_break" of this store's kind vote, asked once from its resolver."""
        if self._tie_break is None:
            self._tie_break = self.resolver.value(SETTINGS["store.tie_break"])
        return self._tie_break

    def get(self, key):
        """The entry stored under a key (without a similarity), or None."""
        position = self._position.get(key)
        return None if position is None else self._public(position)

    def add(self, key, text, payload, *, kind=None, checked=True, vector=None):
        """Store one entry. An entry with the same key is replaced.

        `checked` says that the payload passed a check (for a program: its answer was right). An entry
        that is not checked still has a text and a kind, so it counts in `kind_vote`; `nearest` leaves
        it out unless the caller asks for it. `vector` is the text vector of the entry, when there is one.
        """
        self._put(key, text, payload, kind, checked, None if vector is None else _unit(vector))

    def _put(self, key, text, payload, kind, checked, unit_vector):
        entry = {"key": key, "text": text, "payload": payload, "kind": kind, "checked": bool(checked),
                 "vector": unit_vector}
        position = self._position.get(key)
        if position is None:
            self._position[key] = len(self._entries)
            self._entries.append(entry)
            self._terms.append(text_terms(text))
        else:
            self._entries[position] = entry
            self._terms[position] = text_terms(text)
        self._text_index = self._vector_index = self._masks = None
        self._floors = {}

    # ---- similarity of a query with every entry ----
    def _by_text(self, text):
        if self._text_index is None:  # for each term: the entries that hold it, and its weight in each
            lists = {}
            for position, terms in enumerate(self._terms):
                for term, weight in terms.items():
                    where, weights = lists.setdefault(term, ([], []))
                    where.append(position)
                    weights.append(weight)
            self._text_index = {term: (np.asarray(where, dtype=np.intp), np.asarray(weights, dtype=np.float64))
                                for term, (where, weights) in lists.items()}
        terms = text if isinstance(text, dict) else text_terms(text)
        scores = np.zeros(len(self._entries), dtype=np.float64)
        for term, weight in terms.items():
            found = self._text_index.get(term)
            if found is not None:
                scores[found[0]] += weight * found[1]
        return scores, np.ones(len(self._entries), dtype=bool)

    def _vector_matrix(self):
        """One row per entry (zeros for an entry without a vector), and which entries have a vector."""
        if self._vector_index is None:
            has = np.array([entry["vector"] is not None for entry in self._entries], dtype=bool)
            width = next((len(entry["vector"]) for entry in self._entries if entry["vector"] is not None), 0)
            matrix = np.zeros((len(self._entries), width), dtype=np.float32)
            for position, entry in enumerate(self._entries):
                if entry["vector"] is not None:
                    matrix[position] = entry["vector"]
            self._vector_index = (matrix, has)
        return self._vector_index

    def _by_vector(self, vector):
        matrix, has = self._vector_matrix()
        if not matrix.shape[1]:
            return np.zeros(len(self._entries)), has
        return matrix @ _unit(vector), has

    def _ranked(self, text, vector, need=None, exclude=(), by_key=False):
        """Positions of the usable entries, most similar first, and the similarity of every entry.

        `need` names a field that an entry must have ("checked" or "kind"), or is None for every entry. Equal
        similarities keep the order the entries were added, or, with `by_key`, the order of their keys.
        """
        if not self._entries:
            return [], np.zeros(0)
        if vector is not None:
            scores, usable = self._by_vector(vector)
        elif text is not None:
            scores, usable = self._by_text(text)
        else:
            raise ValueError("give a text or a vector to search with")
        if self._masks is None:
            self._masks = {"checked": np.array([entry["checked"] for entry in self._entries], dtype=bool),
                           "kind": np.array([entry["kind"] is not None for entry in self._entries], dtype=bool)}
        if need is not None:
            usable = usable & self._masks[need]
        skip = [self._position[key] for key in exclude if key in self._position]
        if skip:
            usable = usable.copy()
            usable[skip] = False
        candidates = np.flatnonzero(usable)
        if by_key:
            return sorted(candidates.tolist(), key=lambda p: (-scores[p], str(self._entries[p]["key"]))), scores
        order = candidates[np.argsort(-scores[candidates], kind="stable")]  # equal scores: added first comes first
        return order.tolist(), scores

    def _public(self, position, similarity=None):
        entry = self._entries[position]
        out = {"key": entry["key"], "text": entry["text"], "payload": entry["payload"], "kind": entry["kind"],
               "checked": entry["checked"]}
        if similarity is not None:
            out["similarity"] = float(similarity)
        return out

    def nearest(self, text=None, vector=None, k=3, only_checked=True, exclude=()):
        """The k most similar entries, most similar first. Each is a dictionary with a "similarity".

        Give `vector` to compare text vectors (entries without a vector are left out), or `text` to use
        the built-in text similarity. `exclude` is a list of keys to leave out, for example the key of
        the Task itself. To show examples to a model with the most similar one last, reverse the list.
        """
        order, scores = self._ranked(text, vector, "checked" if only_checked else None, exclude)
        return [self._public(p, scores[p]) for p in order[:k]]

    def kind_vote(self, text=None, vector=None, k=5, exclude=(), tie_break=None):
        """The kind named by most of the k most similar entries. Returns {kind, share, top_similarity, votes}.

        Every entry with a kind votes, checked or not. `share` is the part of the k votes that the
        winning kind got. Two kinds with the same number of votes: the kind of the nearer entry wins.
        Entries with the same similarity are ordered by the rule `tie_break` (a value of "store.tie_break";
        None: this store's setting). `top_similarity` is the similarity of the nearest entry: give it to
        `stepkit.profile.unfamiliar` with this store's `familiarity_floor()`.
        An empty store gives kind None, share 0.0 and top_similarity 0.0; so does the rule
        "no_vote_when_all_zero" when the nearest entry has similarity 0.
        """
        rule = tie_break or self.tie_break
        if rule not in SETTINGS["store.tie_break"].grid:
            raise ValueError(f"unknown tie break {rule!r}; one of {SETTINGS['store.tie_break'].grid}")
        order, scores = self._ranked(text, vector, "kind", exclude, by_key=rule == "by_key")
        top = order[:k]
        if not top or (rule == "no_vote_when_all_zero" and float(scores[top[0]]) == 0.0):
            return {"kind": None, "share": 0.0, "top_similarity": 0.0, "votes": {}}
        votes = Counter(self._entries[p]["kind"] for p in top)
        best = max(votes.values())
        kind = next(self._entries[p]["kind"] for p in top if votes[self._entries[p]["kind"]] == best)
        return {"kind": kind, "share": best / len(top), "top_similarity": float(scores[top[0]]), "votes": dict(votes)}

    # ---- how similar must a Task be to count as familiar ----
    def nearest_other(self, by=None, only_checked=False, skip_blank=True):
        """For each stored entry, its similarity to the nearest OTHER entry. Returns a numpy array.

        `by` names the measure: "vector" (cosine of text vectors) or "text" (the built-in text
        similarity). None means "vector" when every entry has a vector, else "text". It is the same
        similarity as `nearest` and `kind_vote` give for a query of that form.
        An entry that the measure cannot describe is left out when `skip_blank` is True: an entry with
        no vector, and for the text measure an entry with no word (an arithmetic expression).
        """
        if by is None:
            by = "vector" if self._entries and all(e["vector"] is not None for e in self._entries) else "text"
        if by not in ("vector", "text"):
            raise ValueError("by must be 'vector', 'text' or None")
        if not self._entries:
            return np.zeros(0)
        keep = np.array([(not only_checked or entry["checked"]) for entry in self._entries], dtype=bool)
        if by == "vector":
            matrix, has = self._vector_matrix()
            use = np.flatnonzero(keep & has)
            if len(use) < 2:
                return np.zeros(0)
            sims = (matrix[use] @ matrix[use].T).astype(np.float64)
            np.fill_diagonal(sims, -np.inf)
            return sims.max(axis=1)
        described = np.array([bool(terms) for terms in self._terms], dtype=bool)
        use = np.flatnonzero(keep & described) if skip_blank else np.flatnonzero(keep)
        if len(use) < 2:
            return np.zeros(0)
        out = np.zeros(len(use))
        for row, position in enumerate(use):
            scores = self._by_text(self._terms[position])[0]
            scores[position] = -np.inf
            out[row] = scores[use].max()
        return out

    def familiarity_floor(self, q=0.02, by=None, only_checked=False, skip_blank=True):
        """The similarity under which a Task counts as unfamiliar to this store. It calibrates itself.

        It is the q-quantile, over the stored entries, of each entry's similarity to its nearest OTHER
        entry. So about a share q of the Tasks that are like the stored ones fall under it, whatever
        the measure and whatever the store holds. Use it with the "top_similarity" of `kind_vote` or
        the first "similarity" of `nearest`, made with the same measure (`by`, see `nearest_other`):

            floor = store.familiarity_floor()
            vote = store.kind_vote(vector=v)
            if unfamiliar(vote["top_similarity"], floor): use the default node

        A store with fewer than two entries that the measure can describe knows too little: the floor
        is then infinite, so every Task counts as unfamiliar. The value is kept until the store changes.
        """
        found = (q, by, only_checked, skip_blank)
        if found not in self._floors:
            values = self.nearest_other(by, only_checked, skip_blank)
            self._floors[found] = float(np.quantile(values, q)) if len(values) else float("inf")
        return self._floors[found]

    # ---- files ----
    def save(self, path):
        """Write the store as JSON lines, one entry per line. The payloads must be JSON values."""
        with open(path, "w", encoding="utf-8") as out:
            for entry in self._entries:
                row = dict(entry, vector=None if entry["vector"] is None else entry["vector"].tolist())
                out.write(json.dumps(row) + "\n")

    def _read(self, path):
        with open(path, encoding="utf-8") as lines:
            for line in lines:
                if line.strip():
                    row = json.loads(line)
                    vector = row.get("vector")      # saved at unit length: taken as it is, so similarities stay the same
                    self._put(row["key"], row["text"], row["payload"], row.get("kind"), row.get("checked", True),
                              None if vector is None else np.asarray(vector, dtype=np.float32))
        return self

    load = _Load()      # load(path): read a file written by save; see the class _Load above

    @classmethod
    def from_library(cls, library_jsonl, items_jsonl, vectors_json=None, library_positions=N_LIBRARY):
        """Load the checked programs of test 7 (the tool-building test).

        `library_jsonl` holds one line per attempt at a library Task: item, kind, kept, code, pred.
        `items_jsonl` holds the Tasks: id, kind, question. `vectors_json`, when given, maps a Task id to
        its text vector.

        The first kept program of a Task becomes a checked entry with the payload
        {"code", "answer", "attempt"}. The other library Tasks (the first `library_positions` Tasks of
        each kind, by the order of the items file: the split rule of test 7) are stored as NOT checked,
        with no payload: no program passed for them, or their kind needs none (the calculator answers
        arithmetic expressions). They keep their text and kind, so `kind_vote` can still name their
        kind. Give library_positions=0 to store only the Tasks with a kept program.
        """
        with open(items_jsonl, encoding="utf-8") as lines:
            items = [json.loads(line) for line in lines if line.strip()]
        kept = {}
        with open(library_jsonl, encoding="utf-8") as lines:
            for line in lines:
                if line.strip():
                    row = json.loads(line)
                    if row.get("kept") and row["item"] not in kept:
                        kept[row["item"]] = row
        vectors = {}
        if vectors_json:
            with open(vectors_json, encoding="utf-8") as handle:
                vectors = json.load(handle)
        store, seen = cls(), {}
        for item in items:
            place = seen.get(item["kind"], 0)
            seen[item["kind"]] = place + 1
            row = kept.get(item["id"])
            if row is not None:
                payload = {"code": row["code"], "answer": row.get("pred"), "attempt": row.get("attempt")}
                store.add(item["id"], item["question"], payload, kind=item["kind"], checked=True,
                          vector=vectors.get(item["id"]))
            elif place < library_positions:
                store.add(item["id"], item["question"], None, kind=item["kind"], checked=False,
                          vector=vectors.get(item["id"]))
        return store
