# Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md
"""Versioned settings are package resources, with explicit candidate grids."""
import json
from importlib.resources import files

def load(name='profiler'):
 paths={'dimensions':'data/dimensions.json','profiler':'settings.json','harness_grid':'harness-grid.json','decision':'data/decision-settings.json'}
 if name not in paths:raise ValueError('unknown settings resource')
 return json.loads(files('teleion_fabric').joinpath(paths[name]).read_text())

def select(dimensions,overrides=None):
 result={};overrides=overrides or {}
 if set(overrides)-set(dimensions):raise ValueError('unknown setting')
 for key,spec in dimensions.items():
  value=overrides.get(key,spec.get('value'))
  if 'grid' not in spec or value not in spec['grid']:raise ValueError('outside declared grid: '+key)
  result[key]={'value':value,'origin':'caller' if key in overrides else 'default'}
 return result
