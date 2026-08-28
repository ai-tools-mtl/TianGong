import { expect, test } from '@playwright/test'

import { PROJECT, SECTION, USER, mockApi } from './fixtures'

/**
 * 批次 H：AI 输出反馈。
 * 历史回灌的 assistant 消息渲染 👍/👎 反馈条；点 👍 发起 POST feedback、
 * 提交后锁定为已反馈徽标。
 */

const CONV = {
  id: 'conv-1',
  title: '反馈会话',
  status: 'active' as const,
  created_at: '2026-08-27T00:00:00Z',
  updated_at: '2026-08-27T00:00:00Z',
}

const ASSISTANT_MSG = {
  id: 'msg-asst-1',
  role: 'assistant',
  content: '这是需要被反馈的 AI 回复。',
  meta: null,
  created_at: '2026-08-27T00:01:00Z',
}

test('assistant 消息反馈条：👍 提交 → POST 反馈 → 锁定徽标', async ({ page }) => {
  let feedbackPosted = false
  let postedBody: unknown = null

  await mockApi(page, {
    '/auth/me': USER,
    '/projects': [PROJECT],
    '/projects/p1': PROJECT,
    '/projects/p1/sections': [SECTION],
    '/sections/s1': SECTION,
    '/sections/s1/conversations': [CONV],
    '/sections/s1/messages': [ASSISTANT_MSG],
  })

  // mockApi 的兜底 route 先注册；feedback 的专属 route 后注册优先生效
  await page.route('**/api/v1/sections/s1/messages/msg-asst-1/feedback', (route) => {
    feedbackPosted = true
    postedBody = route.request().postDataJSON()
    return route.fulfill({ json: { ok: true, rating: 'good' } })
  })

  await page.goto('/projects/p1')

  // 历史回灌的 assistant 消息可见，反馈条随之渲染
  await expect(page.getByText('这是需要被反馈的 AI 回复。')).toBeVisible({ timeout: 15_000 })
  const goodBtn = page.getByRole('button', { name: '👍 有帮助' })
  await expect(goodBtn).toBeVisible()

  await goodBtn.click()

  // 请求发出 + 内容正确 + 提交后锁定为已反馈
  await expect.poll(() => feedbackPosted).toBe(true)
  expect(postedBody).toMatchObject({ rating: 'good' })
  await expect(page.getByText('👍 已反馈：有帮助')).toBeVisible({ timeout: 10_000 })
  await expect(goodBtn).toHaveCount(0)
})
