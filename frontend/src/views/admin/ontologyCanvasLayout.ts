/** Column packing for Ontology Studio relation canvas (avoids fixed-row overlaps). */

export const CANVAS_COLS = 3
export const CANVAS_COL_GAP = 220
export const CANVAS_ORIGIN_X = 80
export const CANVAS_ORIGIN_Y = 48
export const CANVAS_ENTITY_H = 36
export const CANVAS_ATTR_H = 28
export const CANVAS_ATTR_GAP = 10
export const CANVAS_STACK_GAP = 28
export const CANVAS_PAD = 48

export interface CanvasLayoutEntity {
  id: string
  label: string
  local_name: string
}

export interface CanvasLayoutAttribute {
  id: string
  entity_id: string
  label: string
  name: string
}

export interface CanvasNode {
  id: string
  kind: 'entity' | 'attribute'
  label: string
  x: number
  y: number
  entityId?: string
}

export interface CanvasLayout {
  nodes: CanvasNode[]
  width: number
  height: number
}

export function entityStackHeight(attrCount: number): number {
  if (attrCount <= 0) return CANVAS_ENTITY_H
  return (
    CANVAS_ENTITY_H +
    CANVAS_STACK_GAP +
    attrCount * CANVAS_ATTR_H +
    Math.max(0, attrCount - 1) * CANVAS_ATTR_GAP
  )
}

/** True when two axis-aligned boxes overlap (inclusive edges count as overlap). */
export function boxesOverlap(
  a: { x: number; y: number; w: number; h: number },
  b: { x: number; y: number; w: number; h: number },
): boolean {
  return !(a.x + a.w <= b.x || b.x + b.w <= a.x || a.y + a.h <= b.y || b.y + b.h <= a.y)
}

export function nodeBox(node: CanvasNode): { x: number; y: number; w: number; h: number } {
  if (node.kind === 'entity') {
    return { x: node.x - 48, y: node.y - CANVAS_ENTITY_H / 2, w: 96, h: CANVAS_ENTITY_H }
  }
  return { x: node.x - 42, y: node.y - CANVAS_ATTR_H / 2, w: 84, h: CANVAS_ATTR_H }
}

export function layoutOntologyCanvas(
  entities: CanvasLayoutEntity[],
  attributes: CanvasLayoutAttribute[],
): CanvasLayout {
  const attrsByEntity = new Map<string, CanvasLayoutAttribute[]>()
  for (const a of attributes) {
    const list = attrsByEntity.get(a.entity_id)
    if (list) list.push(a)
    else attrsByEntity.set(a.entity_id, [a])
  }

  const colY = Array.from({ length: CANVAS_COLS }, () => CANVAS_ORIGIN_Y)
  const nodes: CanvasNode[] = []
  let maxX = 0
  let maxY = CANVAS_ORIGIN_Y

  entities.forEach((e, i) => {
    const col = i % CANVAS_COLS
    const mine = attrsByEntity.get(e.id) ?? []
    const x = CANVAS_ORIGIN_X + col * CANVAS_COL_GAP
    const y = colY[col]!
    nodes.push({
      id: `e:${e.id}`,
      kind: 'entity',
      label: e.label || e.local_name,
      x,
      y: y + CANVAS_ENTITY_H / 2,
    })
    mine.forEach((a, j) => {
      const attrY =
        y +
        CANVAS_ENTITY_H +
        CANVAS_STACK_GAP +
        j * (CANVAS_ATTR_H + CANVAS_ATTR_GAP) +
        CANVAS_ATTR_H / 2
      nodes.push({
        id: `a:${a.id}`,
        kind: 'attribute',
        label: a.label || a.name,
        x: x + 36,
        y: attrY,
        entityId: e.id,
      })
    })
    const blockH = entityStackHeight(mine.length)
    colY[col] = y + blockH + CANVAS_STACK_GAP * 2
    maxX = Math.max(maxX, x + 96)
    maxY = Math.max(maxY, y + blockH)
  })

  return {
    nodes,
    width: Math.max(720, maxX + CANVAS_PAD),
    height: Math.max(420, maxY + CANVAS_PAD),
  }
}
