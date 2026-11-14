# Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md
"""Authority must survive flexible child configuration; no model calls occur."""
import unittest
from stepkit.omninode import CONTRACT,PARAMETERS,OmniNode,ContractError,Part,PartsSource
TASK={'id':'scope-test','question':'What is 2 + 2?'}

def parent(**changes):
    values={'budget.depth':2,'budget.nodes':3,'permissions.spawn':True,'output.form':'number'}
    values.update(changes)
    return OmniNode(CONTRACT.with_(values),PARAMETERS)

def source(calls,model='small',live=False):
    def value(task):calls.append(task['id']);return 4
    result=PartsSource(None,{'answer':Part('answer',model=model,value=value)})
    result.live=live
    return result

class Authority(unittest.TestCase):
    def test_spawn_refuses_widened_resource_allowlists(self):
        for field in ['resources.parts','resources.models','resources.stores','resources.cartridges']:
            for value in [['other'],['allowed','other'],None]:
                with self.subTest(field=field,value=value):
                    node=parent(**{field:['allowed']})
                    with self.assertRaises(ContractError):node.spawn(node.derive({field:value}))
                    self.assertEqual(node.children,[])

    def test_spawn_allows_equal_and_narrowed_resources(self):
        for field in ['resources.parts','resources.models','resources.stores','resources.cartridges']:
            for value in [['allowed'],[]]:
                with self.subTest(field=field,value=value):
                    node=parent(**{field:['allowed']})
                    child=node.spawn(node.derive({field:value}))
                    self.assertEqual(child.ask(field),value)
        node=parent(**{'resources.models':None})
        self.assertEqual(node.spawn(node.derive({'resources.models':['small']})).ask('resources.models'),['small'])

    def test_reconfigured_child_cannot_bypass_parent_model_limit(self):
        node=parent(**{'resources.parts':['answer'],'resources.models':['small']})
        child=node.spawn(node.derive(),PARAMETERS.with_({'arrangement':[['answer','take']]}))
        child.contract=child.contract.with_({'resources.models':['large']},by='authored reconfiguration')
        calls=[]
        with self.assertRaises(ContractError):child.run(TASK,source(calls,model='large'))
        self.assertEqual(calls,[])

    def test_runtime_checks_all_ancestors(self):
        root=parent(**{'resources.models':['small']})
        child=root.spawn(root.derive({'budget.nodes':1,'permissions.spawn':True}))
        leaf=child.spawn(child.derive(),PARAMETERS.with_({'arrangement':[['answer','take']]}))
        child.contract=child.contract.with_({'resources.models':None})
        leaf.contract=leaf.contract.with_({'resources.models':None})
        calls=[]
        with self.assertRaises(ContractError):leaf.run(TASK,source(calls,model='large'))
        self.assertEqual(calls,[])

    def test_runtime_retains_parent_live_permission(self):
        root=parent(**{'permissions.live':False})
        child=root.spawn(root.derive(),PARAMETERS.with_({'arrangement':[['answer','take']]}))
        child.contract=child.contract.with_({'permissions.live':True})
        calls=[]
        with self.assertRaises(ContractError):child.run(TASK,source(calls,live=True))
        self.assertEqual(calls,[])

    def test_permitted_child_adapts_after_failed_step(self):
        root=parent(**{'resources.parts':['miss','answer'],'resources.models':['small']})
        child=root.spawn(root.derive(),PARAMETERS.with_({'arrangement':[['miss','take'],['answer','take']]}))
        calls=[];parts=source(calls)
        parts.parts['miss']=Part('miss',value=lambda task:None)
        record=child.run(TASK,parts)
        self.assertEqual(record.answer,4);self.assertTrue(record.accepted)
        self.assertEqual([s.node for s in record.steps],['miss','answer'])
        self.assertEqual(calls,['scope-test'])

if __name__=='__main__':unittest.main(verbosity=2)
