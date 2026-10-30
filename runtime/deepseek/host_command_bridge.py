"""Authenticated, fixed-command Contabo bridge for Open WebUI.

There is deliberately no shell/argv/path input from the model. The existing
/command route accepts only fixed operations. The optional /model-task route
uses a DIFFERENT dedicated token and only creates/reads/cancels persistent
non-broker research tasks. It fails closed until separately provisioned.
No model inference, broker orders, schedule edits or trade decisions here.
"""
import hmac
import ipaddress
import json
import os
from pathlib import Path
import sqlite3
import socketserver
import stat
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import urlopen

BIND = os.getenv("CONTABO_BRIDGE_BIND", "172.18.0.1")
PORT = int(os.getenv("CONTABO_BRIDGE_PORT", "8765"))
TOKEN = os.environ.get("CONTABO_BRIDGE_TOKEN", "")
DATA_ENV = Path("/home/katie/.config/deepseek-runtime/data-api.env")
REPO = Path("/home/katie/t212-runtime-service")
STATE = Path("/home/katie/.local/state/deepseek-runtime/trading_state.db")
ACCEPTANCE = REPO / "deploy/deepseek/webui_tool_binding/scheduled_open_acceptance.py"
NETWORK = ipaddress.ip_network("172.18.0.0/16")
COMMANDS = frozenset({"runtime_status","webui_health","open_acceptance",
                       "repo_revision","data_key_status","alpha_vantage_daily",
                       "twelve_data_quote","twelve_data_series",
                       "twelve_data_search","twelve_data_usage"})

def _run(args, timeout=8):
    p = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                       check=False, cwd=str(REPO))
    return {"ok": p.returncode == 0, "exit_code": p.returncode,
            "output": p.stdout[:7000], "stderr_type": "nonempty" if p.stderr else "empty"}

def _verified_demo_schedule_ready():
    # No manual switch: true only after a recent, authenticated saved WebUI
    # automation completes with an actual T212 function output, persisted by
    # the phase worker and linked to an idempotent controller ACK.
    if not STATE.is_file():
        return False
    try:
        with sqlite3.connect("file:"+str(STATE)+"?mode=ro",uri=True,timeout=3) as db:
            row=db.execute(
                "SELECT 1 FROM webui_run_receipt r "
                "JOIN controller_instruction i ON i.id=r.instruction_id "
                "WHERE r.broker_tool_results>0 AND r.recorded_at>=? "
                "AND i.status='acknowledged' LIMIT 1",
                (int(__import__('time').time())-86400,)
            ).fetchone()
            return row is not None
    except sqlite3.Error:
        return False


def execute(command, symbol="IBM", exchange="", mic_code="", interval="1day",
            outputsize=30):
    if not isinstance(command, str) or command not in COMMANDS:
        return {"ok": False, "error": "unknown_command", "allowed_commands": sorted(COMMANDS)}
    if command.startswith("twelve_data_"):
        from .twelve_data_adapter import query
        operation = {
            "twelve_data_quote": "quote",
            "twelve_data_series": "time_series",
            "twelve_data_search": "symbol_search",
            "twelve_data_usage": "api_usage",
        }[command]
        return query(operation,symbol=symbol,exchange=exchange,
                     mic_code=mic_code,interval=interval,outputsize=outputsize)
    if command == "alpha_vantage_daily":
        from .alpha_vantage_data import daily_bars
        return daily_bars(symbol)
    if command == "repo_revision":
        p=_run(["git","rev-parse","HEAD"])
        return {"ok":p["ok"],"revision":p["output"].strip()[:40]}
    if command == "webui_health":
        try:
            with urlopen("http://127.0.0.1:3000/health", timeout=4) as response:
                return {"ok":response.status==200,"webui_http_status":response.status}
        except Exception as error:
            return {"ok":False,"error_type":type(error).__name__}
    if command == "data_key_status":
        present = {}
        if DATA_ENV.is_file():
            for line in DATA_ENV.read_text().splitlines():
                if "=" not in line or line.lstrip().startswith("#"):
                    continue
                k,v=line.split("=",1)
                if k.strip() in ("TWELVEDATA_API_KEY","ALPHAVANTAGE_API_KEY"):
                    present[k.strip()] = bool(v.strip().strip('"').strip("'"))
        return {"ok":True,"environment":"DEMO",
                "twelve_data_configured":present.get("TWELVEDATA_API_KEY",False),
                "alpha_vantage_configured":present.get("ALPHAVANTAGE_API_KEY",False)}
    if command == "runtime_status":
        status=_run(["systemctl","--user","is-active","deepseek-phase.service"])
        active = status["output"].strip() == "active"
        counts={}
        if STATE.is_file():
            with sqlite3.connect("file:"+str(STATE)+"?mode=ro",uri=True,timeout=4) as c:
                counts=dict(c.execute("SELECT status,count(*) FROM event_queue GROUP BY status").fetchall())
        return {"ok":active,"service":"deepseek-phase.service",
                "service_active":active,"queued_phase_events":counts,
                "trading_ready":_verified_demo_schedule_ready(), "live_trading_enabled_by_bridge":False}
    if command == "open_acceptance":
        cmd=["docker","run","--rm","--network","none","--read-only",
             "--security-opt","no-new-privileges",
             "-v","open-webui_open-webui-data:/app/backend/data:ro",
             "-v",str(ACCEPTANCE)+":/audit.py:ro",
             "local/open-webui-toolbinding-stage:20261020",
             "python","/audit.py","--phase","US OPEN"]
        result=_run(cmd,timeout=40)
        if not result["ok"]:
            return {"ok":False,"error":"acceptance_command_failed","exit_code":result["exit_code"]}
        try: return {"ok":True,"acceptance":json.loads(result["output"])}
        except ValueError:return {"ok":False,"error":"invalid_acceptance_output"}
    return {"ok":False,"error":"unsupported"}

def _reject_nonfinite_constant(value):
    """Reject Python JSON extensions (NaN/Infinity) before task dispatch."""
    raise ValueError("Non-finite JSON constant")


def _unique_json_object(pairs):
    """Reject ambiguous duplicate keys at every JSON nesting level."""
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError("Duplicate JSON field")
        obj[key] = value
    return obj


class Handler(BaseHTTPRequestHandler):
    server_version = "ContaboBridge/1.0"
    def log_message(self, fmt, *args):
        # Deliberately don't log headers, credentials or broker payloads.
        pass
    def respond(self, code, obj):
        blob=json.dumps(obj,separators=(",",":"),ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Cache-Control","no-store")
        self.send_header("Content-Length",str(len(blob)))
        self.end_headers()
        self.wfile.write(blob)
    def do_POST(self):
        model_task = self.path == "/model-task"
        if self.path not in ("/command", "/model-task"):
            return self.respond(404,{"ok":False,"error":"not_found"})
        try:
            addr=ipaddress.ip_address(self.client_address[0])
            allowed=addr.is_loopback or addr in NETWORK
        except (ValueError, IndexError, TypeError):allowed=False
        if getattr(self.server, "address_family", None) == socketserver.socket.AF_UNIX:
            allowed = True
        if not allowed:
            return self.respond(403,{"ok":False,"error":"source_forbidden"})
        if model_task:
            # Dedicated secret: the general bridge token must not authorize
            # model-created persistent work. Fail closed until provisioned.
            expected=os.environ.get("CONTABO_MODEL_TASK_TOKEN","")
            supplied_headers=self.headers.get_all("X-Model-Task-Token",[])
            # Ambiguous duplicate credentials must never select a first/last value.
            if len(supplied_headers)!=1:
                return self.respond(401,{"ok":False,"error":"not_authorized"})
            supplied=supplied_headers[0]
            if len(expected)<48 or not expected.isascii():
                return self.respond(503,{"ok":False,"error":"model_task_not_configured"})
            if not supplied or not supplied.isascii() or not hmac.compare_digest(supplied,expected):
                return self.respond(401,{"ok":False,"error":"not_authorized"})
        else:
            supplied=self.headers.get("X-Bridge-Token","")
            if not supplied or not hmac.compare_digest(supplied,TOKEN):
                return self.respond(401,{"ok":False,"error":"not_authorized"})
        # Untrusted HTTP framing: reject malformed/oversized numeric headers
        # before conversion or body reads, without crashing the handler thread.
        lengths=self.headers.get_all("Content-Length",[])
        # Reject duplicate lengths and Transfer-Encoding: a proxy or client
        # must not be able to disagree with this HTTP/1.0 body parser.
        if len(lengths)!=1 or self.headers.get_all("Transfer-Encoding",[]):
            return self.respond(400,{"ok":False,"error":"invalid_length"})
        raw_length=lengths[0]
        if (raw_length is None or len(raw_length)>8 or
                not raw_length.isascii() or not raw_length.isdecimal()):
            return self.respond(400,{"ok":False,"error":"invalid_length"})
        length=int(raw_length)
        if length < 2 or length > (16384 if model_task else 1024):
            return self.respond(413,{"ok":False,"error":"invalid_length"})
        try:
            payload=json.loads(self.rfile.read(length), object_pairs_hook=_unique_json_object,
                               parse_constant=_reject_nonfinite_constant)
            if not isinstance(payload,dict):raise ValueError
        except (ValueError,UnicodeDecodeError):
            return self.respond(400,{"ok":False,"error":"invalid_json"})
        try:
            if model_task:
                from .model_task_host_commands import dispatch_model_task
                return self.respond(200,dispatch_model_task(payload,verified=True))
            return self.respond(200,execute(
                payload.get("command"), payload.get("symbol", "IBM"),
                exchange=payload.get("exchange", ""),
                mic_code=payload.get("mic_code", ""),
                interval=payload.get("interval", "1day"),
                outputsize=payload.get("outputsize", 30),
            ))
        except (PermissionError, ValueError) as error:
            return self.respond(403 if isinstance(error,PermissionError) else 400,
                                {"ok":False,"error_type":type(error).__name__})
        except Exception as error:
            return self.respond(500,{"ok":False,"error_type":type(error).__name__})

class UnixHTTPServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


def main():
    if len(TOKEN)<48:
        raise RuntimeError("Dedicated bridge token is missing or too short")
    socket_path=Path("/home/katie/.local/state/deepseek-runtime/bridge/command.sock")
    socket_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(socket_path.parent, 0o700)
    if socket_path.exists():
        if not stat.S_ISSOCK(socket_path.stat().st_mode):
            raise RuntimeError("Refusing to overwrite a non-socket bridge path")
        socket_path.unlink()
    try:
        with UnixHTTPServer(str(socket_path), Handler) as httpd:
            os.chmod(socket_path, 0o600)
            print(json.dumps({"component":"contabo_command_bridge","transport":"unix",
                  "allowed_commands":sorted(COMMANDS),"trading_ready":False}),flush=True)
            httpd.serve_forever(poll_interval=0.5)
    finally:
        if socket_path.exists() and stat.S_ISSOCK(socket_path.stat().st_mode):
            socket_path.unlink()


if __name__=="__main__":
    main()
