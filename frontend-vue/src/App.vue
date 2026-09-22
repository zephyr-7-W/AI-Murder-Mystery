<template>
  <Home v-if="gameStore.page === 'home'"/>
  <Game v-else-if="gameStore.page === 'game'"/>
  <Result v-else-if="gameStore.page === 'result'"/>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted } from "vue"
import { useGameStore } from "@/stores/useGameStore"
import { useSettingsStore } from "@/stores/useSettingsStore"
import { connectWebSocket, sendAction, sessionIdFor, setCloseCallback, setMessageCallback } from "@/api/gameSocket"
import { playClick } from "@/utils/sound"
import Home from "@/views/Home.vue"
import Game from "@/views/Game.vue"
import Result from "@/views/Result.vue"
import type { WsMessage, GameState } from "@/types/game"

const gameStore = useGameStore()
const settingsStore = useSettingsStore()

function resumePing() {
  // select_character(null) 只是让服务端把当前整局状态回显一次，不产生多余消息
  sendAction({ action: "select_character", char_id: null })
}

onMounted(() => {
  settingsStore.init()

  // 按钮点击提示音（受开关控制）
  const onDocClick = (event: MouseEvent) => {
    const target = event.target as HTMLElement | null
    if (!settingsStore.sound) return
    if (target && target.closest("button")) playClick()
  }
  document.addEventListener("click", onDocClick)

  setMessageCallback((msg: WsMessage<GameState>) => {
    gameStore.updateServerMessage(msg)
  })
  setCloseCallback(() => {
    // 断线不弹窗打断游戏，交由 Game 页展示离线提示
    if (gameStore.page === "game") gameStore.serverAlive = false
  })

  const restored = gameStore.bootstrap()
  if (restored) {
    // 每个对局独立 session：断线/重启后能按 activeId 从服务端恢复同一局
    connectWebSocket(sessionIdFor(gameStore.activeId))
    // 等待服务端回显；2.5s 无回应视为该局已不在服务端（仅本地可查看）
    setTimeout(() => gameStore.markServerPingFailed(), 2500)
    if (gameStore.page === "game") resumePing()
  }

  onUnmounted(() => {
    document.removeEventListener("click", onDocClick)
  })
})
</script>
