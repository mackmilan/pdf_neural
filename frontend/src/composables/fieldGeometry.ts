import { normalizedFieldHeight } from '../stores/document'
import type { Field } from '../types'

export const ALIGNMENT_GUIDE_THRESHOLD = 4

export interface BoxLike {
  x: number
  y: number
  width: number
  height: number
}

export interface Guide {
  axis: 'x' | 'y'
  value: number
}

export function fieldTextAlign(field: Pick<Field, 'align'>): string {
  return ['left', 'center', 'justify', 'right'].includes(field.align as string) ? (field.align as string) : 'left'
}

export function fieldBoxEdges(box: BoxLike) {
  return {
    x: box.x,
    centerX: box.x + box.width / 2,
    right: box.x + box.width,
    y: box.y,
    centerY: box.y + box.height / 2,
    bottom: box.y + box.height,
  }
}

export function snapFieldBox(
  box: BoxLike,
  pageNumber: number,
  fields: Field[],
  ignoredIndex: number | null = null,
): { box: BoxLike; guides: Guide[] } {
  const guides: Guide[] = []
  const snapped = { ...box }
  const edges = fieldBoxEdges(box)
  const candidates = fields
    .filter((field, index) => index !== ignoredIndex && Number(field.page) === Number(pageNumber))
    .flatMap((field) => {
      const fieldEdges = fieldBoxEdges({ ...field, height: normalizedFieldHeight(field) })
      return [
        { axis: 'x' as const, value: fieldEdges.x },
        { axis: 'x' as const, value: fieldEdges.centerX },
        { axis: 'x' as const, value: fieldEdges.right },
        { axis: 'y' as const, value: fieldEdges.y },
        { axis: 'y' as const, value: fieldEdges.centerY },
        { axis: 'y' as const, value: fieldEdges.bottom },
      ]
    })
  let bestX: { delta: number; value: number } | null = null
  let bestY: { delta: number; value: number } | null = null
  for (const candidate of candidates) {
    const names = candidate.axis === 'x' ? (['x', 'centerX', 'right'] as const) : (['y', 'centerY', 'bottom'] as const)
    for (const name of names) {
      const delta = candidate.value - (edges as any)[name]
      if (Math.abs(delta) > ALIGNMENT_GUIDE_THRESHOLD) continue
      const best = candidate.axis === 'x' ? bestX : bestY
      if (!best || Math.abs(delta) < Math.abs(best.delta)) {
        const next = { delta, value: candidate.value }
        if (candidate.axis === 'x') bestX = next
        else bestY = next
      }
    }
  }
  if (bestX) {
    snapped.x += bestX.delta
    guides.push({ axis: 'x', value: bestX.value })
  }
  if (bestY) {
    snapped.y += bestY.delta
    guides.push({ axis: 'y', value: bestY.value })
  }
  return { box: snapped, guides }
}

export function snapHorizontalResize(
  box: BoxLike,
  pageNumber: number,
  direction: string,
  fields: Field[],
  ignoredIndex: number | null = null,
): { box: BoxLike; guides: Guide[] } {
  const activeEdge = direction.includes('w') ? box.x : box.x + box.width
  let best: { delta: number; value: number } | null = null
  fields
    .filter((field, index) => index !== ignoredIndex && Number(field.page) === Number(pageNumber))
    .forEach((field) => {
      const edges = fieldBoxEdges({ ...field, height: normalizedFieldHeight(field) })
      ;[edges.x, edges.centerX, edges.right].forEach((value) => {
        const delta = value - activeEdge
        if (Math.abs(delta) <= ALIGNMENT_GUIDE_THRESHOLD && (!best || Math.abs(delta) < Math.abs(best.delta))) {
          best = { delta, value }
        }
      })
    })
  if (!best) return { box, guides: [] }
  const match: { delta: number; value: number } = best
  if (direction.includes('w')) {
    return {
      box: { ...box, x: box.x + match.delta, width: box.width - match.delta },
      guides: [{ axis: 'x', value: match.value }],
    }
  }
  return {
    box: { ...box, width: box.width + match.delta },
    guides: [{ axis: 'x', value: match.value }],
  }
}

export function clearAlignmentGuides(doc: Document | null | undefined) {
  doc?.querySelectorAll('.pdf-alignment-guide').forEach((element) => element.remove())
}

export function showAlignmentGuides(page: HTMLElement, guides: Guide[]) {
  const doc = page.ownerDocument
  if (!doc) return
  clearAlignmentGuides(doc)
  guides.forEach((guide) => {
    const line = doc.createElement('div')
    line.className = 'pdf-alignment-guide'
    Object.assign(line.style, {
      position: 'absolute',
      zIndex: '88',
      pointerEvents: 'none',
      background: '#1677ff',
      boxShadow: '0 0 0 1px rgba(255,255,255,.75)',
      opacity: '.95',
    })
    if (guide.axis === 'x') {
      Object.assign(line.style, { left: `${guide.value}px`, top: '0', width: '1px', height: '100%' })
    } else {
      Object.assign(line.style, { left: '0', top: `${guide.value}px`, width: '100%', height: '1px' })
    }
    page.appendChild(line)
  })
}

export function closestFromEvent(event: Event, selector: string): Element | null {
  const target = event.target as Element | null
  if (target?.closest) return target.closest(selector)
  return (target?.parentElement?.closest(selector) as Element | null) || null
}

export function capturePointer(event: PointerEvent) {
  const target = event.target as Element & { setPointerCapture?: (id: number) => void }
  if (target?.setPointerCapture && event.pointerId !== undefined) {
    try {
      target.setPointerCapture(event.pointerId)
    } catch {
      /* ignore */
    }
  }
}
