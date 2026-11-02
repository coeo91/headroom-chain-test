# headroom-chain-test

测量 **LLM 压缩代理 headroom 应该串在 magpie 前面还是后面** 的一套可复现实验。

```
同机主判据（Windows，Qoder 所在机器，全走回环）：

0D    客户端 → 桩                     绝对基准
0M-L  客户端 → magpie → 桩            magpie 自己的开销
A-L   客户端 → headroom → magpie → 桩  headroom 在里侧
B-L   客户端 → magpie → headroom → 桩  headroom 在外侧
H     客户端 → headroom → 桩           归因：headroom 单独贡献

跨机抽查（部署到 Ubuntu Server 前才需要）：0M / A / B
```

不花钱、不外传：全程打本地假供应商桩，桩会记录请求穿过链路后到底还剩什么。

本仓库是独立的第三方测量工具，与 headroom、magpie 官方没有隶属或背书关系；报告里会写明这一点。

完整步骤见 **[RUNBOOK.md](RUNBOOK.md)**，本机自检数据见 **[RESULTS-SAMEMACHINE.md](RESULTS-SAMEMACHINE.md)**（翻译档，主判据）和 **[RESULTS-PASSTHROUGH.md](RESULTS-PASSTHROUGH.md)**（直通档，阴性对照）。

## 为什么不是"看文档选一个"

两臂的区别不在功能，在**可观测的取舍**：

- headroom 在里侧（A-L）时，magpie 的请求先被压缩，网关看到的上下文更小；
- headroom 在外侧（B-L）时，压缩发生在协议翻译之后，但 magpie 可能会丢掉 headroom 注入的检索工具和 `cache_control`，从而让压缩的收益被缓存失效吃掉。

这套测试就是把这两种情况量出来，而不是靠推理。

判定口径写在 RUNBOOK §0（先定死，避免事后挑对自己有利的解释）。**平局判给 B**：agent 的 base URL 由 magpie 在换模型时原子改写，A 方案每次换模型都会把 agent 指回 `3425`、绕过 headroom。

## 快速开始

Windows（Git Bash），仓库在 `/c/22/headroom-chaintest`：

```bash
cd /c/22/headroom-chaintest
py -3 -m venv .venv          # 没有 py 就写你的 Python 3.10+ 绝对路径
.venv/Scripts/python.exe -m pip install "headroom-ai[proxy]==0.42.0"
mkdir -p bin results logs
curl -fL --retry 3 -o bin/magpie.exe \
  https://github.com/yetone/magpie-releases/releases/download/v0.1.2687/magpie-cli-windows-amd64.exe
.venv/Scripts/python.exe gen_payloads.py
```

然后照 RUNBOOK **§3 的"十分钟跑通"** 粘贴一个块即可（起桩 → 起 magpie → 起 headroom → 跑五条臂 → 出表）。

只想先确认桩和脚本没问题，30 秒版本：

```bash
cd /c/22/headroom-chaintest
STUB_PORT=18080 .venv/Scripts/python.exe stub.py            # 另开一个终端
.venv/Scripts/python.exe run_arm.py --arm 0D --url http://127.0.0.1:18080 --repeat 3
.venv/Scripts/python.exe analyze.py --out RESULTS.md
```

## 固定版本

| 组件 | 版本 | 说明 |
|---|---|---|
| headroom | `headroom-ai[proxy]==0.42.0` | PyPI 最新；Windows 有预编译轮子，不需要 Rust |
| magpie | `v0.1.2687` | release 资产 `magpie-cli-windows-amd64.exe`，sha256 `1fa70112864d6d39d6e5e97d8895248085296a483843f4f5cf6c26bfe869a83f` |

**版本的权威来源是官方 feed**，不是 GitHub 的 "latest"：

```bash
curl -s https://usemagpie.ai/api/latest
```

返回里的 `version` 与 `sha256` 才是当前官方认的版本和校验值（本机 2026-11-02 核对：版本 `0.1.2687`，CLI 资产 sha256 与上面一致）。magpie 几乎每天发版，两次查询看到不同版本是正常的——**所以必须写死版本号 + sha256**，别用 `@latest`。

要 GUI 日常用就换 `magpie-windows-amd64.exe`（同一个 release 里的另一个资产，sha256 `67ed06fbb0421d83a4dd720aca670c25623c602522bfc29c7f2cbef25f901fa4`）。Windows 构建没有签名声明，首次运行可能弹 SmartScreen。

## 文件

| 文件 | 作用 |
|---|---|
| `stub.py` | 假供应商。记录字节数、needle 及上下文、逐条消息哈希、工具数、`cache_control` 块数、`content:null` 的 tool_call、长文本哈希、协议形状 |
| `gen_payloads.py` | 生成 P1–P8 与 `manifest.json`（确定性，可复现） |
| `run_arm.py` | 按臂发请求，每条打唯一 `cid` 便于配对，自动切换桩的日志通道 |
| `analyze.py` | 按 `cid` 配对并出判定表，附带 V1–V6 自检；同机/跨机分组可配置，基线臂自动选 `0M-L` |
| `RUNBOOK.md` | 完整测试手册（同机五臂、十分钟一键块、跨机抽查、401 探针、21 条已知坑、§15 实测结论） |
| `RESULTS-SAMEMACHINE.md` | 翻译档实测：0D / 0M-L / A-L / B-L / H 五臂 |
| `RESULTS-PASSTHROUGH.md` | 直通档阴性对照：A-L 与 B-L 逐字节相同 |
| `RESULTS-LOCAL.md` | 早期单机 0D / H 两臂的记录 |
| `reports/` | 给上游的报告草稿与发布记录：magpie [Issue #4899](https://github.com/yetone/magpie/issues/4899)、headroom [Discussion #4612](https://github.com/headroomlabs-ai/headroom/discussions/4612) |

## 跨机抽查（可选）

跨机对照最大的混淆是两台机器之间的 hop。跨机组 `0M / A / B` 用来确认同机结论在跨机拓扑上没有翻转，不产生新的架构结论：

- `0M` 与 `0M-L` 的差 = 跨机 hop 的成本；
- `A / B` 与 `A-L / B-L` 的差 = 结论对网络拓扑有多敏感。

`analyze.py` 默认输出两组对照和一张"跨机 vs 同机"表，并多一条 V6 自检（两边压缩方向是否一致）。

## 主要结论（单机已实测）

- headroom **只压缩工具观察结果**（`role:tool` / Anthropic `tool_result`），用户消息和 Read 输出都被保护。
- 一条 8.7k token 的工具输出压到 2.2k（**-74.8%**）；5.6k token 的路径列表压到 237 token（**-95.8%**）。
- 真实 cargo 构建日志几乎压不动（**-1.9%**）——压缩收益高度依赖内容结构。
- cache mode 会冻结前缀，多轮会话里靠前的大块内容压不到。
- headroom 会注入 `headroom_retrieve` 工具，工具数 +1、Anthropic 的 `cache_control` +1。
- **翻译档（主路径，magpie 真做协议互译）**：P1–P6/P7b/P8 的 A-L 与 B-L 逐字节相同（位置差异不可观测，因为 magpie 的翻译已屏蔽位置信息）；P7a（Anthropic 原生）A-L 3275 B vs B-L 2793 B，B 少 482 B；P7c 差 11 B 可忽略。
- **直通档（对照组，magpie 逐字节透传）**：全部 10 个用例 A-L ≡ B-L 逐字节相同。这是负性对照，证实 harness 可用。

## 依赖

Python 3.10+（只用标准库），[headroom-ai](https://pypi.org/project/headroom-ai/) 的 `[proxy]` extras，以及 [magpie](https://github.com/yetone/magpie)。magpie 原生支持 Qoder / Qoder CN，等链路选型定下来可以直接接管它的 base URL。
