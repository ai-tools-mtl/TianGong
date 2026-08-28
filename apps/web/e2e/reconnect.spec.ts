import type { Server } from 'node:http'
import { createServer } from 'node:http'

import { expect, test } from '@playwright/test'

import { PROJECT, SECTION, USER } from './fixtures'

/**
 * 批次 D：SSE 断线自动接续。
 *
 * 为什么不用 page.route().fulfill() 模拟断流：fulfill 会**缓冲**整个响应体，
 * controller.error() 的流会让整条请求一起失败——start 锚点事件根本到不了浏览器。
 * 因此这里起一个真实本地 HTTP 服务（route.continue 改写 URL 到它），用
 * socket.destroy() 在写出部分帧后掐断连接——与生产环境的网断语义逐字节等价。
 *
 * 断言：
 * 1) 面板凭 start 事件锚点自动发起且仅发起一次 resume（不无限重试）；
 * 2) resume 流的 done 权威全文替换生效，UI 渲染完整文本；
 * 3) 后端同款 start 事件先行（message_id/thread_id/conversation_id 三元组）。
 */

// 动态回显式 CORS：Authorization 头的请求不吃通配符（fetch 规范），
// 必须显式回显 Origin 与 Access-Control-Request-Headers。
function corsHeaders(req: import('node:http').IncomingMessage): Record<string, string> {
  return {
    'Access-Control-Allow-Origin': req.headers.origin ?? '*',
    'Access-Control-Allow-Headers':
      (req.headers['access-control-request-headers'] as string | undefined)
      ?? req.headers.authorization?.split(',')[0] ?? 'authorization, content-type',
    'Access-Control-Allow-Methods': 'GET,POST,PATCH,PUT,DELETE,OPTIONS',
    'Access-Control-Allow-Credentials': 'true',
  }
}

const json = (req: import('node:http').IncomingMessage,
              res: import('node:http').ServerResponse, body: unknown): void => {
  res.writeHead(200, { 'Content-Type': 'application/json', ...corsHeaders(req) })
  res.end(JSON.stringify(body))
}

async function startMockOrigin(mode: 'disconnect' | 'steady' = 'disconnect'): Promise<
  { server: Server; port: number; resumeCalls: () => number }
> {
  // per-test 计数（同文件多用例共用 worker 进程，模块级变量会跨用例串数）
  let resumeCalls = 0
  const server = createServer((req, res) => {
    // continue() 改写后浏览器仍按原始跨域 URL 判定，须带 CORS 头；Authorization 触发预检
    if (req.method === 'OPTIONS') {
      res.writeHead(204, corsHeaders(req))
      return res.end()
    }
    const path = (req.url ?? '').split('?')[0]
    if (path === '/api/v1/auth/me') return json(req, res, USER)
    if (path === '/api/v1/projects') return json(req, res, [PROJECT])
    if (path === '/api/v1/projects/p1') return json(req, res, PROJECT)
    if (path === '/api/v1/projects/p1/sections') return json(req, res, [SECTION])
    if (path === '/api/v1/sections/s1') return json(req, res, SECTION)
    if (path === '/api/v1/sections/s1/messages') {
      // 会话回填后会拉取落库消息（与生产一致）：最终 assistant 全文必须还在
      const q = new URL(req.url ?? '/', 'http://x').searchParams.get('conversation_id')
      return json(req, res, q === 'conv-1'
        ? [{ id: 'msg-asst-9', role: 'assistant', content: '你好世界，恢复完成',
             meta: null, created_at: '2026-08-27T00:00:00Z' }]
        : [])
    }
    if (path === '/api/v1/sections/s1/conversations') return json(req, res, [])
    if (path === '/api/v1/sections/s1/chat') {
      // start（锚点）→ token；disconnect 模式随后掐断 socket（真·网络断开），
      // steady 模式持续慢速输出并保持连接（供「主动停止」用例点停止）。
      res.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache', ...corsHeaders(req) })
      res.write(`event: start\ndata: ${JSON.stringify({
        message_id: 'msg-turn-9', thread_id: 'msg-turn-9', conversation_id: 'conv-1',
      })}\n\n`)
      res.write(`event: token\ndata: ${JSON.stringify({ text: '你好' })}\n\n`)
      if (mode === 'disconnect') {
        setTimeout(() => res.socket?.destroy(), 150)
        return
      }
      let i = 0
      const timer = setInterval(() => {
        // 客户端 abort 后写已断 socket 不抛异常（write 返回 false），防御性兜住
        try {
          res.write(`event: token\ndata: ${JSON.stringify({ text: `第${++i}段` })}\n\n`)
        } catch { clearInterval(timer) }
      }, 300)
      setTimeout(() => { clearInterval(timer); try { res.end() } catch { /* 已断 */ } }, 8_000)
      return
    }
    if (path === '/api/v1/sections/s1/messages/msg-turn-9/resume') {
      resumeCalls += 1
      res.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache', ...corsHeaders(req) })
      res.write(`event: token\ndata: ${JSON.stringify({ text: '世界，恢复' })}\n\n`)
      res.write(`event: token\ndata: ${JSON.stringify({ text: '完成' })}\n\n`)
      res.write(`event: done\ndata: ${JSON.stringify({
        message_id: 'msg-asst-9', conversation_id: 'conv-1',
        title: null, content: '你好世界，恢复完成',
      })}\n\n`)
      res.end()
      return
    }
    res.writeHead(404)
    res.end('{}')
  })
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
  const addr = server.address()
  const port = typeof addr === 'object' && addr ? addr.port : 0
  return { server, port, resumeCalls: () => resumeCalls }
}

test('聊天流中途断网 → 自动 resume 接续 → 权威全文渲染', async ({ page }) => {
  const { server, port, resumeCalls } = await startMockOrigin()
  test.setTimeout(60_000)

  // 把构建期内联的 API 地址整体改写到本地真源（continue 保持原生流式转发）
  await page.route('**/api/v1/**', (route) => {
    const url = new URL(route.request().url())
    if (!url.hostname.includes('e2e-api.test')) return route.continue()
    return route.continue({ url: `http://127.0.0.1:${port}${url.pathname}${url.search}` })
  })

  try {
    await page.goto('/projects/p1')

    const input = page.getByPlaceholder(/问 AI/)
    await expect(input).toBeVisible({ timeout: 15_000 })
    await input.fill('画一下系统框图')
    await page.getByRole('button', { name: '发送' }).click()

    // 自动恢复请求确实发生
    await expect.poll(() => resumeCalls()).toBeGreaterThan(0)

    // resume 只自动发起一次（第二次断开才降级手动；本场景一次即成）
    await page.waitForTimeout(800)
    expect(resumeCalls()).toBeLessThanOrEqual(1)

    // done 权威全文整体替换后，UI 呈现完整文本
    await expect(page.getByText('你好世界，恢复完成')).toBeVisible({ timeout: 20_000 })
    // 断线提示出现过（通知区域），恢复成功提示可存在其一
  } finally {
    server.close()
  }
})

test('流式进行中用户主动停止 → 不触发自动 resume', async ({ page }) => {
  // 回归（批次 D 修复）：abort 触发的 AbortError 曾被 _consumeSSE 误包装为
  // StreamDisconnectedError，导致主动停止落入自动接续分支（误导性「正在自动恢复」
  // 提示 + resume 请求）。断言停止后两者都不发生。
  const { server, port, resumeCalls } = await startMockOrigin('steady')
  test.setTimeout(60_000)

  await page.route('**/api/v1/**', (route) => {
    const url = new URL(route.request().url())
    if (!url.hostname.includes('e2e-api.test')) return route.continue()
    return route.continue({ url: `http://127.0.0.1:${port}${url.pathname}${url.search}` })
  })

  try {
    await page.goto('/projects/p1')

    const input = page.getByPlaceholder(/问 AI/)
    await expect(input).toBeVisible({ timeout: 15_000 })
    await input.fill('随便写点什么')
    await page.getByRole('button', { name: '发送' }).click()

    // 流已在输出（start 锚点已到达、断线自动接续的前提条件已满足）
    await expect(page.getByText('你好')).toBeVisible({ timeout: 15_000 })

    // 流仍在进行时用户主动点停止
    await page.getByRole('button', { name: '停止' }).click()

    // 不弹「正在自动恢复」、不发起任何 resume 请求
    await expect(page.getByText('连接中断，正在自动恢复')).toHaveCount(0)
    await page.waitForTimeout(1_500)
    expect(resumeCalls()).toBe(0)
  } finally {
    server.close()
  }
})
