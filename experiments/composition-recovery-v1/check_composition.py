# Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md
"""Installed-package composition/restart tests; no provider execution."""
import copy, hashlib, importlib.metadata, json, os, random, subprocess, sys, tempfile, unittest
from pathlib import Path
from teleion_fabric.contracts import Engine, Port
from teleion_fabric.plans import compile_plan
from teleion_fabric.task_profiler import profile
from teleion_fabric.prose_tools import segments
from stepkit.store import CheckedStore
from stepkit.record import Trace, StepRecord
HERE=Path(__file__).resolve().parent
CFG=json.loads((HERE/'settings.json').read_text())
NUMBER=Port(int,'exact_integer')
TEXT=Port(str,'task_text')

def node(name,engine,source='$input',version='1'):
    return dict(id=name,engine=engine,version=version,source=source)

def contact_plan():
    raw=Port(list,'contact_rows_raw');clean=Port(list,'contact_rows_clean')
    def normalize(rows):
        return [dict(id=r['id'],name=' '.join(r['name'].split()),email=r['email'].strip().lower()) for r in rows]
    reg={('contacts','1'):Engine('contacts',raw,clean,normalize)}
    return {'nodes':[node('clean','contacts')],'outputs':{'rows':'clean'}},reg,raw

class Composition(unittest.TestCase):
    def test_random_graphs_against_arithmetic_oracle(self):
        registry={(name,'1'):Engine(name,NUMBER,NUMBER,fn) for name,fn in [
            ('add',lambda x:x+7),('scale',lambda x:x*3),('negate',lambda x:-x)]}
        for seed in CFG['seeds']['value']:
            rng=random.Random(seed)
            for case in range(CFG['cases_per_seed']['value']):
                with self.subTest(seed=seed,case=case):
                    initial=rng.randint(-30,30);expected={'$input':initial};nodes=[]
                    for i in range(rng.randint(*CFG['node_count']['value'])):
                        name=f'n{i:02}';source=rng.choice(list(expected));op=rng.choice(['add','scale','negate'])
                        v=expected[source]
                        expected[name]=v+7 if op=='add' else v*3 if op=='scale' else -v
                        nodes.append(node(name,op,source))
                    outputs={k:k for k in expected};document=dict(nodes=nodes,outputs=outputs)
                    compiled=compile_plan(document,registry,NUMBER);actual=compiled.run(initial)
                    self.assertEqual(actual['outputs'],expected);self.assertEqual(actual['status'],'completed')
                    self.assertFalse(actual['task_accepted']);self.assertEqual(len(actual['records']),len(nodes))
                    rng.shuffle(nodes)
                    shuffled=compile_plan(document,registry,NUMBER)
                    self.assertEqual(shuffled.digest,compiled.digest)
                    self.assertEqual(shuffled.run(initial),actual)

    def test_branch_mutation_does_not_modify_sibling_or_caller(self):
        p=Port(dict,'mutable_json'); original={'nested':{'items':[1]}}
        def mutate(x):x['nested']['items'].append(99);return x
        registry={(name,'1'):Engine(name,p,p,fn) for name,fn in [('mutate',mutate),('identity',lambda x:x)]}
        plan={'nodes':[node('a','mutate'),node('b','identity')],'outputs':{'a':'a','b':'b','input':'$input'}}
        result=compile_plan(plan,registry,p).run(original)
        self.assertEqual(original,{'nested':{'items':[1]}})
        self.assertEqual(result['outputs']['b'],original);self.assertEqual(result['outputs']['input'],original)
        self.assertEqual(result['outputs']['a']['nested']['items'],[1,99])

    def test_failed_producer_stops_consumers_and_preserves_record(self):
        calls=[]
        def fail(x):calls.append('fail');raise RuntimeError('authored failure')
        def later(x):calls.append('later');return x
        registry={('fail','1'):Engine('fail',NUMBER,NUMBER,fail),('later','1'):Engine('later',NUMBER,NUMBER,later)}
        result=compile_plan({'nodes':[node('a','fail'),node('b','later','a')],'outputs':{'out':'b'}},registry,NUMBER).run(1)
        self.assertEqual(calls,['fail']);self.assertEqual(result['status'],'failed')
        self.assertEqual(result['outputs'],{});self.assertFalse(result['task_accepted'])
        self.assertEqual(result['records'],[dict(node='a',engine='fail',version='1',status='failed',error_type='RuntimeError')])

    def test_invalid_graphs_are_refused_before_execution(self):
        calls=[]
        def identity(x):calls.append(x);return x
        registry={('ok','1'):Engine('ok',NUMBER,NUMBER,identity),
                  ('effect','1'):Engine('effect',NUMBER,NUMBER,identity,effects=('write',)),
                  ('different','1'):Engine('different',Port(int,'cents'),NUMBER,identity)}
        cases=[ [node('a','missing')], [node('a','ok',version='2')], [node('a','ok','missing')],
                [node('a','ok','b'),node('b','ok','a')], [node('a','effect')],
                [node('a','different')], [node('a','ok'),node('a','ok')] ]
        for nodes in cases:
            with self.subTest(nodes=nodes),self.assertRaises(ValueError):
                compile_plan({'nodes':nodes,'outputs':{'out':'a'}},registry,NUMBER)
        self.assertEqual(calls,[])

    def test_nested_port_validator_blocks_consumer(self):
        p=Port(dict,'positive_count','1','count');calls=[]
        def consume(x):calls.append(x);return x
        registry={('consume','1'):Engine('consume',p,p,consume)}
        validators={('count','1'):lambda x:type(x.get('count')) is int and x['count']>0}
        plan=compile_plan({'nodes':[node('a','consume')],'outputs':{'out':'a'}},registry,p,validators)
        for value in [{'count':True},{'count':-1},{'count':'1'},{}]:
            with self.subTest(value=value),self.assertRaises(ValueError):plan.run(value)
        self.assertEqual(calls,[])
        self.assertEqual(plan.run({'count':2})['status'],'completed')

    def test_saved_plan_retrieved_after_fresh_process(self):
        document,_,_=contact_plan();store=CheckedStore()
        store.add('approved','normalize company contact names emails',document,checked=True)
        store.add('unreviewed','normalize company contact names emails',{'invalid':True},checked=False)
        store.add('unrelated','calculate triangle geometry',{'unrelated':True},checked=True)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'objects.jsonl';store.save(path)
            child=subprocess.run([sys.executable,'-I',str(Path(__file__).resolve()),'--restart-child',str(path)],capture_output=True,text=True,timeout=20)
            self.assertEqual(child.returncode,0,child.stderr)
            result=json.loads(child.stdout)
        self.assertEqual(result['selected'],'approved')
        self.assertEqual(result['rows'],[{'id':'0007','name':'Acme Ltd','email':'hello@example.test'}])
        self.assertFalse(result['task_accepted'])

    def test_store_replacement_invalidates_cached_search(self):
        store=CheckedStore();store.add('a','company names',1,checked=True,vector=[1,0])
        store.add('b','triangle geometry',2,checked=True,vector=[0,1])
        self.assertEqual(store.nearest(text='company names',k=1)[0]['key'],'a')
        self.assertEqual(store.nearest(vector=[1,0],k=1)[0]['key'],'a')
        store.add('a','company names',3,checked=False,vector=[1,0])
        self.assertEqual(store.nearest(text='company names',k=1)[0]['key'],'b')
        self.assertEqual(store.nearest(vector=[1,0],k=1)[0]['key'],'b')
        self.assertEqual(store.nearest(text='company names',k=1,only_checked=False)[0]['payload'],3)

    def test_trace_roundtrip_retains_failed_attempt_cost(self):
        trace=Trace('contact-1')
        trace.append(StepRecord('contact-1',1,'first',accepted=False,cost={'calls':1,'tok_in':11,'tok_out':0,'model_s':.5,'tool_ms':0},reason='rejected'))
        trace.append(StepRecord('contact-1',2,'second',accepted=True,answer='done',cost={'calls':1,'tok_in':7,'tok_out':3,'model_s':.25,'tool_ms':2}))
        trace.finish('done','checker accepted authored case')
        restored=Trace.from_json(trace.to_json())
        self.assertEqual(restored.to_dict(),trace.to_dict())
        self.assertEqual(restored.total_cost(),{'calls':2,'tok_in':18,'tok_out':3,'model_s':.75,'tool_ms':2})
        self.assertFalse(restored.steps[0].accepted)

    def test_contact_checker_handles_identifiers_and_empty_values(self):
        document,registry,port=contact_plan()
        rows=[{'id':'0010','name':'  A   B ','email':' X@EXAMPLE.TEST '},{'id':'0','name':'','email':''},{'id':'é-01','name':' Café  Société ','email':' contact@example.test'}]
        actual=compile_plan(document,registry,port).run(rows)
        self.assertEqual(actual['outputs']['rows'],[{'id':'0010','name':'A B','email':'x@example.test'},{'id':'0','name':'','email':''},{'id':'é-01','name':'Café Société','email':'contact@example.test'}])
        self.assertEqual(rows[0]['name'],'  A   B ')
        self.assertFalse(actual['task_accepted'])

    def test_parallel_profile_and_prose_contracts(self):
        registry={('profile','1'):Engine('profile',TEXT,Port(dict,'profile'),profile),('segments','1'):Engine('segments',TEXT,Port(dict,'structure'),segments)}
        document={'nodes':[node('a','profile'),node('b','segments')],'outputs':{'profile':'a','structure':'b'}}
        text='# Contactos\nPor favor, preserve **0007**.\n- clean names\n- validate emails\n- write table\n\n```text\n0007\n```\n'
        result=compile_plan(document,registry,TEXT).run(text)
        self.assertEqual(result['status'],'completed')
        p=result['outputs']['profile'];self.assertEqual(p['input_sha256'],hashlib.sha256(text.encode()).hexdigest())
        self.assertEqual(p['granularity']['candidate'],'multi_atomic')
        self.assertEqual(p['formatting']['bold'][0]['text'],'**0007**')
        self.assertEqual(p['semantic']['status'],'not_requested');self.assertFalse(result['task_accepted'])
        self.assertEqual(result['outputs']['structure'],{
            'headings':[{'level':1,'text':'Contactos'}],
            'paragraphs':['# Contactos\nPor favor, preserve **0007**.\n- clean names\n- validate emails\n- write table','```text\n0007\n```'],
            'fences':[{'language':'text','text':'0007\n'}],
            'instruction_like_markup_present':False})

if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--restart-child':
        store=CheckedStore.load(sys.argv[2]);hit=store.nearest(text='normalize company contact names emails',k=1)[0]
        _,registry,port=contact_plan();result=compile_plan(hit['payload'],registry,port).run([{'id':'0007','name':' Acme   Ltd ','email':' HELLO@EXAMPLE.TEST '}])
        print(json.dumps({'selected':hit['key'],'rows':result['outputs']['rows'],'task_accepted':result['task_accepted']}))
    else:unittest.main(verbosity=2)
