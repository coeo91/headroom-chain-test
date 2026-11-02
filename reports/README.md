# 上游报告

两份报告按各自项目的语言习惯写，不是同一份翻译：

| 文件 | 目标 | 语言 | 渠道 |
|---|---|---|---|
| `magpie-issue-draft.md` | `yetone/magpie` | 中文 | Issue |
| `headroom-show-and-tell-draft.md` | `headroomlabs-ai/headroom` | 英文 | Discussions → Show and tell |

语言选择的理由：

- magpie 的 issue 区中英文都有，但维护者是中文母语，近期 issue 里中文占多数，技术名词直接用英文不影响可读性。
- headroom 是英文项目，维护团队和 issue 区都是英文；那份纯 benchmark 若翻成中文反而增加沟通成本。

## 已发布

2026-11-02 发出，发布时均为 0 评论：

- magpie Issue #4899：https://github.com/yetone/magpie/issues/4899
- headroom Discussion #4612（Show and tell）：https://github.com/headroomlabs-ai/headroom/discussions/4612

为什么 headroom 走 Discussion 而不是 Issue：那边没有可报的缺陷，实测结果与文档一致，只有一份可复现的字节数；同时仓库里已有若干 cache_control 与 headroom_retrieve 相关讨论，再开 Issue 大概率被判重复。magpie 那条则是明确的兼容性缺陷（翻译档丢掉 body `metadata`、`X-Cid` 头、URL 查询串），走 Issue。

两份都没有真实请求、密钥或本地敏感信息，只用合成负载和本地假桩。本目录的文件是发布前的草稿，发布稿以链接为准。
