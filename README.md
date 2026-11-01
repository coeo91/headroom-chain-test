# headroom-chain-test

测量 **LLM 压缩代理 headroom 应该串在 magpie 前面还是后面** 的一套可复现实验。

```
A 臂：客户端 → headroom → magpie → 供应商
B 臂：客户端 → magpie → headroom → 供应商
C 臂：magpie 也装到本机，A/B/0M 全走回环重跑（可选，用来消掉跨机变量）
```

不花钱、不外传：全程打本地假供应商桩，桩会记录请求穿过链路后到底还剩什么。

完整步骤见 **[RUNBOOK.md](RUNBOOK.md)**，本机自检数据见 **[RESULTS-LOCAL.md](RESULTS-LOCAL.md)**。

## 为什么不是"看文档选一个"

两臂的区别不在功能，在**可观测的取舍**：

- headroom 在里侧（A）时，magpie 的请求先被压缩，网关看到的上下文更小；
- headroom 在外侧（B）时，压缩发生在协议翻译之后，但 magpie 可能会丢掉 headroom 注入的检索工具和 `cache_control`，从而让压缩的收益被缓存失效吃掉。

这套测试就是把这两种情况量出来，而不是靠推理。

## 快速开始

```bash
python3 gen_payloads.py                 # 生成 payloads/ 与 manifest
STUB_PORT=18080 python3 stub.py         # 假供应商（另开一个终端）
python3 run_arm.py --arm 0D --url http://127.0.0.1:18080 --repeat 3
python3 analyze.py --baseline 0M --out RESULTS.md
```

## 文件

| 文件 | 作用 |
|---|---|
| `stub.py` | 假供应商。记录字节数、needle 及上下文、逐条消息哈希、工具数、`cache_control` 块数、`content:null` 的 tool_call、长文本哈希、协议形状 |
| `gen_payloads.py` | 生成 P1–P8 与 `manifest.json`（确定性，可复现） |
| `run_arm.py` | 按臂发请求，每条打唯一 `cid` 便于配对，自动切换桩的日志通道 |
| `analyze.py` | 按 `cid` 配对并出判定表，附带 V1–V6 自检；跨机/同机分组可配置 |
| `RUNBOOK.md` | 完整测试手册（五臂 + 可选 C 臂命令、magpie 配置、401 探针、15 条已知坑） |
| `RESULTS-LOCAL.md` | 单机 0D / H 两臂的实测结果 |

## 五条臂之外的可选 C 臂

跨机对照最大的混淆是两台机器之间的 hop。C 臂把 magpie 也装到被测机，`0M-L / A-L / B-L` 全部走回环：

- `0M-L` 与 `0M` 的差 = 跨机 hop 的成本；
- `A-L / B-L` 与 `A / B` 的差 = 结论对网络拓扑有多敏感。

`analyze.py` 默认就输出两组对照和一张"跨机 vs 同机"表，并多一条 V6 自检（两边压缩方向是否一致）。

## 主要结论（单机已实测）

- headroom **只压缩工具观察结果**（`role:tool` / Anthropic `tool_result`），用户消息和 Read 输出都被保护。
- 一条 8.7k token 的工具输出压到 2.2k（**-74.8%**）；5.6k token 的路径列表压到 237 token（**-95.8%**）。
- 真实 cargo 构建日志几乎压不动（**-1.9%**）——压缩收益高度依赖内容结构。
- cache mode 会冻结前缀，多轮会话里靠前的大块内容压不到。
- headroom 会注入 `headroom_retrieve` 工具，工具数 +1、Anthropic 的 `cache_control` +1。

## 依赖

Python 3.11+（只用标准库），[headroom-ai](https://pypi.org/project/headroom-ai/) 的 `[proxy]` extras，以及可选的 [magpie](https://github.com/yetone/magpie)。
