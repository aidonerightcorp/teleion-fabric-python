# Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md
"""Input -> task profile. No actions, permission changes, or automatic model calls."""
import hashlib,json,re,sys,unicodedata
from pathlib import Path
P=Path(__file__).resolve().parent
from stepkit.profile import text_profile
ANCHORS={'code':'Implement, debug, refactor and test software code.','data':'Parse, clean, transform, join and validate structured data.','research':'Find sources, compare evidence and synthesize a research answer.','reasoning':'Solve logical, mathematical and multistep reasoning problems.','writing':'Write, revise or summarize prose with tone and style constraints.','operations':'Recover interrupted jobs, reconcile effects, monitor services and manage durable work.','optimization':'Compare configurations, evaluate models and improve measured performance.'}
CUES={'code':r'\b(code|python|function|bug|refactor|implement)\b','data':r'\b(csv|table|database|normalize|deduplicate|join)\b','research':r'\b(research|sources|evidence|investigate|compare)\b','reasoning':r'\b(calculate|sum|prove|logic|reason|solve)\b','writing':r'\b(write|summarize|rewrite|tone|essay)\b','operations':r'\b(queue|lease|recover|restart|worker|rollback)\b','optimization':r'\b(optimiz\w*|benchmark|weights|embedding|harness|model)\b'}
LANG={'en':{'the','and','please','with','this','without','do','not'},'es':{'el','la','los','una','por','favor','sin','pero'},'fr':{'le','les','une','avec','sans','pour','mais'}}

def spans(pattern,text):return [{'start':m.start(),'end':m.end(),'text':m.group(0)} for m in re.finditer(pattern,text,re.M)]
def profile(text,semantic=False,transform=None):
 if not isinstance(text,str):raise TypeError('task must be a string')
 cfg=json.loads((P/'settings.json').read_text())
 if len(text)>cfg['max_input_chars']['value']:raise ValueError('input limit; explicit chunking required')
 lower=text.lower();words=re.findall(r'[^\W\d_]+',lower,re.UNICODE)
 fmt={'bold':spans(r'\*\*[^\n]+?\*\*|__[^\n]+?__',text),'highlight':spans(r'==[^\n]+?==',text),'headings':spans(r'^#{1,6}\s+.+$',text),'bullets':spans(r'^\s*(?:[-*+] |\d+[.)] ).+$',text),'code_fences':spans(r'^\s*```.*$',text),'uppercase':spans(r'\b[A-Z]{3,}\b',text)}
 cues={k:[{'start':m.start(),'end':m.end(),'text':m.group(0)} for m in re.finditer(p,text,re.I)] for k,p in CUES.items()}
 langs={k:sum(w in tokens for w in words) for k,tokens in LANG.items()};best=max(langs,key=langs.get);language=best if langs[best]>=2 else 'undetermined'
 scripts={k:sum(k in unicodedata.name(c,'') for c in text) for k in ['LATIN','CYRILLIC','ARABIC','HIRAGANA','KATAKANA','CJK']}
 constraints=spans(r'(?i)\b(?:must|should|never|without|do not|don.t|preserve|only|avoid)\b[^\n.!?]*',text)
 actions=re.findall(r'\b(?:ingest|parse|clean|normalize|deduplicate|join|validate|write|read|search|compare|test|deploy|recover|reconcile|summarize|calculate|implement|inspect|produce)\b',lower)
 steps=len(fmt['bullets']);distinct=len(set(actions))
 if not text.strip() or lower.strip() in ['fix everything','help','do it']:granularity='unknown'
 elif steps>=3 or distinct>=3:granularity='multi_atomic'
 elif distinct==2:granularity='medium'
 else:granularity='atomic_candidate'
 result={'schema':'teleion.task-profile/v1','input_sha256':hashlib.sha256(text.encode()).hexdigest(),'input_chars':len(text),'shape':text_profile(text),'formatting':fmt,'language':{'candidate':language,'cue_counts':langs,'script_counts':scripts,'status':'heuristic cues; not calibrated language identification'},'intent_cues':cues,'constraints':constraints,'granularity':{'candidate':granularity,'distinct_action_cues':distinct,'listed_steps':steps,'status':'heuristic; quoted text, code and repeated objectives may confound'},'semantic':{'status':'not_requested'},'authority':'formatting and semantic similarity confer no permission','engines':['stepkit_shape','formatting','language_cues','intent_cues']}
 if semantic:result['semantic']=semantic_profile(text,cfg,transform);result['engines'].append('semantic_anchors')
 return result

_ENCODER=None
def semantic_profile(text,cfg,transform=None):
 import os
 os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',CUDA_VISIBLE_DEVICES='')
 import numpy as np
 import torch
 from transformers import AutoTokenizer,AutoModel
 global _ENCODER
 path=Path(os.environ['TELEION_EMBEDDING_MODEL_PATH'])
 if _ENCODER is None:
  torch.set_num_threads(cfg['threads']['value']);_ENCODER=(AutoTokenizer.from_pretrained(path,local_files_only=True),AutoModel.from_pretrained(path,local_files_only=True).eval())
 tok,model=_ENCODER;words=text.split();window=cfg['semantic_window_words']['value'];stride=cfg['semantic_stride_words']['value']
 chunks=[' '.join(words[i:i+window]) for i in range(0,len(words),stride)] or ['']
 vectors=[];truncated=0
 for start in range(0,len(chunks)+len(ANCHORS),16):
  texts=(chunks+list(ANCHORS.values()))[start:start+16];truncated+=sum(len(tok.encode(t))>256 for t in texts)
  b=tok(texts,padding=True,truncation=True,max_length=256,return_tensors='pt')
  with torch.inference_mode():
   h=model(**b).last_hidden_state;m=b['attention_mask'].unsqueeze(-1);v=((h*m).sum(1)/m.sum(1)).numpy();vectors.extend(v)
 a=np.stack(vectors);transform_info={'kind':'identity','base_weights_edited':False}
 if transform is not None:
  weights=np.asarray(transform['weights'],dtype=float)
  if weights.shape!=(a.shape[1],) or not np.isfinite(weights).all() or (weights<=0).any():raise ValueError('positive finite diagonal weights of encoder dimension required')
  if not transform.get('source') or not transform.get('version'):raise ValueError('transform provenance required')
  a=a*weights;transform_info={'kind':'diagonal_feature_reweighting','source':transform['source'],'version':transform['version'],'sha256':hashlib.sha256(weights.tobytes()).hexdigest(),'base_weights_edited':False}
 a=a/np.maximum(np.linalg.norm(a,axis=1,keepdims=True),1e-12);similarity=a[:len(chunks)]@a[len(chunks):].T
 return {'status':'computed','encoder':str(path),'dimensions':int(a.shape[1]),'chunks':len(chunks),'truncated_chunks_and_anchors':truncated,'mean_cosine':dict(zip(ANCHORS,map(float,similarity.mean(axis=0)))),'max_cosine':dict(zip(ANCHORS,map(float,similarity.max(axis=0)))),'transform':transform_info,'limits':'Cosine is not meaning certainty, language competence, difficulty or execution authority. Encoder has English-oriented coverage; multilingual quality unqualified.'}

if __name__=='__main__':
 import argparse
 p=argparse.ArgumentParser();p.add_argument('--input',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--semantic',action='store_true');a=p.parse_args();a.output.write_text(json.dumps(profile(a.input.read_text(),a.semantic),indent=2,ensure_ascii=False)+'\n')
