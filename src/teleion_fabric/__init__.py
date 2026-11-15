# Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md
"""Teleion Fabric: typed packages for task-aware solutioning."""
__version__="0.2.6"
from .task_profiler import profile
from .boundary_provenance import BoundaryProvenance,diagnose_json_boundary,strict_json
from stepkit.retention import MemoryRecordPort,NodeRecordSink,record_data_use,record_task_text_allowed,withhold_task_text
