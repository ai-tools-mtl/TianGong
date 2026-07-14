# 计划 7b：管理后台 + LLM BYOK 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans.

**Goal:** 实现管理员后台（全局模板/Rubric 管理 + 用户列表 + LLM 配置）+ LLM BYOK（用户自配 key + 管理员全局开关），完成设计文档第 8 章的剩余能力。

**Architecture:** UserLLMConfig 模型（用户自有 LLM 配置，AES 加密）+ SystemSetting 模型（系统设置键值表）+ require_admin 依赖已有 + admin API + 前端管理页 + 设置页。

**Spec reference:** 设计文档 v1.5 第 8 章
- 8.2 管理员能力域 / 8.4 LLM Key 管理与 Provider 解析 / 8.3 数据可见性红线
- 三级 Provider 解析：用户自配 > 全局 > 报错引导

---

## 任务 0：UserLLMConfig + SystemSetting 模型 + 迁移

UserLLMConfig 存用户自配 LLM（api_key 加密）。SystemSetting 存全局开关与配置。

- 模型：UserLLMConfig（user_id unique, provider, base_url, api_key_encrypted, model, is_active）
- 模型：SystemSetting 已存在于计划 1，但只有表结构无种子。本任务加默认种子（llm_global_enabled=true）
- 迁移 + 种子

## 任务 1：LLM Provider 解析（三级优先级）

修改 `ai/llm_client.py` 和 `rag/embedding.py`，按三级优先级解析配置：
用户自配(is_active=True) → 全局(SystemSetting.llm_global_config) → 报错

## 任务 2：管理员 API + BYOK API

- `/api/v1/admin/users` GET 用户列表（聚合信息，不含私人数据）
- `/api/v1/admin/llm-config` GET/PUT 全局 LLM 配置 + 开关
- `/api/v1/settings/llm` GET/PUT 用户自有 LLM 配置
- `/api/v1/settings/llm/test` POST 测试连通性
- 所有 admin API 走 require_admin

## 任务 3：前端管理页 + 设置页

- `/admin` 管理后台（用户列表 + LLM 配置，仅 admin 可见）
- `/settings` 用户设置（LLM key 配置 + 测试）

## 任务 4：端到端验证
