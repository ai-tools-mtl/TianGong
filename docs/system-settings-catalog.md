# SystemSetting 键目录

> **机器生成，勿手编。** 来源：`apps/api/app` 下全部 `_KEY = "..."` 常量与`SystemSetting(key="...")` 内联字面量。
> 重新生成：`cd apps/api && uv run python -m scripts.gen_llm_usage`；CI 以 --check 模式校验新鲜度。

共 14 个键。

| 键名 | 定义位置 |
|---|---|
| `agent_hitl_config` | `apps/api/app/services/hitl_config_service.py:18` |
| `agent_turn_token_budget` | `apps/api/app/services/agent_budget_service.py:20` |
| `figure_style_presets` | `apps/api/app/services/figure_preset_service.py:21` |
| `ima_config` | `apps/api/app/services/ima_config_service.py:136` |
| `ima_enabled` | `apps/api/app/services/ima_config_service.py:112` |
| `llm_balance_status` | `apps/api/app/services/llm_balance_service.py:19` |
| `llm_balance_threshold` | `apps/api/app/services/llm_balance_service.py:20` |
| `llm_global_chat_config` | `apps/api/app/services/llm_config_service.py:457` |
| `llm_global_enabled` | `apps/api/app/services/llm_config_service.py:441` |
| `llm_lite_config` | `apps/api/app/services/llm_config_service.py:31` |
| `mcp_global_enabled` | `apps/api/app/services/mcp_config_service.py:24` |
| `mineru_config` | `apps/api/app/services/mineru_client.py:149` |
| `mineru_enabled` | `apps/api/app/services/mineru_client.py:130` |
| `vision_model_markers` | `apps/api/app/ai/vision.py:19` |
