// frontend/src/stores/theme.ts
// UI theme state — persisted in sessionStorage so the choice survives page
// reloads within the same browser tab/session, and applied on initial mount
// (before Vue hydrates) to avoid a flash of the wrong theme.

import { ref, watch } from 'vue'

export type Theme = 'dark' | 'light'

const STORAGE_KEY = 'jarvis_ui_theme_v1'

function readStoredTheme(): Theme {
  try {
    const v = sessionStorage.getItem(STORAGE_KEY)
    if (v === 'light' || v === 'dark') return v
  } catch { /* sessionStorage disabled */ }
  return 'dark'  // safe default — matches existing app behavior
}

function writeStoredTheme(t: Theme) {
  try {
    sessionStorage.setItem(STORAGE_KEY, t)
  } catch { /* ignore */ }
}

function applyToDom(t: Theme) {
  if (typeof document === 'undefined') return
  // The .light class in main.css swaps the CSS variable palette.
  // Default (no class) = dark. .light = light.
  document.documentElement.classList.toggle('light', t === 'light')
}

// Reactive singleton
const theme = ref<Theme>(readStoredTheme())

// Apply the persisted value to the DOM immediately on import so the very
// first paint is correct (avoids the previous "always dark on reload" bug).
applyToDom(theme.value)

// Persist on every change
watch(theme, (t) => {
  writeStoredTheme(t)
  applyToDom(t)
})

function setTheme(t: Theme) {
  theme.value = t
}

function toggleTheme() {
  theme.value = theme.value === 'dark' ? 'light' : 'dark'
}

export function useTheme() {
  return { theme, setTheme, toggleTheme }
}
