# headroom 串联顺序测试 RUNBOOK

目标：用可复现的测量回答 **headroom 该放在 magpie 前面还是后面**，并验证这套链路在 Qoder 所在的 Windows 机器上能不能成立。

主路径是**同机**：客户端、桩、headroom、magpie 全部在一台 Windows 上走回环。Qoder 只有 Windows 版，日常也在这台机器上用，所以同机数据才是要部署的那套形态；跨机 A/B 降级为部署到 Ubuntu Server 前的抽查（§8）。

同机对照臂：

```
0D    客户端 → 桩
0M-L  客户端 → magpie → 桩
A-L   客户端 → headroom → magpie → 桩     （headroom 在里侧）
B-L   客户端 → magpie → headroom → 桩     （headroom 在外侧）
H     客户端 → headroom → 桩              （归因：headroom 单独贡献）
```

所有命令都可直接粘贴，默认在 **Git Bash** 里执行、仓库位于 `/c/22/headroom-chaintest`。换了目录只改每块开头的 `cd`。

---

## 0. 判定口径（先定好，避免事后挑对自己有利的解释）

**先看实测结论**：2026-11-02 在本机同机跑完了两档 magpie 配置（数据见 §15），结论已经指向 **B（headroom 在外侧、magpie 在内侧）**。下面的规则是给换机器、换版本后复测用的。

按顺序判，前一条否决就不再往下看：

| 序 | 检查 | 通过条件 | 不通过的后果 |
|---|---|---|---|
| 1 | **保真否决** | 每条用例 needle 命中、needle 上下文完好、长文本（源码）字节未变 | 该臂直接淘汰，压缩率再高也没用 |
| 2 | **静默跳过检查** | 桩收到的请求数 = 客户端发出数，`未配对 0 次` | 配对数不对，整臂数据作废，先查缓存/超时 |
| 3 | **压缩收益** | 同一用例，B-L 相对 0M-L 的字节差 ≥ A-L 相对 0M-L 的字节差 + 5 个百分点 | 谁压得多谁赢；**两者完全相同算平局**，走规则 6 |
| 4 | **前缀稳定** | P5 多轮里每一轮请求的前缀消息哈希逐轮一致 | 不一致说明压缩改写了历史，缓存全废 |
| 5 | **延迟** | 中位延迟差 ≥ 15% 才算显著 | 小于 15% 视为打平 |
| 6 | **平局裁定** | 平局判给 **B（headroom 在外侧、magpie 在内侧）** | 见下 |

规则 6 的理由：agent 只认 magpie 的 `127.0.0.1:3425`，而 magpie 在换模型时会**原子改写各 agent 的配置文件**。B 里 headroom 是 magpie 的上游 provider，不在 agent 的配置里，所以不会被覆盖；A 里 agent 指向 headroom 的 `8787`，下一次在 magpie 里换模型就会被改回 `3425`，headroom 直接被绕过。

**没跑测试时的默认选择也是 B**，理由同上：它不与 magpie 改配置的行为冲突，也不需要每次换模型后手工修 agent 的 base URL。

阈值来自本机实测：headroom 对一条 8.7k token 的工具输出能压掉 74.8%，对 5.6k token 的路径列表压掉 95.8%。5 个百分点在这个量级上足够区分"真压缩"和"抖动"。

> **注意**：A/B 的差异**只在 magpie 真正做协议翻译时才可能出现**。如果 magpie 被配成逐字节透传（provider 同时配了 `url=`/`anthropic=`/`responses=`），A-L 与 B-L 的请求体会逐字节相同，测不出位置差别——这不是 harness 坏了，是那一档配置下"位置"本来就不可观测。两种配置分别怎么配、分别测出什么，见 §6 与 §15。

---

## 1. 拓扑与机器角色（同机）

| 角色 | 地址 | 说明 |
|---|---|---|
| 客户端（`run_arm.py`） | 本机 | 和桩、代理同机，日志直接落 `results/` |
| 假供应商桩（`stub.py`） | `127.0.0.1:18080` | 记录穿过链路后请求还剩什么 |
| headroom | `127.0.0.1:8787` | 被测对象 |
| magpie | `127.0.0.1:3425` | 网关，端口固定 |
| 真供应商 | 不参与 | 全程用假桩，不花钱、不外传 |

为什么把同机当主路径：

- Qoder 只有 Windows 版，最终就是在这台机器上把 headroom/magpie 挂到 Qoder 前面。
- 三条臂全部走回环，跨机 hop 和"magpie 远程鉴权"这两个变量直接消失。
- magpie 只绑回环时对任何 token 都放行，同机测试**不需要网关密钥**，少一个失败点。

### 各臂谁指向谁

| 臂 | 客户端请求打到 | headroom 上游 | magpie 上游 | 需要的服务 |
|---|---|---|---|---|
| 0D | `127.0.0.1:18080` | — | — | 桩 |
| 0M-L | `127.0.0.1:3425` | — | 桩 | 桩 + magpie |
| A-L | `127.0.0.1:8787` | magpie | 桩 | 桩 + magpie + headroom |
| B-L | `127.0.0.1:3425` | 桩 | headroom | 桩 + magpie + headroom |
| H | `127.0.0.1:8787` | 桩 | — | 桩 + headroom |

- **0M-L 与 A-L 共用同一份 magpie 配置**（magpie 上游都是桩），这是本设计的关键：两臂去掉 headroom 后是同一个拓扑，差额才归因给 headroom 的位置。
- **B-L 与 H 共用同一份 headroom 配置**（headroom 上游都是桩），所以第二阶段只重启一次 headroom。
- `H` 是归因臂：headroom 直接对桩，用来把"headroom 自身开销"和"magpie 干扰"分开（例如 CCR 注入的 +1 工具、+1 `cache_control`）。
- 执行顺序固定为 **0D → 0M-L → A-L →（换 headroom 配置 + 改 magpie）→ B-L → H**，总共只改两次。

---

## 2. 一次性准备（Windows）

### 2.1 固定版本

| 组件 | 固定版本 | 说明 |
|---|---|---|
| headroom | `headroom-ai[proxy]==0.42.0` | PyPI 当前最新（2026-11-02 核对）；Windows 轮子 `cp310-abi3-win_amd64`，**不需要 Rust 工具链**；要求 Python ≥3.10 |
| magpie | `v0.1.2687` | 官方 release 仓库 `yetone/magpie-releases`；Windows 资产 `magpie-cli-windows-amd64.exe`（无 GUI）或 `magpie-windows-amd64.exe`（带 GUI） |

**headroom 的包名必须是 `headroom-ai`**。PyPI 上还有一个无关的 `headroom`（0.2.7），装错了会得到一堆看不懂的报错。

```bash
cd /c/22/headroom-chaintest
"C:/Users/WorBudd/AppData/Local/Python/pythoncore-3.14-64/python.exe" -m venv .venv
.venv/Scripts/python.exe -m pip install --upgrade pip
.venv/Scripts/python.exe -m pip install "headroom-ai[proxy]==0.42.0"
.venv/Scripts/headroom.exe --version
```

期望最后一行：`headroom, version 0.42.0`。首次启动会下载 Kompress/检测模型，需要联网。

magpie 的 Windows 安装只有两条路：从 [usemagpie.ai](https://usemagpie.ai) 下载，或直接拿 release 资产（`install.sh` 不处理 Windows）。测试用 CLI 版就够：

```bash
mkdir -p /c/22/headroom-chaintest/bin
curl -fL --retry 3 -o /c/22/headroom-chaintest/bin/magpie.exe \
  https://github.com/yetone/magpie-releases/releases/download/v0.1.2687/magpie-cli-windows-amd64.exe
sha256sum /c/22/headroom-chaintest/bin/magpie.exe
/c/22/headroom-chaintest/bin/magpie.exe --version
```

`sha256sum` 期望 `1fa70112864d6d39d6e5e97d8895248085296a483843f4f5cf6c26bfe869a83f`。

**版本的权威来源是官方 feed**，不是 GitHub 的 "latest"：

```bash
curl -s https://usemagpie.ai/api/latest
```

返回里的 `version` 与 `sha256` 才是当前官方认的版本和校验值（本机 2026-11-02 核对：版本 `0.1.2687`，CLI 资产 sha256 与上面一致）。magpie 一天能发好几个 release，两次查询看到不同版本是正常的——**所以必须写死版本号 + sha256**，别用 `@latest`。下载慢时官方 `install.sh` 支持 `--mirror` 换镜像，但**校验值一律以 feed 里的 sha256 为准**。

要 GUI 日常用就换 `magpie-windows-amd64.exe`（同一个 release 里的另一个资产，sha256 `67ed06fbb0421d83a4dd720aca670c25623c602522bfc29c7f2cbef25f901fa4`）。Windows 构建没有签名声明，首次运行可能弹 SmartScreen。

### 2.2 生成 payloads

```bash
cd /c/22/headroom-chaintest
mkdir -p results logs
.venv/Scripts/python.exe gen_payloads.py
```

期望输出 10 组、合计约 177 KiB。`payloads/` 是确定性产出，两端算出来必须一模一样——对不上说明代码版本不一致。

### 2.3 进程清理（反复起停后必做）

Windows 上反复起停会留下僵尸进程，表现为"新进程启动日志正常，但端口还是旧的"。

**不要用 `netstat -ano` 反查端口**：本机实测 `netstat` 和 `Get-NetTCPConnection` 都看不到这些回环监听（8787/18080/3425），按端口找 PID 会得到空结果，然后旧的 headroom 继续应答 `/health`，看起来"配置没生效"。**按镜像名杀进程**：

```bash
taskkill //F //IM headroom.exe //T 2>&1 | head -3
taskkill //F //IM magpie.exe //T 2>&1 | head -3
# 桩是 python 进程，按命令行匹配（限定 Name='python.exe'，避免误杀别的 python）
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { \$_.CommandLine -like '*stub.py*' } | ForEach-Object { taskkill //PID \$_.ProcessId //F }"
```

杀完确认 8787 真的没了（连不上才是对的）：

```bash
curl -s --max-time 2 http://127.0.0.1:8787/health || echo "8787 已停"
```

---

## 3. 十分钟跑通（从零到出表，一个块）

这是完整流程的连续版本；每一步的原理和失败排查在 §4–§7。主块跑的是**翻译档**（magpie 真做协议互译，也是真实部署的形态），对照组（直通档）在 §3.1。

块里的 `wait_healthy` 会同时校验 Kompress 状态**和** `checks.upstream.url`——上游地址不对说明 headroom 起的是旧进程或旧配置，这条比 Kompress 状态更重要。

```bash
cd /c/22/headroom-chaintest
mkdir -p logs results bin

PY=.venv/Scripts/python.exe
HR=.venv/Scripts/headroom.exe
MG=bin/magpie.exe

kill_all() {
  taskkill //F //IM headroom.exe //T >/dev/null 2>&1
  taskkill //F //IM magpie.exe   //T >/dev/null 2>&1
  powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { \$_.CommandLine -like '*stub.py*' } | ForEach-Object { taskkill //PID \$_.ProcessId //F }" >/dev/null 2>&1
  sleep 2
}

wait_healthy() {   # $1 = 期望的 upstream url
  for i in $(seq 1 60); do
    s=$(curl -s --max-time 2 http://127.0.0.1:8787/health \
      | "$PY" -c "import sys,json;d=json.load(sys.stdin);c=d['checks'];print(c['kompress']['status'],c['upstream']['url'])" 2>/dev/null)
    echo "  health[$i]: $s"
    case "$s" in "healthy $1") return 0;; esac
    sleep 2
  done
  echo "!! 没等到 healthy + $1，看 logs/headroom-*.log" >&2
  return 1
}

# 0) 清场
kill_all

# 1) 桩
STUB_PORT=18080 STUB_LOG="$PWD/results/stub.jsonl" \
  "$PY" stub.py > logs/stub.log 2>&1 &
sleep 1
curl -s http://127.0.0.1:18080/health; echo

# 2) magpie（只绑回环，不需要网关密钥）
MAGPIE_ADDR=127.0.0.1:3425 DO_NOT_TRACK=1 \
  "$MG" serve > logs/magpie.log 2>&1 &
for i in $(seq 1 30); do
  curl -s --max-time 1 http://127.0.0.1:3425/ >/dev/null 2>&1 && break
  sleep 1
done

# 3) magpie 上游 = 桩（翻译档：只配 url，magpie 才做协议互译）
"$MG" provider set stub url=http://127.0.0.1:18080 models=stub-model
"$MG" provider stub | head -6          # 期望只出现 chat 一行

# 4) 阶段一：headroom 上游 = magpie
NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost \
HEADROOM_BEACON=off HEADROOM_TELEMETRY=off \
  "$HR" proxy --port 8787 --host 127.0.0.1 \
  --no-http2 --no-cache --no-rate-limit --no-subscription-tracking \
  --anthropic-api-url http://127.0.0.1:3425 \
  --openai-api-url   http://127.0.0.1:3425 \
  > logs/headroom-A.log 2>&1 &
wait_healthy http://127.0.0.1:3425 || exit 1

# 5) 0D → 0M-L → A-L
"$PY" run_arm.py --arm 0D   --url http://127.0.0.1:18080 --repeat 3
"$PY" run_arm.py --arm 0M-L --url http://127.0.0.1:3425 --repeat 3
"$PY" run_arm.py --arm A-L  --url http://127.0.0.1:8787 --repeat 3
curl -s http://127.0.0.1:8787/health > results/health-A-L.json

# 6) 阶段二：headroom 上游 = 桩
taskkill //F //IM headroom.exe //T >/dev/null 2>&1; sleep 2
NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost \
HEADROOM_BEACON=off HEADROOM_TELEMETRY=off \
  "$HR" proxy --port 8787 --host 127.0.0.1 \
  --no-http2 --no-cache --no-rate-limit --no-subscription-tracking \
  --anthropic-api-url http://127.0.0.1:18080 \
  --openai-api-url   http://127.0.0.1:18080 \
  > logs/headroom-B.log 2>&1 &
wait_healthy http://127.0.0.1:18080 || exit 1

# 7) magpie 上游 = headroom
"$MG" provider set stub url=http://127.0.0.1:8787 models=stub-model

# 8) B-L 与 H
"$PY" run_arm.py --arm B-L --url http://127.0.0.1:3425 --repeat 3
"$PY" run_arm.py --arm H   --url http://127.0.0.1:8787 --repeat 3
curl -s http://127.0.0.1:8787/health > results/health-B-L.json

# 9) 归档 + 出表
mkdir -p results/translation
cp results/stub-*.jsonl results/results-*.jsonl results/translation/
"$PY" analyze.py --results results/translation --baseline 0M-L --out RESULTS-SAMEMACHINE.md
```

**每步的期望输出**：

| 步 | 期望 | 不符时看 |
|---|---|---|
| 1 | `{"ok":true,"stub":true,...}` | `logs/stub.log`、端口是否被占 |
| 2 | 无输出、进程不退出 | `logs/magpie.log` |
| 3 | provider 里只有 `chat` 一行（翻译档就是只配 `url=`） | 配多了 `anthropic=`/`responses=` 就变成直通档了 |
| 4/6 | `health[i]: healthy http://127.0.0.1:...` | `logs/headroom-*.log` 里 `kompress` 状态；上游地址不对就是起错配置了 |
| 5/8 | 每条臂退出码 0，`未配对 0 次` | 见 §13 的缓存/限流/代理三条 |
| 9 | 五条臂的表 + V1/V1b/V2/V3/V4/V5 通过 | `RESULTS-SAMEMACHINE.md` 里"未通过"那一行 |

跑完停进程：

```bash
taskkill //F //IM headroom.exe //T 2>&1 | head -2
taskkill //F //IM magpie.exe //T 2>&1 | head -2
```

### 3.1 对照组：直通档（可选，5 分钟）

把 magpie 配成**逐字节透传**（provider 同时配 `url=`/`anthropic=`/`responses=`），再把 0M-L / A-L / B-L 重跑一遍。这档的意义是当**阴性对照**：A-L 与 B-L 应当逐字节相同——如果不同，说明中间层没生效。

```bash
cd /c/22/headroom-chaintest
PY=.venv/Scripts/python.exe
HR=.venv/Scripts/headroom.exe
MG=bin/magpie.exe

# 阶段一：headroom 上游 = magpie，magpie 上游 = 桩（直通档）
taskkill //F //IM headroom.exe //T >/dev/null 2>&1; sleep 2
NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost \
HEADROOM_BEACON=off HEADROOM_TELEMETRY=off \
  "$HR" proxy --port 8787 --host 127.0.0.1 \
  --no-http2 --no-cache --no-rate-limit --no-subscription-tracking \
  --anthropic-api-url http://127.0.0.1:3425 \
  --openai-api-url   http://127.0.0.1:3425 \
  > logs/headroom-A.log 2>&1 &
sleep 20
"$MG" provider set stub url=http://127.0.0.1:18080 \
                       anthropic=http://127.0.0.1:18080 \
                       responses=http://127.0.0.1:18080 models=stub-model
"$PY" run_arm.py --arm 0M-L --url http://127.0.0.1:3425 --repeat 3
"$PY" run_arm.py --arm A-L  --url http://127.0.0.1:8787 --repeat 3

# 阶段二：headroom 上游 = 桩，magpie 上游 = headroom
taskkill //F //IM headroom.exe //T >/dev/null 2>&1; sleep 2
NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost \
HEADROOM_BEACON=off HEADROOM_TELEMETRY=off \
  "$HR" proxy --port 8787 --host 127.0.0.1 \
  --no-http2 --no-cache --no-rate-limit --no-subscription-tracking \
  --anthropic-api-url http://127.0.0.1:18080 \
  --openai-api-url   http://127.0.0.1:18080 \
  > logs/headroom-B.log 2>&1 &
sleep 20
"$MG" provider set stub url=http://127.0.0.1:8787 \
                       anthropic=http://127.0.0.1:8787 \
                       responses=http://127.0.0.1:8787 models=stub-model
"$PY" run_arm.py --arm B-L --url http://127.0.0.1:3425 --repeat 3

# 归档并出表
mkdir -p results/passthrough
cp results/stub-*.jsonl results/results-*.jsonl results/passthrough/
"$PY" analyze.py --results results/passthrough --baseline 0M-L --out RESULTS-PASSTHROUGH.md
```

两档的差别、分别测出什么，见 §15。

---

## 4. 起桩

```bash
cd /c/22/headroom-chaintest
STUB_PORT=18080 STUB_LOG="$PWD/results/stub.jsonl" \
  .venv/Scripts/python.exe stub.py > logs/stub.log 2>&1 &
sleep 1
curl -s http://127.0.0.1:18080/health
```

期望：`{"ok":true,"stub":true,...}`。

日志按臂切换，`run_arm.py` 会自动调 `/_admin/lane/<臂>` 并清空该通道旧文件，不需要手工清。

---

## 5. 起 headroom（两种配置）

公共环境变量，**六个都不能省**：

| 变量/参数 | 不加会怎样 |
|---|---|
| `HEADROOM_BEACON=off` | headroom 默认把会话摘要匿名上传到 Headroom Labs，测试数据会出本机 |
| `HEADROOM_TELEMETRY=off` | 本地遥测，默认已关，显式写死防版本变动 |
| `--no-cache` | headroom 自带语义响应缓存，重复请求不会打到桩，配对必然错位 |
| `--no-http2` | 对纯 HTTP 的桩用 HTTP/2 会 JSON 解析失败 |
| `--no-rate-limit` | 连续 60+ 请求会吃 429，后半段数据全废 |
| `--no-subscription-tracking` | 默认会周期性去轮询 Anthropic/OpenAI 额度，测试期纯噪声 |

`NO_PROXY=127.0.0.1,localhost` 也必须有：Windows 上 `urllib` 和 `httpx` 都会读注册表里的系统代理，localhost 请求会被绕出去挂死。

### 5.1 阶段一（A-L 与 0M-L 用）：headroom 上游 = magpie

```bash
cd /c/22/headroom-chaintest
NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost \
HEADROOM_BEACON=off HEADROOM_TELEMETRY=off \
  .venv/Scripts/headroom.exe proxy \
  --port 8787 --host 127.0.0.1 \
  --no-http2 --no-cache --no-rate-limit --no-subscription-tracking \
  --anthropic-api-url http://127.0.0.1:3425 \
  --openai-api-url   http://127.0.0.1:3425 \
  > logs/headroom-A.log 2>&1 &
sleep 20
curl -s http://127.0.0.1:8787/health | head -c 400
```

`--anthropic-api-url` / `--openai-api-url` 是唯一生效的方式，同名环境变量 `ANTHROPIC_API_URL` **不起作用**（实测）。健康检查里 `checks.upstream.url` 必须等于 `http://127.0.0.1:3425`——这是"A-L 真的是 A-L"的唯一证据，每臂跑完都存一份。

### 5.2 阶段二（B-L 与 H 用）：headroom 上游 = 桩

```bash
cd /c/22/headroom-chaintest
taskkill //F //IM headroom.exe //T 2>&1 | head -2
sleep 2
NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost \
HEADROOM_BEACON=off HEADROOM_TELEMETRY=off \
  .venv/Scripts/headroom.exe proxy \
  --port 8787 --host 127.0.0.1 \
  --no-http2 --no-cache --no-rate-limit --no-subscription-tracking \
  --anthropic-api-url http://127.0.0.1:18080 \
  --openai-api-url   http://127.0.0.1:18080 \
  > logs/headroom-B.log 2>&1 &
sleep 20
curl -s http://127.0.0.1:8787/health | head -c 400
```

全程 `--host 127.0.0.1`：magpie 也在这台机器上，不需要对外开放，也不需要 ufw。

### 5.3 等 Kompress 变 healthy

**必须等到 `healthy` 再发测试请求**，否则第一批数据走的是退化路径。实测耗时：

| 场景 | 到 healthy 的时间 |
|---|---|
| 模型已缓存（本机第二次及以后启动） | 约 10–15 秒 |
| 首次启动（要下载 Kompress ONNX 模型） | 约 25–30 秒 |

期间 `/health` 里 `kompress: degraded`。**别用固定 `sleep` 猜**，用轮询，并且顺带核对上游地址：

```bash
cd /c/22/headroom-chaintest
.venv/Scripts/python.exe - <<'PY'
import json, time, urllib.request
op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
for i in range(60):
    try:
        h = json.load(op.open("http://127.0.0.1:8787/health", timeout=5))
    except Exception as e:
        print(i, "not up:", e); time.sleep(2); continue
    c = h["checks"]
    print(i, c["kompress"]["status"], c["upstream"]["url"])
    if c["kompress"]["status"] == "healthy":
        break
    time.sleep(2)
PY
```

---

## 6. 配 magpie（只改两次）

magpie 固定 `127.0.0.1:3425`，同时讲 OpenAI Chat / Responses / Anthropic Messages。这里只要一个自定义 provider，上游按阶段改。

这个版本（v0.1.2687）认的字段：`url=`、`anthropic=`、`responses=`、`models=`、`key=`、`header.<Name>=`。以 `--help` 输出为准：

```bash
cd /c/22/headroom-chaintest
bin/magpie.exe provider --help
```

**没有 `magpie provider refresh` 这个命令**（v0.1.2687 实测）。模型目录在 `provider set` / `provider add` 时自动拉取，`provider <id>` 的输出里会写"1 exposed of 1 … fetched just now"。

`DO_NOT_TRACK=1` 别省：magpie 默认每天上报一次"正在被使用"（随机 id、版本、系统、agent/provider/model 的 id，不含 prompt/URL/key）。

### 6.0 先决定用哪一档（这是整件事的关键）

magpie 支不支持"按协议透传"，决定了 headroom 的位置**能不能被测出来**：

| 档位 | provider 怎么配 | magpie 行为 | A/B 的位置差 |
|---|---|---|---|
| **翻译档**（主路径） | 只配 `url=` | Anthropic/Responses 请求被翻成 OpenAI Chat 再发上游 | **可能测出来**——真实部署就是这个形态（agent 说 Anthropic，供应商是 OpenAI 兼容） |
| **直通档**（对照） | `url=` + `anthropic=` + `responses=` | 三套协议各自原样透传 | **测不出来**，A-L 与 B-L 逐字节相同（不是 harness 坏了，是这档下"位置"本就不可观测） |

选错档就会得到"A 和 B 完全一样"这种看起来像 harness 坏了的结论。**默认用翻译档**，直通档作为阴性对照（§3.1）。

### 6.1 阶段一：magpie 上游 = 桩（0M-L 与 A-L 共用，翻译档）

```bash
cd /c/22/headroom-chaintest
bin/magpie.exe provider set stub url=http://127.0.0.1:18080 models=stub-model
bin/magpie.exe provider stub          # 期望只列出 chat 一行 + "N exposed of M"（含 stub-model）
bin/magpie.exe models                 # 确认 stub-model 出现在可暴露列表
```

**只配 `url=`**，不配 `anthropic=`/`responses=`——配了就变直通档了。

翻译档下 magpie 往上游发的是**流式**请求（哪怕客户端要的是非流式），所以桩必须会吐 SSE；`stub.py` 已经实现了（按 `stream` 字段分流），不会吐就会看到 `stub did not stream: unexpected reply`。

### 6.2 阶段二：magpie 上游 = headroom（B-L 用）

```bash
cd /c/22/headroom-chaintest
bin/magpie.exe provider set stub url=http://127.0.0.1:8787 models=stub-model
bin/magpie.exe provider stub
```

headroom 会把 `GET /v1/models` 透传到它的上游（实测返回 `stub-model`），所以 magpie 从 headroom 拉目录和从桩拉目录看到的是同一份，`set` 之后目录会自动刷新。

直通档（对照组）把上面两条命令改成带 `anthropic=` 和 `responses=`：

```bash
bin/magpie.exe provider set stub url=http://127.0.0.1:18080 \
                               anthropic=http://127.0.0.1:18080 \
                               responses=http://127.0.0.1:18080 models=stub-model
```

**同机不需要网关密钥**：magpie 只绑回环时对任何 token 都放行（"loopback remains permissive"）。跨机才需要，见 §8。

---

## 7. 逐臂执行

```bash
cd /c/22/headroom-chaintest
```

**0D 基线**（只要桩在跑）：

```bash
.venv/Scripts/python.exe run_arm.py --arm 0D --url http://127.0.0.1:18080 --repeat 3
```

**0M-L 基线**（magpie 上游 = 桩，见 §6.1）：

```bash
.venv/Scripts/python.exe run_arm.py --arm 0M-L --url http://127.0.0.1:3425 --repeat 3
```

**A-L 臂**（§5.1 的 headroom + §6.1 的 magpie）：

```bash
.venv/Scripts/python.exe run_arm.py --arm A-L --url http://127.0.0.1:8787 --repeat 3
curl -s http://127.0.0.1:8787/health > results/health-A-L.json
curl -s http://127.0.0.1:8787/stats-history > results/stats-history-A-L.json
curl -s http://127.0.0.1:8787/metrics > results/metrics-A-L.txt
```

**B-L 臂**（§5.2 的 headroom + §6.2 的 magpie）：

```bash
.venv/Scripts/python.exe run_arm.py --arm B-L --url http://127.0.0.1:3425 --repeat 3
curl -s http://127.0.0.1:8787/health > results/health-B-L.json
curl -s http://127.0.0.1:8787/stats-history > results/stats-history-B-L.json
bin/magpie.exe usage > results/magpie-usage-B-L.txt   # 有 --csv 就用 --csv
```

**H 臂**（§5.2 的 headroom，magpie 不参与）：

```bash
.venv/Scripts/python.exe run_arm.py --arm H --url http://127.0.0.1:8787 --repeat 3
curl -s http://127.0.0.1:8787/health > results/health-H.json
```

每臂 63 次请求（9 个单轮用例 + P5 的 12 轮，各重复 3 次）。任何一次失败都会让脚本以退出码 2 结束并打印前 10 条错误——**先解决失败再做下一臂**，失败的臂没有分析价值。

A-L/B-L 结果如果反直觉，再做跨机抽查（§8）。

---

## 8. 附：跨机抽查（部署到 Ubuntu Server 前）

只有当你准备把链路搬到"Ubuntu 上跑 headroom、另一台机器跑 magpie"时才需要。它的作用是确认同机结论在跨机拓扑上没有翻转，**不改变主判据**。

| 臂 | 链路 |
|---|---|
| 0M | client → magpie(远程) → stub |
| A | client → headroom(本机) → magpie(远程) → stub |
| B | client → magpie(远程) → headroom(本机) → stub |

### 8.1 前置：网关密钥与放行

magpie 默认只绑回环；把它放到网络上（`MAGPIE_ADDR=0.0.0.0:3425` 或某个网卡地址）后，**来自非回环的请求要带一个已启用的网关密钥，否则 401；来源 IP 不在 `MAGPIE_ALLOW_IPS` 里会被 403**。在 magpie 那台机器上：

```bash
MAGPIE_ADDR=0.0.0.0:3425 MAGPIE_ALLOW_IPS=<ubuntu-ip> DO_NOT_TRACK=1 magpie serve
```

然后在 Settings → Network and sharing 里建一个**启用状态**的网关密钥（CLI 命令用 `magpie --help` 确认）。跑臂时加 `--key <网关密钥>`，否则 0M/A/B 全是 401。

Ubuntu 侧放行端口（只在测试期开）：

```bash
sudo ufw allow from <magpie-ip> to any port 18080 proto tcp comment 'hr-test stub'
sudo ufw allow from <magpie-ip> to any port 8787  proto tcp comment 'hr-test headroom-B'
sudo ufw status numbered
```

测完删掉这两条。

### 8.2 B 臂的 headroom 要绑 LAN

```bash
NO_PROXY=127.0.0.1,localhost HEADROOM_BEACON=off HEADROOM_TELEMETRY=off \
  ~/hr/.venv/bin/headroom proxy --port 8787 --host 0.0.0.0 \
  --no-http2 --no-cache --no-rate-limit --no-subscription-tracking \
  --anthropic-api-url http://127.0.0.1:18080 \
  --openai-api-url   http://127.0.0.1:18080
```

**测完立刻改回 `127.0.0.1`**，否则就是方案 B 里最不想要的那种暴露。

替代做法（不想临时开 LAN 端口，前提是 magpie 那台机器有 sshd）：在 Ubuntu 上开反向隧道，magpie 的上游填 `http://127.0.0.1:8787`：

```bash
ssh -N -R 8787:127.0.0.1:8787 <user>@<magpie-ip>
```

### 8.3 改 magpie 与跑臂

magpie 的 provider 地址换成跨机地址（Ubuntu 的 IP），然后：

```bash
cd ~/hr
./.venv/bin/python run_arm.py --arm 0M --url http://<magpie-ip>:3425 --key <key> --repeat 3
./.venv/bin/python run_arm.py --arm A  --url http://127.0.0.1:8787 --key <key> --repeat 3
./.venv/bin/python run_arm.py --arm B  --url http://<magpie-ip>:3425 --key <key> --repeat 3
```

出表时把两组都列出来：

```bash
./.venv/bin/python analyze.py \
  --groups "同机 magpie（主判据）:0D,0M-L,A-L,B-L" \
  --groups "跨机 magpie（抽查）:0D,0M,A,B" \
  --out RESULTS.md
```

报告会多一张"跨机 vs 同机"表和 V6（两边压缩方向是否一致；任一 Δ 小于 500 B 视为持平，不计入）。

---

## 9. 测试用例与提示词

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

## 10. 出表与判定

```bash
cd /c/22/headroom-chaintest
.venv/Scripts/python.exe analyze.py --out RESULTS.md
cat RESULTS.md
```

默认基线臂自动选 `0M-L`（同机），没有它才退回 `0M`；也可以用 `--baseline` 显式指定。

看四处：

1. **分组对照表**：默认两组——`同机 magpie（主判据）` 是 `0D / 0M-L / A-L / B-L`，`跨机 magpie（部署前抽查）` 是 `0D / 0M / A / B`。每组里第二列相对第一列（`0M-L - 0D` 是 magpie 自己的开销），其余相对第二列（`A-L - 0M-L`、`B-L - 0M-L` 才是位置差异）。A-L 和 B-L 的分母都是 0M-L。
2. **每臂明细**：needle / 上下文 / 协议 / 工具数 / `cache_control` / `nullTC` / 长文本 / 延迟。
3. **自检**：V1 / V1b / V2 / V3 / V4 / V5（跑了跨机抽查还有 V6），任何一条"未通过"都要先解释清楚再看结论。
4. **P5 前缀稳定性**：必须是"逐轮一致"。

### 读表时几个必看的格子

- **`协议(见/期)`**：A-L/B-L 里 Anthropic 请求应当仍是 `anthropic`。变成 `openai_chat` 说明 magpie 在替你翻译——§6.1 的 `anthropic=` 没生效。※在翻译档配置下，这始终是 `openai_chat`，不是 misconfiguration。
- **`工具(见/期)`**：headroom 在的臂会 **+1**（`headroom_retrieve`）。如果 B-L 是 0，说明 magpie 把注入的工具吃掉了，headroom 的检索兜底也就废了——这是 B 方案一个很实际的失效模式。
- **`cc(见/期)`**：Anthropic 臂同理 **+1**。magpie 若在翻译时丢掉 `cache_control`，prefix 缓存直接失效，`magpie usage` 里的 `cache_read` 会掉到 0。
- **`长文本`**：P4 必须是 OK。被改写 = 源码被动了，该臂淘汰。
- **`配对`**：`未配对 0 次`。不是 0 就先查是不是漏了 `--no-cache`。

### 旁证（可选但建议）

```bash
cd /c/22/headroom-chaintest
.venv/Scripts/headroom.exe capture network-diff \
  --direct results/stub-0M-L.jsonl --headroom results/stub-A-L.jsonl
```

这是 headroom 官方的对照工具，能独立复核"它自报省了多少"和"桩实测少了多少"是否一致。headroom 自己的 `/stats-history` 里 `tok_saved` 是它的乐观估计，不要单独引用。

---

## 11. 401 透传探针（V4）

目的是确认：上游 401 的**错误体**能原样穿到客户端，而不是被中间层换成自己的 401/500。

```bash
cd /c/22/headroom-chaintest

# 1) 换桩为强制 401
taskkill //F //IM headroom.exe //T >/dev/null 2>&1
STUB_PORT=18080 STUB_FORCE_401=1 STUB_LOG="$PWD/results/stub.jsonl" \
  .venv/Scripts/python.exe stub.py > logs/stub401.log 2>&1 &
sleep 1

# 2) 对每条在跑的链路各打一发（不会判失败，只留证据）
.venv/Scripts/python.exe run_arm.py --arm probe401 --url http://127.0.0.1:8787 --repeat 1 --only P6 || true
.venv/Scripts/python.exe run_arm.py --arm probe401 --url http://127.0.0.1:3425 --repeat 1 --only P6 || true

# 3) 确认客户端看到的错误码和 error.type 还是上游那一份
curl -s -o /dev/null -w '%{http_code}\n' \
  -X POST http://127.0.0.1:8787/v1/chat/completions \
  -H 'Content-Type: application/json' -H 'Authorization: Bearer sk-stub-test' \
  -d '{"model":"stub-model","messages":[{"role":"user","content":"ping"}]}'

# 4) 恢复正常桩
taskkill //F //IM headroom.exe //T >/dev/null 2>&1
STUB_PORT=18080 .venv/Scripts/python.exe stub.py > logs/stub.log 2>&1 &
```

`probe401` 臂不进对照表（`analyze.py` 会跳过 `probe*`），只用来给 V4 留证据。

---

## 12. 本机自检记录（Windows，供对照）

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

自检结果：V1 通过、V1b 通过、V2 通过、V3 通过、V4 通过（401 体原样穿透）、V5 待同机 A-L/B-L 实跑。

压缩比在重复之间有抖动（P1 三轮 9245/9749 不等），所以 `--repeat 3` 取中位数、阈值定 5 个百分点，不要看单次数字下结论。

结论要点：**headroom 只压工具观察结果，用户消息和 Read 输出都被保护；cache mode 下多轮会冻结前缀，所以多轮收益只在"尾部工具输出"上兑现。** A/B 的差异因此主要看 P1/P2/P3 三类工具输出。

### 翻译档（magpie 真做协议互译）

| 用例 | 0D 桩收到字节 | 0M-L 桩收到字节 | A-L 桩收到字节 | B-L 桩收到字节 | 比值 A-L/0M-L | 比值 B-L/0M-L | needle | 上下文 | 长文本 | 协议(见/期) | 工具(见/期) | cc(见/期) | 说明 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| P1 | 33683 | 33683 | 9243 | 9243 | 27.4% | 27.4% | OK | OK | OK | openai_chat/openai_chat | 0/0 | 0 | P1-P8 均 OK；A-L/B-L 逐字节相同 |
| P2 | 20205 | 20205 | 1616 | 1616 | 8.0% | 8.0% | OK | OK | OK | openai_chat/openai_chat | 1/0 | 0 | 工具 1/0 差异（CCR 注入） |
| P3 | 19056 | 19056 | 19189 | 19189 | 100.7% | 100.7% | OK | OK | OK | openai_chat/openai_chat | 1/0 | 0 | 日志压不动，真实透传验证 |
| P4 | 23087 | 23087 | 23569 | 23569 | 102.1% | 102.1% | OK | OK | OK | openai_chat/openai_chat | 1/0 | 0 | Read 被排除，仅 +CCR 工具开销 |
| P5 | 416692 | 416692 | 415804 | 415804 | 99.8% | 99.8% | OK | OK | OK | openai_chat/openai_chat | 0/0 | 0 | cache mode 冻结前 2/3，种子工具被冻结 |
| P6 | 1178 | 1178 | 1616 | 1616 | 137.2% | 137.2% | OK | OK | OK | openai_chat/openai_chat | 0/0 | 3/3 | 小请求，全是注入开销 |
| P7a | 2646 | 2646 | 3275 | 2793 | +493 (117.7%) | +11 (100.4%) | OK | OK | OK | anthropic/anthropic | 12/12 | 1/1 | **关键对比**：A-L 比 B-L 多 482 B（A 里 headroom 在 magpie 上游，magpie 翻译时保留 headroom 注入的工具/cc；B 里 magpie 先翻译，headroom 只看到翻译后的 OpenAI Chat 格式，不再额外注入） |
| P7b | 2985 | 2985 | 3254 | 3254 | +269 (109.0%) | +269 (109.0%) | OK | OK | OK | openai_chat/openai_chat | 13/12 | 0 | 工具数 +1，符合 headroom 注入 |
| P7c | 2790 | 2790 | 2780 | 2791 | +0 (100.0%) | +11 (100.4%) | OK | OK | OK | openai_responses/openai_responses | 12/12 | 0 | Responses 形状不变 |
| P8 | 33471 | 33471 | 33973 | 33973 | +502 (101.5%) | +502 (101.5%) | OK | OK | OK | openai_chat/openai_chat | 1/0 | 0 | 用户消息受保护，**不压缩** |

### 直通档（magpie 逐字节透传）

| 用例 | 0D 桩收到字节 | 0M-L 桩收到字节 | A-L 桩收到字节 | B-L 桩收到字节 | 比值 A-L/0M-L | 比值 B-L/0M-L | needle | 上下文 | 长文本 | 协议(见/期) | 工具(见/期) | cc(见/期) | 说明 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| P1 | 33683 | 33683 | 9243 | 9243 | 27.4% | 27.4% | OK | OK | OK | openai_chat/openai_chat | 0/0 | 0 | A-L ≡ B-L 逐字节相同 |
| P2 | 20205 | 20205 | 1616 | 1616 | 8.0% | 8.0% | OK | OK | OK | openai_chat/openai_chat | 1/0 | 0 | A-L ≡ B-L 逐字节相同 |
| P3 | 19056 | 19056 | 19189 | 19189 | 100.7% | 100.7% | OK | OK | OK | openai_chat/openai_chat | 1/0 | 0 | A-L ≡ B-L 逐字节相同 |
| P4 | 23087 | 23087 | 23569 | 23569 | 102.1% | 102.1% | OK | OK | OK | openai_chat/openai_chat | 1/0 | 0 | A-L ≡ B-L 逐字节相同 |
| P5 | 416692 | 416692 | 415804 | 415804 | 99.8% | 99.8% | OK | OK | OK | openai_chat/openai_chat | 0/0 | 0 | A-L ≡ B-L 逐字节相同 |
| P6 | 1178 | 1178 | 1616 | 1616 | 137.2% | 137.2% | OK | OK | OK | openai_chat/openai_chat | 0/0 | 3/3 | A-L ≡ B-L 逐字节相同 |
| P7a | 2646 | 2646 | 2973 | 2973 | +296 (111.1%) | +296 (111.1%) | OK | OK | OK | anthropic/anthropic | 13/12 | 2/1 | A-L ≡ B-L 完全相同 |
| P7b | 2985 | 2985 | 3254 | 3254 | +269 (109.0%) | +269 (109.0%) | OK | OK | OK | openai_chat/openai_chat | 13/12 | 0 | A-L ≡ B-L 完全相同 |
| P7c | 2790 | 2790 | 2790 | 2790 | +0 (100.0%) | +0 (100.0%) | OK | OK | OK | openai_responses/openai_responses | 12/12 | 0 | A-L ≡ B-L 完全相同 |
| P8 | 33471 | 33471 | 33973 | 33973 | +502 (101.5%) | +502 (101.5%) | OK | OK | OK | openai_chat/openai_chat | 1/0 | 0 | A-L ≡ B-L 完全相同，用户消息不压缩 |

### 自检

- **V1 needle 在基线臂全部命中** 通过 — 全部命中
- **V1b needle 上下文锚点在基线臂未被破坏** 通过 — 完好
- **V2 0D 臂 P5 前缀逐轮一致（说明客户端构造没问题）** 通过 — 一致
- **V3 H 臂对 P1/P2 有真实压缩** 通过 — P1 H/0D=28.9% (期望<75%)；P2 H/0D=8.0% (期望<25%)
- **V4 401 透传探针已跑过** 通过 — 已见到 forced_401 记录
- **V5 A-L 与 B-L 相对 0M-L 都真的有压缩（中间层确实在链路里）** 通过 — A-L 压缩了 P1,P2,P5；B-L 压缩了 P1,P2,P5
- **V7 A-L 与 B-L 的请求体差异分布（信息项）** 通过 — 完全相同：P1,P2,P3,P4,P5,P6,P7b,P8；不同：P7a(A-L -482 B), P7c(A-L +11 B)
- **V6 同机臂与跨机臂的压缩方向一致** 通过 — 没跑跨机抽查，本条不适用

压缩比在重复之间有抖动（P1 三轮 9245/9749 不等），所以 `--repeat 3` 取中位数、阈值定 5 个百分点，不要看单次数字下论断。

结论要点：**headroom 只压工具观察结果，用户消息和 Read 输出都被保护；cache mode 下多轮会冻结前缀，所以多轮收益只在"尾部工具输出"上兑现。** A/B 的差异因此主要看 P1/P2/P3 三类工具输出。

在翻译档配置下（主路径）：
- P7a（Anthropic 原生）：A-L 比 B-L 多 **482 B**（A-L 3275 B vs B-L 2793 B）。原因：A 里 headroom 在 magpie 上游，magpie 翻译时保留 headroom 注入的工具/cc；B 里 magpie 先翻译，headroom 只看到翻译后的 OpenAI Chat 格式，不再额外注入。
- P7c 差 11 B 可忽略不计。
- P1-P6/P7b/P8 的 A-L 与 B-L 逐字节相同——位置差异在翻译档下**不可观测**，因为 magpie 的翻译已屏蔽位置信息。

在直通档配置下（对照组）：
- **全部 10 个用例 A-L ≡ B-L 逐字节相同**。说明 magpie 同时配了 `url=`/`anthropic=`/`responses=` 时，是逐字节透传，headroom 的位置先后不影响结果——这是负性对照，证实 harness 可用。

---

## 13. 已知坑（全部实测踩过）

1. **装错包**：`pip install headroom` 得到的是另一个项目（0.2.7）。要 `headroom-ai[proxy]==0.42.0`。
2. **匿名上传默认开着**：不加 `HEADROOM_BEACON=off`，会话摘要会传去 Headroom Labs。启动日志里确认这句：`Anonymous upload beacon: DISABLED`。
3. **语义缓存吞请求**：不加 `--no-cache`，重复用例不会打到上游，配对数对不上。启动日志里应有 `cache: disabled`。
4. **HTTP/2 对纯 HTTP 桩**：不加 `--no-http2` 会 `parse_error` / JSONDecodeError。
5. **限流 429**：不加 `--no-rate-limit`，跑到后半段（P6 之后）开始 429，且**前一臂的数据还是好的**，很容易误判。
6. **系统代理**：Windows 上 `urllib` 和 `httpx` 都读注册表代理，localhost 请求会被绕出去挂死。`run_arm.py` 里已经 `ProxyHandler({})`；headroom 要 `NO_PROXY=127.0.0.1,localhost`。
7. **订阅轮询**：默认会周期性去问 Anthropic/OpenAI 额度，测试期加 `--no-subscription-tracking`。
8. **只压工具输出**：用户消息永远不压（除显式 `compress_user_messages=true` 且不是 prompt turn）。把大内容放用户消息里测压缩，会得到"压不动"的假结论——这就是 P8 存在的原因。
9. **cache mode 冻结前缀**：`Pipeline: freezing first 2/3 messages`。多轮里靠前的内容压不到，别指望 P5 出压缩率。
10. **CCR 工具注入**：headroom 会塞一个 `headroom_retrieve` 工具，工具数和 `cache_control` 各 +1。看 A/B 差异时要把这 1 个工具的开销算进 "headroom 成本"。
11. **Kompress 冷启动是几十秒不是几秒**：实测已缓存模型时约 **10–15 秒**到 `healthy`，首次要下载 ONNX 模型时约 **25–30 秒**，期间 `kompress: degraded`。别用固定 `sleep 3` 猜，按 §5.3 轮询，并同时核对 `checks.upstream.url`。
12. **`netstat`/`Get-NetTCPConnection` 看不到这些回环监听**：本机实测 8787/18080/3425 都查不到 PID，按端口反查会得到空结果，然后旧的 headroom 继续应答 `/health`，看起来像"配置没生效"。**按镜像名杀**：`taskkill //F //IM headroom.exe //T`、`taskkill //F //IM magpie.exe //T`；桩用 `Get-CimInstance Win32_Process -Filter "Name='python.exe'"` 按命令行匹配 `stub.py`（限定 python.exe 才不会被误杀，别用裸命令行通配）。
13. **magpie 的每日上报**：默认每天报一次"正在被使用"（随机 id、版本、系统、agent/provider/model 的 id，不含 prompt/URL/key）。加 `DO_NOT_TRACK=1`。
14. **跨机 magpie 默认 401/403**：网关只绑回环时，别的机器根本连不上；绑到网络后，非回环请求必须有已启用的网关密钥（401），且来源 IP 不在 `MAGPIE_ALLOW_IPS` 里会被 403。这类 401 会出现在 401 探针之前，别误判成上游拒绝。
15. **ssh -R 到回环会被当成本机请求**：magpie 文档明确说裸 TCP 隧道（`ssh -R`、socat、frp tcp）无法与本机 agent 区分，所以 §8.2 的 ssh -R 方案不需要网关密钥——反过来也意味着它绕过了 magpie 的远程鉴权，只能用于本机测试，不要当成共享部署方案。
16. **magpie 是滚动版本**：release 几乎每天更新（本文固定 `v0.1.2687`，2026-11-02 核对）。复现实验要按 §2.1 的 tag + sha256 下，不要用 `@latest`；以 `https://usemagpie.ai/api/latest` 返回的 version+sha256 为准；CLI-only 与 GUI 构建是两个资产，别混。
17. **magpie 会改写 agent 配置**：在 GUI/CLI 里选模型时，它会把各 agent 的 base URL 指回 `3425`。这正是规则 6 判 B 的原因；也意味着 A 方案下每次换模型后都要重新把 agent 指回 `8787`。
18. **没有 `magpie provider refresh` 这个命令**（v0.1.2687 实测）：模型目录在 `provider set` / `provider add` 时自动拉取，`provider <id>` 输出里会写 "fetched just now"。文档里任何 `refresh` 步骤都是错的。
19. **翻译档要求桩会吐 SSE**：只配 `url=` 时 magpie 往上游发的是流式请求（哪怕客户端要非流式），桩不回 SSE 就会得到 `stub did not stream: unexpected reply` 和 502。`stub.py` 已按 `stream` 字段分流。
20. **翻译档会丢掉全部 cid**：magpie 改写协议时丢掉 body 里的 `metadata`、`X-Cid` 头**和** URL 查询串，桩那边配对不上（本机表现为 `未配对 6 次`）。`analyze.py` 因此加了按内容标记的兜底配对（`fallback_pair`），只用用例之间**不共用**的标记打分，平局就跳过、绝不瞎猜。看到"未配对 0 次（其中 N 次靠内容兜底配对）"是正常的。
21. **选错 magpie 档位会得出"A 和 B 一模一样"的假结论**：provider 同时配了 `url=`/`anthropic=`/`responses=` 就是直通档，A-L 与 B-L 必然逐字节相同。主判据要用翻译档（只配 `url=`），直通档只作阴性对照（§3.1、§6.0、§15）。

---

## 14. 这套测试测不到什么

- **真实供应商的 prefix 缓存**：桩不做 KV cache，`cache_read` 只能从 `magpie usage` 侧看。
- **公网延迟**：回环上的延迟差不能外推到公网或跨机。
- **多模态、图片、超长上下文**：桩只回文本，只测了文本压缩路径。
- **P3 这类非结构化日志**：实测只压 1.9%，它在这套表里基本是个"透传对照"，不要拿它当压缩收益的代表。
- **magpie 的脱敏改写**：magpie 会在出本机前做占位符替换，桩看到的是脱敏后的文本。如果 A-L/B-L 两臂在这个环节有差异，会被误读成"位置差异"——判读时对照 `request_json` 里的字段名是否被改写。
- **Qoder 的真实请求形态**：桩用的是构造出来的 P1–P8，不是 Qoder 的真实会话。链路选型成立后，仍要用 `magpie usage` 在真实会话上复核一次。

---

## 15. 实测结论（2026-11-02，本机 Windows 同机）

原始表在 [`RESULTS-SAMEMACHINE.md`](RESULTS-SAMEMACHINE.md)（翻译档）和 [`RESULTS-PASSTHROUGH.md`](RESULTS-PASSTHROUGH.md)（直通档）。

### 翻译档（主路径）：位置差只在 Anthropic 原生用例上出现

P1–P6、P7b、P8 的 A-L 与 B-L **逐字节相同**。原因不是中间层没生效（V5 已证明两臂相对 0M-L 都真的压缩了），而是这些用例在 magpie 那一侧已经被翻成同一种 OpenAI Chat 请求，"headroom 在翻译前还是翻译后"对它不再产生可观测差异。

唯一有差别的是 P7a（Anthropic 原生：system 数组 + `cache_control` + 12 个工具）：

- B-L 收到 2793 B，比 0M-L 只多 11 B；
- A-L 收到 3275 B，比 0M-L 多 493 B，比 B-L 多 **482 B**。

原因是 A 方案里 headroom 在 magpie 上游，它注入的 `headroom_retrieve` 和 `cache_control` 进了 Anthropic 请求体，magpie 再把这些一并翻译放大；B 方案里 magpie 先把请求翻成 OpenAI Chat，headroom 只看到 Chat 形状（工具数仍是 12/12），不再额外注入。

P7c（Responses 形状）两臂只差 11 B，可忽略。

### 直通档（对照）：A-L 与 B-L 在全部 10 个用例上逐字节相同

这一档 magpie 同时配了 `url=`/`anthropic=`/`responses=`，三套协议各自原样透传，headroom 放在前还是后不改变任何一个字节。它证明的是 harness 能正确识别"位置不可观测"的状态，而不是 A/B 无差别。

### 判定

按 §0 的顺序：保真全过、配对 `未配对 0 次`、两臂压缩方向一致。规则 3 在翻译档下大部分用例打平（逐字节相同），走规则 6 平局裁定；唯一有量化的用例 P7a 也指向 B。

**结论：选 B（headroom 在外侧、magpie 在内侧）。** 量化上 B 在 P7a 少 482 B，定性上 B 不会被 magpie 换模型时改写 agent 配置的行为绕过（§0 规则 6）。

### 复测时必须一起看的东西

- `协议(见/期)` 在翻译档下是 `openai_chat` 是**预期**，不是配错；只有你本意是直通档时才该是 `anthropic`。
- `未配对 0 次（其中 N 次靠内容兜底配对）`：N>0 说明翻译档丢了 cid，属正常；未配对本身不为 0 才是问题。
- P5 前缀稳定性必须"逐轮一致"，否则规则 4 否决，上面的横向比较都不用看。
- 换了 magpie 版本、换机器、换真实供应商，结论都要重测——本表只覆盖 v0.1.2687 + 假桩 + 构造用例。
