# Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md
import unittest
from stepkit import omninode as O
T={'id':'first','question':'What is 2+2?'}
P=O.PARAMETERS.with_({'arrangement':[['answer','take']],'stop_rules':[]})
class EmptyStore:
 def nearest(self,*a):return {'parameters':None,'key':None,'tried':[]}
class Repeated(unittest.TestCase):
 def setup_case(self,bounds):
  p=O.OmniNode(O.CONTRACT.with_({'permissions.spawn':True,'budget.nodes':2,'budget.depth':1,**bounds}),P);c=p.spawn(p.derive());calls=[]
  def probe(call,task,seed=None):calls.append(task['id']);return {'answer':4,'ok':True,'cost':{'tok_in':1,'tok_out':0,'model_s':1}}
  return p,c,calls,O.PartsSource(probe,{'answer':O.Part('answer',calls=[{'call':'measured'}])})
 def safe_run(self,c,t,s):
  try:return c.run(t,s)
  except O.ContractError:return None
 def test_repeated_child_run(self):
  for field in ['budget.tokens','budget.model_seconds']:
   for id in ['first','second']:
    with self.subTest(field=field,id=id):
     p,c,calls,s=self.setup_case({field:1});self.safe_run(c,T,s);self.safe_run(c,dict(T,id=id),s);self.assertEqual(len(calls),1,repr({'calls':calls,'parent_used':p.used()}))
 def test_configure_does_not_erase_spent(self):
  p,c,calls,s=self.setup_case({'budget.tokens':1});self.safe_run(c,T,s)
  try:c.configure(dict(T,id='prepared'),EmptyStore())
  except O.ContractError:pass
  self.assertEqual(p.used()['tok_in'],1,'configuring a child erased consumed ancestor tokens')
 def test_prepared_context_switching(self):
  p,c,calls,s=self.setup_case({'budget.tokens':1})
  for id in ['first','second']:
   try:c.configure(dict(T,id=id),EmptyStore())
   except O.ContractError:pass
  for id in ['first','second']:self.safe_run(c,dict(T,id=id),s)
  self.assertEqual(len(calls),1,repr({'calls':calls,'parent_used':p.used()}))
 def test_kind_usage_survives_child_rerun(self):
  p,c,calls,s=self.setup_case({'budget.by_kind':{'text':1}});self.safe_run(c,T,s);self.safe_run(c,dict(T,id='second'),s)
  self.assertEqual(len(calls),1,repr({'calls':calls,'kind_usage':p.kind_usage()}))
