#!/usr/bin/env python3
"""把各臂的运行记录与桩日志配对，出判定表。

    python3 analyze.py                       # 扫 results/ 下所有臂
    python3 analyze.py --out RESULTS.md

判定用的期望值来自 payloads/manifest.json，不写死在代码里。
"""

import argparse
import json
import os
import statistics

DEFAULT_BASELINE = "0M"


def load_jsonl(path):
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def find_arms(results_dir):
    """probe* 是 401 透传探针，不是对照臂，不进表。"""
    arms = []
    for name in sorted(os.listdir(results_dir)):
        if name.startswith("stub-") and name.endswith(".jsonl"):
            arm = name[len("stub-"):-len(".jsonl")]
            if not arm.startswith("probe"):
                arms.append(arm)
    return arms


def all_stub_logs(results_dir):
    return [
        os.path.join(results_dir, n)
        for n in sorted(os.listdir(results_dir))
        if n.startswith("stub-") and n.endswith(".jsonl")
    ]


def pair(arm, results_dir):
    """按 cid 配对运行记录与桩记录。

    不能按下标配对：headroom 会命中响应缓存而跳过上游调用，桩收到的请求数会少于
    发出的请求数，下标会整体错位。
    """
    runs = load_jsonl(os.path.join(results_dir, "results-%s.jsonl" % arm))
    stub = load_jsonl(os.path.join(results_dir, "stub-%s.jsonl" % arm))
    by_cid = {}
    for s in stub:
        cid = s.get("cid")
        if cid:
            by_cid.setdefault(cid, []).append(s)
    pairs = []
    unmatched = 0
    for r in runs:
        cid = r.get("cid")
        bucket = by_cid.get(cid) if cid else None
        if bucket:
            pairs.append((r, bucket.pop(0)))
        else:
            unmatched += 1
    return pairs, unmatched, len(runs), len(stub)


def med(xs):
    return statistics.median(xs) if xs else None


def fmt_bytes(x):
    return "-" if x is None else str(x)


def case_rows(arm, manifest, results_dir):
    pairs, unmatched, n_runs, n_stub = pair(arm, results_dir)
    out = {}
    for c in manifest["cases"]:
        picked = [(r, s) for r, s in pairs if r.get("case") == c["case"]]
        if not picked:
            continue
        first = picked[0][1]
        per_rep = {}
        for r, s in picked:
            per_rep.setdefault(r.get("rep"), []).append(s["body_bytes"])
        bytes_all = [sum(v) for v in per_rep.values()]
        out[c["case"]] = {
            "case": c["case"],
            "n": len(picked),
            "bytes": med(bytes_all),
            "bytes_all": bytes_all,
            "ms": med([r["ms"] for r, _ in picked]),
            "status": sorted(set(r["status"] for r, _ in picked)),
            "needle_ok": c["needle"] in (first.get("needles") or []),
            "needles": first.get("needles") or [],
            "ctx_ok": any(
                c["needle_anchor"] in w for w in (first.get("needle_windows") or [])
            ),
            "proto_seen": first.get("proto_shape"),
            "proto_expected": c["proto"],
            "tools_seen": first.get("tool_count"),
            "tools_expected": c["expect_tool_count"],
            "cc_seen": first.get("cache_control_blocks"),
            "cc_expected": c["expect_cache_control"],
            "null_tc_seen": first.get("tool_call_null_content"),
            "null_tc_expected": c["expect_null_tool_calls"],
            "long_ok": (
                True
                if c["expect_long_sha"] is None
                else c["expect_long_sha"] in [f["sha256"] for f in (first.get("long_strings") or [])]
            ),
            "msg_count": first.get("msg_count"),
            "records": picked,
            "unmatched": unmatched,
            "n_runs": n_runs,
            "n_stub": n_stub,
        }
    return out


def prefix_stability(arm, manifest, results_dir):
    """P5 多轮：第 k 轮请求的前 len(第 k-1 轮) 条消息哈希必须与第 k-1 轮完全一致。"""
    pairs, _, _, _ = pair(arm, results_dir)
    picked = [(r, s) for r, s in pairs if r.get("case") == "P5"]
    reps = {}
    for r, s in picked:
        reps.setdefault(r.get("rep"), []).append((r.get("turn"), s.get("msg_hashes") or []))
    detail = []
    ok = True
    for rep, items in sorted(reps.items()):
        items.sort(key=lambda x: x[0] or 0)
        for i in range(1, len(items)):
            prev = items[i - 1][1]
            cur = items[i][1]
            n = len(prev)
            same = cur[:n] == prev
            if not same:
                ok = False
                diff = [j for j in range(min(n, len(cur))) if cur[j] != prev[j]]
                detail.append(
                    "  rep%d turn%s: 前 %d 条中 %d 条被改写（首次差异在第 %s 条）"
                    % (rep, items[i][0], n, len(diff), diff[0] if diff else "?")
                )
    return ok, detail, len(reps)


def pair_cell(seen, expected):
    return str(seen) if expected is None else "%s/%s" % (seen, expected)


def table(arm, rows, base_rows, baseline):
    lines = []
    lines.append("### 臂 %s" % arm)
    lines.append("")
    lines.append(
        "| 用例 | 桩收到字节 | Δ vs %s | 压缩率 | needle | 上下文 | 协议(见/期) | 工具(见/期) | cc(见/期) | nullTC(见/期) | 长文本 | 中位延迟 |"
        % baseline
    )
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for c in rows.values():
        b = base_rows.get(c["case"], {}).get("bytes")
        delta = ""
        ratio = ""
        if b and c["bytes"]:
            delta = "%+d" % (c["bytes"] - b)
            ratio = "%.1f%%" % (100.0 * c["bytes"] / b)
        needle = "OK" if c["needle_ok"] else "**丢失**"
        ctx = "OK" if c["ctx_ok"] else "~"
        proto = "%s/%s" % (c["proto_seen"], c["proto_expected"])
        tools = pair_cell(c["tools_seen"], c["tools_expected"])
        cc = pair_cell(c["cc_seen"], c["cc_expected"])
        ntc = pair_cell(c["null_tc_seen"], c["null_tc_expected"])
        fence = "OK" if c["long_ok"] else "**被改写**"
        ms = "-" if c["ms"] is None else "%.0f" % c["ms"]
        lines.append(
            "| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |"
            % (c["case"], fmt_bytes(c["bytes"]), delta or "-", ratio or "-", needle, ctx, proto, tools, cc, ntc, fence, ms)
        )
    lines.append("")
    return lines


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default="results")
    ap.add_argument("--manifest", default="payloads/manifest.json")
    ap.add_argument("--baseline", default=DEFAULT_BASELINE)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    with open(args.manifest, encoding="utf-8") as f:
        manifest = json.load(f)

    arms = find_arms(args.results)
    if not arms:
        raise SystemExit("在 %s 下没找到 stub-<arm>.jsonl" % args.results)

    all_rows = {}
    for arm in arms:
        all_rows[arm] = case_rows(arm, manifest, args.results)

    base_rows = all_rows.get(args.baseline, {})
    if not base_rows:
        print("注意：没找到基线臂 %s，压缩率列留空" % args.baseline)

    out = []
    out.append("# headroom 链路对照结果")
    out.append("")
    out.append("基线臂 = `%s`（两臂去掉 headroom 后的同一拓扑）" % args.baseline)
    out.append("")
    out.append("## 三段对照")
    out.append("")
    out.append("| 用例 | 0D 原始 | 0M 过 magpie | Δmagpie | A 过 magpie→headroom? | Δheadroom(A) | B | Δheadroom(B) |")
    out.append("|---|---|---|---|---|---|---|---|")
    for c in manifest["cases"]:
        name = c["case"]

        def get(arm):
            return all_rows.get(arm, {}).get(name, {}).get("bytes")

        d0, m0, a, b = get("0D"), get("0M"), get("A"), get("B")

        def delta(x, y):
            if x is None or y is None:
                return "-"
            return "%+d (%.1f%%)" % (y - x, 100.0 * y / x)

        out.append(
            "| %s | %s | %s | %s | %s | %s | %s | %s |"
            % (name, fmt_bytes(d0), fmt_bytes(m0), delta(d0, m0), fmt_bytes(a), delta(m0, a), fmt_bytes(b), delta(m0, b))
        )
    out.append("")

    for arm in arms:
        out.extend(table(arm, all_rows[arm], base_rows, args.baseline))
        any_row = next(iter(all_rows[arm].values()), None)
        if any_row:
            out.append(
                "- 臂 %s 配对：发出 %d 次，桩收到 %d 次，未配对 %d 次"
                % (arm, any_row["n_runs"], any_row["n_stub"], any_row["unmatched"])
            )
    out.append("")

    out.append("## P5 前缀稳定性（cache mode 前提）")
    out.append("")
    for arm in arms:
        ok, detail, reps = prefix_stability(arm, manifest, args.results)
        verdict = "逐轮一致" if ok else "**被改写**"
        out.append("- 臂 %s：%s（%d 组重复）" % (arm, verdict, reps))
        for d in detail:
            out.append(d)
    out.append("")

    out.append("## 自检")
    out.append("")
    v = []
    base = all_rows.get("0D") or all_rows.get("0M")
    if base:
        lost = [k for k, r in base.items() if not r["needle_ok"]]
        v.append(("V1 needle 在基线臂全部命中", not lost, ("丢失用例：" + ",".join(lost)) if lost else "全部命中"))
        line_lost = [k for k, r in base.items() if not r["ctx_ok"]]
        v.append(("V1b needle 上下文锚点在基线臂未被破坏", not line_lost, ("被破坏：" + ",".join(line_lost)) if line_lost else "完好"))
    else:
        v.append(("V1 needle 在基线臂全部命中", False, "缺 0D/0M 臂"))

    if "0D" in all_rows:
        ok, detail, reps = prefix_stability("0D", manifest, args.results)
        v.append(("V2 0D 臂 P5 前缀逐轮一致（说明客户端构造没问题）", ok, "一致" if ok else "; ".join(detail[:3])))
    else:
        v.append(("V2 0D 臂 P5 前缀逐轮一致", False, "缺 0D 臂"))

    if "H" in all_rows and "0D" in all_rows:
        h, d = all_rows["H"], all_rows["0D"]
        checks = []
        for name, limit in (("P1", 0.75), ("P2", 0.25)):
            hb, db = h.get(name, {}).get("bytes"), d.get(name, {}).get("bytes")
            checks.append((name, hb, db, (hb / db) if (hb and db) else None, limit))
        good = all(c[3] is not None and c[3] < c[4] for c in checks)
        detail = "；".join(
            "%s H/0D=%s (期望<%.0f%%)" % (c[0], ("%.1f%%" % (100 * c[3])) if c[3] is not None else "?", 100 * c[4])
            for c in checks
        )
        v.append(("V3 H 臂对 P1/P2 有真实压缩", good, detail))
    else:
        v.append(("V3 H 臂对 P1/P2 有真实压缩", False, "缺 H 或 0D 臂"))

    if "A" in all_rows and "B" in all_rows:
        same = []
        for c in manifest["cases"]:
            a = all_rows["A"].get(c["case"], {}).get("bytes")
            b = all_rows["B"].get(c["case"], {}).get("bytes")
            if a is not None and b is not None and a == b:
                same.append(c["case"])
        v.append(
            (
                "V5 A 与 B 的请求体不完全相同（相同说明中间层没生效）",
                not same,
                ("完全相同的用例：" + ",".join(same)) if same else "存在差异",
            )
        )
    else:
        v.append(("V5 A 与 B 的请求体不完全相同", False, "缺 A 或 B 臂"))

    forced = any(
        rec.get("forced_401") for path in all_stub_logs(args.results) for rec in load_jsonl(path)
    )
    v.append(("V4 401 透传探针已跑过", forced, "已见到 forced_401 记录" if forced else "还没跑过 401 模式（V4 未验证）"))

    for name, ok, detail in v:
        out.append("- **%s** %s — %s" % (name, "通过" if ok else "未通过", detail))
    out.append("")

    text = "\n".join(out)
    print(text)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        print("\n已写入 %s" % args.out)


if __name__ == "__main__":
    main()
