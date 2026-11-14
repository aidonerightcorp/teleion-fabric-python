# Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md
"""Records of steps: every step that was tried is kept, with its profiles, node, result and cost.

A StepRecord is one try of one node on one Task. A Trace is the list of the steps tried for a Task, in
order, with the final answer and the reason for it. The cost of a Trace is the cost of ALL its steps,
also of the steps whose answer was not kept: this is how the source replays add up cost.

Sources (under the notes folder), for the way cost is added up:
  work-2026-11-12-next-tests/t7-toolsmith/replay_t7.py   cost()
  work-2026-11-12-next-tests/t4-whole-loop/replay.py     Path.cost()
Python 3 standard library only.
"""
import json
from dataclasses import asdict, dataclass, field

# calls: model calls. tok_in, tok_out: tokens read and written by the model. model_s: model seconds.
# tool_ms: milliseconds spent in exact tools (the calculator, the program runner, a query).
COST_KEYS = ("calls", "tok_in", "tok_out", "model_s", "tool_ms")


def task_id_of(task):
    """The id of a Task: its "id" field when it is a dictionary, else the value itself."""
    return task.get("id") if isinstance(task, dict) else task


def task_text_of(task):
    """The text of a Task: its "question" or "text" field. None for a Task that is not a dictionary
    (a bare value is taken as the Task's id, not as its text)."""
    if isinstance(task, dict):
        return task.get("question", task.get("text"))
    return None


def cost_of(source=None) -> dict:
    """A cost dictionary with all five keys. Missing or empty values count as 0."""
    source = source or {}
    return {"calls": int(source.get("calls") or 0), "tok_in": int(source.get("tok_in") or 0),
            "tok_out": int(source.get("tok_out") or 0), "model_s": float(source.get("model_s") or 0.0),
            "tool_ms": float(source.get("tool_ms") or 0.0)}


def add_costs(costs) -> dict:
    """The sum of several cost dictionaries."""
    total = cost_of()
    for cost in costs:
        for key in COST_KEYS:
            total[key] += (cost or {}).get(key) or 0
    return total


@dataclass
class StepRecord:
    """One try of one node on one Task."""
    task_id: str
    step_no: int                    # 1 for the first step of the Task
    node: str                       # the name of the node that was tried
    input_profile: dict = field(default_factory=dict)    # made BEFORE the step, from this step's own input
    output_profile: dict = field(default_factory=dict)   # made AFTER the step, from the real output
    accepted: bool = False          # True when the decider stopped at this step
    answer: object = None           # the answer of THIS step, in the answer form of the question
    cost: dict = field(default_factory=cost_of)
    reason: str = ""                # why the decider stopped here, or why it went on

    def to_dict(self) -> dict:
        return asdict(self)


class Trace:
    """The steps tried for one Task, in order. Works like a list of StepRecord.

    `answer` is the final answer and `reason` says why. The final answer is what the decider chose at
    the step where it stopped: that step's own answer, the answer of an earlier step, or a combined one.
    """

    def __init__(self, task_id=None, steps=None):
        self.task_id = task_id
        self.steps = list(steps or [])
        self.answer = None
        self.reason = ""

    def append(self, step):
        self.steps.append(step)

    def finish(self, answer, reason=""):
        """Set the final answer and the reason for it. Called by the decider when it stops."""
        self.answer, self.reason = answer, reason

    def __len__(self):
        return len(self.steps)

    def __iter__(self):
        return iter(self.steps)

    def __getitem__(self, index):
        return self.steps[index]

    def step(self, node):
        """The last step that tried this node, or None."""
        return next((step for step in reversed(self.steps) if step.node == node), None)

    @property
    def accepted_step(self):
        """The step at which the decider stopped, or None."""
        return next((step for step in reversed(self.steps) if step.accepted), None)

    @property
    def nodes(self):
        """The names of the nodes that were tried, in order."""
        return [step.node for step in self.steps]

    def total_cost(self) -> dict:
        """The cost of every step that was tried, added up."""
        return add_costs(step.cost for step in self.steps)

    def cost_by_node(self) -> dict:
        """The same cost, split by node name: {node: cost}."""
        out = {}
        for step in self.steps:
            out[step.node] = add_costs([out.get(step.node), step.cost])
        return out

    def to_dict(self) -> dict:
        return {"task_id": self.task_id, "answer": self.answer, "reason": self.reason, "nodes": self.nodes,
                "total_cost": self.total_cost(), "steps": [step.to_dict() for step in self.steps]}

    def to_json(self) -> str:
        """One line of JSON for a records file. A value that JSON cannot hold is written as its text."""
        return json.dumps(self.to_dict(), default=str)

    @classmethod
    def from_json(cls, line):
        """Read back a line written by `to_json`."""
        data = json.loads(line)
        trace = cls(data.get("task_id"), [StepRecord(**step) for step in data.get("steps", [])])
        trace.finish(data.get("answer"), data.get("reason", ""))
        return trace
