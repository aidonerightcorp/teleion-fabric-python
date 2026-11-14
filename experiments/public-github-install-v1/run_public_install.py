# Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md
"""Anonymous public-source installation matrix. Contains no packaged implementation."""
import datetime,hashlib,json,os,shutil,subprocess,sys,time,urllib.request,zipfile
from pathlib import Path
REPO='https://github.com/aidonerightcorp/teleion-fabric-python.git'
COMMIT='52095288673f4902fe794b4a448caf21bf75aee6'
TAG='v0.2.0'
WHEEL='teleion_fabric-0.2.0-py3-none-any.whl'
WHEEL_URL='https://github.com/aidonerightcorp/teleion-fabric-python/releases/download/'+TAG+'/'+WHEEL
WHEEL_SHA='7d0ff38bcd3e8fc5370848d834284adca4453b2134cca85dd0d02a1d46b62e03'
ROOT=Path(os.environ.get('TELEION_INSTALL_TEST_ROOT','/kaggle/working/github-install-matrix')).resolve()
ROOT.mkdir(parents=True,exist_ok=True)
OUT=ROOT.parent/'github-install-results.json'
START=time.monotonic();DEADLINE=900
ENV={k:v for k,v in os.environ.items() if k in ['PATH','LANG','LC_ALL','LD_LIBRARY_PATH','SSL_CERT_FILE','REQUESTS_CA_BUNDLE','SYSTEMROOT']}
ENV.update(OMP_NUM_THREADS='2',OPENBLAS_NUM_THREADS='2',MKL_NUM_THREADS='2',PYTHONDONTWRITEBYTECODE='1',PIP_DISABLE_PIP_VERSION_CHECK='1',PIP_CONFIG_FILE='/dev/null',PIP_INDEX_URL='https://pypi.org/simple',GIT_TERMINAL_PROMPT='0',GIT_CONFIG_NOSYSTEM='1',GIT_CONFIG_GLOBAL='/dev/null',GIT_CONFIG_COUNT='1',GIT_CONFIG_KEY_0='credential.helper',GIT_CONFIG_VALUE_0='')
REPORT={'started_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'expected_commit':COMMIT,'version':'0.2.0','status':'running','setup':[],'routes':[], 'scope':'anonymous GitHub download and installed-package behavior; system dependencies shared; no model calls/GPU'}
def save():
 REPORT['elapsed_seconds']=round(time.monotonic()-START,3)
 temporary=OUT.with_suffix('.tmp');temporary.write_text(json.dumps(REPORT,indent=2)+'\n');temporary.replace(OUT)
def command(args,records,label,timeout=180,cwd=ROOT):
 remaining=DEADLINE-(time.monotonic()-START)
 if remaining<=0:raise TimeoutError('matrix deadline')
 start=time.monotonic();record={'stage':label,'command':list(map(str,args))};records.append(record);save()
 try:
  p=subprocess.run(list(map(str,args)),cwd=cwd,env=ENV,text=True,capture_output=True,timeout=min(timeout,remaining))
  record.update(exit_code=p.returncode,stdout=p.stdout[-16000:],stderr=p.stderr[-16000:],seconds=round(time.monotonic()-start,3));save()
  if p.returncode:raise RuntimeError(label+' failed')
  return p.stdout
 except subprocess.TimeoutExpired:
  record.update(status='timeout',seconds=round(time.monotonic()-start,3));save();raise

def download(url,path,records,label):
 start=time.monotonic()
 with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Teleion-package-install-test'}),timeout=45) as response:
  raw=response.read(10_000_001)
  if len(raw)>10_000_000:raise ValueError('download size cap')
 path.write_bytes(raw);digest=hashlib.sha256(raw).hexdigest()
 records.append({'stage':label,'url':url,'sha256':digest,'bytes':len(raw),'seconds':round(time.monotonic()-start,3)});save();return digest

# The test code itself comes from public GitHub, not a hidden source bundle.
checkout=ROOT/'public-checkout'
try:
 command(['git','clone','--depth','1','--branch',TAG,REPO,checkout],REPORT['setup'],'public_clone')
 actual=command(['git','-C',checkout,'rev-parse','HEAD'],REPORT['setup'],'verify_commit').strip()
 if actual!=COMMIT:raise ValueError('tag no longer matches pinned commit')
 REPORT['actual_commit']=actual
 command([sys.executable,'-I',checkout/'tools/sync_context.py','--check'],REPORT['setup'],'source_context_manifest')
 command([sys.executable,'-I','-m','pip','--version'],REPORT['setup'],'host_pip_version')
except Exception as exc:
 REPORT.update(status='setup_failed',error_type=type(exc).__name__);save();raise

probe='''import json,sys,importlib.metadata,pathlib
import teleion_fabric,numpy,scipy
origin=pathlib.Path(teleion_fabric.__file__).resolve()
assert origin.is_relative_to(pathlib.Path(sys.prefix).resolve()),str(origin)
assert importlib.metadata.version('teleion-fabric')=='0.2.0'
from teleion_fabric.settings import load
assert len(load('dimensions'))==88
assert load('plans')['max_nodes']['value']==64
assert 'teleion_fabric.plans' in __import__('importlib').import_module('teleion_fabric.plans').__name__
print(json.dumps({'version':teleion_fabric.__version__,'origin':str(origin),'prefix':sys.prefix,'numpy':numpy.__version__,'scipy':scipy.__version__,'direct_url':json.loads(importlib.metadata.distribution('teleion-fabric').read_text('direct_url.json'))}))
'''
for name in ['git_tag','release_wheel','commit_archive']:
 route={'name':name,'status':'running','stages':[]};REPORT['routes'].append(route);save()
 records=route['stages'];folder=ROOT/name;folder.mkdir();envpath=folder/'venv'
 try:
  command([sys.executable,'-I','-m','venv','--without-pip','--system-site-packages',envpath],records,'create_environment')
  python=envpath/'bin/python'
  if name=='git_tag':
   target='git+'+REPO+'@'+TAG
  elif name=='release_wheel':
   target=folder/WHEEL
   if download(WHEEL_URL,target,records,'download_release_wheel')!=WHEEL_SHA:raise ValueError('release wheel digest mismatch')
  else:
   archive=folder/'source.zip';download('https://codeload.github.com/aidonerightcorp/teleion-fabric-python/zip/'+COMMIT,archive,records,'download_commit_archive')
   with zipfile.ZipFile(archive) as z:
    for item in z.infolist():
     destination=(folder/item.filename).resolve()
     if not destination.is_relative_to(folder):raise ValueError('archive path escape')
    z.extractall(folder)
   target=folder/('teleion-fabric-python-'+COMMIT)
   if hashlib.sha256((target/'context-manifest.json').read_bytes()).digest()!=hashlib.sha256((checkout/'context-manifest.json').read_bytes()).digest():raise ValueError('archive/source manifest mismatch')
   command([python,'-I',target/'tools/sync_context.py','--check'],records,'archive_context_manifest')
  command([sys.executable,'-I','-m','pip','--python',python,'install','--no-cache-dir','--no-deps','--no-build-isolation','--ignore-installed',target],records,'install_public_package',timeout=240,cwd=folder)
  origin=json.loads(command([python,'-I','-c',probe],records,'installed_origin_and_resources',cwd=folder))
  route['installed']=origin
  if name=='git_tag' and origin['direct_url']['vcs_info']['commit_id']!=COMMIT:raise ValueError('pip installed wrong Git commit')
  command([python,'-I','-m','unittest','discover','-s',checkout/'tests','-v'],records,'full_contract_suite',cwd=folder)
  for example in ['compose_prose.py','registered_plan.py']:
   command([python,'-I',checkout/'examples'/example],records,'example_'+example,cwd=folder)
  command([envpath/'bin/teleion-fabric','settings','--settings','plans'],records,'installed_cli',cwd=folder)
  route['status']='pass'
 except Exception as exc:
  route.update(status='fail',error_type=type(exc).__name__,failed_stage=records[-1]['stage'] if records else 'preparation')
 save()
REPORT['status']='pass' if len(REPORT['routes'])==3 and all(r['status']=='pass' for r in REPORT['routes']) else 'fail'
save();print(json.dumps({'status':REPORT['status'],'routes':[(r['name'],r['status']) for r in REPORT['routes']],'result':str(OUT)}))
if REPORT['status']!='pass':raise SystemExit(1)
