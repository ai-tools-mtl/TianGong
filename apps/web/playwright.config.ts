import { defineConfig } from '@playwright/test'

/**
 * E2E 冒烟配置（优化计划批次 4）。
 *
 * 设计决策 D2 落地形态：原计划写 MSW，实施改为 Playwright 原生 page.route()
 * 网络拦截——同样达成「mock API 层、不起真后端」，且零侵入应用代码
 * （MSW service-worker 模式需向应用注入 worker 脚本）。已知限制不变：
 * 后端契约变更 mock 不会自动红，靠后端 1300+ 测试兜底。
 *
 * API 域名用假主机 e2e-api.test（build 期 NEXT_PUBLIC_API_URL 内联）：
 * 所有 /api/v1 请求都被 fixtures.ts 的 route 拦截，永不出网。
 */
export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['github'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: 'http://localhost:3100',
  },
  webServer: {
    command: 'pnpm build && pnpm start',
    port: 3100,
    timeout: 240_000,
    reuseExistingServer: !process.env.CI,
    env: {
      NEXT_PUBLIC_API_URL: 'http://e2e-api.test',
      PORT: '3100',
    },
  },
  projects: [{ name: 'chromium', use: { browserName: 'chromium' } }],
})
