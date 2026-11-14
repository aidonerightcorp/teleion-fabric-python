# Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md
import unittest
from stepkit import omninode as O
T={'id':'exception-cost','question':'What is 2+2?'}
class Exceptions(unittest.TestCase):
 def case(self,mode):
  def explode(*a,**kw):raise RuntimeError('authored callback failure')
  calls=[]
  def probe(call,task,seed=None):
   calls.append(call)
   if call=='explode':explode()
   return {'answer':None if mode=='stage' else 4,'ok':mode!='stage','cost':{'tok_in':1,'tok_out':0,'model_s':1}}
  part=O.Part('part',calls=[{'call':'charged'}]);params={'arrangement':[['part','take']]};contract={'permissions.spawn':True,'budget.depth':1,'budget.nodes':1,'budget.tokens':2};parts={'part':part}
  if mode=='probe':part.calls.append({'call':'explode'})
  if mode=='value':part.value=explode
  if mode=='evidence':part.evidence=('checker_explode',);O.EVIDENCE_RULES['checker_explode']=explode
  if mode=='check':contract['output.checks']=['checker_explode'];O.CHECKS['checker_explode']=explode
  if mode=='stage':parts['explode']=O.Part('explode',value=explode);params['arrangement'].append(['explode','take'])
  p=O.OmniNode(O.CONTRACT.with_(contract),O.PARAMETERS.with_(params));c=p.spawn(p.derive())
  try:
   with self.assertRaises(RuntimeError):c.run(T,O.PartsSource(probe,parts))
   self.assertEqual(p.used()['tok_in'],1,repr({'mode':mode,'calls':calls,'used':p.used()}));self.assertEqual(p.used()['model_s'],1)
  finally:O.EVIDENCE_RULES.pop('checker_explode',None);O.CHECKS.pop('checker_explode',None)
 def test_separate_stage_cost_retained(self):self.case('stage')
 def test_later_probe_in_same_part(self):self.case('probe')
 def test_value_after_probe_in_same_part(self):self.case('value')
 def test_evidence_after_probe_in_same_part(self):self.case('evidence')
 def test_check_after_probe_in_same_part(self):self.case('check')
