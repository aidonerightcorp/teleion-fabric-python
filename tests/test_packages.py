# Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md
import importlib,json,pkgutil,unittest,tempfile,os
from pathlib import Path
from teleion_fabric import profile
from teleion_fabric.prose_tools import extract_json
from teleion_fabric.contracts import Engine,Port,compose
from teleion_fabric.settings import load,select
from teleion_fabric.context import packet
from teleion_fabric import opencode_omninode as Node

class Packages(unittest.TestCase):
 def test_profile(self):
  result=profile('Clean a table; preserve **identifier strings**.')
  self.assertTrue(result['formatting']['bold'])
 def test_json(self):
  self.assertEqual(extract_json('```json\n["001"]\n```','array')['value'],['001'])
  for raw in ['1e999','NaN']:self.assertEqual(extract_json(raw,'number')['status'],'no_matching_json')
  self.assertEqual(extract_json('{"a":1,"a":2}','object')['status'],'no_matching_json')
 def test_context(self):
  text,manifest=packet('task');self.assertEqual(len(manifest['all_component_ids']),73);self.assertEqual(len(manifest['all_edges']),309)
  self.assertIn('CURRENT TASK',text)
 def test_settings(self):
  selected=select(load());self.assertEqual(selected['threads']['value'],2)
  with self.assertRaises(ValueError):select(load(),{'threads':99})
 def test_composition(self):
  engine=Engine('split',Port(str,'text'),Port(list,'words'),str.split)
  result=compose([engine])('one two');self.assertEqual(result['value'],['one','two']);self.assertFalse(result['task_accepted'])
  with self.assertRaises(ValueError):compose([engine,Engine('bad',Port(list,'addresses'),Port(list,'addresses'),lambda x:x)])
  with self.assertRaises(ValueError):compose([Engine('effect',Port(str,'text'),Port(str,'text'),lambda x:x,('network',))])
 def test_imports(self):
  import stepkit,teleion_fabric
  for root in [stepkit,teleion_fabric]:
   for info in pkgutil.walk_packages(root.__path__,root.__name__+'.'):importlib.import_module(info.name)
 def test_harness_failure_records(self):
  request={'task_id':'t','attempt_id':'a','task':'Return an array','harness':{'name':'opencode','model':'fixture','version':'fixture'},'output_contract':{'kind':'json','json_type':'array'}}
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);stub=root/'opencode';stub.write_text('#!/usr/bin/env python3\nprint("null")\n');stub.chmod(0o700)
   env={**os.environ,'PATH':str(root)+':'+os.environ['PATH']}
   for k in ['XDG_DATA_HOME','XDG_STATE_HOME','XDG_CACHE_HOME','XDG_CONFIG_HOME']:env[k]=str(root/k)
   saved=[]
   def sink(record):saved.append(record);return {'ordinal':len(saved)}
   with self.assertRaises(Node.NodeFailure) as failure:Node.execute(request,env,sink,5)
   self.assertEqual(len(saved),2);self.assertEqual(saved[-1]['execution_record']['status'],'failed');self.assertIn('null',saved[-1]['raw_output']);self.assertEqual(failure.exception.artifact_ref,{'ordinal':2})
if __name__=='__main__':unittest.main()
