# Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md
"""Sequential ancestor accounting and explicit exact-tool fallback."""
import unittest
from types import SimpleNamespace
from stepkit import omninode as O

class AncestorBudget(unittest.TestCase):
    def parent(self,field='budget.tokens',cap=1):
        return O.OmniNode(O.CONTRACT.with_({'permissions.spawn':True,'budget.nodes':2,'budget.depth':1,field:cap}),O.PARAMETERS.with_({'arrangement':[['answer','take']]}))

    def test_implicit_child_grant_is_bounded(self):
        for field in ['budget.tokens','budget.model_seconds']:
            parent=self.parent(field)
            self.assertEqual(parent.spawn(parent.derive()).ask(field),1)
            with self.assertRaises(O.ContractError):parent.spawn(parent.derive({field:None}))

    def test_sequential_children_share_actual_usage(self):
        for field in ['budget.tokens','budget.model_seconds']:
            parent=self.parent(field)
            children=[parent.spawn(parent.derive()) for _ in range(2)]
            calls=[]
            def probe(call,task,seed=None):
                calls.append(call)
                return {'answer':4,'ok':True,'cost':{'model_s':1,'tok_in':1,'tok_out':0}}
            source=O.PartsSource(probe,{'answer':O.Part('answer',calls=[{'call':'authored'}])})
            records=[child.run({'id':str(i),'question':'What is 2+2?'},source) for i,child in enumerate(children)]
            self.assertEqual(len(calls),1)
            self.assertTrue(records[0].accepted)
            self.assertFalse(records[1].accepted)
            self.assertIn('ancestor',records[1].reason)

    def test_exact_fallback_survives_model_budget_exhaustion(self):
        parent=self.parent(cap=0)
        parent.contract=parent.contract.with_({'input.form':'batch','budget.when_used_up':'free_parts'})
        parent.parameters=parent.parameters.with_({'children.rule':'one_per_task','children.fallback_arrangement':[['answer','take']]})
        source=O.PartsSource(None,{'answer':O.Part('answer',value=lambda task:4)})
        record=parent.run([{'id':'exact','question':'What is 2+2?'}],source)
        self.assertEqual(len(record.children),1)
        self.assertTrue(record.children[0].accepted)
        self.assertTrue(record.children[0].evidence['zero_cost_only'])

    def test_exact_mode_refuses_probe_and_live_sources(self):
        for mode in ['probe','live','model']:
            parent=self.parent(cap=0)
            child=parent.spawn(parent.derive({'budget.tokens':None}),zero_cost_only=True)
            part=O.Part('answer',value=lambda task:4)
            if mode=='probe':part.calls=[{'call':'hidden'}]
            if mode=='model':part.model='authored'
            source=O.PartsSource(lambda *a,**k:self.fail('probe invoked'),{'answer':part})
            if mode=='live':source.live=True
            with self.assertRaises(O.ContractError):child.run({'id':mode,'question':'What is 2+2?'},source)

    def test_repeat_and_prepared_children_retain_charges(self):
        store=SimpleNamespace(nearest=lambda *args:{'parameters':None,'key':'authored','tried':[]})
        for field in ['budget.tokens','budget.model_seconds']:
            for mode in ['repeat','configure_between','prepare_two']:
                with self.subTest(field=field,mode=mode):
                    parent=self.parent(field);child=parent.spawn(parent.derive());calls=[]
                    def probe(call,task,seed=None):
                        calls.append(task['id'])
                        return {'answer':4,'ok':True,'cost':{'tok_in':1,'tok_out':0,'model_s':1}}
                    source=O.PartsSource(probe,{'answer':O.Part('answer',calls=[{'call':'authored'}])})
                    tasks=[{'id':name,'question':'What is 2+2?'} for name in ['a','b']]
                    if mode=='prepare_two':
                        for task in tasks:child.configure(task,store)
                    child.run(tasks[0],source)
                    if mode=='configure_between':child.configure(tasks[1],store)
                    child.run(tasks[1],source)
                    self.assertEqual(calls,['a'])
                    self.assertEqual(parent.used()['tok_in'],1)
                    self.assertEqual(parent.used()['model_s'],1)

    def test_fresh_root_run_has_independent_budget_and_stale_children_refused(self):
        parent=self.parent();old=parent.spawn(parent.derive());calls=[]
        def probe(call,task,seed=None):
            calls.append(task['id'])
            return {'answer':4,'ok':True,'cost':{'tok_in':1,'tok_out':0,'model_s':1}}
        source=O.PartsSource(probe,{'answer':O.Part('answer',calls=[{'call':'authored'}])})
        old.run({'id':'old','question':'What is 2+2?'},source)
        record=parent.run({'id':'fresh-root','question':'What is 2+2?'},source)
        self.assertTrue(record.accepted)
        self.assertEqual(parent.used()['tok_in'],1)
        with self.assertRaises(O.ContractError):old.run({'id':'stale','question':'What is 2+2?'},source)
        self.assertEqual(calls,['old','fresh-root'])

    def test_reported_probe_cost_survives_evidence_failure(self):
        parent=self.parent(cap=2);child=parent.spawn(parent.derive())
        def probe(call,task,seed=None):
            return {'answer':4,'ok':True,'cost':{'tok_in':1,'tok_out':0,'model_s':1}}
        def fail(*args):raise RuntimeError('authored evidence failure')
        source=O.PartsSource(probe,{'answer':O.Part('answer',calls=[{'call':'reported'}])})
        source.evidence=fail
        with self.assertRaises(RuntimeError):child.run({'id':'failure','question':'What is 2+2?'},source)
        self.assertEqual(parent.used()['tok_in'],1)
        self.assertEqual(parent.used()['model_s'],1)
