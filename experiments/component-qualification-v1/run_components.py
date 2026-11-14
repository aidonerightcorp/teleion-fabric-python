# Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md
"""Sequential, separately recorded component contracts against an installed package."""
import argparse,datetime,hashlib,json,os,subprocess,sys,time
from pathlib import Path
HERE=Path(__file__).resolve().parent

def dump(path,data):
 temp=path.with_suffix('.tmp');temp.write_text(json.dumps(data,indent=2)+'\n');temp.replace(path)

def main():
 p=argparse.ArgumentParser();p.add_argument('--python',type=Path,default=Path(sys.executable));p.add_argument('--migration',type=Path,default=HERE.parent.parent/'MIGRATION.json');p.add_argument('--output',type=Path,required=True);p.add_argument('--prefix',default='');args=p.parse_args()
 args.output.mkdir(parents=True,exist_ok=False);(args.output/'logs').mkdir()
 migration=json.loads(args.migration.read_text());env={k:v for k,v in os.environ.items() if k in ['PATH','LANG','LC_ALL','LD_LIBRARY_PATH','SSL_CERT_FILE']};env.update(OMP_NUM_THREADS='2',OPENBLAS_NUM_THREADS='2',MKL_NUM_THREADS='2',CUDA_VISIBLE_DEVICES='',PYTHONDONTWRITEBYTECODE='1')
 probe="import teleion_fabric,stepkit,sys,json,pathlib,importlib.metadata; prefix=pathlib.Path(sys.prefix).resolve(); origins={m.__name__:str(pathlib.Path(m.__file__).resolve()) for m in [teleion_fabric,stepkit]}; assert all(pathlib.Path(p).is_relative_to(prefix) for p in origins.values()); print(json.dumps({'version':importlib.metadata.version('teleion-fabric'),'prefix':str(prefix),'origins':origins,'python':sys.version.split()[0]}))"
 check=subprocess.run([str(args.python),'-I','-c',probe],text=True,capture_output=True,env=env,timeout=30)
 if check.returncode:raise RuntimeError('installed package provenance failed: '+check.stderr)
 provenance=json.loads(check.stdout)
 if provenance['version']!='0.2.0':raise ValueError('campaign requires frozen release0.2.0')
 rows=[]
 for entry in migration['modules']:
  name=entry['module'];bundled=entry['delivery']=='bundled_source'
  rows.append({'component':name,'packaging':entry['delivery'],'package_version':'0.2.0' if bundled else None,'status':'not_run' if bundled else 'external_pending','checks':[],'limits':[] if bundled else ['Not bundled; provider/artifact migration and owning tests required.'],'container_image':'not_built_or_qualified_by_this_campaign','kaggle_individual_status':'not_run_api_rate_limited'})
 report={'started_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'environment':provenance,'venue':'local','migration_sha256':hashlib.sha256(args.migration.read_bytes()).hexdigest(),'provenance_limit':'Installed version and origin verified; wheel identity is not independently attested by this runner','execution':'one child process per component, sequential CPU','rows':rows,'scope':'component fixtures with explicit limits; imports alone do not qualify engines'}
 def snapshot():
  report['counts']={status:sum(r['status']==status for r in rows) for status in sorted({r['status'] for r in rows})};dump(args.output/'results.json',report)
 snapshot()
 deadline=time.monotonic()+900
 for row in rows:
  name=row['component']
  if row['status']!='not_run' or not name.startswith(args.prefix):continue
  if time.monotonic()>=deadline:row.update(status='blocked',limits=['Campaign time budget exhausted']);snapshot();continue
  script=HERE/('teleion_checks.py' if name.startswith('teleion_fabric.') else 'stepkit_checks.py')
  if not script.exists():row.update(status='blocked',limits=['Component fixture not yet supplied']);snapshot();continue
  row['fixture_sha256']=hashlib.sha256(script.read_bytes()).hexdigest();start=time.monotonic();raw={}
  try:
   proc=subprocess.run([str(args.python),'-I',str(script),'--component',name],cwd=args.output,env=env,text=True,capture_output=True,timeout=min(30,max(.01,deadline-time.monotonic())) )
   raw={'exit_code':proc.returncode,'stdout':proc.stdout,'stderr':proc.stderr}
   result=json.loads(proc.stdout)
   if result.get('component')!=name or result.get('status') not in ['pass_scoped','packaging_only','blocked','fail']:raise ValueError('invalid fixture result identity/status')
   if proc.returncode and result['status']!='fail':raise ValueError('exit/status mismatch')
   if result['status'] in ['pass_scoped','packaging_only'] and not result.get('checks'):raise ValueError('no checks recorded')
   row.update(result)
  except subprocess.TimeoutExpired as error:
   normalize=lambda v:v.decode('utf-8',errors='replace') if isinstance(v,bytes) else v
   raw={'stdout':normalize(error.stdout),'stderr':normalize(error.stderr),'timeout':error.timeout,'termination':'child killed and waited by subprocess.run'}
   row.update(status='fail',error_type='TimeoutExpired',error='Component time limit exceeded')
  except Exception as error:row.update(status='fail',error_type=type(error).__name__,error=str(error))
  row['seconds']=round(time.monotonic()-start,4)
  dump(args.output/'logs'/(name+'.json'),{'result':row,'process':raw})
  snapshot();print(json.dumps({'component':name,'status':row['status'],'checks':len(row.get('checks',[]))}),flush=True)
 report['finished_at']=datetime.datetime.now(datetime.timezone.utc).isoformat();snapshot()
 print(json.dumps({'summary':report['counts'],'output':str(args.output/'results.json')}));return int(any(r['status']=='fail' for r in rows))
if __name__=='__main__':raise SystemExit(main())
