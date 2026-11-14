# Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md
"""Build by edges: prose -> normalized object -> identifiers."""
from teleion_fabric.contracts import Port,Engine,compose
from teleion_fabric.prose_tools import extract_json

def decode(text):
 result=extract_json(text,'object')
 if result['status']!='format_validated':raise ValueError(result['status'])
 return result['value']

def identifiers(value):
 ids=value['ids']
 if not isinstance(ids,list) or not all(type(i) is str for i in ids):raise ValueError('string identifiers required')
 return ids

workflow=compose([
 Engine('prose.decode',Port(str,'model_prose'),Port(dict,'identifier_object'),decode),
 Engine('identifiers.select',Port(dict,'identifier_object'),Port(list,'unchanged_identifiers'),identifiers),
])
if __name__=='__main__':
 result=workflow('Result:\n```json\n{"ids":["001","A-02"]}\n```')
 assert result['value']==['001','A-02']
 print(result)
