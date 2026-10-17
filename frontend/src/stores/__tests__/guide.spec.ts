import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { listGuideProgress, resetGuideProgress, saveGuideProgress } from '@/api/guides'
import { useAuthStore } from '@/stores/auth'
import { useGuideStore } from '@/stores/guide'
import { LAYOUT_TOUR, findTour } from '@/guide/tours'
import { makeProfile } from '@/test/fixtures'
import { i18n } from '@/i18n'

vi.mock('@/api/guides', () => ({
  listGuideProgress: vi.fn(),
  saveGuideProgress: vi.fn(),
  resetGuideProgress: vi.fn(),
}))

const layoutVersion = findTour(LAYOUT_TOUR)!.version

function setup(perms: string[] = ['*']) {
  setActivePinia(createPinia())
  useAuthStore().setProfile(makeProfile(perms))
  return useGuideStore()
}

describe('guide store', () => {
  beforeEach(() => {
    vi.mocked(listGuideProgress).mockReset()
    vi.mocked(saveGuideProgress).mockReset()
    vi.mocked(resetGuideProgress).mockReset()
  })

  it('needs nothing until progress has loaded', async () => {
    const guide = setup()
    expect(guide.needs(LAYOUT_TOUR)).toBe(false)
    vi.mocked(listGuideProgress).mockRejectedValue(new Error('down'))
    await guide.load()
    expect(guide.needs(LAYOUT_TOUR)).toBe(false)

    vi.mocked(listGuideProgress).mockResolvedValue([])
    await guide.load()
    expect(guide.needs(LAYOUT_TOUR)).toBe(true)
  })

  it('treats an older version as unseen', async () => {
    const guide = setup()
    vi.mocked(listGuideProgress).mockResolvedValue([
      { guide_key: LAYOUT_TOUR, version: layoutVersion - 1, status: 'completed', updated_at: '' },
      { guide_key: 'search', version: 99, status: 'skipped', updated_at: '' },
    ])
    await guide.load()
    expect(guide.needs(LAYOUT_TOUR)).toBe(true)
    expect(guide.needs('search')).toBe(false)
  })

  it('starts a tour once and saves the result when it ends', async () => {
    const guide = setup()
    vi.mocked(listGuideProgress).mockResolvedValue([])
    vi.mocked(saveGuideProgress).mockImplementation(async (key, version, status) => ({
      guide_key: key,
      version,
      status: status ?? 'completed',
      updated_at: '2026-10-15T00:00:00Z',
    }))
    await guide.load()

    expect(guide.start(LAYOUT_TOUR)).toBe(true)
    expect(guide.running).toBe(true)
    expect(guide.steps.length).toBeGreaterThan(0)
    expect(guide.start('search')).toBe(false)

    await guide.end('skipped')
    expect(guide.running).toBe(false)
    expect(saveGuideProgress).toHaveBeenCalledWith(LAYOUT_TOUR, layoutVersion, 'skipped')
    expect(guide.progress[LAYOUT_TOUR]?.status).toBe('skipped')
    expect(guide.needs(LAYOUT_TOUR)).toBe(false)
  })

  it('keeps progress locally when saving fails', async () => {
    const guide = setup()
    vi.mocked(listGuideProgress).mockResolvedValue([])
    vi.mocked(saveGuideProgress).mockRejectedValue(new Error('down'))
    await guide.load()
    guide.start(LAYOUT_TOUR)
    await guide.end('completed')
    expect(guide.needs(LAYOUT_TOUR)).toBe(false)
  })

  it('refuses tours the user has no permission for or with nothing to show', async () => {
    const guide = setup(['search:use'])
    vi.mocked(listGuideProgress).mockResolvedValue([])
    await guide.load()
    expect(guide.start('assistant')).toBe(false)
    expect(guide.start('search')).toBe(false)
    expect(guide.start('nope')).toBe(false)
    expect(guide.running).toBe(false)
  })

  it('shows a running tour in the newly selected language', async () => {
    const guide = setup()
    vi.mocked(listGuideProgress).mockResolvedValue([])
    await guide.load()
    expect(guide.start(LAYOUT_TOUR)).toBe(true)
    const zhTitle = guide.steps[0]!.title
    const count = guide.steps.length
    i18n.global.locale.value = 'en'
    try {
      expect(guide.steps[0]!.title).not.toBe(zhTitle)
      expect(guide.steps.length).toBe(count)
      expect(guide.active?.key).toBe(LAYOUT_TOUR)
    } finally {
      i18n.global.locale.value = 'zh-CN'
    }
  })

  it('reset clears progress so every tour plays again', async () => {
    const guide = setup()
    vi.mocked(listGuideProgress).mockResolvedValue([
      { guide_key: LAYOUT_TOUR, version: layoutVersion, status: 'completed', updated_at: '' },
    ])
    vi.mocked(resetGuideProgress).mockResolvedValue(undefined)
    await guide.load()
    expect(guide.needs(LAYOUT_TOUR)).toBe(false)
    await guide.reset()
    expect(resetGuideProgress).toHaveBeenCalled()
    expect(guide.needs(LAYOUT_TOUR)).toBe(true)
  })
})
