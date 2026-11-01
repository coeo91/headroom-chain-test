# headroom 串联顺序测试 RUNBOOK

目标：用可复现的测量，回答 **headroom 该放在 magpie 前面还是后面**。

```
A 臂：客户端 → headroom → magpie → 供应商
B 臂：客户端 → magpie → headroom → 供应商
```

所有命令都可直接粘贴。`<ubuntu-ip>`、`<magpie-ip>`、`<user>` 三处占位自己替换。
本机（Windows）已经跑过的自检记录和踩过的坑在 §0 和 §11，先看，能省掉大部分返工。

---

## 0. 判定口径（先定好，避免事后挑对自己有利的解释）

按顺序判，前一条否决就不再往下看：

| 序 | 检查 | 通过条件 | 不通过的后果 |
|---|---|---|---|
| 1 | **保真否决** | 每条用例 needle 命中、needle 上下文完好、长文本（源码）字节未变 | 该臂直接淘汰，压缩率再高也没用 |
| 2 | **静默跳过检查** | 桩收到的请求数 = 客户端发出数，`未配对 0 次` | 配对数不对，整臂数据作废，先查缓存/超时 |
| 3 | **压缩收益** | 同一用例，B 相对 0M 的字节差 ≥ A 相对 0M 的字节差 + 5 个百分点 | 谁压得多谁赢 |
| 4 | **前缀稳定** | P5 多轮里每一轮请求的前缀消息哈希逐轮一致 | 不一致说明压缩改写了历史，缓存全废 |
| 5 | **延迟** | 中位延迟差 ≥ 15% 才算显著 | 小于 15% 视为打平 |
| 6 | **平局裁定** | 平局判给 **A（headroom 在内侧、magpie 在外侧）** | 理由：agent 的 base URL 始终由 magpie 管，headroom 的地址不会被 magpie 换模型时覆盖掉 |

阈值来自本机实测：headroom 对一条 8.7k token 的工具输出能压掉 74.8%，对 5.6k token 的路径列表压掉 95.8%。5 个百分点在这个量级上足够区分"真压缩"和"抖动"。

---

## 1. 拓扑与机器角色

| 角色 | 放在哪 | 地址 | 说明 |
|---|---|---|---|
| 客户端（run_arm.py） | **Ubuntu** | 本机 | 和桩、headroom 同机，日志好收 |
| 假供应商桩（stub.py） | **Ubuntu** | `<ubuntu-ip>:18080` | 记录穿过链路后请求还剩什么 |
| headroom | **Ubuntu** | `127.0.0.1:8787`（B 臂临时开放到 LAN） | 被测对象 |
| magpie | **局域网另一台** | `<magpie-ip>:3425` | 网关，固定端口 |
| 真供应商 | 不参与 | — | 全程用假桩，不花钱、不外传 |

为什么桩和 runner 同机：`run_arm.py` 会把桩的日志切到 `results/stub-<臂>.jsonl`，`analyze.py` 直接读同目录；分机放就要来回 scp，容易数据错版。

### 各臂谁指向谁

| 臂 | 客户端请求打到 | headroom 上游 | magpie 上游 | 需要的服务 |
|---|---|---|---|---|
| 0D | `<ubuntu-ip>:18080` | — | — | 桩 |
| 0M | `<magpie-ip>:3425` | — | 桩 | 桩 + magpie |
| A | `127.0.0.1:8787` | magpie | 桩 | 桩 + magpie + headroom |
| B | `<magpie-ip>:3425` | 桩 | headroom | 桩 + magpie + headroom |
| H | `127.0.0.1:8787` | 桩 | — | 桩 + headroom |

- **A 和 0M 共用同一份 magpie 配置**（magpie 上游都是桩），这是本设计的关键：两臂去掉 headroom 后是同一个拓扑，差额才归因给位置。
- `H` 臂是归因臂：headroom 直接对桩，用来把"headroom 自身开销"和"magpie 干扰"分开。
- 执行顺序固定为 **0D → 0M → A → （改 magpie）→ B → H**，只改两次 magpie 配置，不来回折腾。

---

## 2. 一次性准备

### 2.1 Ubuntu 上装 headroom

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip curl
mkdir -p ~/hr && cd ~/hr
python3 -m venv .venv
. .venv/bin/activate
pip install -U pip
pip install "headroom-ai[proxy]"
headroom --version
```

**包名必须是 `headroom-ai`**。PyPI 上还有一个无关的 `headroom`（0.2.7，某 CLI 助手），装错了会得到一堆看不懂的报错。本机实测版本 0.42.0；要可复现就写死 `"headroom-ai[proxy]==0.42.0"`。

### 2.2 把 harness 拷到 Ubuntu

在 Windows 本机执行（Git Bash）：

```bash
cd /c/22/headroom-chaintest
scp stub.py gen_payloads.py run_arm.py analyze.py <user>@<ubuntu-ip>:~/hr/
```

然后在 Ubuntu 上：

```bash
cd ~/hr
mkdir -p results logs
python3 gen_payloads.py
```

期望输出 10 组、合计约 177 KiB。`payloads/` 由生成器确定性产出，两端算出来必须一模一样——对不上说明代码版本不一致。

### 2.3 放行端口（只在测试期开）

```bash
sudo ufw allow from <magpie-ip> to any port 18080 proto tcp comment 'hr-test stub'
sudo ufw allow from <magpie-ip> to any port 8787  proto tcp comment 'hr-test headroom-B'
sudo ufw status numbered
```

测完记得删：

```bash
sudo ufw status numbered
sudo ufw delete <编号>   # 两条都删
```

---

## 3. 起桩

```bash
cd ~/hr
STUB_PORT=18080 STUB_LOG=~/hr/results/stub.jsonl \
  ./.venv/bin/python stub.py > logs/stub.log 2>&1 &
sleep 1
curl -s http://127.0.0.1:18080/health
```

期望：`{"ok":true,"stub":true,...}`。

日志按臂切换，`run_arm.py` 会自动调 `/_admin/lane/<臂>` 并清空该通道旧文件，不需要手工清。

---

## 4. 起 headroom（每条臂的完整命令）

公共环境变量，**五个都不能省**：

| 变量/参数 | 不加会怎样 |
|---|---|
| `HEADROOM_BEACON=off` | headroom 默认把会话摘要匿名上传到 Headroom Labs，测试数据会出本机 |
| `HEADROOM_TELEMETRY=off` | 本地遥测，默认已关，显式写死防版本变动 |
| `--no-cache` | headroom 自带语义响应缓存，重复请求不会打到桩，配对必然错位 |
| `--no-http2` | 对纯 HTTP 的桩用 HTTP/2 会 JSON 解析失败 |
| `--no-rate-limit` | 连续 60+ 请求会吃 429，后半段数据全废 |
| `--no-subscription-tracking` | 默认会周期性去轮询 Anthropic/OpenAI 额度，测试期纯噪声 |

### 4.1 A 臂 / 前置（headroom 上游 = magpie）

```bash
cd ~/hr
NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost \
HEADROOM_BEACON=off HEADROOM_TELEMETRY=off \
  ./.venv/bin/headroom proxy \
  --port 8787 --host 127.0.0.1 \
  --no-http2 --no-cache --no-rate-limit --no-subscription-tracking \
  --anthropic-api-url http://<magpie-ip>:3425 \
  --openai-api-url   http://<magpie-ip>:3425 \
  > logs/headroom-A.log 2>&1 &
sleep 25
curl -s http://127.0.0.1:8787/health | head -c 400
```

`--anthropic-api-url` / `--openai-api-url` 是唯一生效的方式，同名环境变量 `ANTHROPIC_API_URL` **不起作用**（实测）。
健康检查里 `checks.upstream.url` 必须等于你刚填的地址——这是"A 臂真的是 A 臂"的唯一证据，每臂跑完都存一份。

### 4.2 B 臂（headroom 上游 = 桩，且 magpie 要能连到它）

```bash
pkill -f "headroom proxy" ; sleep 2
cd ~/hr
NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost \
HEADROOM_BEACON=off HEADROOM_TELEMETRY=off \
  ./.venv/bin/headroom proxy \
  --port 8787 --host 0.0.0.0 \
  --no-http2 --no-cache --no-rate-limit --no-subscription-tracking \
  --anthropic-api-url http://127.0.0.1:18080 \
  --openai-api-url   http://127.0.0.1:18080 \
  > logs/headroom-B.log 2>&1 &
sleep 25
curl -s http://127.0.0.1:8787/health | head -c 400
```

B 臂期间 headroom 必须绑 `0.0.0.0`（magpie 在另一台机器上），靠 §2.3 的 ufw 规则限制只有 magpie 的 IP 能进。**测完立刻改回 `127.0.0.1`**，否则就是你方案 B 里最不想要的那种暴露。

替代做法（不想临时开 LAN 端口，前提是 magpie 那台机器有 sshd）：Ubuntu 上开一条反向隧道，把 magpie 的 8787 转到 Ubuntu 的回环：

```bash
ssh -N -R 8787:127.0.0.1:8787 <user>@<magpie-ip>
```

此时 headroom 保持 `--host 127.0.0.1`，magpie 的上游填 `http://127.0.0.1:8787`。

### 4.3 H 臂（归因：headroom 直接对桩）

```bash
pkill -f "headroom proxy" ; sleep 2
cd ~/hr
NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost \
HEADROOM_BEACON=off HEADROOM_TELEMETRY=off \
  ./.venv/bin/headroom proxy \
  --port 8787 --host 127.0.0.1 \
  --no-http2 --no-cache --no-rate-limit --no-subscription-tracking \
  --anthropic-api-url http://127.0.0.1:18080 \
  --openai-api-url   http://127.0.0.1:18080 \
  > logs/headroom-H.log 2>&1 &
sleep 25
```

冷启动约 2.6 秒加载 Kompress ONNX 模型，期间 `/health` 里 `kompress: degraded`。**必须等到 `healthy` 再发测试请求**，否则第一批数据是退化路径的：

```bash
cd ~/hr
./.venv/bin/python - <<'PY'
import json, time, urllib.request
op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
for i in range(40):
    try:
        h = json.load(op.open("http://127.0.0.1:8787/health", timeout=5))
    except Exception as e:
        print(i, "not up:", e); time.sleep(2); continue
    s = h["checks"]["kompress"]["status"]
    print(i, s)
    if s == "healthy":
        break
    time.sleep(2)
PY
```

---

## 5. 配 magpie（只改两次）

magpie 固定 `127.0.0.1:3425`，同时讲 OpenAI Chat / Responses / Anthropic Messages。这里只要一个自定义 provider，上游按臂改。

先确认 CLI 认的字段（不同版本一致的是 `url=`、`anthropic=`、`responses=`、`models=`、`header.<Name>=`，以 `--help` 输出为准）：

```bash
magpie provider --help
magpie provider set --help 2>/dev/null || true
```

### 5.1 第一次：magpie 上游 = 桩（0M 与 A 共用）

```bash
magpie provider set stub url=http://<ubuntu-ip>:18080 \
                         anthropic=http://<ubuntu-ip>:18080 \
                         models=stub-model
magpie provider refresh stub
magpie provider stub          # 期望看到 "N exposed of M"，且 stub-model 在内
magpie models                 # 确认 stub-model 出现在可暴露列表
```

`anthropic=` 这一项很重要：不填的话 Anthropic 原生请求（P7a）会被 magpie 翻成 OpenAI 形状再发出去，桩看到的协议就变了，A/B 两臂的差异会被协议翻译污染。填了之后三套协议各自原样透传，测的才是"位置"而不是"翻译"。

### 5.2 第二次：magpie 上游 = headroom（B 臂）

```bash
magpie provider set stub url=http://<ubuntu-ip>:8787 \
                         anthropic=http://<ubuntu-ip>:8787 \
                         models=stub-model
magpie provider refresh stub
```

（若走 §4.2 的 ssh -R 方案，填 `http://127.0.0.1:8787`。）

两次 `refresh` 都能成功：headroom 会把 `GET /v1/models` 透传到它的上游（实测返回 `stub-model`），所以 magpie 从 headroom 拉目录和从桩拉目录看到的是同一份。

---

## 6. 逐臂执行

```bash
cd ~/hr
```

**0D 基线**（只要桩在跑）：

```bash
./.venv/bin/python run_arm.py --arm 0D --url http://127.0.0.1:18080 --repeat 3
```

**0M 基线**（magpie 上游 = 桩，见 §5.1）：

```bash
./.venv/bin/python run_arm.py --arm 0M --url http://<magpie-ip>:3425 --repeat 3
```

**A 臂**（§4.1 的 headroom + §5.1 的 magpie）：

```bash
./.venv/bin/python run_arm.py --arm A --url http://127.0.0.1:8787 --repeat 3
curl -s http://127.0.0.1:8787/health > results/health-A.json
curl -s http://127.0.0.1:8787/stats-history > results/stats-history-A.json
curl -s http://127.0.0.1:8787/metrics > results/metrics-A.txt
```

**B 臂**（§4.2 的 headroom + §5.2 的 magpie）：

```bash
./.venv/bin/python run_arm.py --arm B --url http://<magpie-ip>:3425 --repeat 3
curl -s http://127.0.0.1:8787/health > results/health-B.json
curl -s http://127.0.0.1:8787/stats-history > results/stats-history-B.json
magpie usage > results/magpie-usage-B.txt   # 有 --csv 就用 --csv
```

**H 臂**（§4.3 的 headroom，magpie 不参与）：

```bash
./.venv/bin/python run_arm.py --arm H --url http://127.0.0.1:8787 --repeat 3
curl -s http://127.0.0.1:8787/health > results/health-H.json
```

每臂 63 次请求（9 个单轮用例 + P5 的 12 轮，各重复 3 次）。任何一次失败都会让脚本以退出码 2 结束并打印前 10 条错误——**先解决失败再做下一臂**，失败的臂没有分析价值。

---

## 7. 测试用例与提示词

大块内容全部放在**工具观察结果**里（`role:tool` / Anthropic 的 `tool_result`），这是唯一会被 headroom 压缩的位置；纯用户消息会被当 prompt 保护（P8 就是用来证明这一点的对照）。

| 用例 | 形态 | 让模型做什么 | 埋点 | 期望 |
|---|---|---|---|---|
| **P1** | 工具输出 = 240 条记录的 JSON 数组（33 KB） | "找出 note 字段以 NEEDLE-7f3a91 开头的那条记录，回答 id/amount/status" | 第 138 条的 note | 强压缩档，needle 必须活下来 |
| **P2** | 工具输出 = 600 条文件路径（20 KB） | "有没有路径包含 NEEDLE-7f3a91 的文件？src/ 下有多少 .ts？" | 第 314 条路径 | 压得最狠的一档（实测剩 8%），needle 必须活下来 |
| **P3** | 工具输出 = 320 行 cargo build 日志 | "有没有 FATAL？原样引用整行。出现最多的 WARN 关键字？" | 第 217 行 | 对照组：真实日志几乎压不动（实测 1.9%），看它是否被原样透传 |
| **P4** | 工具输出 = 约 900 行 TypeScript（Read 工具） | "列出 compressOnce 里所有提前 return 的行号" | 文件名 | 期望**逐字节原样透传**（Read 被 headroom 显式排除） |
| **P5** | 12 轮会话，首轮先 cat 一份 240 条 JSON | 第 k 轮："把第 1 轮 cat 出来的 JSON 里第 k×17 条记录的 status 报出来" | 第 138 条 | 判**前缀逐轮字节一致**，前缀一改缓存全废 |
| **P6** | 三次 tool_call + 三条工具结果（`content:null`） | "直接回答最后一次 tool 结果里的 checksum" | `artifact=/tmp/NEEDLE-7f3a91/out.bin` | 3 条 `content:null` 的 assistant 消息必须还在 |
| **P7a** | Anthropic 原生：system 数组 + `cache_control` + 12 个工具 + `tool_result` | 同上 | 同上 | 工具数、cache_control 块数应该原样；headroom 会 +1 工具/+1 cc（CCR 注入） |
| **P7b** | 同语义 OpenAI Chat 形状 | 同上 | 同上 | 12 个工具保留 |
| **P7c** | 同语义 OpenAI Responses 形状 | 同上 | 同上 | 12 个工具保留，形状不得变成 Chat |
| **P8** | **对照**：同样的 33 KB JSON 放在用户消息里 | 同上 | 同上 | 期望**不压缩**——证明压缩只发生在工具输出上 |

`needle` 统一是 `NEEDLE-7f3a91`，桩会记录它出现的位置和前后 400 字符，用来判断"token 还在、但上下文被截掉了"这种隐性损坏。

---

## 8. 出表与判定

```bash
cd ~/hr
./.venv/bin/python analyze.py --baseline 0M --out RESULTS.md
cat RESULTS.md
```

看三处：

1. **三段对照表**：`0D / 0M / A / B` 每用例的桩收到字节。`Δmagpie = 0M - 0D` 是 magpie 自己带来的开销；`Δheadroom(A) = A - 0M`、`Δheadroom(B) = B - 0M` 才是位置差异。注意 A 和 B 的分母都是 0M。
2. **自检**：V1 / V1b / V2 / V3 / V4 / V5 六条，任何一条"未通过"都要先解释清楚再看结论。
3. **P5 前缀稳定性**：必须是"逐轮一致"。

### 读表时几个必看的格子

- **`协议(见/期)`**：A/B 臂里 Anthropic 请求应当仍是 `anthropic`。变成 `openai_chat` 说明 magpie 在替你翻译——§5.1 的 `anthropic=` 没生效。
- **`工具(见/期)`**：headroom 在的臂会 **+1**（`headroom_retrieve`）。如果 B 臂是 0，说明 magpie 把注入的工具吃掉了，headroom 的检索兜底也就废了——这是 B 方案一个很实际的失效模式。
- **`cc(见/期)`**：Anthropic 臂同理 **+1**。magpie 若在翻译时丢掉 `cache_control`，prefix 缓存直接失效，`magpie usage` 里的 `cache_read` 会掉到 0。
- **`长文本`**：P4 必须是 OK。被改写 = 源码被动了，该臂淘汰。
- **`配对`**：`未配对 0 次`。不是 0 就先查是不是漏了 `--no-cache`。

### 旁证（可选但建议）

```bash
headroom capture network-diff --direct results/stub-0M.jsonl --headroom results/stub-A.jsonl
```

这是 headroom 官方的对照工具，能独立复核"它自报省了多少"和"桩实测少了多少"是否一致。headroom 自己的 `/stats-history` 里 `tok_saved` 是它的乐观估计，不要单独引用。

---

## 9. 401 透传探针（V4）

目的是确认：上游 401 的**错误体**能原样穿到客户端，而不是被中间层换成自己的 401/500。

```bash
# 1. 换桩为强制 401
pkill -f "stub.py"; sleep 1
cd ~/hr
STUB_PORT=18080 STUB_FORCE_401=1 STUB_LOG=~/hr/results/stub.jsonl \
  ./.venv/bin/python stub.py > logs/stub401.log 2>&1 &
sleep 1

# 2. 对每条在跑的链路各打一发（这条不会被判失败，只是记录）
./.venv/bin/python run_arm.py --arm probe401 --url http://127.0.0.1:8787 --repeat 1 --only P6 || true
# B 臂期间再补一发：
./.venv/bin/python run_arm.py --arm probe401 --url http://<magpie-ip>:3425 --repeat 1 --only P6 || true

# 3. 确认客户端看到的错误码和 error.type 还是上游那一份
curl -s -o /dev/null -w '%{http_code}\n' \
  -X POST http://127.0.0.1:8787/v1/chat/completions \
  -H 'Content-Type: application/json' -H 'Authorization: Bearer sk-stub-test' \
  -d '{"model":"stub-model","messages":[{"role":"user","content":"ping"}]}'

# 4. 恢复正常桩
pkill -f "stub.py"; sleep 1
STUB_PORT=18080 ./.venv/bin/python stub.py > logs/stub.log 2>&1 &
```

`probe401` 臂不进对照表（`analyze.py` 会跳过 `probe*`），只用来给 V4 留证据。

---

## 10. 本机自检记录（已在 Windows 上跑通，供对照）

| 用例 | 0D 桩收到字节 | H 桩收到字节 | 比值 | needle | 上下文 | 长文本 | 说明 |
|---|---|---|---|---|---|---|---|
| P1 | 33685 | 9749 | 28.9% | OK | OK | OK | 8695→2188 token（-74.8%）；三轮里字节有 9245~9749 的抖动 |
| P2 | 20207 | 1618 | 8.0% | OK | OK | OK | 5646→237 token（-95.8%） |
| P3 | 19058 | 19191 | 100.7% | OK | OK | OK | 4616→4529 token（-1.9%），真实日志压不动 |
| P4 | 23089 | 23571 | 102.1% | OK | OK | OK | Read 被排除，仅 +CCR 工具开销 |
| P5 | 416716 | 415828 | 99.8% | OK | OK | OK | cache mode 冻结前 2/3，种子工具结果被冻住，压不到 |
| P6 | 1180 | 1618 | 137% | OK | OK | OK | 小请求，全是注入开销 |
| P7a | 2647 | 2943 | 111% | OK | OK | OK | 工具 12→13，cache_control 1→2 |
| P7b | 2987 | 3256 | 109% | OK | OK | OK | 工具 12→13 |
| P7c | 2792 | 2792 | 100% | OK | OK | OK | Responses 路径直通 |
| P8 | 33473 | 33975 | 101.5% | OK | OK | OK | 用户消息受保护，**不压缩**（符合设计） |

自检结果：V1 通过、V1b 通过、V2 通过、V3 通过、V4 通过（401 体原样穿透）、V5 待真机 A/B。

压缩比在重复之间有抖动（P1 三轮 9245/9749 不等），所以 `--repeat 3` 取中位数、阈值定 5 个百分点，不要看单次数字下结论。

结论要点：**headroom 只压工具观察结果，用户消息和 Read 输出都被保护；cache mode 下多轮会冻结前缀，所以多轮收益只在"尾部工具输出"上兑现。** A/B 的差异因此主要看 P1/P2/P3 三类工具输出。

---

## 11. 已知坑（全部实测踩过）

1. **装错包**：`pip install headroom` 得到的是另一个项目（0.2.7）。要 `headroom-ai[proxy]`。
2. **匿名上传默认开着**：不加 `HEADROOM_BEACON=off`，会话摘要会传去 Headroom Labs。启动日志里确认这句：`Anonymous upload beacon: DISABLED`。
3. **语义缓存吞请求**：不加 `--no-cache`，重复用例不会打到上游，配对数对不上。启动日志里应有 `cache: disabled`。
4. **HTTP/2 对纯 HTTP 桩**：不加 `--no-http2` 会 `parse_error` / JSONDecodeError。
5. **限流 429**：不加 `--no-rate-limit`，跑到后半段（P6 之后）开始 429，且**前一臂的数据还是好的**，很容易误判。
6. **系统代理**：Windows 上 `urllib` 和 `httpx` 都读注册表代理，localhost 请求会被绕出去挂死。`run_arm.py` 里已经 `ProxyHandler({})`；headroom 要 `NO_PROXY=127.0.0.1,localhost`。
7. **订阅轮询**：默认会周期性去问 Anthropic/OpenAI 额度，测试期加 `--no-subscription-tracking`。
8. **只压工具输出**：用户消息永远不压（除显式 `compress_user_messages=true` 且不是 prompt turn）。把大内容放用户消息里测压缩，会得到"压不动"的假结论——这就是 P8 存在的原因。
9. **cache mode 冻结前缀**：`Pipeline: freezing first 2/3 messages`。多轮里靠前的内容压不到，别指望 P5 出压缩率。
10. **CCR 工具注入**：headroom 会塞一个 `headroom_retrieve` 工具，工具数和 `cache_control` 各 +1。看 A/B 差异时要把这 1 个工具的开销算进 "headroom 成本"。
11. **Kompress 冷启动**：约 2.6 秒，期间 `kompress: degraded`。跑测试前必须等 `healthy`。
12. **多进程占端口**：反复起停会留下僵尸 stub/headroom，表现为"新进程启动日志正常但端口是旧的"。动手前先 `pgrep -af "stub.py|headroom proxy"` 清干净。

---

## 12. 这套测试测不到什么

- **真实供应商的 prefix 缓存**：桩不做 KV cache，`cache_read` 只能从 `magpie usage` 侧看。
- **公网延迟**：本机/局域网回环上的延迟差不能外推。
- **多模态、图片、超长上下文**：桩只回文本，只测了文本压缩路径。
- **P3 这类非结构化日志**：实测只压 1.9%，它在这套表里基本是个"透传对照"，不要拿它当压缩收益的代表。
- **magpie 的脱敏改写**：magpie 会在出本机前做占位符替换，桩看到的是脱敏后的文本。如果 A/B 两臂在这个环节有差异，会被误读成"位置差异"——判读时对照 `request_json` 里的字段名是否被改写。
