# Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md
"""Own-task declarations survive adaptation; child task contracts can differ."""
import unittest
from types import SimpleNamespace
from stepkit import omninode as O
TASK={'id':'own-policy','question':'Authored local task'}
class OwnPolicy(unittest.TestCase):
 def setUp(self):
  self.saved=dict(O.CHECKS);O.CHECKS.update({'own_nine':lambda a,p:a==9,'own_positive':lambda a,p:isinstance(a,int) and a>0})
 def tearDown(self):O.CHECKS.clear();O.CHECKS.update(self.saved)
 def node(self,bounds=None,proposals=None,via='parameters'):
  return O.OmniNode(O.CONTRACT.with_(bounds or {}),O.PARAMETERS.with_({'arrangement':[['answer','take']],**(proposals or {} if via=='parameters' else {})}),resolver=O.Resolver(evidence={k:{'value':v,'source':'authored proposal'} for k,v in (proposals or {}).items()} if via=='evidence' else {}))
 def run_value(self,n,value=9):
  calls=[]
  def answer(t):calls.append(t['id']);return value
  source=O.PartsSource(None,{'answer':O.Part('answer',value=answer)})
  return n,source,calls
 def test_required_checks_cannot_be_removed(self):
  for via in ['parameters','evidence']:
   n,s,c=self.run_value(self.node({'output.checks':['own_nine']},{'output.checks':[]},via),4)
   with self.assertRaises(O.ContractError):n.run(TASK,s)
   self.assertEqual(c,[])
 def test_declared_check_rejects_wrong_answer(self):
  n,s,c=self.run_value(self.node({'output.checks':['own_nine']}),4);r=n.run(TASK,s)
  self.assertFalse(r.accepted);self.assertEqual(c,[TASK['id']])
 def test_extra_checks_apply_and_effective_policy_is_recorded(self):
  n,s,c=self.run_value(self.node({'output.checks':['own_positive']},{'output.checks':['own_positive','own_nine']},'evidence'),4);r=n.run(TASK,s)
  self.assertFalse(r.accepted);self.assertEqual(r.contract['output.checks'],['own_positive'])
  self.assertEqual(r.effective_policy['output.checks'],['own_positive','own_nine']);self.assertEqual(r.to_dict()['effective_policy'],r.effective_policy)
  self.assertTrue(any(x['dimension']=='output.checks' and 'authored proposal' in x['why'] for x in r.choices))
 def test_input_form_cannot_be_shadowed(self):
  for via in ['parameters','evidence']:
   n,s,c=self.run_value(self.node({'input.form':'table'},{'input.form':'text'},via))
   with self.assertRaises(O.ContractError):n.run(TASK,s)
   self.assertEqual(c,[])
 def test_output_form_cannot_be_widened(self):
  for via in ['parameters','evidence']:
   n,s,c=self.run_value(self.node({'output.form':'number'},{'output.form':'text'},via),'wrong form')
   with self.assertRaises(O.ContractError):n.run(TASK,s)
   self.assertEqual(c,[])
 def test_output_form_narrows_and_preserves_declaration(self):
  n,s,c=self.run_value(self.node({'output.form':'any'},{'output.form':'number'}));r=n.run(TASK,s)
  self.assertTrue(r.accepted);self.assertEqual(r.contract['output.form'],'any');self.assertEqual(r.effective_policy['output.form'],'number')
 def test_task_text_cannot_be_enabled(self):
  for via in ['parameters','evidence']:
   n=self.node({'records.task_text':False},{'records.task_text':True},via)
   with self.assertRaises(O.ContractError):n.ask('records.task_text')
 def test_task_text_narrowing_is_recorded(self):
  n,s,c=self.run_value(self.node({'records.task_text':True},{'records.task_text':False},'evidence'));r=n.run(TASK,s)
  self.assertTrue(r.contract['records.task_text']);self.assertFalse(r.effective_policy['records.task_text'])
 def test_configured_store_cannot_drop_checks(self):
  n,s,c=self.run_value(self.node({'output.checks':['own_nine']}),4)
  n.configure(TASK,SimpleNamespace(nearest=lambda *a:{'parameters':O.PARAMETERS.with_({'arrangement':[['answer','take']],'output.checks':[]}), 'key':'authored'}))
  with self.assertRaises(O.ContractError):n.run(TASK,s)
  self.assertEqual(c,[])
 def test_explicit_child_forms_and_checks_can_differ(self):
  root=self.node({'input.form':'batch','output.form':'any','output.checks':['own_positive'],'permissions.spawn':True,'budget.depth':1,'budget.nodes':1})
  child=root.spawn(root.derive({'input.form':'text','output.form':'number','output.checks':['own_nine']}),O.PARAMETERS.with_({'arrangement':[['answer','take']]}))
  n,s,c=self.run_value(child);r=n.run(TASK,s);self.assertTrue(r.accepted);self.assertEqual(r.output_checks,{'own_nine':True})
 def test_malformed_or_unknown_checks_refused(self):
  for value in ['own_nine',[1],['unknown_check']]:
   n,s,c=self.run_value(self.node({}, {'output.checks':value}))
   with self.assertRaises(O.ContractError):n.run(TASK,s)
   self.assertEqual(c,[])
 def test_fresh_run_after_configured_policy_refusal(self):
  n,s,c=self.run_value(self.node({'output.checks':['own_nine']}))
  n.configure(TASK,SimpleNamespace(nearest=lambda *a:{'parameters':O.PARAMETERS.with_({'arrangement':[['answer','take']],'output.checks':[]}), 'key':'authored'}))
  with self.assertRaises(O.ContractError):n.run(TASK,s)
  r=n.run(dict(TASK,id='fresh'),s);self.assertTrue(r.accepted);self.assertEqual(c,['fresh'])
if __name__=='__main__':unittest.main(verbosity=2)
