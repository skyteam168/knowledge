import { computed, ref, watchEffect } from 'vue'

export type ThemeMode = 'light' | 'dark' | 'system'

const STORAGE_KEY = 'ekb-theme'
const MODES: ThemeMode[] = ['light', 'dark', 'system']
const THEME_COLOR = { light: '#3370ff', dark: '#1c1d20' }

function readMode(): ThemeMode {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    return MODES.includes(saved as ThemeMode) ? (saved as ThemeMode) : 'system'
  } catch {
    return 'system'
  }
}

const media =
  typeof window !== 'undefined' && typeof window.matchMedia === 'function'
    ? window.matchMedia('(prefers-color-scheme: dark)')
    : null

const mode = ref<ThemeMode>(readMode())
const systemDark = ref(media?.matches ?? false)
media?.addEventListener('change', (event) => {
  systemDark.value = event.matches
})

const isDark = computed(
  () => mode.value === 'dark' || (mode.value === 'system' && systemDark.value),
)

watchEffect(() => {
  if (typeof document === 'undefined') return
  document.documentElement.classList.toggle('dark', isDark.value)
  document
    .querySelector('meta[name="theme-color"]')
    ?.setAttribute('content', THEME_COLOR[isDark.value ? 'dark' : 'light'])
})

function setThemeMode(next: ThemeMode): void {
  mode.value = next
  try {
    localStorage.setItem(STORAGE_KEY, next)
  } catch {
    // Private mode: the choice just isn't remembered.
  }
}

export function useTheme() {
  return { mode, isDark, setThemeMode }
}
