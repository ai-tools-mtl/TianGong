'use client'

import { Maximize2, Minus, Plus, X } from 'lucide-react'
import { useEffect, useState } from 'react'

import { Button } from '@/components/ui/button'

/**
 * 图片放大浏览（Lightbox）。
 * 手写而非套 Dialog：需要自由缩放 + 超出视口滚动平移，Dialog 的居中
 * 约束反而碍事（且 shadcn CLI 装不了组件，本就手写，见 GOTCHAS F8）。
 * - 适配模式（默认）：等比缩进视口（max 92vw × 88vh）
 * - 缩放：+/- 步进 25%（50%–400%）；双击在 适配/2x 间切换；放大后容器滚动平移
 * - 关闭：Esc / 点击背景 / 右上角 X
 *
 * 缩放不用 transform（不撑滚动区，放大后没法平移），改为按「适配态实测
 * 尺寸 × scale」显式设 width/height，超出容器自然出滚动条。
 */

interface ImageLightboxProps {
  src: string
  alt?: string
  onClose: () => void
}

const MIN_SCALE = 0.5
const MAX_SCALE = 4
const STEP = 0.25

export function ImageLightbox({ src, alt = '', onClose }: ImageLightboxProps) {
  const [scale, setScale] = useState(1)
  const [base, setBase] = useState<{ w: number; h: number } | null>(null)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    const prevOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      window.removeEventListener('keydown', onKey)
      document.body.style.overflow = prevOverflow
    }
  }, [onClose])

  const zoom = (next: number) =>
    setScale(Math.min(MAX_SCALE, Math.max(MIN_SCALE, Math.round(next * 100) / 100)))

  return (
    <div
      className="fixed inset-0 z-[60] flex flex-col bg-black/85"
      role="dialog"
      aria-modal="true"
      aria-label="图片预览"
    >
      <div className="flex items-center gap-2 px-4 py-2.5">
        <span className="min-w-0 flex-1 truncate text-xs text-white/70" title={alt}>
          {alt || '图片预览'}
        </span>
        <div className="flex shrink-0 items-center gap-0.5">
          <Button
            variant="ghost"
            size="icon-xs"
            className="text-white/80 hover:bg-white/10 hover:text-white"
            aria-label="缩小"
            disabled={scale <= MIN_SCALE}
            onClick={() => zoom(scale - STEP)}
          >
            <Minus className="size-3.5" />
          </Button>
          <span className="w-11 text-center text-xs tabular-nums text-white/70">
            {Math.round(scale * 100)}%
          </span>
          <Button
            variant="ghost"
            size="icon-xs"
            className="text-white/80 hover:bg-white/10 hover:text-white"
            aria-label="放大"
            disabled={scale >= MAX_SCALE}
            onClick={() => zoom(scale + STEP)}
          >
            <Plus className="size-3.5" />
          </Button>
          <Button
            variant="ghost"
            size="icon-xs"
            className="text-white/80 hover:bg-white/10 hover:text-white"
            aria-label="适配窗口"
            title="适配窗口（缩放重置 100%）"
            onClick={() => setScale(1)}
          >
            <Maximize2 className="size-3.5" />
          </Button>
          <Button
            variant="ghost"
            size="icon-xs"
            className="text-white/80 hover:bg-white/10 hover:text-white"
            aria-label="关闭预览"
            onClick={onClose}
          >
            <X className="size-4" />
          </Button>
        </div>
      </div>
      {/* 背景点击关闭；图片自身 stopPropagation。放大超出后 overflow-auto 滚动平移 */}
      <div className="flex-1 overflow-auto" onClick={onClose}>
        <div className="flex min-h-full min-w-full items-center justify-center p-6">
          {/* eslint-disable-next-line @next/next/no-img-element -- 鉴权 blob/任意用户 URL，next/image 不适用 */}
          <img
            src={src}
            alt={alt}
            draggable={false}
            onLoad={(e) => {
              // 记录适配态实测渲染尺寸，后续缩放按它换算像素（只记一次）
              if (!base) {
                const el = e.currentTarget
                setBase({ w: el.clientWidth, h: el.clientHeight })
              }
            }}
            onClick={(e) => e.stopPropagation()}
            onDoubleClick={(e) => {
              e.stopPropagation()
              setScale((s) => (s === 1 ? 2 : 1))
            }}
            style={base && scale !== 1 ? { width: base.w * scale, height: base.h * scale } : undefined}
            className={`select-none rounded-md object-contain shadow-2xl ${
              !base || scale === 1 ? 'max-h-[88vh] max-w-[92vw]' : ''
            }`}
          />
        </div>
      </div>
    </div>
  )
}
