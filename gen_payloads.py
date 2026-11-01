#!/usr/bin/env python3
"""生成全部测试 payload 与 manifest.json。

    python3 gen_payloads.py

产物：
    payloads/*.json      完整请求体（多轮题只存零件，由 run_arm.py 组装）
    payloads/manifest.json  每组题的期望值，analyze.py 用它判定

设计要点：headroom 的 ContentRouter 默认不压缩用户消息（最新一条 user 消息被当作
"prompt turn"保护），真正走压缩器的是工具观察结果（OpenAI 的 role=tool /
Anthropic 的 tool_result block）。所以所有大块内容都放进工具输出里，另外留一组
纯用户消息作为对照。
"""

import hashlib
import json
import os

OUT_DIR = "payloads"
NEEDLE = "NEEDLE-7f3a91"
MODEL = "stub-model"


def sha(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def dump(name, obj):
    path = os.path.join(OUT_DIR, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    return path


def tool_call_msg(call_id, name, args):
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)},
            }
        ],
    }


def chat_with_obs(user_text, tool_name, tool_args, obs_text, call_id="call_obs"):
    """OpenAI Chat 形状：用户提问 -> 模型调工具 -> 工具观察结果。"""
    return {
        "model": MODEL,
        "max_tokens": 512,
        "messages": [
            {"role": "user", "content": user_text},
            tool_call_msg(call_id, tool_name, tool_args),
            {"role": "tool", "tool_call_id": call_id, "content": obs_text},
        ],
    }


# ---------------------------------------------------------------- 素材

def records(n=240, note_value=None, id_base=4000):
    recs = []
    statuses = ["open", "closed", "pending", "void"]
    for i in range(n):
        recs.append(
            {
                "id": id_base + i,
                "sku": "SKU-%04d" % i,
                "amount": round(10 + (i * 37) % 900 + (i % 7) * 0.25, 2),
                "status": statuses[i % 4],
                "note": "batch %d" % (i // 20),
            }
        )
    if note_value is not None:
        recs[137]["note"] = note_value
    return recs


def json_array_blob(recs):
    return json.dumps(recs, ensure_ascii=False, indent=2)


def path_list(n=600):
    exts = ["ts", "tsx", "md", "json", "css"]
    roots = ["src", "src/core", "src/util", "tests", "docs", "scripts", "assets"]
    out = []
    for i in range(n):
        if i == 313:
            out.append("src/" + NEEDLE + "/handler.ts")
        else:
            out.append("%s/mod%02d/unit%03d.%s" % (roots[i % len(roots)], i % 40, i, exts[i % len(exts)]))
    return out


def build_log(n=320):
    lines = []
    for i in range(n):
        if i == 216:
            lines.append(
                "FATAL [build] panic at src/%s/engine.rs:217 -- assertion failed: checksum mismatch" % NEEDLE
            )
        elif i % 3 == 0:
            lines.append("WARN  [cargo] timeout while fetching index (attempt %d)" % (i % 5 + 1))
        elif i % 5 == 0:
            lines.append("WARN  [cargo] retry scheduled for registry update")
        elif i % 11 == 0:
            lines.append("ERROR [linker] unresolved symbol `_ZN4core3fmt` referenced by crate `engine`")
        else:
            lines.append(
                "  Compiling engine v0.%d.%d (/workspace/crates/engine-%03d)" % (i % 9, i % 17, i)
            )
    return "\n".join(lines)


def ts_file():
    out = [
        "// src/%s/engine.ts" % NEEDLE,
        "// deterministic fixture for the headroom chain test",
        "type Chunk = { id: string; body: string; size: number };",
        "",
    ]
    for i in range(60):
        out += [
            "function helper%d(c: Chunk): number {" % i,
            "  const weight = (c.size * %d) ^ 0x%04x;" % (i + 1, (i * 7919) & 0xFFFF),
            "  return weight + %d;" % i,
            "}",
            "",
        ]
    out += [
        "export function compressOnce(input: Chunk): Chunk {",
        "  if (!input) return input;",
        "  if (input.size === 0) return input;",
        "  const trimmed = input.body.trim();",
        "  if (!trimmed) return input;",
        "  if (trimmed.length < 16) return input;",
        '  const cleaned = trimmed.replace(/\\s+/g, " ");',
        "  return { ...input, body: cleaned, size: cleaned.length };",
        "}",
        "",
    ]
    for i in range(60, 200):
        out += [
            "function helper%d(c: Chunk): number {" % i,
            "  const weight = (c.size ^ %d) + 0x%04x;" % (i + 1, (i * 104729) & 0xFFFF),
            "  return weight - %d;" % i,
            "}",
            "",
        ]
    return "\n".join(out)


# ---------------------------------------------------------------- 工具定义

TOOL_SPECS = [
    ("read_file", "读取文件内容", {"path": {"type": "string"}}),
    ("write_file", "写入文件内容", {"path": {"type": "string"}, "content": {"type": "string"}}),
    ("list_dir", "列出目录", {"path": {"type": "string"}}),
    ("grep", "全文搜索", {"pattern": {"type": "string"}}),
    ("run_shell", "执行命令", {"cmd": {"type": "string"}}),
    ("git_status", "查看工作区状态", {}),
    ("git_diff", "查看差异", {"ref": {"type": "string"}}),
    ("http_get", "发起 GET 请求", {"url": {"type": "string"}}),
    ("sql_query", "执行 SQL", {"sql": {"type": "string"}}),
    ("json_parse", "解析 JSON", {"text": {"type": "string"}}),
    ("task_create", "创建任务", {"title": {"type": "string"}}),
    ("task_update", "更新任务", {"id": {"type": "string"}, "status": {"type": "string"}}),
]


def tools_anthropic():
    return [
        {
            "name": n,
            "description": d,
            "input_schema": {"type": "object", "properties": p, "required": sorted(p.keys())},
        }
        for n, d, p in TOOL_SPECS
    ]


def tools_chat():
    return [
        {
            "type": "function",
            "function": {
                "name": n,
                "description": d,
                "parameters": {"type": "object", "properties": p, "required": sorted(p.keys())},
            },
        }
        for n, d, p in TOOL_SPECS
    ]


def tools_responses():
    return [
        {
            "type": "function",
            "name": n,
            "description": d,
            "parameters": {"type": "object", "properties": p, "required": sorted(p.keys())},
        }
        for n, d, p in TOOL_SPECS
    ]


# ---------------------------------------------------------------- 各个用例

def p1_body():
    blob = json_array_blob(records(note_value=NEEDLE + " keep-this-note-p1"))
    q = (
        "下面这次 cat records.json 的输出是 240 条记录。只做一件事：\n"
        "找出 note 字段以 " + NEEDLE + " 开头的那条记录，回答它的 id、amount、status。\n"
        "不要输出其它内容。"
    )
    return chat_with_obs(q, "run_shell", {"cmd": "cat records.json"}, blob, "call_p1")


def p2_body():
    blob = json.dumps(path_list(), ensure_ascii=False, indent=2)
    q = (
        "下面这份 find . -type f | sort 的输出是 600 个文件路径。\n"
        "1) 是否存在路径中包含 " + NEEDLE + " 的文件？回答 yes/no 并给出完整路径。\n"
        "2) src/ 下 .ts 文件有多少个？"
    )
    return chat_with_obs(q, "run_shell", {"cmd": "find . -type f | sort"}, blob, "call_p2")


def p3_body():
    blob = build_log()
    q = (
        "下面这次 cargo build 的完整输出（约 320 行）。回答：\n"
        "1) 有没有 FATAL 级别的错误行？原样引用整行。\n"
        "2) 出现次数最多的 WARN 关键字是什么？"
    )
    return chat_with_obs(q, "run_shell", {"cmd": "cargo build 2>&1"}, blob, "call_p3")


def p4_body():
    code = ts_file()
    q = (
        "下面是 src/" + NEEDLE + "/engine.ts 的内容。\n"
        "列出函数 compressOnce 中所有提前 return 的行号。"
    )
    body = chat_with_obs(q, "Read", {"file_path": "src/" + NEEDLE + "/engine.ts"}, code, "call_p4")
    return body, code


def p8_body():
    """对照：同样的 JSON 放在用户消息里，应该被当 prompt 保护、不压缩。"""
    blob = json_array_blob(records(note_value=NEEDLE + " keep-this-note-p8"))
    q = (
        "下面是一次 API 分页查询返回的全部 240 条记录（JSON 数组）。只做一件事：\n"
        "找出 note 字段以 " + NEEDLE + " 开头的那条记录，回答它的 id、amount、status。\n"
        "不要输出其它内容。\n\n" + blob
    )
    return {"model": MODEL, "max_tokens": 512, "messages": [{"role": "user", "content": q}]}


def p5_parts():
    blob = json_array_blob(records(note_value=NEEDLE + " keep-this-note-p5", id_base=9000))
    turns = [
        "第 %d 轮：把第 1 轮 cat 出来的 JSON 里第 %d 条记录的 status 报出来。" % (k, k * 17)
        for k in range(1, 13)
    ]
    return {
        "case": "P5",
        "system": "你是一个严谨的数据助手。",
        "seed_user": "下面这次 cat records.json 的输出是 240 条记录。记住它，之后我会逐条问。",
        "seed_assistant": tool_call_msg("call_p5", "run_shell", {"cmd": "cat records.json"}),
        "tool_result": blob,
        "turns": turns,
    }


def p6_body():
    def tool_msg(call_id, name, payload):
        return {"role": "tool", "tool_call_id": call_id, "content": payload}

    msgs = [
        {
            "role": "user",
            "content": "按顺序跑完三个步骤，最后直接回答最后一次 tool 结果里的 checksum 是多少。",
        },
        tool_call_msg("call_001", "run_shell", {"cmd": "make build"}),
        tool_msg("call_001", "run_shell", "ok, 0 warnings\nchecksum=aaaa1111"),
        tool_call_msg("call_002", "run_shell", {"cmd": "make test"}),
        tool_msg("call_002", "run_shell", "ok, 42 passed\nchecksum=bbbb2222"),
        tool_call_msg("call_003", "run_shell", {"cmd": "make pack"}),
        tool_msg("call_003", "run_shell", "ok\nchecksum=cccc3333\nartifact=/tmp/%s/out.bin" % NEEDLE),
        {"role": "user", "content": "直接回答最后一次 tool 结果里的 checksum 是多少。"},
    ]
    return {"model": MODEL, "max_tokens": 256, "messages": msgs}


P7_OBS = (
    "ok\nchecksum=dddd4444\nartifact=/tmp/%s/out.bin\nexit code 0\nstdout lines 1187" % NEEDLE
)
P7_QUESTION = "直接回答最后一次 tool 结果里的 checksum 是多少。"


def p7_anthropic():
    return {
        "model": MODEL,
        "max_tokens": 256,
        "system": [
            {
                "type": "text",
                "text": "你是一个严格的构建助手，只回答被问到的字段。",
                "cache_control": {"type": "ephemeral"},
            }
        ],
        "tools": tools_anthropic(),
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": P7_QUESTION}]},
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_p7",
                        "name": "run_shell",
                        "input": {"cmd": "cat build.log"},
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_p7",
                        "content": P7_OBS,
                    }
                ],
            },
        ],
    }


def p7_chat():
    return {
        "model": MODEL,
        "max_tokens": 256,
        "tools": tools_chat(),
        "messages": [
            {"role": "system", "content": "你是一个严格的构建助手，只回答被问到的字段。"},
            {"role": "user", "content": P7_QUESTION},
            tool_call_msg("call_p7", "run_shell", {"cmd": "cat build.log"}),
            {"role": "tool", "tool_call_id": "call_p7", "content": P7_OBS},
        ],
    }


def p7_responses():
    return {
        "model": MODEL,
        "max_output_tokens": 256,
        "instructions": "你是一个严格的构建助手，只回答被问到的字段。",
        "tools": tools_responses(),
        "input": [
            {"role": "user", "content": [{"type": "input_text", "text": P7_QUESTION}]},
            {
                "type": "function_call",
                "call_id": "call_p7",
                "name": "run_shell",
                "arguments": json.dumps({"cmd": "cat build.log"}),
            },
            {"type": "function_call_output", "call_id": "call_p7", "output": P7_OBS},
        ],
    }


# ---------------------------------------------------------------- main

def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    p1 = p1_body()
    p2 = p2_body()
    p3 = p3_body()
    p4, p4_code = p4_body()
    p5 = p5_parts()
    p6 = p6_body()
    p7a = p7_anthropic()
    p7b = p7_chat()
    p7c = p7_responses()
    p8 = p8_body()

    dump("p1-json-array.json", p1)
    dump("p2-string-array.json", p2)
    dump("p3-build-log.json", p3)
    dump("p4-source-code.json", p4)
    dump("p5-multiturn.json", p5)
    dump("p6-tool-calls.json", p6)
    dump("p7a-anthropic.json", p7a)
    dump("p7b-chat.json", p7b)
    dump("p7c-responses.json", p7c)
    dump("p8-user-message.json", p8)

    def case(cid, fname, path, proto, target, anchor, **kw):
        d = {
            "case": cid,
            "file": fname,
            "path": path,
            "proto": proto,
            "target": target,
            "needle": NEEDLE,
            "needle_anchor": anchor,
            "expect_tool_count": 0,
            "expect_cache_control": None,
            "expect_null_tool_calls": 0,
            "expect_long_sha": None,
            "multi_turn": False,
        }
        d.update(kw)
        return d

    manifest = [
        case("P1", "p1-json-array.json", "/v1/chat/completions", "openai_chat",
             "工具观察里的 JSON 对象数组（SmartCrusher 主力档）",
             NEEDLE + " keep-this-note-p1",
             expect_null_tool_calls=1),
        case("P2", "p2-string-array.json", "/v1/chat/completions", "openai_chat",
             "工具观察里的字符串数组（最狠的一档）",
             "src/" + NEEDLE + "/handler.ts",
             expect_null_tool_calls=1),
        case("P3", "p3-build-log.json", "/v1/chat/completions", "openai_chat",
             "工具观察里的长日志，FATAL 深埋第 217 行",
             "panic at src/" + NEEDLE + "/engine.rs:217",
             expect_null_tool_calls=1),
        case("P4", "p4-source-code.json", "/v1/chat/completions", "openai_chat",
             "Read 工具读出来的源码，期望原样透传",
             "src/" + NEEDLE + "/engine.ts",
             expect_null_tool_calls=1,
             expect_long_sha=sha(p4_code)),
        case("P5", "p5-multiturn.json", "/v1/chat/completions", "openai_chat",
             "12 轮会话，判前缀是否逐轮字节一致",
             NEEDLE + " keep-this-note-p5",
             expect_null_tool_calls=1,
             multi_turn=True),
        case("P6", "p6-tool-calls.json", "/v1/chat/completions", "openai_chat",
             "content:null + tool_calls 结构保真",
             "artifact=/tmp/" + NEEDLE + "/out.bin",
             expect_null_tool_calls=3),
        case("P7a", "p7a-anthropic.json", "/v1/messages", "anthropic",
             "原生 Anthropic：system 数组 + cache_control + 12 工具 + tool_result",
             "artifact=/tmp/" + NEEDLE + "/out.bin",
             expect_tool_count=12, expect_cache_control=1),
        case("P7b", "p7b-chat.json", "/v1/chat/completions", "openai_chat",
             "同一语义的 OpenAI Chat 形状",
             "artifact=/tmp/" + NEEDLE + "/out.bin",
             expect_tool_count=12, expect_null_tool_calls=1),
        case("P7c", "p7c-responses.json", "/v1/responses", "openai_responses",
             "同一语义的 OpenAI Responses 形状",
             "artifact=/tmp/" + NEEDLE + "/out.bin",
             expect_tool_count=12),
        case("P8", "p8-user-message.json", "/v1/chat/completions", "openai_chat",
             "对照：同样内容放在用户消息里，期望被 prompt 保护不压缩",
             NEEDLE + " keep-this-note-p8"),
    ]

    with open(os.path.join(OUT_DIR, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"needle": NEEDLE, "cases": manifest}, f, ensure_ascii=False, indent=2)

    total = sum(os.path.getsize(os.path.join(OUT_DIR, m["file"])) for m in manifest)
    print("生成 %d 组 payload，合计 %.1f KiB" % (len(manifest), total / 1024.0))
    for m in manifest:
        p = os.path.join(OUT_DIR, m["file"])
        print("  %-4s %8d B  %s" % (m["case"], os.path.getsize(p), m["target"]))


if __name__ == "__main__":
    main()
