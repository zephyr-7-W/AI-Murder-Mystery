import { defineStore } from "pinia"

export type ThemeMode = "light" | "dark"
/** 0 标准 / 1 大字 / 2 特大 */
export type FontLevel = 0 | 1 | 2

const SETTINGS_KEY = "ai-murder-settings-v1"

interface StoredSettings {
  theme?: ThemeMode
  font?: FontLevel
  sound?: boolean
  guideSeen?: boolean
  sceneCollapsed?: boolean
}

function loadSettings(): StoredSettings {
  try {
    const raw = localStorage.getItem(SETTINGS_KEY)
    return raw ? (JSON.parse(raw) as StoredSettings) : {}
  } catch {
    return {}
  }
}

export const useSettingsStore = defineStore("settings", {
  state: () => {
    const saved = loadSettings()
    return {
      theme: (saved.theme === "dark" ? "dark" : "light") as ThemeMode,
      font: (saved.font ?? 1) as FontLevel,
      sound: saved.sound ?? true,
      guideSeen: Boolean(saved.guideSeen),
      sceneCollapsed: Boolean(saved.sceneCollapsed),
    }
  },

  getters: {
    dark: (s): boolean => s.theme === "dark",
    fontLabel(): string {
      return ["标准", "大字", "特大"][this.font] ?? "标准"
    },
    fontKey(): string {
      return String(this.font + 1)
    },
  },

  actions: {
    persist() {
      try {
        localStorage.setItem(
          SETTINGS_KEY,
          JSON.stringify({
            theme: this.theme,
            font: this.font,
            sound: this.sound,
            guideSeen: this.guideSeen,
            sceneCollapsed: this.sceneCollapsed,
          }),
        )
      } catch {
        // 存储不可用时静默降级
      }
    },

    apply() {
      const root = document.documentElement
      root.dataset.theme = this.theme
      root.dataset.font = this.fontKey
      document.body.style.colorScheme = this.theme
      this.persist()
    },

    init() {
      this.apply()
    },

    toggleTheme() {
      this.theme = this.theme === "dark" ? "light" : "dark"
      this.apply()
    },

    cycleFont() {
      this.font = ((this.font + 1) % 3) as FontLevel
      this.apply()
    },

    toggleSound() {
      this.sound = !this.sound
      this.persist()
    },

    markGuideSeen() {
      this.guideSeen = true
      this.persist()
    },

    toggleSceneCollapsed() {
      this.sceneCollapsed = !this.sceneCollapsed
      this.apply()
    },
  },
})
