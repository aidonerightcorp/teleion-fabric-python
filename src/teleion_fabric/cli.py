# Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md
import argparse,json
from pathlib import Path
from . import profile
from .prose_tools import segments,extract_json
from .context import packet
from .settings import load

def main():
 parser=argparse.ArgumentParser();parser.add_argument('action',choices=['profile','segments','extract-json','context','settings']);parser.add_argument('--input',type=Path);parser.add_argument('--type',default='any');parser.add_argument('--settings',default='profiler');args=parser.parse_args()
 if args.action=='settings':result=load(args.settings)
 else:
  if args.input is None:parser.error('--input required')
  text=args.input.read_text()
  if args.action=='profile':result=profile(text)
  elif args.action=='segments':result=segments(text)
  elif args.action=='extract-json':result=extract_json(text,args.type)
  else:result={'packet':packet(text)[0],'manifest':packet(text)[1]}
 print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
