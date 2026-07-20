import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // 关闭 Next.js dev 模式右下/左下角的浮动指示器（Next.js 15+ 默认开启，
  // 16 升级为更显眼的 DevTools 浮窗）。仅在 dev 出现，build 后生产版本本就没有。
  devIndicators: false,
};

export default nextConfig;
