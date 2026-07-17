'use client'

import { useCallback, useEffect, useRef } from 'react'

import { cn } from '@/lib/utils'

interface ResizeHandleProps {
  /** 拖拽时回调，参数为本次拖拽的像素增量（负=向左拖=变宽） */
  onResize: (delta: number) => void
  /** 拖拽方向：left = 手柄在目标左侧（向左拖增大），right = 手柄在目标右侧 */
  side?: 'left' | 'right'
  className?: string
}

/**
 * 可复用的拖拽分隔条。
 *
 * 用法：放在要调整宽度的面板边缘。
 * - side="left"：手柄在面板左边缘，鼠标向左拖 → delta 为负 → 面板变宽
 * - side="right"：手柄在面板右边缘，鼠标向右拖 → delta 为正 → 面板变宽
 *
 * 拖拽时给 body 加 cursor-col-resize + 禁止选中文本，松开恢复。
 */
export function ResizeHandle({ onResize, side = 'left', className }: ResizeHandleProps) {
  const draggingRef = useRef(false)
  const lastXRef = useRef(0)

  const handleMouseDown = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault()
      draggingRef.current = true
      lastXRef.current = e.clientX
      document.body.style.cursor = 'col-resize'
      document.body.style.userSelect = 'none'
    },
    [],
  )

  useEffect(() => {
    function handleMouseMove(e: MouseEvent) {
      if (!draggingRef.current) return
      const delta = e.clientX - lastXRef.current
      lastXRef.current = e.clientX
      // side="left" 时向左拖（delta 负）= 增宽，所以取反
      onResize(side === 'left' ? -delta : delta)
    }

    function handleMouseUp() {
      if (!draggingRef.current) return
      draggingRef.current = false
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }

    document.addEventListener('mousemove', handleMouseMove)
    document.addEventListener('mouseup', handleMouseUp)
    return () => {
      document.removeEventListener('mousemove', handleMouseMove)
      document.removeEventListener('mouseup', handleMouseUp)
    }
  }, [onResize, side])

  return (
    <div
      onMouseDown={handleMouseDown}
      className={cn(
        'group relative w-1 shrink-0 cursor-col-resize bg-border transition-colors hover:bg-primary/30',
        className,
      )}
    >
      {/* 加宽命中区域（不可见但好抓） */}
      <div className="absolute inset-y-0 -left-1 -right-1" />
    </div>
  )
}
