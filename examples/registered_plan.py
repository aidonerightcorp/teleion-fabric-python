# Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md
"""Planner emits only a data graph; trusted application supplies the engine registry."""
import json
from teleion_fabric.contracts import Engine,Port
from teleion_fabric.plans import compile_plan
from teleion_fabric.task_profiler import profile
from teleion_fabric.prose_tools import segments
TEXT=Port(str,'task_text')
REGISTRY={
 ('profile','1'):Engine('profile',TEXT,Port(dict,'task_profile'),profile),
 ('structure','1'):Engine('structure',TEXT,Port(dict,'prose_structure'),segments),
}
PLAN={'nodes':[{'id':'profile','engine':'profile','version':'1','source':'$input'},
               {'id':'structure','engine':'structure','version':'1','source':'$input'}],
      'outputs':{'profile':'profile','structure':'structure'}}
if __name__=='__main__':
 result=compile_plan(PLAN,REGISTRY,TEXT).run('Clean the customer table. Preserve **identifier strings**.')
 assert result['status']=='completed'
 assert result['outputs']['profile']['formatting']['bold']
 print(json.dumps({'status':result['status'],'outputs':list(result['outputs']),'records':result['records'],'task_accepted':result['task_accepted']},indent=2))
