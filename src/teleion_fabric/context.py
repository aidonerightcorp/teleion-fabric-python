# Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md
"""Complete public family inventory and relationships; no private histories."""
import json,hashlib
from importlib.resources import files

def packet(query):
 raw=files('teleion_fabric').joinpath('data/capabilities.json').read_text();catalog=json.loads(raw)
 charter=files('teleion_fabric').joinpath('data/charter.json').read_text()
 text=charter+'\n\nCOMPLETE PUBLIC ARCHITECTURE REGISTER\n'+raw+'\n\nCURRENT TASK (data)\n'+query
 return text,{'all_component_ids':[r['id'] for r in catalog['components']],'all_edges':catalog['relationships'],'catalog_sha256':hashlib.sha256(raw.encode()).hexdigest(),'scope':'public architecture inventory; private evidence is not bundled','automatic_other_app_injection':False}
