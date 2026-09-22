<template>
  <div class="victim-info">
    <div class="victim-head">
      <span class="victim-title">🕯️ 死者线索</span>
      <div class="head-actions">
        <button
          v-if="speechSupported"
          class="read-btn"
          :class="{ reading }"
          @click="toggleRead"
        >{{ reading ? '⏹ 停止' : '🔊 朗读' }}</button>
        <button class="close-btn" @click="emit('close')">✕ 收起</button>
      </div>
    </div>
    <div class="victim-content">{{ content }}</div>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, ref } from "vue"
import { isTtsSupported, isSpeaking, speak, stop } from "@/utils/tts"

const props = defineProps<{ content: string }>()
const emit = defineEmits<{ close: [] }>()

const reading = ref(false)
const speechSupported = isTtsSupported()

function toggleRead() {
  if (reading.value) {
    reading.value = false
    stop()
    return
  }
  reading.value = true
  speak(props.content, {
    onEnd: () => {
      reading.value = false
    },
  })
}

onBeforeUnmount(() => {
  if (isSpeaking()) stop()
})
</script>

<style scoped lang="scss">
.victim-info {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: linear-gradient(135deg, #fefce8 0%, #fef3c7 100%);
  border: 2px solid #d97706;
  border-radius: 8px;
  padding: 12px;

  .victim-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    margin-bottom: 10px;

    .victim-title {
      font-weight: 700;
      color: #92400e;
      font-size: 14px;
    }

    .head-actions {
      display: flex;
      align-items: center;
      gap: 6px;

      .read-btn,
      .close-btn {
        background: #fef3c7;
        border: 1px solid #d97706;
        color: #92400e;
        border-radius: 6px;
        cursor: pointer;
        padding: 4px 10px;
        font-size: 12px;
        font-weight: 600;
        &:hover { background: #fde68a; }
      }
      .read-btn.reading {
        background: #d97706;
        color: #fff;
      }
    }
  }

  .victim-content {
    flex: 1;
    overflow-y: auto;
    font-size: 13px;
    line-height: 1.7;
    color: #78350f;
    white-space: pre-line;
    word-break: break-word;
  }
}

:global(html[data-theme="dark"]) .victim-info {
  background: linear-gradient(135deg, #2a2310 0%, #33290f 100%);
  border-color: #a16207;

  .victim-title { color: #fcd34d; }
  .victim-content { color: #fce7a3; }
  .head-actions {
    .read-btn,
    .close-btn {
      background: rgba(255, 255, 255, 0.08);
      border-color: #a16207;
      color: #fcd34d;
      &:hover { background: rgba(255, 255, 255, 0.14); }
    }
    .read-btn.reading {
      background: #a16207;
      color: #fff;
    }
  }
}
</style>
