# headroom 链路对照结果

基线臂 = `0M`（两臂去掉 headroom 后的同一拓扑）

## 三段对照

| 用例 | 0D 原始 | 0M 过 magpie | Δmagpie | A 过 magpie→headroom? | Δheadroom(A) | B | Δheadroom(B) |
|---|---|---|---|---|---|---|---|
| P1 | 33685 | - | - | - | - | - | - |
| P2 | 20207 | - | - | - | - | - | - |
| P3 | 19058 | - | - | - | - | - | - |
| P4 | 23089 | - | - | - | - | - | - |
| P5 | 416716 | - | - | - | - | - | - |
| P6 | 1180 | - | - | - | - | - | - |
| P7a | 2647 | - | - | - | - | - | - |
| P7b | 2987 | - | - | - | - | - | - |
| P7c | 2792 | - | - | - | - | - | - |
| P8 | 33473 | - | - | - | - | - | - |

### 臂 0D

| 用例 | 桩收到字节 | Δ vs 0M | 压缩率 | needle | 上下文 | 协议(见/期) | 工具(见/期) | cc(见/期) | nullTC(见/期) | 长文本 | 中位延迟 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| P1 | 33685 | - | - | OK | OK | openai_chat/openai_chat | 0/0 | 0 | 1/1 | OK | 2 |
| P2 | 20207 | - | - | OK | OK | openai_chat/openai_chat | 0/0 | 0 | 1/1 | OK | 16 |
| P3 | 19058 | - | - | OK | OK | openai_chat/openai_chat | 0/0 | 0 | 1/1 | OK | 2 |
| P4 | 23089 | - | - | OK | OK | openai_chat/openai_chat | 0/0 | 0 | 1/1 | OK | 2 |
| P5 | 416716 | - | - | OK | OK | openai_chat/openai_chat | 0/0 | 0 | 1/1 | OK | 2 |
| P6 | 1180 | - | - | OK | OK | openai_chat/openai_chat | 0/0 | 0 | 3/3 | OK | 2 |
| P7a | 2647 | - | - | OK | OK | anthropic/anthropic | 12/12 | 1/1 | 0/0 | OK | 11 |
| P7b | 2987 | - | - | OK | OK | openai_chat/openai_chat | 12/12 | 0 | 1/1 | OK | 1 |
| P7c | 2792 | - | - | OK | OK | openai_responses/openai_responses | 12/12 | 0 | 0/0 | OK | 1 |
| P8 | 33473 | - | - | OK | OK | openai_chat/openai_chat | 0/0 | 0 | 0/0 | OK | 3 |

- 臂 0D 配对：发出 63 次，桩收到 63 次，未配对 0 次
### 臂 H

| 用例 | 桩收到字节 | Δ vs 0M | 压缩率 | needle | 上下文 | 协议(见/期) | 工具(见/期) | cc(见/期) | nullTC(见/期) | 长文本 | 中位延迟 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| P1 | 9749 | - | - | OK | OK | openai_chat/openai_chat | 1/0 | 0 | 1/1 | OK | 38 |
| P2 | 1618 | - | - | OK | OK | openai_chat/openai_chat | 1/0 | 0 | 1/1 | OK | 15 |
| P3 | 19191 | - | - | OK | OK | openai_chat/openai_chat | 1/0 | 0 | 1/1 | OK | 12 |
| P4 | 23571 | - | - | OK | OK | openai_chat/openai_chat | 1/0 | 0 | 1/1 | OK | 11 |
| P5 | 415828 | - | - | OK | OK | openai_chat/openai_chat | 0/0 | 0 | 1/1 | OK | 13 |
| P6 | 1618 | - | - | OK | OK | openai_chat/openai_chat | 1/0 | 0 | 3/3 | OK | 22 |
| P7a | 2943 | - | - | OK | OK | anthropic/anthropic | 13/12 | 2/1 | 0/0 | OK | 13 |
| P7b | 3256 | - | - | OK | OK | openai_chat/openai_chat | 13/12 | 0 | 1/1 | OK | 33 |
| P7c | 2792 | - | - | OK | OK | openai_responses/openai_responses | 12/12 | 0 | 0/0 | OK | 10 |
| P8 | 33975 | - | - | OK | OK | openai_chat/openai_chat | 1/0 | 0 | 0/0 | OK | 13 |

- 臂 H 配对：发出 63 次，桩收到 63 次，未配对 0 次

## P5 前缀稳定性（cache mode 前提）

- 臂 0D：逐轮一致（3 组重复）
- 臂 H：逐轮一致（3 组重复）

## 自检

- **V1 needle 在基线臂全部命中** 通过 — 全部命中
- **V1b needle 上下文锚点在基线臂未被破坏** 通过 — 完好
- **V2 0D 臂 P5 前缀逐轮一致（说明客户端构造没问题）** 通过 — 一致
- **V3 H 臂对 P1/P2 有真实压缩** 通过 — P1 H/0D=28.9% (期望<75%)；P2 H/0D=8.0% (期望<25%)
- **V5 A 与 B 的请求体不完全相同** 未通过 — 缺 A 或 B 臂
- **V4 401 透传探针已跑过** 通过 — 已见到 forced_401 记录

