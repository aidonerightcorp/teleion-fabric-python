# Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md
"""Deterministic prose operations; untrusted response text never becomes instructions."""
import hashlib,json,re,math

def segments(text):
 return {'headings':[{'level':len(m[1]),'text':m[2]} for m in re.finditer(r'(?m)^(#{1,6})\s+(.+)$',text)],'paragraphs':[p.strip() for p in re.split(r'\n\s*\n',text) if p.strip()],'fences':[{'language':m[1],'text':m[2]} for m in re.finditer(r'```([^\n]*)\n(.*?)```',text,re.S)],'instruction_like_markup_present':bool(re.search(r'<(?:system-reminder|system|developer)\b',text,re.I))}

def _object(pairs):
 d={}
 for k,v in pairs:
  if k in d:raise ValueError('duplicate object keys')
  d[k]=v
 return d

def _reject_constant(value):raise ValueError('nonfinite JSON constant')
def _float(value):
 number=float(value)
 if not math.isfinite(number):raise ValueError('nonfinite JSON number')
 return number
def _loads(text):return json.loads(text,object_pairs_hook=_object,parse_constant=_reject_constant,parse_float=_float)
def _type(value):return 'boolean' if isinstance(value,bool) else 'null' if value is None else 'array' if isinstance(value,list) else 'object' if isinstance(value,dict) else 'number' if isinstance(value,(int,float)) else 'string'

def extract_json(text,expected_type,allow_value_wrapper=False):
 if type(allow_value_wrapper) is not bool:raise ValueError('wrapper policy must be boolean')
 if expected_type not in ['array','object','number','string','boolean','null','any']:raise ValueError('unsupported JSON contract')
 candidates=[];spans=[('whole_response',text)]+[('fenced_block',m[2].strip()) for m in re.finditer(r'```(json)?\s*\n(.*?)```',text,re.S|re.I)]
 for source,body in spans:
  try:value=_loads(body)
  except ValueError:continue
  transforms=[]
  if allow_value_wrapper and isinstance(value,dict) and len(value)==1 and next(iter(value)) in ['value','answer'] and expected_type!='object':value=next(iter(value.values()));transforms.append('explicitly_allowed_single_value_wrapper')
  if expected_type!='any' and _type(value)!=expected_type:continue
  key=json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)
  if all(c['canonical']!=key for c in candidates):candidates.append({'canonical':key,'value':value,'source':source,'transforms':transforms})
 status='format_validated' if len(candidates)==1 else 'ambiguous' if candidates else 'no_matching_json'
 return {'status':status,'value':candidates[0]['value'] if len(candidates)==1 else None,'candidates':candidates,'raw_sha256':hashlib.sha256(text.encode()).hexdigest(),'semantic_acceptance':'not_checked','execution_authorized':False}

if __name__=='__main__':
 import argparse
 from pathlib import Path
 a=argparse.ArgumentParser();a.add_argument('action',choices=['segments','extract_json']);a.add_argument('--input',type=Path,required=True);a.add_argument('--expected-type',default='any');a.add_argument('--allow-value-wrapper',action='store_true');args=a.parse_args();t=args.input.read_text();print(json.dumps(segments(t) if args.action=='segments' else extract_json(t,args.expected_type,args.allow_value_wrapper),ensure_ascii=False))
