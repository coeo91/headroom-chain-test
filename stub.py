#!/usr/bin/env python3
"""假 provider：记录穿过代理链之后请求还剩什么。

用法：
    STUB_PORT=18080 STUB_LOG=results/stub-A.jsonl python3 stub.py

环境变量：
    STUB_PORT        监听端口，默认 18080
    STUB_LOG         jsonl 落盘路径，默认 results/stub.jsonl
    STUB_FORCE_401   非空即所有 POST 返回 401，用来定位错误被哪一层吃掉
    STUB_ECHO_BYTES  非空则在响应文本里附带收到的字节数

协议端点是 OpenAI Chat / OpenAI Responses / Anthropic Messages 三套，
响应都是确定性打回，重复可复现。
"""

import hashlib
import json
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("STUB_PORT", "18080"))
DEFAULT_LOG_PATH = os.environ.get("STUB_LOG", "results/stub.jsonl")
FORCE_401 = os.environ.get("STUB_FORCE_401", "").strip().lower() in ("1", "true", "yes", "on")
ECHO_BYTES = os.environ.get("STUB_ECHO_BYTES", "").strip().lower() in ("1", "true", "yes", "on")

SENSITIVE_HEADERS = ("authorization", "api-key", "apikey", "token", "secret", "cookie")

NEEDLE_RE = re.compile(r"NEEDLE-[A-Za-z0-9_-]+")
FENCE_RE = re.compile(r"```[A-Za-z0-9_+.-]*\n(.*?)\n```", re.S)
LONG_STRING_MIN = 2000
MAX_LONG_STRINGS = 30
MAX_FENCED = 10
MAX_NEEDLE_LINES = 20
LINE_CLIP = 600

_lock = threading.Lock()
_seq = [0]
_lane = {"name": os.environ.get("STUB_LANE", ""), "log": DEFAULT_LOG_PATH}


def sha(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def canon(obj):
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def walk_strings(obj, out):
    if isinstance(obj, str):
        out.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            walk_strings(v, out)
    elif isinstance(obj, list):
        for v in obj:
            walk_strings(v, out)


def count_cache_control(obj):
    n = 0
    if isinstance(obj, dict):
        if "cache_control" in obj:
            n += 1
        for v in obj.values():
            n += count_cache_control(v)
    elif isinstance(obj, list):
        for v in obj:
            n += count_cache_control(v)
    return n


def split_request(body, path):
    """把三种协议归一成 (shape, system, messages, tools)。"""
    if path.endswith("/messages"):
        return (
            "anthropic",
            body.get("system"),
            body.get("messages") or [],
            body.get("tools") or [],
        )
    if path.endswith("/responses"):
        msgs = body.get("input") or []
        system = body.get("instructions")
        if not system:
            for m in msgs:
                if isinstance(m, dict) and m.get("role") in ("system", "developer"):
                    system = m.get("content")
                    break
        return "openai_responses", system, msgs, body.get("tools") or []

    msgs = list(body.get("messages") or [])
    system = None
    if msgs and isinstance(msgs[0], dict) and msgs[0].get("role") == "system":
        system = msgs[0].get("content")
        msgs = msgs[1:]
    return "openai_chat", system, msgs, body.get("tools") or []


def tool_names(tools):
    out = []
    for t in tools:
        if not isinstance(t, dict):
            continue
        fn = t.get("function")
        out.append(fn.get("name") if isinstance(fn, dict) else t.get("name"))
    return out


def null_content_tool_calls(msgs):
    """上游偶发不吃 content:null + tool_calls 的组合，这里数一下还在不在。"""
    n = 0
    for m in msgs:
        if isinstance(m, dict) and m.get("role") == "assistant" and m.get("tool_calls"):
            if m.get("content") in (None, ""):
                n += 1
    return n


def extract_cid(body, headers):
    """关联 id：客户端放进 metadata / user / model 后缀，网关一般原样透传。"""
    meta = body.get("metadata")
    if isinstance(meta, dict):
        for k in ("cid", "user_id"):
            if meta.get(k):
                return str(meta[k])
    if body.get("user"):
        return str(body["user"])
    model = body.get("model")
    if isinstance(model, str) and "|cid=" in model:
        return model.split("|cid=", 1)[1]
    return headers.get("x-cid")


def build_record(raw, path, headers):
    text = raw.decode("utf-8", "replace")
    try:
        body = json.loads(text)
        if not isinstance(body, dict):
            body = {}
    except Exception:
        body = {}

    shape, system, msgs, tools = split_request(body, path)

    strings = []
    walk_strings(body, strings)

    needle_windows = []
    for m in NEEDLE_RE.finditer(text):
        w = text[max(0, m.start() - 400):min(len(text), m.end() + 400)]
        if w not in needle_windows:
            needle_windows.append(w)
        if len(needle_windows) >= 10:
            break

    long_strings = [
        {"len": len(s), "sha256": sha(s)}
        for s in strings
        if len(s) >= LONG_STRING_MIN
    ][:MAX_LONG_STRINGS]

    fenced = []
    seen_fence = set()
    for s in strings:
        for m in FENCE_RE.finditer(s):
            inner = m.group(1)
            h = sha(inner)
            if h in seen_fence:
                continue
            seen_fence.add(h)
            fenced.append({"len": len(inner), "sha256": h})
            if len(fenced) >= MAX_FENCED:
                break
        if len(fenced) >= MAX_FENCED:
            break

    return {
        "seq": None,
        "t_wall": round(time.time(), 3),
        "t_iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "method": "POST",
        "host": headers.get("Host") or ("127.0.0.1:%d" % PORT),
        "url": "http://%s%s" % (headers.get("Host") or ("127.0.0.1:%d" % PORT), path),
        "path": path,
        "proto_shape": shape,
        "cid": extract_cid(body, headers),
        "body_bytes": len(raw),
        "request_body_size": len(raw),
        "request_body_sha256": hashlib.sha256(raw).hexdigest(),
        "request_headers": sanitize_headers(dict(headers)),
        "request_json": body,
        "model": body.get("model"),
        "system_sha256": sha(canon(system)) if system is not None else None,
        "msg_count": len(msgs),
        "msg_hashes": [sha(canon(m)) for m in msgs],
        "msgs_prefix_sha256": sha(canon(msgs[:-1])) if msgs else None,
        "msgs_full_sha256": sha(canon(msgs)),
        "tool_count": len(tools),
        "tool_names": tool_names(tools),
        "cache_control_blocks": count_cache_control(body),
        "needles": sorted(set(NEEDLE_RE.findall(text))),
        "needle_windows": needle_windows,
        "tool_call_null_content": null_content_tool_calls(msgs),
        "long_strings": long_strings,
        "fenced_blocks": fenced,
        "auth": {
            "authorization": (headers.get("authorization") or "")[:16],
            "x_api_key": (headers.get("x-api-key") or "")[:16],
        },
        "x_arm": headers.get("x-arm"),
        "forced_401": FORCE_401,
    }


def log_record(rec):
    with _lock:
        _seq[0] += 1
        rec["seq"] = _seq[0]
        rec["sequence"] = rec["seq"]
        rec["lane"] = _lane["name"]
        path = _lane["log"]
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def sanitize_headers(headers):
    out = {}
    for k, v in headers.items():
        if k.lower() in SENSITIVE_HEADERS:
            out[k] = "<redacted>"
        else:
            out[k] = v
    return out


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "headroom-stub/1.0"

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, payload, extra_headers=None):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/health", "/livez", "/readyz"):
            return self._send(200, {"ok": True, "stub": True, "seq": _seq[0], "lane": _lane["name"], "log": _lane["log"]})
        if path.startswith("/_admin/lane"):
            name = path[len("/_admin/lane"):].strip("/")
            if name:
                with _lock:
                    _lane["name"] = name
                    _lane["log"] = os.path.join("results", "stub-%s.jsonl" % name)
                    _seq[0] = 0
            return self._send(200, {"ok": True, "lane": _lane["name"], "log": _lane["log"]})
        if path.startswith("/v1/models"):
            return self._send(
                200,
                {
                    "object": "list",
                    "data": [{"id": "stub-model", "object": "model", "owned_by": "stub"}],
                    "has_more": False,
                },
            )
        return self._send(404, {"error": {"type": "not_found", "message": path}})

    def do_POST(self):
        path = self.path.split("?")[0]
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        raw = self.rfile.read(n) if n else b""

        rec = build_record(raw, path, self.headers)
        rec["response_status"] = 401 if FORCE_401 else 200
        rec["response_headers"] = {"content-type": "application/json"}
        log_record(rec)

        if FORCE_401:
            return self._send(
                401,
                {
                    "error": {
                        "type": "authentication_error",
                        "message": "stub forced 401 (STUB_FORCE_401=1)",
                        "code": "stub_forced_401",
                    }
                },
            )

        checksum = hashlib.sha256(raw).hexdigest()[:8]
        text = "checksum=" + checksum
        if ECHO_BYTES:
            text += " bytes=%d" % len(raw)

        if path.endswith("/messages"):
            return self._send(200, self._anthropic(rec, text))
        if path.endswith("/responses"):
            return self._send(200, self._responses(rec, text))
        return self._send(200, self._chat(rec, text))

    @staticmethod
    def _anthropic(rec, text):
        return {
            "id": "msg_stub_0001",
            "type": "message",
            "role": "assistant",
            "model": rec.get("model") or "stub-model",
            "content": [{"type": "text", "text": text}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }

    @staticmethod
    def _chat(rec, text):
        return {
            "id": "chatcmpl-stub",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": rec.get("model") or "stub-model",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }

    @staticmethod
    def _responses(rec, text):
        return {
            "id": "resp_stub",
            "object": "response",
            "created_at": int(time.time()),
            "model": rec.get("model") or "stub-model",
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "id": "msg_stub",
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": text, "annotations": []}],
                }
            ],
            "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
        }


def main():
    d = os.path.dirname(_lane["log"])
    if d:
        os.makedirs(d, exist_ok=True)
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print("stub listening on 0.0.0.0:%d -> %s" % (PORT, os.path.abspath(_lane["log"])), flush=True)
    print("FORCE_401=%s ECHO_BYTES=%s" % (FORCE_401, ECHO_BYTES), flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
