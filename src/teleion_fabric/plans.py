# Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md
"""Compile declarative branches over explicitly registered pure Engine/Port objects.

No arbitrary imports, queue replacement, permission inference, or result cache.
Registered Python functions are trusted code; this is not a sandbox.
"""
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from importlib.resources import files
from .contracts import Engine, Port
from .values import validate_json

@dataclass(frozen=True)
class Step:
    id: str
    engine: Engine
    version: str
    source: str

@dataclass(frozen=True)
class CompiledPlan:
    steps: tuple
    outputs: tuple
    input_port: Port
    digest: str
    validators: tuple=()

    def run(self, value):
        validators=dict(self.validators)
        _validate(self.input_port,value,validators)
        values={'$input':deepcopy(value)}; records=[]
        for step in self.steps:
            record={'node':step.id,'engine':step.engine.id,'version':step.version}
            try:
                # Each branch receives its own value; a mutation cannot poison siblings.
                argument=deepcopy(values[step.source])
                _validate(step.engine.input,argument,validators)
                result=step.engine.implementation(argument)
                _validate(step.engine.output,result,validators)
                values[step.id]=deepcopy(result)
            except Exception as error:
                records.append(dict(record,status='failed',error_type=type(error).__name__))
                return {'status':'failed','plan_digest':self.digest,'records':records,
                        'failed_node':step.id,'outputs':{},'task_accepted':False}
            records.append(dict(record,status='completed',semantic_acceptance='not_checked'))
        return {'status':'completed','plan_digest':self.digest,'records':records,
                'outputs':{key:deepcopy(values[source]) for key,source in self.outputs},
                'task_accepted':False}

def _validate(port,value,validators):
    validate_json(value)
    if type(value) is not port.python_type:raise TypeError('invalid port value')
    if port.validator_id is not None:
        if validators[(port.validator_id,port.version)](deepcopy(value)) is not True:
            raise ValueError('port validator refused value')

def _port(port):
    if not isinstance(port,Port) or port.python_type not in (str,int,float,bool,list,dict,type(None)):
        raise ValueError('supported JSON-shaped Port required')
    if not isinstance(port.semantic_type,str) or not port.semantic_type.strip() or not isinstance(port.version,str) or not port.version:
        raise ValueError('port semantic type/version required')

def compile_plan(document, registry, input_port, validators=None):
    """registry maps (engine ID, exact version) to caller-admitted Engine objects."""
    _port(input_port)
    validators=dict(validators or {})
    if not isinstance(document,dict) or set(document)!={'nodes','outputs'}:
        raise ValueError('plan requires only nodes and outputs')
    validate_json(document)
    document=deepcopy(document)
    limit=json.loads(files('teleion_fabric').joinpath('data/plan-settings.json').read_text())['max_nodes']['value']
    nodes=document['nodes']; outputs=document['outputs']
    if not isinstance(nodes,list) or not 1<=len(nodes)<=limit:raise ValueError('node count outside bound')
    if not isinstance(outputs,dict) or not outputs:raise ValueError('named outputs required')
    specs={}; selected={}
    for node in nodes:
        if not isinstance(node,dict) or set(node)!={'id','engine','version','source'}:raise ValueError('invalid node fields')
        if any(not isinstance(v,str) or not v.strip() for v in node.values()):raise ValueError('node fields require nonempty strings')
        name=node['id']
        if name=='$input' or name in specs:raise ValueError('reserved or duplicate node ID')
        engine=registry.get((node['engine'],node['version']))
        if not isinstance(engine,Engine) or engine.id!=node['engine']:raise ValueError('unknown engine or exact version')
        _port(engine.input);_port(engine.output)
        if type(engine.effects) is not tuple:raise ValueError('immutable effect declaration required')
        if engine.effects:raise ValueError('effectful engine requires owning executor')
        if not callable(engine.implementation):raise ValueError('engine implementation required')
        specs[name]=node;selected[name]=engine
    ports={'$input':input_port,**{name:engine.output for name,engine in selected.items()}}
    used_validators={}
    for port in [input_port]+[p for e in selected.values() for p in [e.input,e.output]]:
        if port.validator_id is not None:
            if not isinstance(port.validator_id,str) or not port.validator_id:raise ValueError('validator ID required')
            key=(port.validator_id,port.version)
            if not callable(validators.get(key)):raise ValueError('missing versioned port validator')
            used_validators[key]=validators[key]
    for name,node in specs.items():
        if node['source'] not in ports:raise ValueError('missing source')
        if ports[node['source']]!=selected[name].input:raise ValueError('incompatible semantic/type/version edge')
    for key,source in outputs.items():
        if not isinstance(key,str) or not key.strip() or not isinstance(source,str) or source not in ports:
            raise ValueError('invalid output reference')
    # Deterministic topological order, independent of planner serialization order.
    steps=[];done={'$input'};remaining=set(specs)
    while remaining:
        ready=sorted(name for name in remaining if specs[name]['source'] in done)
        if not ready:raise ValueError('cycle detected')
        for name in ready:
            node=specs[name];steps.append(Step(name,selected[name],node['version'],node['source']))
            done.add(name);remaining.remove(name)
    canonical={'nodes':[specs[s.id] for s in steps],'outputs':outputs,
               'input':{'type':input_port.python_type.__name__,'semantic_type':input_port.semantic_type,'version':input_port.version,'validator_id':input_port.validator_id},
               'ports':{s.id:{'input':vars(s.engine.input)|{'python_type':s.engine.input.python_type.__name__},
                                'output':vars(s.engine.output)|{'python_type':s.engine.output.python_type.__name__}} for s in steps}}
    digest=hashlib.sha256(json.dumps(canonical,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
    return CompiledPlan(tuple(steps),tuple(sorted(outputs.items())),input_port,digest,tuple(sorted(used_validators.items())))
