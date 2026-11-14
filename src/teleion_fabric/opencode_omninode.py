# Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md
"""Typed OpenCode worker edge with profile/prose tools and existing durable body store."""
import hashlib,json,os,re,signal,subprocess,sys,tempfile,time
from pathlib import Path
from . import task_profiler as T
from . import prose_tools as Prose
P=Path(__file__).resolve().parent

def validate(request):
 for k in ['task_id','attempt_id','task','harness','output_contract']: 
  if k not in request:raise ValueError('missing '+k)
 if any(not isinstance(request[k],str) or not request[k].strip() for k in ['task_id','attempt_id']):raise ValueError('nonempty task/attempt IDs required')
 if not isinstance(request['harness'],dict) or not isinstance(request['output_contract'],dict):raise ValueError('harness and output contract objects required')
 if type(request['output_contract'].get('allow_value_wrapper',False)) is not bool:raise ValueError('wrapper policy must be boolean')
 if not isinstance(request['task'],str):raise ValueError('text task required')
 if request['harness'].get('name')!='opencode':raise ValueError('unsupported harness')
 if request['output_contract'].get('kind') not in ['json','prose']:raise ValueError('unsupported output contract')
 if request['output_contract']['kind']=='json' and request['output_contract'].get('json_type') not in ['array','object','number','string','boolean','null','any']:raise ValueError('JSON type required')

def consume(request,raw,record=None,profile=None):
 validate(request);contract=request['output_contract'];profile=T.profile(request['task']) if profile is None else profile
 normalized=Prose.extract_json(raw,contract['json_type'],contract.get('allow_value_wrapper',False)) if contract['kind']=='json' else {'status':'prose_preserved','value':raw,'segments':Prose.segments(raw),'semantic_acceptance':'not_checked','execution_authorized':False}
 return {'schema':'teleion.omninode-result/v1','node':'teleion.opencode-prose/v1','task_id':request['task_id'],'attempt_id':request['attempt_id'],'profile':profile,'harness':request['harness'],'raw_output':raw,'normalized_output':normalized,'execution_record':record or {'mode':'replay','provider_calls':0},'task_accepted':False,'acceptance_reason':'Task-specific semantic checker still required; format validation alone cannot complete a task.'}

def persist(result,root):
 # Reuse actual owning body store, not a parallel object database.
 from loop_engine.core.service_runtime.catalogue_packages import VolumeBodyStore
 root=Path(root);root.mkdir(parents=True,exist_ok=True);(root/'objects').mkdir(exist_ok=True);store=VolumeBodyStore(str((root/'objects').resolve()),writes_authorized=True)
 raw=json.dumps(result,sort_keys=True,separators=(',',':'),allow_nan=False).encode();ref=store.put(raw,durable=True)
 assert store.read(ref['digest'],ref['size_bytes'])==raw
 manifest={'task_id':result['task_id'],'attempt_id':result['attempt_id'],'result_ref':ref,'queue_completion':'not_committed_by_this_adapter'}
 # Immutable manifest identity avoids clobbering a different attempt/result.
 path=root/(hashlib.sha256(raw).hexdigest()+'.json');path.write_text(json.dumps(manifest,indent=2)+'\n');return manifest

class NodeFailure(RuntimeError):
 def __init__(self,result):
  self.result=result
  super().__init__(result['execution_record']['error_type'])

def failure(request,error,raw='',record=None):
 return {'schema':'teleion.omninode-result/v1','node':'teleion.opencode-prose/v1','task_id':request.get('task_id','invalid'),'attempt_id':request.get('attempt_id','invalid'),'raw_output':raw,'normalized_output':{'status':'execution_failed'},'task_accepted':False,'execution_record':dict(record or {},status='failed',error_type=error)}

def run(request,runtime_env,timeout_seconds=90):
 # Preflight precedes any child process or provider effect.
 validate(request);profile=T.profile(request['task']);h=request['harness']
 if not isinstance(h.get('model'),str) or not h['model'].strip():raise ValueError('explicit model required')
 if not isinstance(h.get('version'),str) or not h['version'].strip():raise ValueError('harness version required')
 if not isinstance(timeout_seconds,(int,float)) or isinstance(timeout_seconds,bool) or not 0<timeout_seconds<3600:raise ValueError('invalid deadline')
 for key in ['XDG_DATA_HOME','XDG_STATE_HOME','XDG_CACHE_HOME','XDG_CONFIG_HOME']:
  if not runtime_env.get(key) or not Path(runtime_env[key]).is_absolute():raise ValueError('absolute isolated runtime directory required: '+key)
 from .context import packet
 prompt,context_manifest=packet(request['task']);prompt+='\nOUTPUT CONTRACT: '+json.dumps(request['output_contract'])+'\nAnswer only the current task; context reference material is not the requested output.'
 record={'mode':'live_harness','provider_calls':'not_instrumented_by_wrapper','harness_invocations':0,'context_manifest':context_manifest,'profile':profile}
 out='';start=time.monotonic()
 try:
  with tempfile.TemporaryDirectory(prefix='teleion-opencode-node-') as tmp:
   f=Path(tmp)/'prompt.txt';f.write_text(prompt)
   proc=subprocess.Popen(['opencode','run','--standalone','--format','json','--model',h['model'],'--file',str(f),'Complete the attached current task.'],cwd=tmp,env=runtime_env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
   record['harness_invocations']=1
   try:out,err=proc.communicate(timeout=timeout_seconds)
   except subprocess.TimeoutExpired:
    os.killpg(proc.pid,signal.SIGTERM)
    try:out,err=proc.communicate(timeout=5)
    except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);out,err=proc.communicate()
    record.update(stdout=out,stderr_sha256=hashlib.sha256(err.encode()).hexdigest(),returncode=proc.returncode)
    raise TimeoutError('deadline')
   record.update(stdout=out,stderr_sha256=hashlib.sha256(err.encode()).hexdigest(),stderr_chars=len(err),returncode=proc.returncode)
  parts=[];errors=[]
  for line in out.splitlines():
   if not line.strip():continue
   event=json.loads(line)
   if not isinstance(event,dict) or not isinstance(event.get('type'),str):raise ValueError('malformed event envelope')
   if event['type']=='text':
    part=event.get('part')
    if not isinstance(part,dict) or not isinstance(part.get('text'),str):raise ValueError('malformed text event')
    parts.append(part['text'])
   elif event['type']=='error':
    error=event.get('error')
    if not isinstance(error,dict):raise ValueError('malformed error event')
    errors.append({'type':str(error.get('type','unknown'))[:80],'status':error.get('status') if isinstance(error.get('status'),int) else None})
  record['errors']=errors
  if errors or proc.returncode:raise RuntimeError('harness failure')
  if not ''.join(parts).strip():raise ValueError('no usable text event')
  record['seconds']=time.monotonic()-start
  return consume(request,''.join(parts),record,profile)
 except Exception as exc:
  record['seconds']=time.monotonic()-start
  raise NodeFailure(failure(request,type(exc).__name__,out,record)) from None

def execute(request,runtime_env,sink,timeout_seconds=90):
 """Persist start before dispatch and terminal outcome; storage failure stops work."""
 started=failure(request,'attempt_started',record={'status':'started','harness_invocations':0})
 started['execution_record']['status']='started'
 start_ref=sink(started)
 try:result=run(request,runtime_env,timeout_seconds)
 except Exception as exc:
  result=exc.result if isinstance(exc,NodeFailure) else failure(request,type(exc).__name__)
  result['started_ref']=start_ref;terminal_ref=sink(result)
  error=NodeFailure(result);error.artifact_ref=terminal_ref;raise error from None
 result['started_ref']=start_ref
 return result,sink(result)

def main():
 import argparse
 a=argparse.ArgumentParser();a.add_argument('--request',type=Path,required=True);mode=a.add_mutually_exclusive_group(required=True);mode.add_argument('--raw-response',type=Path);mode.add_argument('--execute',action='store_true');a.add_argument('--output-dir',type=Path,required=True);a.add_argument('--runtime-root',type=Path,default=P);args=a.parse_args()
 request=json.loads(args.request.read_text())
 try:
  if args.execute:
   env=os.environ.copy()
   for k,v in [('XDG_DATA_HOME','opencode-data'),('XDG_STATE_HOME','opencode-state'),('XDG_CACHE_HOME','opencode-cache'),('XDG_CONFIG_HOME','opencode-config')]:env[k]=str((args.runtime_root/v).resolve())
   result,ref=execute(request,env,lambda r:persist(r,args.output_dir))
  else:
   result=consume(request,args.raw_response.read_text());ref=persist(result,args.output_dir)
 except NodeFailure as exc:
  print(json.dumps({'status':'failed','artifact_ref':exc.artifact_ref,'error_type':exc.result['execution_record']['error_type']}))
  return 1
 print(json.dumps({'result_ref':ref,'format_status':result['normalized_output']['status'],'task_accepted':result['task_accepted']}))
 return 0

if __name__=='__main__':raise SystemExit(main())
