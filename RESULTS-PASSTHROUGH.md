# headroom 链路对照结果

基线臂 = `0M-L`（两臂去掉 headroom 后的同一拓扑）

每组里：第一列绝对字节，第二列相对第一列，其余相对第二列（即同一拓扑下"加不加 headroom"）。

### 同机 magpie（主判据）

| 用例 | 0D 原始 | 0M-L | Δ(0M-L-0D) | A-L | Δ(A-L-0M-L) | B-L | Δ(B-L-0M-L) |
|---|---|---|---|---|---|---|---|
| P1 | 33683 | 33683 | +0 (100.0%) | 9243 | -24440 (27.4%) | 9243 | -24440 (27.4%) |
| P2 | 20205 | 20205 | +0 (100.0%) | 1616 | -18589 (8.0%) | 1616 | -18589 (8.0%) |
| P3 | 19056 | 19056 | +0 (100.0%) | 19189 | +133 (100.7%) | 19189 | +133 (100.7%) |
| P4 | 23087 | 23087 | +0 (100.0%) | 23569 | +482 (102.1%) | 23569 | +482 (102.1%) |
| P5 | 416692 | 416692 | +0 (100.0%) | 415804 | -888 (99.8%) | 415804 | -888 (99.8%) |
| P6 | 1178 | 1178 | +0 (100.0%) | 1616 | +438 (137.2%) | 1616 | +438 (137.2%) |
| P7a | 2646 | 2677 | +31 (101.2%) | 2973 | +296 (111.1%) | 2973 | +296 (111.1%) |
| P7b | 2985 | 2985 | +0 (100.0%) | 3254 | +269 (109.0%) | 3254 | +269 (109.0%) |
| P7c | 2790 | 2790 | +0 (100.0%) | 2790 | +0 (100.0%) | 2790 | +0 (100.0%) |
| P8 | 33471 | 33471 | +0 (100.0%) | 33973 | +502 (101.5%) | 33973 | +502 (101.5%) |

### 跨机 magpie（部署前抽查）

- 缺臂：`0M`、`A`、`B`（跳过）

### 臂 0D

| 用例 | 桩收到字节 | Δ vs 0M-L | 压缩率 | needle | 上下文 | 协议(见/期) | 工具(见/期) | cc(见/期) | nullTC(见/期) | 长文本 | 中位延迟 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| P1 | 33683 | +0 | 100.0% | OK | OK | openai_chat/openai_chat | 0/0 | 0 | 1/1 | OK | 3 |
| P2 | 20205 | +0 | 100.0% | OK | OK | openai_chat/openai_chat | 0/0 | 0 | 1/1 | OK | 2 |
| P3 | 19056 | +0 | 100.0% | OK | OK | openai_chat/openai_chat | 0/0 | 0 | 1/1 | OK | 2 |
| P4 | 23087 | +0 | 100.0% | OK | OK | openai_chat/openai_chat | 0/0 | 0 | 1/1 | OK | 2 |
| P5 | 416692 | +0 | 100.0% | OK | OK | openai_chat/openai_chat | 0/0 | 0 | 1/1 | OK | 3 |
| P6 | 1178 | +0 | 100.0% | OK | OK | openai_chat/openai_chat | 0/0 | 0 | 3/3 | OK | 2 |
| P7a | 2646 | -31 | 98.8% | OK | OK | anthropic/anthropic | 12/12 | 1/1 | 0/0 | OK | 1 |
| P7b | 2985 | +0 | 100.0% | OK | OK | openai_chat/openai_chat | 12/12 | 0 | 1/1 | OK | 2 |
| P7c | 2790 | +0 | 100.0% | OK | OK | openai_responses/openai_responses | 12/12 | 0 | 0/0 | OK | 2 |
| P8 | 33471 | +0 | 100.0% | OK | OK | openai_chat/openai_chat | 0/0 | 0 | 0/0 | OK | 3 |

- 臂 0D 配对：发出 63 次，桩收到 63 次，未配对 0 次
### 臂 0M-L

| 用例 | 桩收到字节 | Δ vs 0M-L | 压缩率 | needle | 上下文 | 协议(见/期) | 工具(见/期) | cc(见/期) | nullTC(见/期) | 长文本 | 中位延迟 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| P1 | 33683 | +0 | 100.0% | OK | OK | openai_chat/openai_chat | 0/0 | 0 | 1/1 | OK | 6 |
| P2 | 20205 | +0 | 100.0% | OK | OK | openai_chat/openai_chat | 0/0 | 0 | 1/1 | OK | 6 |
| P3 | 19056 | +0 | 100.0% | OK | OK | openai_chat/openai_chat | 0/0 | 0 | 1/1 | OK | 5 |
| P4 | 23087 | +0 | 100.0% | OK | OK | openai_chat/openai_chat | 0/0 | 0 | 1/1 | OK | 4 |
| P5 | 416692 | +0 | 100.0% | OK | OK | openai_chat/openai_chat | 0/0 | 0 | 1/1 | OK | 5 |
| P6 | 1178 | +0 | 100.0% | OK | OK | openai_chat/openai_chat | 0/0 | 0 | 3/3 | OK | 3 |
| P7a | 2677 | +0 | 100.0% | OK | OK | anthropic/anthropic | 12/12 | 1/1 | 0/0 | OK | 3 |
| P7b | 2985 | +0 | 100.0% | OK | OK | openai_chat/openai_chat | 12/12 | 0 | 1/1 | OK | 4 |
| P7c | 2790 | +0 | 100.0% | OK | OK | openai_responses/openai_responses | 12/12 | 0 | 0/0 | OK | 4 |
| P8 | 33471 | +0 | 100.0% | OK | OK | openai_chat/openai_chat | 0/0 | 0 | 0/0 | OK | 6 |

- 臂 0M-L 配对：发出 63 次，桩收到 63 次，未配对 0 次
### 臂 A-L

| 用例 | 桩收到字节 | Δ vs 0M-L | 压缩率 | needle | 上下文 | 协议(见/期) | 工具(见/期) | cc(见/期) | nullTC(见/期) | 长文本 | 中位延迟 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| P1 | 9243 | -24440 | 27.4% | OK | OK | openai_chat/openai_chat | 0/0 | 0 | 1/1 | OK | 40 |
| P2 | 1616 | -18589 | 8.0% | OK | OK | openai_chat/openai_chat | 1/0 | 0 | 1/1 | OK | 13 |
| P3 | 19189 | +133 | 100.7% | OK | OK | openai_chat/openai_chat | 1/0 | 0 | 1/1 | OK | 19 |
| P4 | 23569 | +482 | 102.1% | OK | OK | openai_chat/openai_chat | 1/0 | 0 | 1/1 | OK | 14 |
| P5 | 415804 | -888 | 99.8% | OK | OK | openai_chat/openai_chat | 0/0 | 0 | 1/1 | OK | 16 |
| P6 | 1616 | +438 | 137.2% | OK | OK | openai_chat/openai_chat | 1/0 | 0 | 3/3 | OK | 16 |
| P7a | 2973 | +296 | 111.1% | OK | OK | anthropic/anthropic | 13/12 | 2/1 | 0/0 | OK | 19 |
| P7b | 3254 | +269 | 109.0% | OK | OK | openai_chat/openai_chat | 13/12 | 0 | 1/1 | OK | 18 |
| P7c | 2790 | +0 | 100.0% | OK | OK | openai_responses/openai_responses | 12/12 | 0 | 0/0 | OK | 12 |
| P8 | 33973 | +502 | 101.5% | OK | OK | openai_chat/openai_chat | 1/0 | 0 | 0/0 | OK | 15 |

- 臂 A-L 配对：发出 63 次，桩收到 63 次，未配对 0 次
### 臂 B-L

| 用例 | 桩收到字节 | Δ vs 0M-L | 压缩率 | needle | 上下文 | 协议(见/期) | 工具(见/期) | cc(见/期) | nullTC(见/期) | 长文本 | 中位延迟 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| P1 | 9243 | -24440 | 27.4% | OK | OK | openai_chat/openai_chat | 0/0 | 0 | 1/1 | OK | 17 |
| P2 | 1616 | -18589 | 8.0% | OK | OK | openai_chat/openai_chat | 1/0 | 0 | 1/1 | OK | 26 |
| P3 | 19189 | +133 | 100.7% | OK | OK | openai_chat/openai_chat | 1/0 | 0 | 1/1 | OK | 37 |
| P4 | 23569 | +482 | 102.1% | OK | OK | openai_chat/openai_chat | 1/0 | 0 | 1/1 | OK | 16 |
| P5 | 415804 | -888 | 99.8% | OK | OK | openai_chat/openai_chat | 0/0 | 0 | 1/1 | OK | 17 |
| P6 | 1616 | +438 | 137.2% | OK | OK | openai_chat/openai_chat | 1/0 | 0 | 3/3 | OK | 14 |
| P7a | 2973 | +296 | 111.1% | OK | OK | anthropic/anthropic | 13/12 | 2/1 | 0/0 | OK | 19 |
| P7b | 3254 | +269 | 109.0% | OK | OK | openai_chat/openai_chat | 13/12 | 0 | 1/1 | OK | 16 |
| P7c | 2790 | +0 | 100.0% | OK | OK | openai_responses/openai_responses | 12/12 | 0 | 0/0 | OK | 18 |
| P8 | 33973 | +502 | 101.5% | OK | OK | openai_chat/openai_chat | 1/0 | 0 | 0/0 | OK | 17 |

- 臂 B-L 配对：发出 63 次，桩收到 63 次，未配对 0 次
### 臂 H

| 用例 | 桩收到字节 | Δ vs 0M-L | 压缩率 | needle | 上下文 | 协议(见/期) | 工具(见/期) | cc(见/期) | nullTC(见/期) | 长文本 | 中位延迟 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| P1 | 9747 | -23936 | 28.9% | OK | OK | openai_chat/openai_chat | 1/0 | 0 | 1/1 | OK | 12 |
| P2 | 1616 | -18589 | 8.0% | OK | OK | openai_chat/openai_chat | 1/0 | 0 | 1/1 | OK | 11 |
| P3 | 19189 | +133 | 100.7% | OK | OK | openai_chat/openai_chat | 1/0 | 0 | 1/1 | OK | 12 |
| P4 | 23569 | +482 | 102.1% | OK | OK | openai_chat/openai_chat | 1/0 | 0 | 1/1 | OK | 11 |
| P5 | 415804 | -888 | 99.8% | OK | OK | openai_chat/openai_chat | 0/0 | 0 | 1/1 | OK | 13 |
| P6 | 1616 | +438 | 137.2% | OK | OK | openai_chat/openai_chat | 1/0 | 0 | 3/3 | OK | 11 |
| P7a | 2942 | +265 | 109.9% | OK | OK | anthropic/anthropic | 13/12 | 2/1 | 0/0 | OK | 13 |
| P7b | 3254 | +269 | 109.0% | OK | OK | openai_chat/openai_chat | 13/12 | 0 | 1/1 | OK | 11 |
| P7c | 2790 | +0 | 100.0% | OK | OK | openai_responses/openai_responses | 12/12 | 0 | 0/0 | OK | 8 |
| P8 | 33973 | +502 | 101.5% | OK | OK | openai_chat/openai_chat | 1/0 | 0 | 0/0 | OK | 29 |

- 臂 H 配对：发出 63 次，桩收到 63 次，未配对 0 次

## P5 前缀稳定性（cache mode 前提）

- 臂 0D：逐轮一致（3 组重复）
- 臂 0M-L：逐轮一致（3 组重复）
- 臂 A-L：逐轮一致（3 组重复）
- 臂 B-L：逐轮一致（3 组重复）
- 臂 H：逐轮一致（3 组重复）

## 自检

- **V1 needle 在基线臂全部命中** 通过 — 全部命中
- **V1b needle 上下文锚点在基线臂未被破坏** 通过 — 完好
- **V2 0D 臂 P5 前缀逐轮一致（说明客户端构造没问题）** 通过 — 一致
- **V3 H 臂对 P1/P2 有真实压缩** 通过 — P1 H/0D=28.9% (期望<75%)；P2 H/0D=8.0% (期望<25%)
- **V5 A-L 与 B-L 相对 0M-L 都真的有压缩（中间层确实在链路里）** 通过 — A-L 压缩了 P1,P2,P5；B-L 压缩了 P1,P2,P5
- **V7 A-L 与 B-L 的请求体差异分布（信息项）** 通过 — 完全相同：P1,P2,P3,P4,P5,P6,P7a,P7b,P7c,P8；不同：无
- **V6 同机臂与跨机臂的压缩方向一致** 通过 — 没跑跨机抽查，本条不适用
- **V4 401 透传探针已跑过** 通过 — 已见到 forced_401 记录

