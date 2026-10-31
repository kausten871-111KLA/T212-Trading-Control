#!/usr/bin/env bash
# Operator-supervised read-only post-restart acceptance; no tokens or account rows printed.
set -euo pipefail
export LC_ALL=C
printf 'UTC_TIMESTAMP:%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
http_code="$(curl --max-time 8 -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:3000/health)"
printf 'WEBUI_HEALTH_HTTP:%s\n' "$http_code"
printf 'CONTAINER_STATE:%s\n' "$(docker inspect --format '{{.State.Status}}' open-webui)"
printf 'CONTAINER_HEALTH:%s\n' "$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}not_configured{{end}}' open-webui)"
python3 - <<'PY'
from pathlib import Path
p=Path('/home/katie/open-webui/.env')
if not p.is_file():
    print('ENV_ADMIN_KEY_PRESENT:False;UNIQUE:False')
else:
    lines=[x for x in p.read_text().splitlines() if x.startswith('OPENWEBUI_ADMIN_API_KEY=')]
    print(f'ENV_ADMIN_KEY_PRESENT:{len(lines)==1 and bool(lines[0].partition("=")[2].strip()) if lines else False};UNIQUE:{len(lines)==1}')
print('AUTHENTICATED_ENDPOINTS:NOT_TESTED_BY_THIS_SCRIPT')
PY
docker exec -i open-webui python - <<'PY'
import ast, hashlib, json, os, sqlite3
p='/app/backend/data/webui.db'
print('WEBUI_DB_PRESENT:',os.path.isfile(p))
if not os.path.isfile(p):
    raise SystemExit(0)
db=sqlite3.connect('file:'+p+'?mode=ro',uri=True,timeout=2)
try:
    print('WEBUI_DB_QUICK_CHECK:',db.execute('PRAGMA quick_check').fetchone()[0])
    tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for table in ('model','tool','function','automation','task'):
        if table not in tables:
            print('TABLE_'+table.upper()+':ABSENT')
            continue
        cols=[r[1] for r in db.execute('PRAGMA table_info("'+table+'")')]
        print('TABLE_'+table.upper()+'_ROWS:',db.execute('SELECT COUNT(*) FROM "'+table+'"').fetchone()[0])
        print('TABLE_'+table.upper()+'_COLUMN_NAMES:',','.join(cols))
        if table=='model' and 'id' in cols:
            row=db.execute('SELECT * FROM "model" WHERE id=?',('trading-operations--deepseek',)).fetchone()
            print('TARGET_MODEL_PRESENT:',row is not None)
            if row is not None:
                obj=dict(zip(cols,row))
                counts=[]
                for v in obj.values():
                    if not isinstance(v,str): continue
                    try: data=json.loads(v)
                    except (ValueError,TypeError): continue
                    if isinstance(data,dict):
                        for k in ('toolIds','tool_ids'):
                            if isinstance(data.get(k),list): counts.append(len(data[k]))
                print('TARGET_MODEL_TOOL_BINDINGS:',counts if counts else 'UNRESOLVED_SCHEMA')
        if table in ('tool','function') and 'id' in cols:
            for row in db.execute('SELECT * FROM "'+table+'" WHERE id LIKE ?',('%market_data_gateway%',)):
                obj=dict(zip(cols,row))
                source=obj.get('content')
                if not isinstance(source,str):
                    print('MARKET_DATA_SOURCE:UNRESOLVED_SCHEMA')
                    continue
                print('MARKET_DATA_SOURCE_SHA256:',hashlib.sha256(source.encode()).hexdigest())
                try:
                    tree=ast.parse(source)
                    funcs=[n.name for n in ast.walk(tree) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))]
                    print('MARKET_DATA_FUNCTION_DEFINITIONS:',len(funcs))
                    print('MARKET_DATA_TOP_MOVERS_PRESENT:','top_movers' in funcs)
                except SyntaxError:
                    print('MARKET_DATA_SOURCE_AST:SYNTAX_ERROR')
    print('AUTOMATION_ENABLED_COUNT:NOT_ASSERTED_WITHOUT_CONFIRMED_STORE_SCHEMA')
finally:
    db.close()
PY
