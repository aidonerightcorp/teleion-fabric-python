# Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md
"""Versioned settings are package resources, with explicit candidate grids."""
import json
from copy import deepcopy
from .values import validate_json
from importlib.resources import files

def load(name='profiler'):
 paths={'plans':'data/plan-settings.json','dimensions':'data/dimensions.json','profiler':'settings.json','harness_grid':'harness-grid.json','decision':'data/decision-settings.json','retention':'data/retention-settings.json','boundary':'data/boundary-settings.json'}
 if name not in paths:raise ValueError('unknown settings resource')
 return json.loads(files('teleion_fabric').joinpath(paths[name]).read_text())

def _equal(a,b):
 if type(a) is not type(b):return False
 if isinstance(a,list):return len(a)==len(b) and all(_equal(x,y) for x,y in zip(a,b))
 if isinstance(a,dict):return a.keys()==b.keys() and all(_equal(a[k],b[k]) for k in a)
 return a==b

def select(dimensions,overrides=None):
 if not isinstance(dimensions,dict) or (overrides is not None and not isinstance(overrides,dict)):raise ValueError('selection requires normalized mapping grids, not a design catalog')
 validate_json(dimensions)
 if overrides is not None:validate_json(overrides)
 result={};overrides={} if overrides is None else overrides
 if set(overrides)-set(dimensions):raise ValueError('unknown setting')
 for key,spec in dimensions.items():
  if not isinstance(spec,dict) or not isinstance(spec.get('grid'),list) or not spec['grid']:raise ValueError('explicit enumerable grid required: '+str(key))
  value=overrides.get(key,spec.get('value'))
  if 'grid' not in spec or not any(_equal(value,candidate) for candidate in spec['grid']):raise ValueError('outside declared grid: '+key)
  result[key]={'value':deepcopy(value),'origin':'caller' if key in overrides else 'default'}
 return result
