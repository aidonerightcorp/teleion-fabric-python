# Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md
import unittest
from types import SimpleNamespace
from stepkit.omninode import CONTRACT,PARAMETERS,OmniNode,ContractError
from stepkit.dimension import Resolver
from test_omninode_contract_authority import TASK,source,parameters
class Reviewer(unittest.TestCase):
 def test_explicit_live_permission(self):
  calls=[];n=OmniNode(CONTRACT.with_({'permissions.live':True}),parameters())
  self.assertEqual(n.run(TASK,source(calls,live=True)).answer,4);self.assertEqual(calls,[TASK['id']])
 def test_narrow_permission_before_dispatch(self):
  n=OmniNode(CONTRACT.with_({'permissions.live':True}),parameters(),resolver=Resolver(evidence={'permissions.live':{'value':False,'source':'restrict'}}));calls=[]
  with self.assertRaises(ContractError):n.run(TASK,source(calls,live=True))
  self.assertEqual(calls,[])
 def test_child_configure_cannot_widen(self):
  root=OmniNode(CONTRACT.with_({'budget.depth':1,'budget.nodes':1,'permissions.spawn':True,'resources.models':['small']}),PARAMETERS)
  child=root.spawn(root.derive(),parameters());child.configure(TASK,SimpleNamespace(nearest=lambda *a:{'parameters':parameters(**{'resources.models':['large']}),'key':'authored'}));calls=[]
  with self.assertRaises(ContractError):child.run(TASK,source(calls,model='large'))
  self.assertEqual(calls,[])
 def test_fresh_run_after_configured_refusal(self):
  n=OmniNode(CONTRACT,parameters());n.configure(TASK,SimpleNamespace(nearest=lambda *a:{'parameters':parameters(**{'permissions.live':True}),'key':'authored'}));calls=[]
  with self.assertRaises(ContractError):n.run(TASK,source(calls,live=True))
  second=dict(TASK,id='second');self.assertEqual(n.run(second,source(calls)).answer,4);self.assertEqual(calls,['second']);self.assertFalse(n.ask('permissions.live'))
 def test_ordinary_evidence_and_choices(self):
  n=OmniNode(CONTRACT,parameters(),resolver=Resolver(evidence={'fallback':{'value':'none','source':'authored narrower workflow'}}))
  self.assertEqual(n.ask('fallback'),'none');self.assertTrue(any(c['dimension']=='fallback' and 'authored narrower workflow' in c['why'] for c in n.resolver.choices))
 def test_direct_ask_oracle_now_refusal(self):
  for via in ['parameters','evidence']:
   for k,b,v in [('permissions.live',False,True),('resources.parts',['A'],['B']),('resources.models',['small'],['large']),('budget.tokens',10,100)]:
    with self.subTest(via=via,key=k):
     n=OmniNode(CONTRACT.with_({k:b}),parameters(**({k:v} if via=='parameters' else {})),resolver=Resolver(evidence={k:{'value':v,'source':'authored'}} if via=='evidence' else {}))
     with self.assertRaises(ContractError):n.ask(k)
     self.assertTrue(any(c['dimension']==k and c['value']==v for c in n.resolver.choices))
