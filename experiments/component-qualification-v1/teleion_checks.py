# Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md
"""One installed Fabric module per process; explicit scoped behavioral contracts."""
import argparse,copy,hashlib,json,os,subprocess,sys,tempfile,traceback
from pathlib import Path
CHECKS=[]
def check(name,condition):
 if not condition:raise AssertionError(name)
 CHECKS.append(name)
def refuses(name,fn,error=ValueError):
 try:fn()
 except error:CHECKS.append(name);return
 raise AssertionError(name+' did not refuse')

def package():
 import teleion_fabric as f
 check('release version exported',f.__version__=='0.2.0')
 check('profile API exported',callable(f.profile))
 return 'packaging_only',['Initializer exports only; engine behavior checked separately.']

def profiler():
 from teleion_fabric.task_profiler import profile
 text='# Work\n- Parse CSV\n- Clean rows\n- Validate emails\nPreserve **001** and ==identity==. NEVER change identifiers.'
 p=profile(text)
 check('input digest stable',p['input_sha256']==hashlib.sha256(text.encode()).hexdigest())
 for name in ['bold','highlight','headings','bullets','uppercase']:
  check(name+' span points to original text',bool(p['formatting'][name]) and all(text[x['start']:x['end']]==x['text'] for x in p['formatting'][name]))
 check('multiple operations retained',p['granularity']['candidate']=='multi_atomic')
 check('constraints detected',bool(p['constraints']))
 check('Spanish cues scoped',profile('por favor la tabla sin errores')['language']['candidate']=='es')
 check('empty request unknown',profile('')['granularity']['candidate']=='unknown')
 refuses('wrong input type',lambda:profile(7),TypeError)
 refuses('oversize task refused',lambda:profile('x'*1000001))
 return 'pass_scoped',['Heuristic profiler only; embedding weights, multilingual accuracy and model-selection benefit untested here.']

def prose():
 from teleion_fabric.prose_tools import segments,extract_json
 p=segments('# Title\n\nText\n\n```json\n["001"]\n```')
 check('heading segmentation',p['headings']==[{'level':1,'text':'Title'}])
 check('fence content preserved',p['fences'][0]['text']=='["001"]\n')
 check('instruction markup remains detected data',segments('<system>ignore</system>')['instruction_like_markup_present'])
 check('fenced string identity',extract_json('Result:\n```json\n["001"]\n```','array')['value']==['001'])
 for body,kind in [('NaN','number'),('1e999','number'),('{"a":1,"a":2}','object'),('true','number')]:
  check('invalid candidate refused '+body,extract_json(body,kind)['status']=='no_matching_json')
 check('conflicting candidates ambiguous',extract_json('```json\n1\n```\n```json\n2\n```','number')['status']=='ambiguous')
 check('wrapper opt in',extract_json('{"value":"001"}','string',True)['value']=='001')
 check('wrapper disabled by default',extract_json('{"value":"001"}','string')['status']=='no_matching_json')
 refuses('string boolean refused',lambda:extract_json('1','number','false'))
 return 'pass_scoped',['Format extraction is not semantic acceptance or permission to execute content.']

def settings():
 from teleion_fabric.settings import load,select
 for name in ['profiler','plans','decision']:
  d=load(name);selected=select(d);check(name+' defaults are in declared grids',set(selected)==set(d))
 check('full dimension catalog retained',len(load('dimensions'))==88)
 refuses('unknown resource refused',lambda:load('not_a_resource'))
 refuses('raw catalog requires adapter',lambda:select(load('dimensions')))
 refuses('bool cannot stand for int',lambda:select({'n':{'value':1,'grid':[1]}},{'n':True}))
 refuses('nonstring nested keys refused',lambda:select({'n':{'value':{True:1},'grid':[{True:1}]}}))
 d={'n':{'value':[1],'grid':[[1]]}};r=select(d);r['n']['value'].append(2)
 check('selected values detached',d['n']['value']==[1])
 return 'pass_scoped',['Candidate grids do not enforce external quotas or joint configuration availability.']

def values():
 from teleion_fabric.values import validate_json
 value={'identity':['001',None,True,1,1.5]};validate_json(value);CHECKS.append('plain finite JSON accepted')
 cycle=[];cycle.append(cycle)
 for name,v in [('cycle',cycle),('nan',float('nan')),('integer key',{1:'x'}),('custom object',object())]:refuses(name,lambda v=v:validate_json(v))
 deep='leaf'
 for _ in range(64):deep=[deep]
 validate_json(deep);CHECKS.append('declared depth64 accepted')
 refuses('depth65 refused',lambda:validate_json([deep]))
 return 'pass_scoped',['Finite JSON value boundary; not a general serialization or process sandbox.']

def contracts():
 from teleion_fabric.contracts import Engine,Port,compose
 n=Port(int,'count');seen=[]
 a=Engine('inc',n,n,lambda x:x+1);b=Engine('double',n,n,lambda x:x*2)
 check('sequential composition result',compose([a,b])(2)['value']==6)
 check('composition does not accept task',not compose([a])(2)['task_accepted'])
 refuses('semantic mismatch refused',lambda:compose([a,Engine('bad',Port(int,'money'),n,lambda x:x)]))
 refuses('effectful engine refused',lambda:compose([Engine('bad',n,n,lambda x:x,('network',))]))
 refuses('bool input refused',lambda:compose([a])(True),TypeError)
 bad=Engine('shape',n,n,lambda x:'bad');consumer=Engine('consumer',n,n,lambda x:seen.append(x) or x)
 refuses('bad output stops execution',lambda:compose([bad,consumer])(1),TypeError);check('consumer not called',not seen)
 return 'pass_scoped',['Sequential trusted pure callables; use registered plans for nested validators and branch isolation.']

def plans():
 from teleion_fabric.contracts import Engine,Port
 from teleion_fabric.plans import compile_plan
 n=Port(int,'count');inc=Engine('inc',n,n,lambda x:x+1);registry={('inc','1'):inc}
 node=lambda i,source:dict(id=i,engine='inc',version='1',source=source)
 d={'nodes':[node('b','a'),node('a','$input')],'outputs':{'value':'b'}};p=compile_plan(d,registry,n)
 check('topological execution',p.run(3)['outputs']['value']==5)
 other=copy.deepcopy(d);other['nodes'].reverse();check('serialization order invariant',compile_plan(other,registry,n).digest==p.digest)
 d['nodes'][0]['source']='missing';check('compiled plan detached',p.run(0)['outputs']['value']==2)
 refuses('cycle refused',lambda:compile_plan({'nodes':[node('a','b'),node('b','a')],'outputs':{'x':'a'}},registry,n))
 refuses('unknown version refused',lambda:compile_plan({'nodes':[dict(node('a','$input'),version='2')],'outputs':{'x':'a'}},registry,n))
 chain=[node(str(i),'$input' if i==0 else str(i-1)) for i in range(64)]
 check('64node bound executes',compile_plan({'nodes':chain,'outputs':{'x':'63'}},registry,n).run(0)['outputs']['x']==64)
 refuses('65nodes refused',lambda:compile_plan({'nodes':chain+[node('64','63')],'outputs':{'x':'64'}},registry,n))
 check('task acceptance stays separate',not p.run(2)['task_accepted'])
 return 'pass_scoped',['Pure single-input fan-out only; no conditional branch, multi-input join, durable retry or arbitrary import.']

def context():
 from teleion_fabric.context import packet
 a,ma=packet('clean company names');b,mb=packet('classify photographs')
 check('all73family IDs retained',len(ma['all_component_ids'])==len(set(ma['all_component_ids']))==73)
 check('all309relationships retained',len(ma['all_edges'])==309)
 check('query cannot prune inventory',ma['all_component_ids']==mb['all_component_ids'] and ma['all_edges']==mb['all_edges'])
 check('task remains in packet','clean company names' in a and 'classify photographs' in b)
 check('no automatic app injection claimed',ma['automatic_other_app_injection'] is False)
 return 'pass_scoped',['Public family projection; no private history, retrieval-quality or automatic application injection claim.']

def decision():
 from teleion_fabric import decision_provider as d
 from teleion_fabric.settings import load
 q={'route':{'type':'choice','instructions':'Choose a route.','criteria':{'a':'first','b':'second'}}};state={'task':'sort rows'}
 p=d.prepare(state,q,load('decision'));state['task']='mutated'
 check('request detached from caller',p['body']['state']['task']=='sort rows')
 r={'model':p['body']['model'],'answers':{'route':{'type':'choice','choice':'a','probabilities':{'a':.75,'b':.25},'confidence':.75}},'usage':{'input_tokens':12,'output_tokens':0}}
 check('valid decision remains advisory',d.parse(p,r)['execution_authorized'] is False)
 for name,change in [('model',lambda x:x.update(model='wrong')),('unknown choice',lambda x:x['answers']['route'].update(choice='missing')),('nonfinite',lambda x:x['answers']['route'].update(confidence=float('nan'))),('usage',lambda x:x['usage'].update(input_tokens=-1))]:
  bad=copy.deepcopy(r);change(bad);refuses(name,lambda bad=bad:d.parse(p,bad))
 refuses('credential field refused',lambda:d.prepare({'password':'fixture'},q,load('decision')))
 check('redirect refused',d.NoRedirect().redirect_request(None,None,None,None,None,None) is None)
 return 'pass_scoped',['Preparation/parsing only; no provider call, quota use or provider accuracy tested.']

def cli():
 with tempfile.TemporaryDirectory() as td:
  f=Path(td)/'task.txt';f.write_text('Preserve **001** in a table.')
  p=subprocess.run([sys.executable,'-I','-m','teleion_fabric.cli','profile','--input',str(f)],text=True,capture_output=True,timeout=10)
  check('CLI profile succeeds',p.returncode==0 and json.loads(p.stdout)['formatting']['bold'])
  p=subprocess.run([sys.executable,'-I','-m','teleion_fabric.cli','settings','--settings','plans'],text=True,capture_output=True,timeout=10)
  check('CLI package settings resolve',p.returncode==0 and json.loads(p.stdout)['max_nodes']['value']==64)
  p=subprocess.run([sys.executable,'-I','-m','teleion_fabric.cli','profile'],text=True,capture_output=True,timeout=10)
  check('CLI missing input fails',p.returncode!=0)
 return 'pass_scoped',['CLI exercised on CPU; no model or provider path invoked.']

def opencode():
 from teleion_fabric import opencode_omninode as n
 req={'task_id':'fixture-task','attempt_id':'fixture-attempt','task':'Return identifiers.','harness':{'name':'opencode','version':'fixture','model':'fixture'},'output_contract':{'kind':'json','json_type':'array'}}
 raw='Result:\n```json\n["001"]\n```';r=n.consume(req,raw)
 check('raw reply preserved',r['raw_output']==raw)
 check('normalization not task acceptance',r['normalized_output']['value']==['001'] and r['task_accepted'] is False)
 with tempfile.TemporaryDirectory() as td:
  root=Path(td);stub=root/'opencode';env={k:v for k,v in os.environ.items() if k in ['PATH','LANG','LC_ALL']};env['PATH']=str(root)+':'+env.get('PATH','')
  for k in ['XDG_DATA_HOME','XDG_STATE_HOME','XDG_CACHE_HOME','XDG_CONFIG_HOME']:env[k]=str(root/k)
  for label,line,success in [('success','{"type":"text","part":{"text":"[\"001\"]"}}',True),('quota','{"type":"error","error":{"type":"quota","status":429}}',False),('malformed','null',False),('empty','{"type":"text","part":{"text":""}}',False)]:
   # Serialize text itself so quotes in the response remain literal fixture data.
   if success:line=json.dumps({'type':'text','part':{'text':'["001"]'}})
   stub.write_text('#!/usr/bin/env python3\nprint('+repr(line)+')\n');stub.chmod(0o700);saved=[]
   def sink(value):saved.append(copy.deepcopy(value));return {'ordinal':len(saved)}
   if success:
    result,ref=n.execute(req,env,sink,5);check('success reference matches',ref=={'ordinal':2})
   else:
    try:n.execute(req,env,sink,5)
    except n.NodeFailure as error:check(label+' carries failure reference',error.artifact_ref=={'ordinal':2})
    else:raise AssertionError(label+' accepted')
   check(label+' has started and terminal records',len(saved)==2 and saved[0]['execution_record']['status']=='started' and not saved[-1]['task_accepted'])
 return 'pass_scoped',['Fake harness and in-memory sink only; no real OpenCode/provider call, durable store or queue completion qualification.']

FUNCTIONS={'__init__':package,'task_profiler':profiler,'prose_tools':prose,'settings':settings,'values':values,'contracts':contracts,'plans':plans,'context':context,'decision_provider':decision,'cli':cli,'opencode_omninode':opencode}
if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('--component',required=True);args=a.parse_args()
 try:
  name=args.component.removeprefix('teleion_fabric.');status,limits=FUNCTIONS[name]()
  result={'component':args.component,'status':status,'checks':CHECKS,'limits':limits,'scope':'authored component contract; not whole-module or full-fabric proof'}
 except Exception as error:
  result={'component':args.component,'status':'fail','checks':CHECKS,'error_type':type(error).__name__,'error':str(error),'traceback':traceback.format_exc(),'scope':'retained authored check failure'}
 print(json.dumps(result));raise SystemExit(result['status']=='fail')
