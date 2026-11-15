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

def _validate_json_contract(text,expected_type,allow_value_wrapper):
 if not isinstance(text,str):raise ValueError('text payload required')
 if type(allow_value_wrapper) is not bool:raise ValueError('wrapper policy must be boolean')
 if expected_type not in ['array','object','number','string','boolean','null','any']:raise ValueError('unsupported JSON contract')

def _parse_strict_value(body,expected_type,allow_value_wrapper):
 value=_loads(body)
 transforms=[]
 if allow_value_wrapper and isinstance(value,dict) and len(value)==1 and next(iter(value)) in ['value','answer'] and expected_type!='object':
  value=next(iter(value.values()));transforms.append('explicitly_allowed_single_value_wrapper')
 if expected_type!='any' and _type(value)!=expected_type:raise ValueError('JSON type mismatch')
 return value,transforms

def strict_json(text,expected_type,allow_value_wrapper=False):
 """Fail-closed whole-payload JSON check; rejects envelope prefixes, fences, and surrounding prose."""
 _validate_json_contract(text,expected_type,allow_value_wrapper)
 raw_sha=hashlib.sha256(text.encode('utf-8')).hexdigest()
 try:value,transforms=_parse_strict_value(text,expected_type,allow_value_wrapper);ok=True
 except ValueError:value=None;transforms=[];ok=False
 return {'status':'strict_json_valid' if ok else 'strict_json_rejected','strict_valid':ok,'value':value,'transforms':transforms,'raw_sha256':raw_sha,'task_accepted':False,'semantic_acceptance':'not_checked','execution_authorized':False}

def extract_json(text,expected_type,allow_value_wrapper=False):
 _validate_json_contract(text,expected_type,allow_value_wrapper)
 candidates=[];spans=[('whole_response',text)]+[('fenced_block',m[2].strip()) for m in re.finditer(r'```(json)?\s*\n(.*?)```',text,re.S|re.I)]
 for source,body in spans:
  try:value,transforms=_parse_strict_value(body,expected_type,allow_value_wrapper)
  except ValueError:continue
  key=json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)
  if all(c['canonical']!=key for c in candidates):candidates.append({'canonical':key,'value':value,'source':source,'transforms':transforms})
 status='format_validated' if len(candidates)==1 else 'ambiguous' if candidates else 'no_matching_json'
 return {'status':status,'value':candidates[0]['value'] if len(candidates)==1 else None,'candidates':candidates,'raw_sha256':hashlib.sha256(text.encode('utf-8')).hexdigest(),'semantic_acceptance':'not_checked','execution_authorized':False}

def diagnose_json_boundary(text,expected_type,allow_value_wrapper=False,settings_overrides=None):
 """Distinguish fail-closed strict JSON failures from envelope-prefix or markdown-fence contamination."""
 from . import settings as S
 selected=S.select(S.load('boundary'),settings_overrides)
 schema=selected['diagnosis_schema_version']['value']
 tags=selected['envelope_tags']['value']
 strict=strict_json(text,expected_type,allow_value_wrapper)
 tag_group='|'.join(re.escape(tag) for tag in tags)
 block_re=re.compile(rf'<({tag_group})\b[^>]*>.*?</\1>',re.S|re.I)
 open_re=re.compile(rf'<(?:{tag_group})\b[^>]*>',re.I)
 lead_re=re.compile(rf'^\s*<(?:{tag_group})\b',re.I)
 fence_re=re.compile(r'```(?:json)?\s*\n(.*?)```',re.S|re.I)
 full_fence_re=re.compile(r'^\s*```(?:json)?\s*\n(.*?)```\s*$',re.S|re.I)
 envelope_present=bool(open_re.search(text))
 leading_prefix=bool(lead_re.search(text))
 fence_present=bool(fence_re.search(text))
 stripped=open_re.sub('',block_re.sub('',text)).strip() if envelope_present else text.strip()
 stripped_sha=hashlib.sha256(stripped.encode('utf-8')).hexdigest()
 if strict['strict_valid']:
  return {'schema':schema,'strict_valid':True,'status':strict['status'],'value':strict['value'],'failure_kind':'none','contamination_detected':False,'contamination_layers':[],'leading_envelope_prefix':False,'envelope_markup_present':envelope_present,'markdown_fence_present':fence_present,'diagnostic_candidate':None,'diagnostic_only':False,'raw_sha256':strict['raw_sha256'],'stripped_sha256':stripped_sha,'task_accepted':False,'semantic_acceptance':'not_checked','execution_authorized':False}
 layers=[];candidate=None;failure_kind='type_mismatch_or_malformed_json'
 stripped_strict=strict_json(stripped,expected_type,allow_value_wrapper)
 if envelope_present and stripped_strict['strict_valid']:
  layers=['instruction_envelope'];candidate=stripped_strict['value'];failure_kind='envelope_prefix_only' if leading_prefix else 'envelope_markup_only'
 else:
  full_fence=full_fence_re.match(text)
  fenced_strict=strict_json(full_fence.group(1).strip(),expected_type,allow_value_wrapper) if (not envelope_present and full_fence is not None) else None
  if fenced_strict is not None and fenced_strict['strict_valid']:
   layers=['markdown_fence'];candidate=fenced_strict['value'];failure_kind='markdown_fence_only'
  else:
   extracted=extract_json(stripped,expected_type,allow_value_wrapper)
   raw_extracted=extract_json(text,expected_type,allow_value_wrapper)
   if extracted['status']=='format_validated':
    if envelope_present:layers.append('instruction_envelope')
    if bool(fence_re.search(stripped)):layers.append('markdown_fence')
    without_fences=fence_re.sub('',stripped).strip()
    if without_fences:layers.append('surrounding_prose')
    candidate=extracted['value']
    failure_kind='envelope_and_fence_or_prose' if envelope_present else 'fence_and_surrounding_prose'
   elif extracted['status']=='ambiguous' or raw_extracted['status']=='ambiguous':
    failure_kind='ambiguous_embedded_candidates'
 return {'schema':schema,'strict_valid':False,'status':strict['status'],'value':None,'failure_kind':failure_kind,'contamination_detected':bool(layers),'contamination_layers':layers,'leading_envelope_prefix':leading_prefix,'envelope_markup_present':envelope_present,'markdown_fence_present':fence_present,'diagnostic_candidate':candidate,'diagnostic_only':candidate is not None,'raw_sha256':strict['raw_sha256'],'stripped_sha256':stripped_sha,'task_accepted':False,'semantic_acceptance':'not_checked','execution_authorized':False}

if __name__=='__main__':
 import argparse
 from pathlib import Path
 a=argparse.ArgumentParser();a.add_argument('action',choices=['segments','extract_json','strict_json','diagnose_json_boundary']);a.add_argument('--input',type=Path,required=True);a.add_argument('--expected-type',default='any');a.add_argument('--allow-value-wrapper',action='store_true');args=a.parse_args();t=args.input.read_text()
 dispatch={'segments':lambda:segments(t),'extract_json':lambda:extract_json(t,args.expected_type,args.allow_value_wrapper),'strict_json':lambda:strict_json(t,args.expected_type,args.allow_value_wrapper),'diagnose_json_boundary':lambda:diagnose_json_boundary(t,args.expected_type,args.allow_value_wrapper)}
 print(json.dumps(dispatch[args.action](),ensure_ascii=False))
