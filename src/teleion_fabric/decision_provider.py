# Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md
"""Optional SubQ decision edge; prepares and validates, never executes a chosen tool."""
import hashlib,json,math,re,urllib.request,urllib.error
from pathlib import Path
BASE='https://api.subq.ai/v1'
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs):return None

def prepare(state,questions,config):
 if not isinstance(questions,dict) or not 1<=len(questions)<=128:raise ValueError('question count')
 for name,q in questions.items():
  if not isinstance(name,str) or not 1<=len(name)<=100:raise ValueError('question name')
  if q.get('type')!='choice':raise ValueError('this adapter currently qualifies choice only')
  if not isinstance(q.get('instructions'),str) or not q['instructions']:raise ValueError('instructions required')
  if not isinstance(q.get('criteria'),dict) or not 2<=len(q['criteria'])<=255:raise ValueError('choice criteria')
 def inspect(value):
  if isinstance(value,str) and re.search(r'\bsk-[A-Za-z0-9_-]{16,}|Bearer\s+[A-Za-z0-9_-]{16,}',value):raise ValueError('credential-like input refused')
  if isinstance(value,dict):
   for k,v in value.items():
    if re.sub(r'[^a-z]','',str(k).lower()) in {'authorization','apikey','password','secret','accesstoken','refreshtoken'}:raise ValueError('credential field refused')
    inspect(k);inspect(v)
  elif isinstance(value,(list,tuple)):
   for v in value:inspect(v)
 inspect(state);inspect(questions)
 body=json.loads(json.dumps({'model':config['model']['value'],'state':state,'questions':questions}))
 raw=json.dumps(body,separators=(',',':'),ensure_ascii=True).encode()
 if len(raw)>config['max_body_bytes']['value']:raise ValueError('body exceeds local request allowance')
 if re.search(rb'\bsk-[A-Za-z0-9_-]{16,}|Bearer\s+[A-Za-z0-9_-]{16,}',raw):raise ValueError('credential-like input refused')
 return {'body':body,'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'endpoint':BASE+'/systemone'}

def parse(prepared,response):
 raw=json.dumps(prepared['body'],separators=(',',':'),ensure_ascii=True).encode()
 if hashlib.sha256(raw).hexdigest()!=prepared['sha256']:raise ValueError('prepared contract changed')
 if response.get('model')!=prepared['body']['model']:raise ValueError('model mismatch')
 answers=response.get('answers',{});questions=prepared['body']['questions']
 if set(answers)!=set(questions):raise ValueError('answer keys mismatch')
 for k,a in answers.items():
  choices=questions[k]['criteria'];probs=a.get('probabilities',{})
  if a.get('type')!='choice' or a.get('choice') not in choices or set(probs)!=set(choices):raise ValueError('choice contract mismatch')
  values=[*probs.values(),a.get('confidence')]
  if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not 0<=v<=1 for v in values):raise ValueError('invalid probability')
  if abs(sum(probs.values())-1)>0.001:raise ValueError('probability normalization')
 usage=response.get('usage',{})
 if any(type(usage.get(k)) is not int or usage[k]<0 for k in ['input_tokens','output_tokens']):raise ValueError('missing/invalid token usage')
 if usage['output_tokens']!=0:raise ValueError('unexpected billed decision output')
 return {'provider':'subq','model':response['model'],'request_sha256':prepared['sha256'],'answers':answers,'usage':usage,'execution_authorized':False,'qualification':'provider decision only; confidence uncalibrated; deterministic contract and permissions still govern'}

def send(prepared,key,timeout):
 # No generic URL argument; credentials are sent only to the documented HTTPS host.
 raw=json.dumps(prepared['body'],separators=(',',':'),ensure_ascii=True).encode()
 if hashlib.sha256(raw).hexdigest()!=prepared['sha256']:raise ValueError('prepared body changed')
 req=urllib.request.Request(BASE+'/systemone',data=raw,headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},method='POST')
 opener=urllib.request.build_opener(NoRedirect)
 with opener.open(req,timeout=timeout) as r:return parse(prepared,json.load(r))
