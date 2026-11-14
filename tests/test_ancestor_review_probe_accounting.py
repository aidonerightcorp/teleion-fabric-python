# Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md
import unittest
from stepkit import omninode as O
T={'id':'reported-probe','question':'What is 2+2?'}
class ProbeAccounting(unittest.TestCase):
 def node(self,arrangement):return O.OmniNode(O.CONTRACT.with_({'budget.tokens':10}),O.PARAMETERS.with_({'arrangement':arrangement}))
 def test_source_evidence_failure_retains_report(self):
  class Source(O.PartsSource):
   def evidence(self,*a):raise RuntimeError('evidence failure')
  source=Source(lambda *a,**k:{'answer':4,'cost':{'tok_in':1,'tok_out':0,'model_s':1}}, {'a':O.Part('a',calls=[{'call':'one'}])});n=self.node([['a','take']])
  with self.assertRaises(RuntimeError):n.run(T,source)
  self.assertEqual(n.used()['tok_in'],1);self.assertEqual(n.used()['model_s'],1)
 def test_cached_probe_reuse_not_double_charged(self):
  calls=[]
  def probe(call,*a,**k):calls.append(call);return {'answer':None,'ok':False,'cost':{'tok_in':1,'tok_out':0,'model_s':1}}
  source=O.PartsSource(probe,{x:O.Part(x,calls=[{'call':'same'}]) for x in ['a','b']});n=self.node([['a','take'],['b','take']]);r=n.run(T,source)
  self.assertEqual(calls,['same']);self.assertEqual(n.used()['tok_in'],1);self.assertEqual(r.cost_with_children['model_s'],1)
 def test_multiple_reported_probes_before_value_failure(self):
  def fail(t):raise RuntimeError('value failure')
  source=O.PartsSource(lambda *a,**k:{'answer':4,'ok':True,'cost':{'tok_in':1,'tok_out':0,'model_s':1}}, {'a':O.Part('a',calls=[{'call':'one'},{'call':'two'}],value=fail)});n=self.node([['a','take']])
  with self.assertRaises(RuntimeError):n.run(T,source)
  self.assertEqual(n.used()['tok_in'],2);self.assertEqual(n.used()['model_s'],2)
