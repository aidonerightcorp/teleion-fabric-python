# Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md
"""Typed package boundaries; caller registers implementations explicitly."""
from dataclasses import dataclass,field
from typing import Callable,Any

@dataclass(frozen=True)
class Port:
 python_type:type
 semantic_type:str
 version:str='1'
 validator_id:str|None=None

@dataclass(frozen=True)
class Engine:
 id:str
 input:Port
 output:Port
 implementation:Callable
 effects:tuple=()
 summary:str=''

def compose(engines):
 """Small sequential pure-engine composition; not a general DAG/queue replacement."""
 engines=tuple(engines)
 if not engines:raise ValueError('empty composition')
 for engine in engines:
  if engine.effects:raise ValueError('effectful engines require the owning executor')
  if engine.input.validator_id is not None or engine.output.validator_id is not None:raise ValueError('registered validators require compile_plan')
 for left,right in zip(engines,engines[1:]):
  if left.output!=right.input:raise ValueError('incompatible type, semantics or version')
 def run(value):
  records=[]
  for engine in engines:
   if type(value) is not engine.input.python_type:raise TypeError('invalid input: '+engine.id)
   value=engine.implementation(value)
   if type(value) is not engine.output.python_type:raise TypeError('invalid output: '+engine.id)
   records.append({'engine':engine.id,'shape_valid':True,'semantic_acceptance':'requires task checker'})
  return {'value':value,'records':records,'task_accepted':False}
 return run
