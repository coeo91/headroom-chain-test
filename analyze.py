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

DEFAULT_BASELINE = None


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


def collect_tokens(value, out):
    """从 payload 里收集字符串标记，用来在 cid 被网关丢掉时认领桩记录。

    只收 5~300 字的串：太短的不够区分（"grep"），太长的多半是会被压缩掉的大块
    工具输出，压完就不逐字存在于请求体里了。
    """
    if isinstance(value, str):
        s = value.strip()
        if 5 <= len(s) <= 300:
            out.add(s)
    elif isinstance(value, dict):
        for v in value.values():
            collect_tokens(v, out)
    elif isinstance(value, list):
        for v in value:
            collect_tokens(v, out)


def case_token_sets(manifest, payloads_dir):
    """{用例: [(轮次或 None, 标记集合)]}。"""
    out = {}
    for c in manifest["cases"]:
        try:
            with open(os.path.join(payloads_dir, c["file"]), encoding="utf-8") as f:
                payload = json.load(f)
        except Exception:
            continue
        if c.get("multi_turn"):
            acc = set()
            collect_tokens(payload.get("system"), acc)
            collect_tokens(payload.get("seed_user"), acc)
            collect_tokens(payload.get("seed_assistant"), acc)
            sets = []
            for i, t in enumerate(payload.get("turns") or [], 1):
                acc = set(acc)
                collect_tokens(t, acc)
                sets.append((i, acc))
            out[c["case"]] = sets
        else:
            toks = set()
            collect_tokens(payload, toks)
            # 单轮用例在运行记录里 turn 也是 1，两个键都登记上
            out[c["case"]] = [(None, toks), (1, toks)]
    return out


def body_leaves(value, out):
    """取出请求体里所有字符串叶子，用于精确匹配标记。"""
    if isinstance(value, str):
        out.add(value.strip())
    elif isinstance(value, dict):
        for v in value.values():
            body_leaves(v, out)
    elif isinstance(value, list):
        for v in value:
            body_leaves(v, out)


def fallback_pair(runs, stub_records, manifest, payloads_dir):
    """cid 被网关改协议丢掉时的兜底配对。

    magpie 把 Anthropic/Responses 翻译成 OpenAI Chat 时会丢掉 metadata、X-Cid 头
    和 URL 查询串，桩那边就没有 cid 了。这种情况下按"用例内容"认领：只有候选用例
    之间**不共用**的标记才拿来打分（tool_call id、cache_control 标记之类），
    认不准就不认，宁可留未配对也不把数据配错。
    """
    token_sets = case_token_sets(manifest, payloads_dir)
    if not token_sets:
        return [], 0

    candidates = {}
    for r in runs:
        key = (r.get("case"), r.get("turn"))
        candidates.setdefault(key, []).append(r)

    own = {}
    for key in candidates:
        case, turn = key
        for t, toks in token_sets.get(case, []):
            if t == turn:
                own[key] = toks
                break

    # 候选用例之间的专属标记
    case_union = {}
    for key, toks in own.items():
        case_union.setdefault(key[0], set()).update(toks)
    all_cases = set(case_union)
    distinctive = {}
    for key, toks in own.items():
        others = set()
        for c in all_cases:
            if c != key[0]:
                others |= case_union[c]
        if key[1] is not None:  # 多轮：只看本轮新增的标记
            prev = own.get((key[0], key[1] - 1), set())
            distinctive[key] = toks - prev - others
        else:
            distinctive[key] = toks - others

    expect = {c["case"]: c for c in manifest["cases"]}

    # 标记稀有度：出现在越多用例里越不值钱（"assistant" 这类几乎每条都有）
    global_count = {}
    for sets in token_sets.values():
        seen = set()
        for _, toks in sets:
            seen |= toks
        for t in seen:
            global_count[t] = global_count.get(t, 0) + 1

    def weight(t):
        return 1.0 / global_count.get(t, 1)

    pairs = []
    used = set()
    for s in stub_records:
        leaves = set()
        body_leaves(s.get("request_json") or {}, leaves)
        blob = json.dumps(s.get("request_json") or {}, ensure_ascii=False)
        scored = []
        for key in candidates:
            toks = distinctive.get(key)
            if not toks:
                continue
            score = 0.0
            for t in toks:
                hit = t in leaves or (len(t) >= 40 and t in blob)
                if hit:
                    score += weight(t)
            if score > 0:
                scored.append((score, key))
        if not scored:
            continue
        scored.sort(key=lambda x: (-x[0], str(x[1])))
        if len(scored) > 1 and scored[0][0] - scored[1][0] < 1e-9:
            continue  # 认不准就不认
        key = scored[0][1]
        c = expect.get(key[0]) or {}
        needle = c.get("needle")
        if needle and needle not in (s.get("needles") or []):
            continue
        et = c.get("expect_tool_count")
        if et is not None and s.get("tool_count") not in (et, et + 1):
            continue
        for r in candidates.get(key, []):
            if id(r) not in used:
                pairs.append((r, s))
                used.add(id(r))
                break
    return pairs, len(pairs)


def pair(arm, results_dir, manifest=None, payloads_dir="payloads"):
    """按 cid 配对运行记录与桩记录。

    不能按下标配对：headroom 会命中响应缓存而跳过上游调用，桩收到的请求数会少于
    发出的请求数，下标会整体错位。

    cid 被网关改协议丢掉时（magpie 翻译 Anthropic/Responses 会丢 metadata），
    再按内容兜底配对一次。
    """
    runs = load_jsonl(os.path.join(results_dir, "results-%s.jsonl" % arm))
    stub = load_jsonl(os.path.join(results_dir, "stub-%s.jsonl" % arm))
    by_cid = {}
    for s in stub:
        cid = s.get("cid")
        if cid:
            by_cid.setdefault(cid, []).append(s)
    pairs = []
    leftover = []
    for r in runs:
        cid = r.get("cid")
        bucket = by_cid.get(cid) if cid else None
        if bucket:
            pairs.append((r, bucket.pop(0)))
        else:
            leftover.append(r)
    cidless = [s for s in stub if not s.get("cid")]
    fallback = 0
    if leftover and cidless and manifest:
        extra, fallback = fallback_pair(leftover, cidless, manifest, payloads_dir)
        pairs.extend(extra)
    unmatched = len(leftover) - fallback
    return pairs, unmatched, len(runs), len(stub), fallback


def med(xs):
    return statistics.median(xs) if xs else None


def fmt_bytes(x):
    return "-" if x is None else str(x)


def case_rows(arm, manifest, results_dir):
    pairs, unmatched, n_runs, n_stub, fallback = pair(arm, results_dir, manifest)
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
            "fallback": fallback,
            "n_runs": n_runs,
            "n_stub": n_stub,
        }
    return out


def prefix_stability(arm, manifest, results_dir):
    """P5 多轮：第 k 轮请求的前 len(第 k-1 轮) 条消息哈希必须与第 k-1 轮完全一致。"""
    pairs, _, _, _, _ = pair(arm, results_dir, manifest)
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


def parse_groups(specs):
    """`--groups 标签:臂1,臂2,...`；不写标签就用臂名拼一个。"""
    groups = []
    for spec in specs:
        spec = spec.strip()
        if not spec:
            continue
        if ":" in spec:
            label, arms = spec.split(":", 1)
        else:
            label, arms = "", spec
        arms = [a.strip() for a in arms.split(",") if a.strip()]
        if len(arms) < 2:
            raise SystemExit("--groups 至少要两个臂：%s" % spec)
        groups.append((label or " → ".join(arms), arms))
    return groups


def delta_str(x, y):
    if x is None or y is None or not x:
        return "-"
    return "%+d (%.1f%%)" % (y - x, 100.0 * y / x)


def compare_block(all_rows, manifest, label, arms):
    """第一列是绝对基准，第二列相对第一列，其余相对第二列。

    这样 A/B 组的 Δ 是"加不加 headroom"（相对 0M），C 组的 Δ 同理（相对 0M-L），
    两组之间可以直接横向比。
    """
    base_arm, ref_arm = arms[0], arms[1]
    head = [arms[0] + " 原始", arms[1], "Δ(%s-%s)" % (arms[1], arms[0])]
    for a in arms[2:]:
        head += [a, "Δ(%s-%s)" % (a, arms[1])]
    lines = ["### %s" % label, "", "| 用例 | " + " | ".join(head) + " |", "|" + "---|" * (len(head) + 1)]
    for c in manifest["cases"]:
        name = c["case"]

        def get(arm):
            return all_rows.get(arm, {}).get(name, {}).get("bytes")

        row = [name, fmt_bytes(get(base_arm)), fmt_bytes(get(ref_arm)), delta_str(get(base_arm), get(ref_arm))]
        for a in arms[2:]:
            row += [fmt_bytes(get(a)), delta_str(get(ref_arm), get(a))]
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")
    return lines


def topology_block(all_rows, manifest, pairs):
    """跨机 vs 同机：同一位置的 headroom 收益差多少。

    pairs: [(名字, (基线臂, 目标臂), (同机基线臂, 同机目标臂)), ...]
    """
    usable = [
        (name, cross, local)
        for name, cross, local in pairs
        if all(a in all_rows for a in cross + local)
    ]
    if not usable:
        return []

    lines = ["## 跨机 vs 同机（抽查）", ""]
    head = ["用例"]
    for name, _, _ in usable:
        head += ["%s 跨机 Δ" % name, "%s 同机 Δ" % name, "%s 差" % name]
    lines.append("| " + " | ".join(head) + " |")
    lines.append("|" + "---|" * len(head))

    per_pair = {name: [] for name, _, _ in usable}
    for c in manifest["cases"]:
        name = c["case"]
        row = [name]
        for pname, cross, local in usable:
            def d(pair):
                b = all_rows[pair[0]].get(name, {}).get("bytes")
                a = all_rows[pair[1]].get(name, {}).get("bytes")
                return None if (b is None or a is None) else a - b

            dc, dl = d(cross), d(local)
            if dc is None or dl is None:
                row += ["-", "-", "-"]
                continue
            per_pair[pname].append((name, dc, dl, dl - dc))
            row += ["%+d" % dc, "%+d" % dl, "%+d" % (dl - dc)]
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")

    for pname, cross, local in usable:
        diffs = per_pair[pname]
        if not diffs:
            continue
        worst = max(diffs, key=lambda x: abs(x[3]))
        real = [x for x in diffs if abs(x[1]) >= 500]
        agreed = sum(1 for x in real if (x[1] <= 0) == (x[2] <= 0))
        lines.append(
            "- %s：差值最大 %s（跨机 %+d B，同机 %+d B）；压缩方向一致 %d/%d 个用例（跨机 Δ<500B 的视为持平，不计入）"
            % (pname, worst[0], worst[1], worst[2], agreed, len(real))
        )
    lines.append("")
    return lines


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
    ap.add_argument(
        "--baseline",
        default=DEFAULT_BASELINE,
        help="压缩率列的基线臂，默认自动选 0M-L（同机），没有再用 0M",
    )
    ap.add_argument(
        "--groups",
        action="append",
        metavar="标签:臂1,臂2,...",
        help="对照表的分组，可重复。默认两个：同机主判据与跨机抽查",
    )
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    groups = parse_groups(
        args.groups
        or [
            "同机 magpie（主判据）:0D,0M-L,A-L,B-L",
            "跨机 magpie（部署前抽查）:0D,0M,A,B",
        ]
    )

    with open(args.manifest, encoding="utf-8") as f:
        manifest = json.load(f)

    arms = find_arms(args.results)
    if not arms:
        raise SystemExit("在 %s 下没找到 stub-<arm>.jsonl" % args.results)

    all_rows = {}
    for arm in arms:
        all_rows[arm] = case_rows(arm, manifest, args.results)

    baseline = args.baseline or next(
        (a for a in ("0M-L", "0M", "0D") if a in all_rows), "0D"
    )
    base_rows = all_rows.get(baseline, {})
    if not base_rows:
        print("注意：没找到基线臂 %s，压缩率列留空" % baseline)

    out = []
    out.append("# headroom 链路对照结果")
    out.append("")
    out.append("基线臂 = `%s`（两臂去掉 headroom 后的同一拓扑）" % baseline)
    out.append("")
    out.append("每组里：第一列绝对字节，第二列相对第一列，其余相对第二列（即同一拓扑下\"加不加 headroom\"）。")
    out.append("")
    for label, g_arms in groups:
        missing = [a for a in g_arms if a not in all_rows]
        if missing:
            out.append("### %s" % label)
            out.append("")
            out.append("- 缺臂：%s（跳过）" % "、".join("`%s`" % a for a in missing))
            out.append("")
            continue
        out.extend(compare_block(all_rows, manifest, label, g_arms))

    for arm in arms:
        out.extend(table(arm, all_rows[arm], base_rows, baseline))
        any_row = next(iter(all_rows[arm].values()), None)
        if any_row:
            fb = any_row.get("fallback") or 0
            fb_note = "（其中 %d 次靠内容兜底配对：网关改协议丢了 cid）" % fb if fb else ""
            out.append(
                "- 臂 %s 配对：发出 %d 次，桩收到 %d 次，未配对 %d 次%s"
                % (arm, any_row["n_runs"], any_row["n_stub"], any_row["unmatched"], fb_note)
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

    out.extend(
        topology_block(
            all_rows,
            manifest,
            [
                ("A", ("0M", "A"), ("0M-L", "A-L")),
                ("B", ("0M", "B"), ("0M-L", "B-L")),
            ],
        )
    )

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

    for x, y, base in (("A", "B", "0M"), ("A-L", "B-L", "0M-L")):
        if x not in all_rows or y not in all_rows or base not in all_rows:
            continue
        # V5：两条臂相对各自基线都要真的压缩过，说明中间层确实在链路里
        squeezed = {}
        for arm in (x, y):
            hits = []
            for c in manifest["cases"]:
                a = all_rows[arm].get(c["case"], {}).get("bytes")
                b = all_rows[base].get(c["case"], {}).get("bytes")
                if a is not None and b is not None and a < b:
                    hits.append(c["case"])
            squeezed[arm] = hits
        ok = bool(squeezed[x]) and bool(squeezed[y])
        detail = "；".join(
            "%s 压缩了 %s" % (arm, ",".join(squeezed[arm]) or "无") for arm in (x, y)
        )
        v.append(
            (
                "V5 %s 与 %s 相对 %s 都真的有压缩（中间层确实在链路里）" % (x, y, base),
                ok,
                detail,
            )
        )

        # V7：A 与 B 的逐用例差异——这才是"位置有没有用"的测量结果
        same = []
        diff = []
        for c in manifest["cases"]:
            a = all_rows[x].get(c["case"], {}).get("bytes")
            b = all_rows[y].get(c["case"], {}).get("bytes")
            if a is None or b is None:
                continue
            if a == b:
                same.append(c["case"])
            else:
                diff.append("%s(%s %+d B)" % (c["case"], x, b - a))
        if same or diff:
            v.append(
                (
                    "V7 %s 与 %s 的请求体差异分布（信息项）" % (x, y),
                    True,
                    "完全相同：%s；不同：%s"
                    % (",".join(same) or "无", ", ".join(diff) or "无"),
                )
            )

    if "0M-L" in all_rows and ("A-L" in all_rows or "B-L" in all_rows):
        cross_ok = any(a in all_rows for a in ("0M", "A", "B"))
        rows = []
        for pname, cross, local in (("A", ("0M", "A"), ("0M-L", "A-L")), ("B", ("0M", "B"), ("0M-L", "B-L"))):
            if not all(a in all_rows for a in cross + local):
                continue
            for c in manifest["cases"]:
                name = c["case"]

                def d(pair):
                    b = all_rows[pair[0]].get(name, {}).get("bytes")
                    a = all_rows[pair[1]].get(name, {}).get("bytes")
                    return None if (b is None or a is None) else a - b

                dc, dl = d(cross), d(local)
                if dc is not None and dl is not None and abs(dc) >= 500:
                    rows.append((pname, name, dc, dl))
        bad = [r for r in rows if (r[2] <= 0) != (r[3] <= 0)]
        v.append(
            (
                "V6 同机臂与跨机臂的压缩方向一致",
                not bad,
                ("方向相反的用例：%s" % "、".join("%s/%s" % (r[0], r[1]) for r in bad))
                if bad
                else ("%d 个有明显压缩的用例方向一致" % len(rows) if cross_ok else "没跑跨机抽查，本条不适用"),
            )
        )

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
