import type { Page } from '@playwright/test'

/**
 * E2E API mock（优化计划批次 4）。
 *
 * 拦截所有 ${BASE}/api/v1/** 请求（BASE=e2e-api.test，见 playwright.config.ts），
 * 按「路径后缀 → 响应体」字典分发；未命中的路径默认 401（react-query 各查询
 * 走 error 分支渲染空态，页面骨架仍可断言）。
 */

export const USER = { id: 'u1', username: 'e2e', name: 'E2E 用户', role: 'user' }
export const ADMIN_USER = { id: 'a1', username: 'admin', name: '管理员', role: 'admin' }

export const PROJECT = {
  id: 'p1',
  title: '一种基于大模型的专利交底书生成方法',
  stage: 'drafting',
  status: 'active',
  progress_pct: 40,
  metadata: null,
  archived_at: null,
  tags: [],
  created_at: '2026-08-26T00:00:00Z',
  updated_at: '2026-08-26T00:00:00Z',
}

export const SECTION = {
  id: 's1',
  project_id: 'p1',
  order: 0,
  key: 'tech-field',
  title: '技术领域',
  content: { type: 'doc', content: [] },
  summary: null,
  status: 'drafting' as const,
  version: 1,
  created_at: '2026-08-26T00:00:00Z',
  updated_at: '2026-08-26T00:00:00Z',
}

/** 按天趋势 fixture（批次 2a 契约：恒 days 条、缺天补零）。 */
export const LLM_STATS = {
  days: 7,
  total_calls: 12,
  total_success: 11,
  total_failed: 1,
  avg_duration_ms: 820,
  total_prompt_tokens: 24000,
  total_completion_tokens: 9600,
  by_model: [
    {
      model: 'deepseek-chat', calls: 12, success: 11, failed: 1, avg_duration_ms: 820,
      prompt_tokens: 24000, completion_tokens: 9600,
    },
  ],
  by_user: [
    {
      user_id: 'u1', email: 'e2e@test.dev', calls: 12, success: 11, failed: 1,
      prompt_tokens: 24000, completion_tokens: 9600,
    },
  ],
  by_day: Array.from({ length: 7 }, (_, i) => ({
    date: `2026-08-${20 + i}`,
    calls: i < 5 ? 2 : 1,
    failed: i === 3 ? 1 : 0,
    prompt_tokens: 3000 + i * 100,
    completion_tokens: 1200 + i * 50,
  })),
}

/** 余额告警 fixture：low 态（批次 2b 契约）。 */
export const BALANCE_LOW = {
  threshold: 10,
  last: {
    supported: true,
    status: 'low' as const,
    provider: 'deepseek',
    amount: 3.2,
    currency: 'CNY',
    threshold: 10,
    is_low: true,
    probed_at: '2026-08-26T00:00:00Z',
    error: null,
  },
}

/**
 * 安装 API mock。overrides 的 key 是路径后缀（如 '/auth/me'），value 为响应体；
 * value 为 null 表示显式 401（如「未登录」场景的 /auth/me）。
 *
 * 兜底必须是 200 + 空数组而非 401：authFetch 对 401 会走「刷新→重试→强跳 /login」
 * 机制，未 mock 的查询若兜底 401 会把所有登录态测试整页拽回登录页（首轮实测踩坑）。
 */
export async function mockApi(page: Page, overrides: Record<string, unknown> = {}) {
  await page.route('**/api/v1/**', (route) => {
    const url = new URL(route.request().url())
    const path = url.pathname.replace(/^.*\/api\/v1/, '')

    if (path === '/auth/login') {
      return route.fulfill({ json: { access_token: 'e2e-token' } })
    }
    if (path in overrides) {
      const hit = overrides[path]
      if (hit === null) {
        return route.fulfill({ status: 401, json: { code: 'unauthorized', message: 'e2e 未登录' } })
      }
      return route.fulfill({ json: hit })
    }
    // 未命中：空列表（查询走空态渲染，页面骨架可断言）
    return route.fulfill({ json: [] })
  })
}
