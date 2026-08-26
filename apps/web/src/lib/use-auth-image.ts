'use client'

import { useEffect, useState } from 'react'

import { authFetch } from '@/lib/api'

/**
 * 鉴权图片加载 hook：用 authFetch（复用 401 自动刷新）加载图片字节转 blob URL。
 *
 * 背景：附图 PNG 通过鉴权端点（走 cookie）返回。本地开发 web(3000) 与 api(8000)
 * 跨端口，<img src> 直接引用跨端口 URL 会 Failed to fetch（CORS/cookie 限制）。
 * 本 hook 复用 authFetch（已验证在同源 fetch 场景工作）加载，转 blob URL 供 <img>。
 *
 * 用法：const src = useAuthImage(rawUrl); return src ? <img src={src}/> : <占位/>
 *
 * version：内容版本号，变更时强制重新加载。regenerate 原地覆写同一附件
 * （URL 不变），须由调用方在覆写后 bump version 才会重新拉取。
 *
 * 返回：blob URL（成功）/ null（加载中或失败）。
 */
export function useAuthImage(
  rawSrc: string | null | undefined,
  version?: number,
): string | null {
  const [blobUrl, setBlobUrl] = useState<string | null>(null)

  useEffect(() => {
    if (!rawSrc) {
      setBlobUrl(null)
      return
    }
    let revoked = false
    let createdUrl: string | null = null

    // authFetch 接受相对路径（无 /api/v1 前缀）或完整 URL（含 http 前缀）
    authFetch(rawSrc)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        return res.blob()
      })
      .then((blob) => {
        if (revoked) return
        createdUrl = URL.createObjectURL(blob)
        setBlobUrl(createdUrl)
      })
      .catch(() => {
        if (!revoked) setBlobUrl(null)
      })

    return () => {
      revoked = true
      if (createdUrl) URL.revokeObjectURL(createdUrl)
    }
  }, [rawSrc, version])

  return blobUrl
}

