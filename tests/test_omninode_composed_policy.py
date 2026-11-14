# Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md
"""Final maker acceptance applies to the parent task, not just a child's task."""
import unittest
from stepkit import omninode as O
TASK={'id':'composed-policy','question':'Return an authored answer'}
def composed(parent_form,child_form,value,checks=()):
 contract=O.CONTRACT.with_({'output.form':parent_form,'output.checks':list(checks),'permissions.spawn':True,'budget.nodes':1,'budget.depth':1})
 params=O.PARAMETERS.with_({'children.rule':'steps','children.steps':[{'name':'child','contract':{'output.form':child_form,'output.checks':[]},'parameters':{'children.rule':'none','arrangement':[['answer','take']]}}]})
 return O.OmniNode(contract,params).run(TASK,O.PartsSource(None,{'answer':O.Part('answer',value=lambda t:value)}))
class ComposedPolicy(unittest.TestCase):
 def test_parent_rejects_child_answer_wrong_for_own_form(self):
  r=composed('number','text','not a number')
  self.assertFalse(r.accepted);self.assertIsNone(r.answer);self.assertTrue(r.children[0].accepted)
  self.assertEqual(r.children[0].answer,'not a number');self.assertFalse(r.output_validation['form_ok'])
  self.assertEqual(r.output_validation['raw_answer'],'not a number')
 def test_compatible_child_forms_remain_allowed(self):
  for parent,child,value in [('any','text','text answer'),('number','number',9),('any','values',[9]),('any','query_result',[9])]:
   with self.subTest(parent=parent,child=child):
    r=composed(parent,child,value);self.assertTrue(r.accepted);self.assertEqual(r.answer,value);self.assertTrue(r.output_validation['form_ok'])
 def test_parent_failed_check_records_candidate_truth_once(self):
  calls=[];name='composed_nine';prior=O.CHECKS.get(name)
  O.CHECKS[name]=lambda a,p:calls.append(a) or a==9
  try:
   r=composed('number','number',4,[name]);self.assertFalse(r.accepted);self.assertIsNone(r.answer);self.assertEqual(r.output_checks,{name:False});self.assertEqual(calls,[4]);self.assertEqual(r.output_validation['raw_answer'],4);self.assertTrue(r.children[0].accepted)
  finally:
   if prior is None:O.CHECKS.pop(name,None)
   else:O.CHECKS[name]=prior
 def test_all_builtin_any_narrowings_execute(self):
  for form,value in [('number',9),('text','ok'),('choice','(A)'),('values',[9]),('query_result',[9])]:
   with self.subTest(form=form):
    n=O.OmniNode(O.CONTRACT.with_({'output.form':'any'}),O.PARAMETERS.with_({'output.form':form,'arrangement':[['answer','take']]}))
    self.assertEqual(n.ask('output.form'),form)
    r=n.run(TASK,O.PartsSource(None,{'answer':O.Part('answer',value=lambda t:value)}));self.assertTrue(r.accepted)
 def test_valid_unaccepted_candidate_is_not_promoted(self):
  n=O.OmniNode(O.CONTRACT.with_({'output.form':'number'}),O.PARAMETERS)
  r=n.record(TASK,[],9,False,'authored fallback',{})
  self.assertFalse(r.accepted);self.assertEqual(r.answer,9);self.assertTrue(r.output_validation['form_ok'])
if __name__=='__main__':unittest.main(verbosity=2)
