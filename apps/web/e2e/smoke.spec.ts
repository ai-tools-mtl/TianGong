import { expect, test } from '@playwright/test'

import {
  ADMIN_USER,
  BALANCE_LOW,
  LLM_STATS,
  PROJECT,
  SECTION,
  USER,
  mockApi,
} from './fixtures'

/**
 * E2E 冒烟（优化计划批次 4）：核心链路「改前端别把流程改断」的回归网。
 * API 全 mock（page.route），不起真后端；契约正确性由后端 1300+ 测试兜底。
 */

test('未登录访问根路径 → 重定向登录页', async ({ page }) => {
  await mockApi(page, { '/auth/me': null }) // 显式 401 → 跳 /login
  await page.goto('/')
  await expect(page).toHaveURL(/\/login/)
  await expect(page.getByRole('heading', { name: '登录' })).toBeVisible()
})

test('登录成功 → 进入工作台看到项目列表', async ({ page }) => {
  await mockApi(page, {
    '/auth/me': USER,
    '/projects': [PROJECT],
  })
  await page.goto('/login')
  await page.getByPlaceholder(/3-32 位/).fill('e2e')
  await page.getByPlaceholder('至少 8 位').fill('Pass1234!')
  await page.getByRole('button', { name: '登录' }).click()

  await expect(page).toHaveURL(/\/dashboard/)
  await expect(page.getByText(PROJECT.title)).toBeVisible()
})

test('项目详情页可达：章节渲染', async ({ page }) => {
  await mockApi(page, {
    '/auth/me': USER,
    '/projects/p1': PROJECT,
    '/projects/p1/sections': [SECTION],
  })
  await page.goto('/projects/p1')
  // 章节标题出现在大纲或编辑器（至少页面壳与章节名可见）
  await expect(page.getByText('技术领域').first()).toBeVisible({ timeout: 15_000 })
})

test('admin 统计页：趋势图渲染 + 低余额横幅（批次 2 回归）', async ({ page }) => {
  await mockApi(page, {
    '/auth/me': ADMIN_USER,
    '/admin/stats/llm': LLM_STATS,
    '/admin/llm-balance': BALANCE_LOW,
  })
  await page.goto('/admin/console/stats')

  // 趋势卡片 + 图例（recharts 渲染出的 SVG 文本）
  await expect(page.getByText('每日趋势')).toBeVisible()
  await expect(page.getByText('输入 tokens').first()).toBeVisible()

  // by_user token 列（批次 2a）：切到「按用户」tab
  await page.getByRole('tab', { name: '按用户' }).click()
  await expect(page.getByText('e2e@test.dev')).toBeVisible()

  // 低余额红横幅（批次 2b，console 布局层）
  await expect(page.getByText(/全局 LLM 账户余额低/)).toBeVisible()
})

test('登出后未登录守卫：普通用户进不了 admin', async ({ page }) => {
  await mockApi(page, {
    '/auth/me': USER,
  })
  await page.goto('/admin')
  // 非admin被重定向回 dashboard
  await expect(page).toHaveURL(/\/dashboard/, { timeout: 15_000 })
})
