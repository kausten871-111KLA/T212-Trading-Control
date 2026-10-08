"""Local deterministic OpenAI-compatible provider for disposable WebUI acceptance."""
import argparse, json, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

class State:
    def __init__(self, capture):
        self.capture = Path(capture)
        self.requests = json.loads(self.capture.read_text()) if self.capture.exists() else []
        self.lock = threading.Lock()
        self.fail = False
        self.delay = 0

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def json_reply(self, value, status=200):
        body = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        if self.path == "/v1/models":
            self.json_reply({"object":"list","data":[{"id":"it-mock","object":"model","owned_by":"test"}]})
        elif self.path == "/requests":
            with self.server.state.lock: self.json_reply(self.server.state.requests)
        else: self.json_reply({"error":"not found"},404)
    def do_POST(self):
        data = json.loads(self.rfile.read(int(self.headers.get("Content-Length","0"))))
        if self.path == "/control":
            self.server.state.fail = bool(data.get("fail"))
            self.server.state.delay = float(data.get("delay",0))
            self.json_reply({"fail":self.server.state.fail}); return
        if self.path != "/v1/chat/completions":
            self.json_reply({"error":"not found"},404); return
        state = self.server.state
        with state.lock:
            # Synthetic test messages only; never record headers, keys or arbitrary payload fields.
            record = {"model":data.get("model"),"messages":data.get("messages",[]),"stream":data.get("stream")}
            state.requests.append(record)
            number = len(state.requests)
            state.capture.write_text(json.dumps(state.requests,indent=2))
        if state.delay: time.sleep(state.delay)
        if state.fail:
            self.json_reply({"error":{"message":"deliberate IT provider failure","type":"test_error"}},500); return
        text = "IT_RUN_" + str(number)
        common = {"id":"it-"+str(number),"object":"chat.completion.chunk","created":int(time.time()),"model":"it-mock"}
        if not data.get("stream"):
            self.json_reply({**common,"object":"chat.completion","choices":[{"index":0,"message":{"role":"assistant","content":text},"finish_reason":"stop"}]}); return
        self.send_response(200)
        self.send_header("Content-Type","text/event-stream")
        self.send_header("Cache-Control","no-cache")
        self.send_header("Connection","close")
        self.end_headers()
        for delta,finish in [({"role":"assistant"},None),({"content":text},None),({},"stop")]:
            chunk={**common,"choices":[{"index":0,"delta":delta,"finish_reason":finish}]}
            self.wfile.write(("data: "+json.dumps(chunk)+"\n\n").encode());self.wfile.flush()
        self.wfile.write(b"data: [DONE]\n\n");self.wfile.flush()
        self.close_connection=True

def serve(port,capture):
    server=ThreadingHTTPServer(("127.0.0.1",port),Handler)
    server.state=State(capture)
    server.serve_forever()

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--port",type=int,default=38181)
    parser.add_argument("--capture",required=True)
    args=parser.parse_args()
    serve(args.port,args.capture)
