# Prefix cache：易变上下文的注入位置取舍（借鉴机制批次 A / 决策 D1）

Status: implemented
Date: 2026-08-27
Related: docs/superpowers/plans/2026-08-27-harness-mechanisms-adoption-plan.md（批次 A）

## Problem

全局 chat 走 DeepSeek（自动磁盘级前缀缓存，命中价约为未命中价的 1/10），但
`context_assembler` 把全部动态内容（已写章节、术语表、KB 检索结果、长期记忆、
意图指令）每轮拼进 SystemMessage——检索结果按 query 逐轮变化，等于每轮把整段
system prompt 打成 cache miss，长对话成本近乎全额。需要把「跨轮字节稳定的层」
与「逐轮易变的层」拆开：易变层随当轮用户消息注入、落库剥离，使
[system + history] 前缀连续轮次逐字节不变。

## Decision

方案 (b)：**落库剥离、仅发送时向当轮消息注入**。历史永远 = messages 表原文；
易变快照由 `build_turn_reminder` 渲染，经 `wrap_user_message` 包成
`<system-reminder>` 附着在当轮 user 消息尾部。DB 只存用户原始输入，每轮唯一
变化的是尾部新消息——与供应商前缀缓存模型完全对齐。灵魂测试钉死：
连续两轮装配的前缀逐字节一致（`tests/test_context_prefix_stability.py`）。

## Alternatives considered

- **(a) 易变快照整块落库进消息正文**：历史天然 append-only 字节稳定，实现最省。
  否决：旧检索快照会随每轮请求重复计费（即使 cache 命中也白占 context window），
  且过期知识滞留历史可能误导后续轮次。
- **(c) 会话首条统一注入**：快照落在首条消息即可长期稳定。否决：首条注入的是
  当时快照，第二轮起它就是过时信息——要么容忍过期，要么刷新（刷新即破坏前缀），
  两头不讨好。

## Consequences

- 实施 EV 偏差（有意为之，已记录在计划总览表）：**已写章节全文与术语表最终留在
  静态前缀**而非计划原文的易变块——它们在同一章节会话内通常字节不变且体积可观
  （前文层软上限 8000 字符），进前缀可按 1/10 命中价重复计费；被编辑时只付一次
  冷启动 miss。放易变块则每轮全价，得不偿失。分层规则由此固化为：
  「会话内大概率字节不变且体积大 → 静态层；几乎必然逐轮变化（query 相关）→ 快照」。
- resume 场景自动受益：快照随 checkpoint 中已包裹的历史消息还原首跑上下文，
  比旧实现（resume 时重建检索）更忠实。
- 观测依赖：`llm_call_log.token_prompt_cached` 列 + admin stats 每日趋势线
  （A-3）。验收目标 warm 会话命中率 ≥50%，待内测真实用量回填。
- 逐轮变化最大的来源（按-query 的记忆/KB 检索）仍是必然 miss，属预期，不再优化。
