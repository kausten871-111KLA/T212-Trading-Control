from pathlib import Path
import ast,urllib.request,difflib,json,hashlib
root=Path(__file__).resolve().parents[1];dest=root/'patches/openwebui-v0.11.4/open_webui'
def fetch(tag,rel):
 with urllib.request.urlopen('https://raw.githubusercontent.com/open-webui/open-webui/'+tag+'/backend/open_webui/'+rel,timeout=20) as response:return response.read().decode()
def find(s,name):return next(n for n in ast.parse(s).body if isinstance(n,(ast.ClassDef,ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==name)
def segment(s,name):return ast.get_source_segment(s,find(s,name))
def replace(s,name,text):
 n=find(s,name);lines=s.splitlines(keepends=True)
 return ''.join(lines[:n.lineno-1])+text+'\n'+''.join(lines[n.end_lineno:])
rels=['models/automations.py','routers/automations.py','utils/automations.py','utils/middleware.py']
up={rel:fetch('v0.11.4',rel) for rel in rels}
manifest={'tag':'v0.11.4','status':'STAGED_SOURCE_ONLY','files':{}}
ported={}
for rel in rels:manifest['files'][rel]={'upstream_sha256':hashlib.sha256(up[rel].encode()).hexdigest()}
rel='models/automations.py';c=(root/'patches/openwebui-v0.11.3/open_webui'/rel).read_text()
s=replace(up[rel],'AutomationTarget',segment(c,'AutomationTarget'));ported[rel]=s
rel='routers/automations.py';c=(root/'patches/openwebui-v0.11.3/open_webui'/rel).read_text();s=up[rel]
s=s.replace('from open_webui.models.channels import Channels','from open_webui.models.channels import Channels\nfrom open_webui.models.chats import Chats',1)
s=s.replace('async def check_automation_channel_access',segment(c,'check_automation_chat_access')+'\n\n\nasync def check_automation_channel_access',1)
anchor='    await check_automation_folder_access(form_data.folder_id, user, db)\n';assert s.count(anchor)==2
s=s.replace(anchor,anchor+'    await check_automation_chat_access(form_data, user, db)\n');ported[rel]=s
rel='utils/automations.py';old=fetch('v0.11.3',rel);c=(root/'patches/openwebui-v0.11.3/open_webui'/rel).read_text();s=up[rel]
defaults="""        # Resolve model defaults (frontend does this, backend doesn't)
        tool_ids, features, filter_ids, terminal_id = await _resolve_model_defaults(app, model_id)

"""
conditionals="""        if tool_ids:
            form_data['tool_ids'] = tool_ids
        if features:
            form_data['features'] = features
        if filter_ids:
            form_data['filter_ids'] = filter_ids
        if terminal_id:
            form_data['terminal_id'] = terminal_id

"""
def adopt_v4_defaults(text):
 assert text.count(defaults)==1;assert text.count(conditionals)==1
 text=text.replace(defaults,'').replace(conditionals,'')
 anchor="""        form_data = {
            'model': model_id,"""
 assert text.count(anchor)==1
 return text.replace(anchor,"""        form_data = {
            **await _resolve_model_defaults(app, model_id),
            'model': model_id,""",1)
old_fn=adopt_v4_defaults(segment(old,'execute_automation'))
assert ast.dump(ast.parse(old_fn),include_attributes=False)==ast.dump(ast.parse(segment(s,'execute_automation')),include_attributes=False),'Unreviewed upstream executor changes remain'
custom=c[c.index('def _bounded_chat_context'):c.index('\n\n####################\n# Internals',c.index('def _bounded_chat_context'))]
custom=adopt_v4_defaults(custom)
s=replace(s,'execute_automation',custom)
s=s.replace('import time\n','import time\nimport weakref\nimport hashlib\nfrom contextlib import asynccontextmanager\nfrom pathlib import Path\n',1);ported[rel]=s
rel='utils/middleware.py';old=fetch('v0.11.3',rel);c=(root/'patches/openwebui-v0.11.3/open_webui'/rel).read_text();s=up[rel]
a=old.splitlines(keepends=True);b=c.splitlines(keepends=True)
changes=[]
for tag,a1,a2,b1,b2 in difflib.SequenceMatcher(a=a,b=b,autojunk=False).get_opcodes():
 if tag=='equal':continue
 before=''.join(a[max(0,a1-3):min(len(a),a2+3)])
 after=''.join(a[max(0,a1-3):a1])+''.join(b[b1:b2])+''.join(a[a2:min(len(a),a2+3)])
 changes.append((before,after))
for before,after in changes:
 assert s.count(before)==1,'Middleware port anchor changed or ambiguous'
 s=s.replace(before,after,1)
ported[rel]=s
for rel in rels:
 ported[rel]='\n'.join(line.rstrip() for line in ported[rel].splitlines())+'\n'
 p=dest/rel;compile(ported[rel],str(p),'exec')
 manifest['files'][rel]['candidate_sha256']=hashlib.sha256(ported[rel].encode()).hexdigest()
for rel,text in ported.items():
 p=dest/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)
manifest['upstream_v4_model_defaults_preserved']=True
manifest['middleware_custom_hunks']=len(changes)
(root/'docs/evidence-deltas/2026-10-08-v0114-forward-port.json').write_text(json.dumps(manifest,indent=2))
print('Four-file selective forward-port compiled; asynchronous recurrence and v4 defaults dictionary retained')
print('Middleware custom hunks',len(changes))
