# Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md
"""Local callback tests: adaptive settings cannot grant contract authority."""
import unittest
from types import SimpleNamespace
from stepkit.dimension import Resolver
from stepkit.omninode import CONTRACT,PARAMETERS,OmniNode,ContractError,Part,PartsSource
TASK={'id':'root-boundary','question':'What is 2 + 2?'}

def source(calls,model='small',live=False):
    def answer(task):calls.append(task['id']);return 4
    s=PartsSource(None,{'answer':Part('answer',model=model,value=answer)})
    s.live=live
    return s

def parameters(**settings):
    return PARAMETERS.with_({'arrangement':[['answer','take']],**settings})

class ContractAuthority(unittest.TestCase):
    def test_parameters_do_not_grant_live_permission(self):
        n=OmniNode(CONTRACT.with_({'permissions.live':False}),parameters(**{'permissions.live':True}))
        calls=[]
        with self.assertRaises(ContractError):n.run(TASK,source(calls,live=True))
        self.assertEqual(calls,[])

    def test_evidence_does_not_grant_another_model(self):
        n=OmniNode(CONTRACT.with_({'resources.models':['small']}),parameters(),
                   resolver=Resolver(evidence={'resources.models':{'value':['large'],'source':'retrieved record'}}))
        calls=[]
        with self.assertRaises(ContractError):n.run(TASK,source(calls,model='large'))
        self.assertEqual(calls,[])

    def test_configured_store_does_not_grant_permission(self):
        stored=parameters(**{'permissions.live':True})
        store=SimpleNamespace(nearest=lambda *args:{'parameters':stored,'key':'authored-profile','tried':['authored-profile']})
        n=OmniNode(CONTRACT.with_({'permissions.live':False}),parameters())
        n.configure(TASK,store)
        calls=[]
        with self.assertRaises(ContractError):n.run(TASK,source(calls,live=True))
        self.assertEqual(calls,[])

    def test_exploration_does_not_enable_default_denial(self):
        n=OmniNode(CONTRACT,parameters(),resolver=Resolver(strategies={'permissions.live':'explore'}))
        calls=[]
        with self.assertRaises(ContractError):n.run(TASK,source(calls,live=True))
        self.assertEqual(calls,[])

    def test_valid_narrowing_remains_adaptive(self):
        cases=[('permissions.live',True,False),('resources.models',['small','large'],['small']),
               ('resources.parts',None,['answer']),('resources.stores',['one','two'],['one']),
               ('resources.cartridges',['one'],[]),('budget.tokens',100,20),
               ('budget.model_seconds',None,2),('budget.by_kind',{'lookup':10},{'lookup':5,'write':1})]
        for name,bound,value in cases:
            with self.subTest(name=name):
                n=OmniNode(CONTRACT.with_({name:bound}),parameters(),
                           resolver=Resolver(evidence={name:{'value':value,'source':'admitted proposal'}}))
                self.assertEqual(n.ask(name),value)
                self.assertTrue(any(c['dimension']==name and c['value']==value for c in n.resolver.choices))

    def test_widening_budget_and_resource_proposals_are_refused(self):
        cases=[('resources.models',[],None),('resources.stores',['one'],['two']),
               ('resources.cartridges',['one'],None),('permissions.spawn',False,True),
               ('budget.tokens',10,100),('budget.model_seconds',2,None),('budget.nodes',1,2),
               ('budget.depth',1,2),('budget.by_kind',{'lookup':10},{}),('budget.by_kind',{'lookup':10},{'lookup':11})]
        for name,bound,value in cases:
            with self.subTest(name=name,value=value):
                n=OmniNode(CONTRACT.with_({name:bound}),parameters(**{name:value}))
                with self.assertRaises(ContractError):n.ask(name)

    def test_malformed_authority_proposals_are_refused(self):
        cases=[('permissions.live',True,'yes'),('resources.models',None,'small'),
               ('budget.tokens',None,True),('budget.tokens',None,float('nan')),
               ('budget.tokens',None,float('inf')),('budget.tokens',None,-1),
               ('budget.by_kind',None,{'lookup':float('nan')})]
        for name,bound,value in cases:
            with self.subTest(name=name,value=value):
                n=OmniNode(CONTRACT.with_({name:bound}),parameters(),
                           resolver=Resolver(evidence={name:{'value':value}}))
                with self.assertRaises((ContractError,ValueError)):n.ask(name)

    def test_store_can_still_select_permitted_arrangement(self):
        stored=parameters()
        store=SimpleNamespace(nearest=lambda *args:{'parameters':stored,'key':'authored-profile','tried':['authored-profile']})
        n=OmniNode(CONTRACT.with_({'resources.parts':['answer'],'resources.models':['small']}),PARAMETERS)
        n.configure(TASK,store);calls=[]
        result=n.run(TASK,source(calls))
        self.assertTrue(result.accepted);self.assertEqual(result.answer,4);self.assertEqual(calls,['root-boundary'])

if __name__=='__main__':unittest.main(verbosity=2)
