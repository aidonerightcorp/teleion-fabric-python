# Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md
"""Independently recompute the frozen installation-matrix acceptance criteria."""
import json,re,sys
from pathlib import Path
P=Path(__file__).resolve().parent
path=Path(sys.argv[1]) if len(sys.argv)>1 else P/'remote/github-install-results.json'
r=json.loads(path.read_text());failures=[];summaries=[]
expected='52095288673f4902fe794b4a448caf21bf75aee6'
if r.get('actual_commit')!=expected:failures.append('setup commit mismatch')
if r.get('status')!='pass':failures.append('runner did not pass')
setup={stage['stage']:stage for stage in r.get('setup',[])}
for required in ['public_clone','verify_commit','source_context_manifest','host_pip_version']:
 if setup.get(required,{}).get('exit_code')!=0:failures.append('setup '+required+' missing or failed')
routes=r.get('routes',[])
if {x.get('name') for x in routes}!={'git_tag','release_wheel','commit_archive'} or len(routes)!=3:failures.append('missing/duplicate routes')
for route in routes:
 name=route['name'];stages={s['stage']:s for s in route['stages']};issues=[]
 if route.get('status')!='pass':issues.append('route failed')
 for label in ['create_environment','install_public_package','installed_origin_and_resources','full_contract_suite','example_compose_prose.py','example_registered_plan.py','installed_cli']:
  if stages.get(label,{}).get('exit_code')!=0:issues.append(label+' missing or failed')
 suite=stages.get('full_contract_suite',{}).get('stderr','');counts=re.findall(r'Ran (\d+) tests?',suite)
 if counts!=['21'] or not re.search(r'\nOK\s*$',suite):issues.append('not exactly21passing tests')
 installed=route.get('installed',{})
 expected_prefix='/kaggle/working/github-install-matrix/'+name+'/venv'
 if installed.get('prefix')!=expected_prefix:issues.append('unexpected target environment prefix')
 for label in ['installed_origin_and_resources','full_contract_suite','example_compose_prose.py','example_registered_plan.py']:
  cmd=stages.get(label,{}).get('command',[])
  if not cmd or cmd[0]!=expected_prefix+'/bin/python':issues.append('unexpected interpreter '+label)
 if installed.get('version')!='0.2.0':issues.append('wrong version')
 if not Path(installed.get('origin','/missing')).is_relative_to(Path(installed.get('prefix','/invalid'))):issues.append('origin outside installed environment')
 if name=='git_tag' and installed.get('direct_url',{}).get('vcs_info',{}).get('commit_id')!=expected:issues.append('pip Git commit mismatch')
 if name=='release_wheel' and stages.get('download_release_wheel',{}).get('sha256')!='7d0ff38bcd3e8fc5370848d834284adca4453b2134cca85dd0d02a1d46b62e03':issues.append('wheel mismatch')
 if name=='commit_archive' and stages.get('archive_context_manifest',{}).get('exit_code')!=0:issues.append('archive manifest invalid')
 failures.extend(name+': '+i for i in issues)
 summaries.append({'route':name,'status':'pass' if not issues else 'fail','tests':int(counts[0]) if len(counts)==1 else None,'install_seconds':stages.get('install_public_package',{}).get('seconds'),'numpy':installed.get('numpy'),'scipy':installed.get('scipy')})
out={'status':'pass' if not failures else 'fail','routes':summaries,'failures':failures,'scope':'maker recomputation of remote installation/behavior evidence; no fully isolated dependency solve or model efficacy claim'}
(P/'VERIFICATION.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out));raise SystemExit(bool(failures))
