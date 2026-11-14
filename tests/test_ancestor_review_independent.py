# Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md
import unittest
from stepkit import omninode as O
T={'id':'review','question':'What is 2+2?'}
P=O.PARAMETERS.with_({'arrangement':[['answer','take']],'stop_rules':[]})
class Independent(unittest.TestCase):
 def parent(self,cap=1,**kw):return O.OmniNode(O.CONTRACT.with_({'permissions.spawn':True,'budget.nodes':4,'budget.depth':2,'budget.tokens':cap,**kw}),P)
 def source(self,calls):
  def probe(call,task,seed=None):calls.append((task['id'],call));return {'answer':None if call=='miss' else 4,'ok':call!='miss','cost':{'model_s':1,'tok_in':1,'tok_out':0}}
  return O.PartsSource(probe,{'answer':O.Part('answer',calls=[{'call':'answer'}]),'miss':O.Part('miss',calls=[{'call':'miss'}]),'exact':O.Part('exact',value=lambda task:4)})
 def run_child(self,child,source,id='review'):
  try:return child.run(dict(T,id=id),source)
  except O.ContractError:return None
 def test_parent_reconfigured_lower(self):
  p=self.parent(2);c=p.spawn(p.derive());p.contract=p.contract.with_({'budget.tokens':0});calls=[];self.run_child(c,self.source(calls));self.assertEqual(calls,[])
 def test_child_reconfigured_wider(self):
  p=self.parent(1);a=p.spawn(p.derive());b=p.spawn(p.derive());calls=[];s=self.source(calls);self.run_child(a,s,'a');b.contract=b.contract.with_({'budget.tokens':None});self.run_child(b,s,'b');self.assertEqual(len(calls),1)
 def test_multistage_delta(self):
  p=self.parent(3);q=P.with_({'arrangement':[['miss','take'],['answer','take']]});a=p.spawn(p.derive(),q);b=p.spawn(p.derive(),q);calls=[];s=self.source(calls);ra=self.run_child(a,s,'a');rb=self.run_child(b,s,'b');self.assertEqual(calls,[('a','miss'),('a','answer'),('b','miss')]);self.assertTrue(ra.accepted);self.assertFalse(rb.accepted);self.assertEqual(p.used()['tok_in'],3)
 def test_free_descendant_exact(self):
  p=self.parent(0);c=p.spawn(p.derive({'budget.tokens':None,'permissions.spawn':True,'budget.nodes':1}),zero_cost_only=True);d=c.spawn(c.derive(),P.with_({'arrangement':[['exact','take']]}));calls=[];r=self.run_child(d,self.source(calls));self.assertTrue(r.accepted);self.assertTrue(r.evidence['zero_cost_only']);self.assertEqual(calls,[])
 def test_free_descendant_probe_refused(self):
  p=self.parent(0);c=p.spawn(p.derive({'budget.tokens':None,'permissions.spawn':True,'budget.nodes':1}),zero_cost_only=True);d=c.spawn(c.derive());calls=[];self.run_child(d,self.source(calls));self.assertEqual(calls,[])
 def test_manual_children_kind_budget(self):
  kind=O.profile_of(T)['work'];p=self.parent(None,**{'budget.by_kind':{kind:1}});a=p.spawn(p.derive(kind=kind));b=p.spawn(p.derive(kind=kind));calls=[];s=self.source(calls);self.run_child(a,s,'a');self.run_child(b,s,'b');self.assertEqual(len(calls),1,repr({'kind':kind,'calls':calls,'parent_used':p.used()}))
 def test_stale_children_after_parent_context_reset(self):
  p=self.parent(1);a=p.spawn(p.derive());b=p.spawn(p.derive());calls=[];s=self.source(calls)
  p.parameters=P.with_({'arrangement':[['exact','take']]});p.run(dict(T,id='new-parent-run'),s)
  self.run_child(a,s,'old-a');self.run_child(b,s,'old-b');self.assertLessEqual(len(calls),1,repr({'calls':calls,'parent_used':p.used(),'attached_children':len(p.children)}))
if __name__=='__main__':unittest.main(verbosity=2)
