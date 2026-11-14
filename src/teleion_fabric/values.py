# Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md
"""Finite JSON values with string object keys, before any Python copy hooks."""
import json,math
from importlib.resources import files

def validate_json(value):
    limit=json.loads(files('teleion_fabric').joinpath('data/value-settings.json').read_text())['max_depth']['value']
    active=set()
    def visit(item,depth):
        if depth>limit:raise ValueError('JSON value nesting limit')
        kind=type(item)
        if kind in (str,int,bool,type(None)):return
        if kind is float:
            if not math.isfinite(item):raise ValueError('nonfinite JSON number')
            return
        if kind not in (list,dict):raise ValueError('only plain JSON values are supported')
        identity=id(item)
        if identity in active:raise ValueError('cyclic JSON value')
        active.add(identity)
        if kind is dict:
            if any(type(key) is not str for key in item):raise ValueError('JSON object keys must be strings')
            for child in item.values():visit(child,depth+1)
        else:
            for child in item:visit(child,depth+1)
        active.remove(identity)
    visit(value,0)
