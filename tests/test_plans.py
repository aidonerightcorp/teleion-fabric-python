# Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md
import copy,unittest
from teleion_fabric.contracts import Engine,Port,compose
from teleion_fabric.plans import compile_plan
from teleion_fabric.settings import select
N=Port(int,'count');L=Port(list,'items')
def node(name,engine,source='$input',version='1'):return dict(id=name,engine=engine,version=version,source=source)
def document(nodes,outputs=None):return dict(nodes=nodes,outputs=outputs or {'result':nodes[-1]['id']})
class Plans(unittest.TestCase):
 def setUp(self):
  self.calls=[]
  def inc(x):self.calls.append('inc');return x+1
  self.inc=Engine('inc',N,N,inc);self.double=Engine('double',N,N,lambda x:x*2)
  self.registry={('inc','1'):self.inc,('double','1'):self.double}
 def test_generated_equivalence(self):
  p=compile_plan(document([node('a','inc'),node('b','double','a')]),self.registry,N)
  baseline=compose([self.inc,self.double])
  for value in range(-50,50):
   with self.subTest(value=value):self.assertEqual(p.run(value)['outputs']['result'],baseline(value)['value'])
 def test_branch_and_permutation(self):
  d=document([node('a','inc'),node('b','double')],{'increment':'a','doubled':'b'})
  p=compile_plan(d,self.registry,N);d['nodes'].reverse();q=compile_plan(d,self.registry,N)
  self.assertEqual(p.digest,q.digest);self.assertEqual(p.run(4)['outputs'],{'increment':5,'doubled':8})
 def test_reject_before_calls(self):
  bad=[document([node('a','missing')]),document([node('a','inc',version='2')]),document([node('a','inc','b'),node('b','double','a')]),document([node('a','inc'),node('a','inc')]),document([node('a','inc','missing')]),document([node('$input','inc')]),document([node('a','inc')],{'out':'absent'}),{'nodes':[node('a','inc')],'outputs':{'out':'a'},'execute':'evil'}]
  for d in bad:
   with self.subTest(d=d),self.assertRaises(ValueError):compile_plan(d,self.registry,N)
  self.assertEqual(self.calls,[])
 def test_semantics_versions_effects(self):
  for wrong in [Port(int,'dollars'),Port(int,'count','2'),Port(bool,'count')]:
   with self.assertRaises(ValueError):compile_plan(document([node('a','inc')]),self.registry,wrong)
  r={('net','1'):Engine('net',N,N,lambda x:x,('network',))}
  with self.assertRaises(ValueError):compile_plan(document([node('a','net')]),r,N)
 def test_failure_stops_downstream(self):
  r={**self.registry,('bad','1'):Engine('bad',N,N,lambda x:'wrong')}
  p=compile_plan(document([node('a','bad'),node('b','inc','a')]),r,N);result=p.run(2)
  self.assertEqual(result['status'],'failed');self.assertEqual(result['failed_node'],'a');self.assertFalse(result['task_accepted']);self.assertEqual(self.calls,[])
 def test_mutation_isolation(self):
  def mutate(x):x.append('changed');return x
  r={('mutate','1'):Engine('mutate',L,L,mutate),('copy','1'):Engine('copy',L,L,lambda x:x)}
  d=document([node('a','mutate'),node('b','copy')],{'changed':'a','original':'b'})
  p=compile_plan(d,r,L);d['nodes'][0]['source']='broken';value=['original'];result=p.run(value)
  self.assertEqual(value,['original']);self.assertEqual(result['outputs']['original'],value);self.assertEqual(result['outputs']['changed'],['original','changed'])
 def test_input_and_bounds(self):
  p=compile_plan(document([node('a','inc')]),self.registry,N)
  with self.assertRaises(TypeError):p.run(True)
  with self.assertRaises(ValueError):compile_plan(document([node(str(i),'inc') for i in range(65)]),self.registry,N)
  self.assertEqual(self.calls,[])
 def test_settings_types_and_ownership(self):
  for value in [True,1.0]:
   with self.assertRaises(ValueError):select({'n':{'value':1,'grid':[1]}},{'n':value})
  original={'x':{'value':[1],'grid':[[1]]}};selected=select(original);selected['x']['value'].append(2)
  self.assertEqual(original['x']['value'],[1])
  with self.assertRaises(ValueError):select(original,{'x':[True]})

 def test_registered_nested_validator(self):
  port=Port(list,'identifier_strings','1','string_items')
  validators={('string_items','1'):lambda value:all(type(x) is str for x in value)}
  r={('bad','1'):Engine('bad',N,port,lambda x:[1]),('consumer','1'):Engine('consumer',port,port,lambda x:self.calls.append('consumer') or x)}
  plan=document([node('a','bad'),node('b','consumer','a')])
  with self.assertRaises(ValueError):compile_plan(plan,r,N)
  result=compile_plan(plan,r,N,validators).run(2)
  self.assertEqual(result['failed_node'],'a');self.assertEqual(self.calls,[])
 def test_setting_schema_refusal(self):
  for malformed in [[],{'version':1},{'x':{'grid':'any'}},{'x':{'grid':[]}}]:
   with self.assertRaises(ValueError):select(malformed)
  with self.assertRaises(ValueError):select({},[])

 def test_legacy_compose_cannot_skip_validator(self):
  port=Port(list,'ids','1','string_items')
  with self.assertRaises(ValueError):compose([Engine('ids',port,port,lambda x:x)])

 def test_mutable_effects_and_truthy_validator_refused(self):
  r={('effect','1'):Engine('effect',N,N,lambda x:x,[])}
  with self.assertRaises(ValueError):compile_plan(document([node('a','effect')]),r,N)
  port=Port(int,'count','1','valid')
  r={('checked','1'):Engine('checked',port,port,lambda x:x)}
  plan=compile_plan(document([node('a','checked')]),r,port,{('valid','1'):lambda x:1})
  with self.assertRaises(ValueError):plan.run(1)

 def test_setting_object_key_confusion_refused(self):
  for value in [{True:'a'},{1:'a'},{1.0:'a'}]:
   with self.assertRaises(ValueError):select({'mode':{'value':value,'grid':[value]}})
   with self.assertRaises(ValueError):select({next(iter(value)):{'value':1,'grid':[1]}})
  self.assertEqual(select({'x':{'value':{'flag':True},'grid':[{'flag':True}]}})['x']['value'],{'flag':True})
 def test_copy_hooks_cycles_and_nonfinite_refused(self):
  called=[]
  class Alias:
   def __deepcopy__(self,memo):called.append('hook');return self
  r={('copy','1'):Engine('copy',L,L,lambda x:called.append('engine') or x)}
  p=compile_plan(document([node('a','copy')]),r,L)
  cycle=[];cycle.append(cycle)
  for value in [[Alias()],cycle,[float('nan')],[{1:'bad'}]]:
   with self.assertRaises(ValueError):p.run(value)
  self.assertEqual(called,[])
