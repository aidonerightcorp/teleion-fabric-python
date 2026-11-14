# Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md
"""Bind every distributed file to the charter; write comments only to owned text."""
import argparse,hashlib,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
PY_MARK=re.compile(r'\A# Teleion context: CHARTER.md sha256=[a-f0-9]+; read AGENTS.md\n')
MD_MARK=re.compile(r'\A<!-- Teleion context: CHARTER.md sha256=[a-f0-9]+; read AGENTS.md -->\n\n')
def clean(text):return MD_MARK.sub('',PY_MARK.sub('',text))
def synchronize(write=False):
 digest=hashlib.sha256(clean((ROOT/'CHARTER.md').read_text()).encode()).hexdigest();hashes={};stale=[]
 resource=ROOT/'src/teleion_fabric/data/charter.json'
 data=json.loads(resource.read_text());current=clean((ROOT/'CHARTER.md').read_text())
 if data.get('charter')!=current:
  stale.append(str(resource.relative_to(ROOT)))
  if write:
   data['charter']=current;resource.write_text(json.dumps(data,indent=2)+'\n')
 for path in sorted(ROOT.rglob('*')):
  relative=path.relative_to(ROOT)
  if not path.is_file() or any((p.startswith('.') and p not in ['.github','.gitignore']) or p in ['__pycache__','build','dist'] or p.endswith('.egg-info') for p in relative.parts):continue
  if path.name in ['context-manifest.json','test-results.json']:continue
  if path.suffix in ['.py','.md']:
   body=clean(path.read_text());header=('# Teleion context: CHARTER.md sha256='+digest+'; read AGENTS.md\n') if path.suffix=='.py' else ('<!-- Teleion context: CHARTER.md sha256='+digest+'; read AGENTS.md -->\n\n')
   wanted=header+body
   if path.read_text()!=wanted:
    stale.append(str(relative))
    if write:path.write_text(wanted)
  hashes[str(relative)]=hashlib.sha256(path.read_bytes()).hexdigest()
 report={'charter_sha256':digest,'files':hashes,'scope':'owned source/docs receive comments; JSON/configuration use this sidecar; private history excluded'}
 manifest=ROOT/'context-manifest.json'
 if write:manifest.write_text(json.dumps(report,indent=2)+'\n')
 elif not manifest.exists() or json.loads(manifest.read_text())!=report:stale.append('context-manifest.json')
 return {'status':'synchronized' if write else 'pass' if not stale else 'stale','stale':stale,'files':len(hashes)}
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--write',action='store_true');p.add_argument('--check',action='store_true');args=p.parse_args();report=synchronize(args.write);print(json.dumps(report));raise SystemExit(report['status']=='stale')
