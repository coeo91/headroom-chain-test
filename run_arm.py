#!/usr/bin/env python3
"""按臂发请求，逐条记录。

    python3 run_arm.py --arm A --url http://127.0.0.1:8787 --repeat 3

    --arm      臂名，写进 results/results-<arm>.jsonl
    --url      目标 base url（0D 指向 stub，A 指向 headroom，B 指向 magpie）
    --repeat   每个用例重复次数，默认 3；P5 多轮题每次重复跑完整 12 轮
    --key      转发给上游的 key，默认 sk-stub-test
    --manifest payload 清单，默认 payloads/manifest.json
    --out      结果文件，默认 results/results-<arm>.jsonl
"""

import argparse
import json
import os
import statistics
import time
import urllib.error
import urllib.request

DEFAULT_KEY = "sk-stub-test"
TIMEOUT = 60

# urllib 在 Windows 上会读注册表里的系统代理，测试桩会被绕到代理上导致卡死，这里显式关掉。
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def canon(obj):
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def stamp(body, proto, cid):
    """给每个请求打一个唯一 cid。

    两个作用：一是让桩能按 cid 精确配对（headroom 会命中响应缓存而跳过上游调用，
    下标配对必然错位）；二是让每次请求 body 唯一，绕开缓存，保证每次都真的走到上游。
    """
    out = dict(body)
    meta = dict(out.get("metadata") or {})
    if proto == "anthropic":
        meta["user_id"] = cid
    else:
        meta["cid"] = cid
        out["user"] = cid
    out["metadata"] = meta
    return out


def post(url, body, proto, key, arm, cid):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("X-Arm", arm)
    req.add_header("X-Cid", cid)
    if proto == "anthropic":
        req.add_header("x-api-key", key)
        req.add_header("anthropic-version", "2023-06-01")
    else:
        req.add_header("Authorization", "Bearer " + key)

    t0 = time.time()
    status = 0
    raw = b""
    err = None
    try:
        with OPENER.open(req, timeout=TIMEOUT) as r:
            raw = r.read()
            status = r.status
    except urllib.error.HTTPError as e:
        raw = e.read()
        status = e.code
        err = "http_%d" % e.code
    except Exception as e:  # 连不上、超时等
        err = type(e).__name__ + ": " + str(e)
    t1 = time.time()

    return {
        "status": status,
        "err": err,
        "ms": round((t1 - t0) * 1000, 1),
        "sent_bytes": len(data),
        "resp_bytes": len(raw),
        "raw": raw,
    }


def reply_text(status, raw, proto):
    if status >= 400 or not raw:
        return ""
    try:
        j = json.loads(raw)
    except Exception:
        return ""
    if proto == "anthropic":
        parts = []
        for b in j.get("content") or []:
            if isinstance(b, dict) and b.get("type") == "text":
                parts.append(b.get("text", ""))
        return "".join(parts)
    if proto == "openai_responses":
        parts = []
        for item in j.get("output") or []:
            for c in item.get("content") or []:
                if isinstance(c, dict) and c.get("type") == "output_text":
                    parts.append(c.get("text", ""))
        return "".join(parts)
    try:
        return j["choices"][0]["message"].get("content") or ""
    except Exception:
        return ""


def build_multiturn(parts):
    """P5 的种子消息：system + 首问 + 一次工具调用 + 工具结果。

    大块 JSON 必须在 tool 消息里才会进压缩器，放用户消息会被当 prompt 保护。
    """
    seed = parts["seed_assistant"]
    call_id = (seed.get("tool_calls") or [{}])[0].get("id") or "call_p5"
    msgs = []
    if parts.get("system"):
        msgs.append({"role": "system", "content": parts["system"]})
    msgs.append({"role": "user", "content": parts["seed_user"]})
    msgs.append(seed)
    msgs.append({"role": "tool", "tool_call_id": call_id, "content": parts["tool_result"]})
    return msgs


def switch_lane(admin_url, arm):
    """告诉桩把这一臂的记录写进 results/stub-<arm>.jsonl。"""
    if not admin_url:
        return None
    url = admin_url.rstrip("/") + "/_admin/lane/" + arm
    try:
        with OPENER.open(url, timeout=10) as r:
            lane = json.loads(r.read())
    except Exception as e:
        print("警告：切换桩通道失败 %s (%s)" % (url, e))
        return None
    try:
        if lane.get("log") and os.path.exists(lane["log"]):
            os.remove(lane["log"])
    except Exception as e:
        print("警告：清空旧日志失败 %s (%s)" % (lane.get("log"), e))
    return lane


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", required=True)
    ap.add_argument("--url", required=True)
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--key", default=DEFAULT_KEY)
    ap.add_argument("--manifest", default="payloads/manifest.json")
    ap.add_argument("--out", default=None)
    ap.add_argument("--stub-admin", default="http://127.0.0.1:18080")
    ap.add_argument("--only", default=None, help="只跑指定用例，如 P1,P5")
    args = ap.parse_args()

    out_path = args.out or os.path.join("results", "results-%s.jsonl" % args.arm)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

    lane = switch_lane(args.stub_admin, args.arm)
    if lane:
        print("桩通道 -> %s（%s）" % (lane.get("lane"), lane.get("log")))

    with open(args.manifest, encoding="utf-8") as f:
        manifest = json.load(f)
    cases = manifest["cases"]
    if args.only:
        keep = set(args.only.split(","))
        cases = [c for c in cases if c["case"] in keep]

    rows = []
    failures = []
    nonce = "%d" % (int(time.time() * 1000) % 100000000)

    for case in cases:
        body = None
        if case["multi_turn"]:
            with open(os.path.join("payloads", case["file"]), encoding="utf-8") as f:
                parts = json.load(f)
        else:
            with open(os.path.join("payloads", case["file"]), encoding="utf-8") as f:
                body = json.load(f)

        for rep in range(1, args.repeat + 1):
            if case["multi_turn"]:
                msgs = build_multiturn(parts)
                for turn, user_text in enumerate(parts["turns"], 1):
                    msgs = msgs + [{"role": "user", "content": user_text}]
                    cid = "%s-r%d-t%d-%s" % (case["case"], rep, turn, nonce)
                    req = {"model": "stub-model", "max_tokens": 512, "messages": msgs}
                    req = stamp(req, case["proto"], cid)
                    r = post(args.url + case["path"], req, case["proto"], args.key, args.arm, cid)
                    rows.append(
                        {
                            "arm": args.arm,
                            "case": case["case"],
                            "rep": rep,
                            "turn": turn,
                            "cid": cid,
                            "status": r["status"],
                            "err": r["err"],
                            "ms": r["ms"],
                            "sent_bytes": r["sent_bytes"],
                            "resp_bytes": r["resp_bytes"],
                            "client_prefix_sha": None,
                        }
                    )
                    if r["err"] or r["status"] >= 400:
                        failures.append((case["case"], rep, turn, r["err"] or r["status"]))
                        break
                    reply = reply_text(r["status"], r["raw"], case["proto"])
                    msgs = msgs + [{"role": "assistant", "content": reply}]
            else:
                cid = "%s-r%d-t1-%s" % (case["case"], rep, nonce)
                req = stamp(body, case["proto"], cid)
                r = post(args.url + case["path"], req, case["proto"], args.key, args.arm, cid)
                rows.append(
                    {
                        "arm": args.arm,
                        "case": case["case"],
                        "rep": rep,
                        "turn": 1,
                        "cid": cid,
                        "status": r["status"],
                        "err": r["err"],
                        "ms": r["ms"],
                        "sent_bytes": r["sent_bytes"],
                        "resp_bytes": r["resp_bytes"],
                        "client_prefix_sha": None,
                    }
                )
                if r["err"] or r["status"] >= 400:
                    failures.append((case["case"], rep, 1, r["err"] or r["status"]))

    with open(out_path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    by_case = {}
    for row in rows:
        by_case.setdefault(row["case"], []).append(row)
    print("臂 %s -> %s" % (args.arm, args.url))
    for c in manifest["cases"]:
        rs = by_case.get(c["case"])
        if not rs:
            continue
        med = statistics.median([r["ms"] for r in rs])
        st = sorted(set(r["status"] for r in rs))
        print(
            "  %-4s n=%-3d 中位延迟 %7.1f ms  状态 %s  发出 %d B"
            % (c["case"], len(rs), med, ",".join(str(x) for x in st), rs[0]["sent_bytes"])
        )
    if failures:
        print("\n有 %d 次请求失败，前 10 条：" % len(failures))
        for x in failures[:10]:
            print("  ", x)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
