<template>
  <div class="reading-controls">
    <button
      class="rc-btn"
      :title="settings.sound ? '关闭音效' : '开启音效'"
      @click="settings.toggleSound()"
    >{{ settings.sound ? '🔊' : '🔇' }}</button>
    <button
      class="rc-btn rc-font"
      :title="'切换字号（当前：' + settings.fontLabel + '）'"
      @click="settings.cycleFont()"
    >字 {{ settings.fontLabel }}</button>
    <button
      class="rc-btn"
      :title="settings.dark ? '切换浅色主题' : '切换夜间主题'"
      @click="settings.toggleTheme()"
    >{{ settings.dark ? '☀️' : '🌙' }}</button>
  </div>
</template>

<script setup lang="ts">
import { useSettingsStore } from "@/stores/useSettingsStore"

const settings = useSettingsStore()
</script>

<style scoped lang="scss">
.reading-controls {
  position: fixed;
  top: 12px;
  right: 14px;
  z-index: 220;
  display: flex;
  align-items: center;
  gap: 6px;
  background: rgba(30, 41, 59, 0.92);
  border: 1px solid rgba(255, 255, 255, 0.14);
  border-radius: 999px;
  padding: 4px 6px;
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.16);

  .rc-btn {
    border: none;
    background: rgba(255, 255, 255, 0.1);
    color: #e2e8f0;
    border-radius: 999px;
    font-size: 13px;
    padding: 5px 10px;
    cursor: pointer;
    &:hover { background: rgba(255, 255, 255, 0.22); }

    &.rc-font {
      font-size: 12px;
      font-weight: 700;
    }
  }
}
</style>
