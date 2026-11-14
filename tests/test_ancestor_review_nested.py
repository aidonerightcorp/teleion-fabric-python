# Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md
import unittest
from stepkit import omninode as O
T={'id':'nested','question':'What is 2+2?'}
P=O.PARAMETERS.with_({'arrangement':[['answer','take']],'stop_rules':[]})
class Store:
 def nearest(self,*args):return {'parameters':None,'key':None,'tried':[]}
class Nested(unittest.TestCase):
 def setup_case(self,cap):
  root=O.OmniNode(O.CONTRACT.with_({'permissions.spawn':True,'budget.nodes':4,'budget.depth':2,'budget.tokens':cap}),P);calls=[]
  def probe(call,task,seed=None):calls.append(task['id']);return {'answer':4,'ok':True,'cost':{'tok_in':1,'tok_out':0,'model_s':1}}
  return root,calls,O.PartsSource(probe,{'answer':O.Part('answer',calls=[{'call':'meter'}])})
 def mid(self,r):return r.spawn(r.derive({'permissions.spawn':True,'budget.nodes':2}))
 def test_nested_no_double_count(self):
  r,calls,s=self.setup_case(2);m=self.mid(r);g=m.spawn(m.derive())
  for i in range(3):g.run(dict(T,id=str(i)),s)
  self.assertEqual(len(calls),2);self.assertEqual(r.used()['tok_in'],2);self.assertEqual(m.used()['tok_in'],2);self.assertEqual(r.kind_usage()['text'],2)
 def test_prepared_totals(self):
  r,calls,s=self.setup_case(2);c=r.spawn(r.derive())
  for i in range(3):c.configure(dict(T,id=str(i)),Store())
  for i in range(3):c.run(dict(T,id=str(i)),s)
  self.assertEqual(len(calls),2);self.assertEqual(r.used()['tok_in'],2);self.assertEqual(r.kind_usage()['text'],2)
 def test_root_runs_independent(self):
  r,calls,s=self.setup_case(1)
  for i in range(3):
   rec=r.run(dict(T,id=str(i)),s);self.assertTrue(rec.accepted);self.assertEqual(r.used()['tok_in'],1)
  self.assertEqual(len(calls),3)
 def test_nested_reconfigure_remaining_implicit_grant(self):
  r,calls,s=self.setup_case(2);m=self.mid(r);g=m.spawn(m.derive());g.run(T,s)
  m.configure(dict(T,id='new-mid'),Store())
  self.assertEqual(r.used()['tok_in'],1)
  try:second=m.spawn(m.derive())
  except O.ContractError as exc:self.fail('valid implicit remaining-budget grandchild refused: '+str(exc))
  self.assertLessEqual(second.ask('budget.tokens'),1);second.run(dict(T,id='second'),s)
  self.assertEqual(len(calls),2);self.assertEqual(r.used()['tok_in'],2)
