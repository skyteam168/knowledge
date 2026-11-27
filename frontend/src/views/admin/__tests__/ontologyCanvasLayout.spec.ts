import { describe, expect, it } from 'vitest'
import {
  boxesOverlap,
  entityStackHeight,
  layoutOntologyCanvas,
  nodeBox,
} from '../ontologyCanvasLayout'

describe('ontologyCanvasLayout', () => {
  it('grows stack height with attribute count', () => {
    expect(entityStackHeight(0)).toBeLessThan(entityStackHeight(1))
    expect(entityStackHeight(1)).toBeLessThan(entityStackHeight(8))
  })

  it('does not overlap node boxes when entities have many attributes', () => {
    const entities = Array.from({ length: 9 }, (_, i) => ({
      id: `e${i}`,
      label: `Table${i}`,
      local_name: `t${i}`,
    }))
    const attributes = entities.flatMap((e, ei) =>
      Array.from({ length: 12 }, (_, j) => ({
        id: `a${ei}-${j}`,
        entity_id: e.id,
        label: `col${j}`,
        name: `col${j}`,
      })),
    )

    const { nodes, height } = layoutOntologyCanvas(entities, attributes)
    expect(nodes.length).toBe(9 + 9 * 12)
    expect(height).toBeGreaterThan(420)

    const boxes = nodes.map(nodeBox)
    for (let i = 0; i < boxes.length; i++) {
      for (let j = i + 1; j < boxes.length; j++) {
        expect(boxesOverlap(boxes[i]!, boxes[j]!)).toBe(false)
      }
    }
  })

  it('packs into three columns without colliding across tall stacks', () => {
    const entities = [
      { id: 'tall', label: 'Tall', local_name: 'tall' },
      { id: 'short', label: 'Short', local_name: 'short' },
      { id: 'mid', label: 'Mid', local_name: 'mid' },
      { id: 'next', label: 'Next', local_name: 'next' },
    ]
    const attributes = [
      ...Array.from({ length: 20 }, (_, j) => ({
        id: `t${j}`,
        entity_id: 'tall',
        label: `c${j}`,
        name: `c${j}`,
      })),
      { id: 's0', entity_id: 'short', label: 'c0', name: 'c0' },
    ]

    const { nodes } = layoutOntologyCanvas(entities, attributes)
    const tallEntity = nodes.find((n) => n.id === 'e:tall')!
    const nextEntity = nodes.find((n) => n.id === 'e:next')!
    // 4th entity shares column 0 with tall; must sit below tall's attributes
    expect(nextEntity.x).toBe(tallEntity.x)
    expect(nextEntity.y).toBeGreaterThan(
      Math.max(...nodes.filter((n) => n.entityId === 'tall').map((n) => n.y)),
    )
  })
})
