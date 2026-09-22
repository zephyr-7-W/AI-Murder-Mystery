<template>
  <div class="narration-card" :class="{ folded: folded }">
    <div class="narration-head">
      <button class="fold-btn" type="button" @click="folded = !folded">
        <span class="title">📖 案情引入</span>
        <span class="fold-hint">{{ folded ? '展开全文 ▼' : '收起 ▲' }}</span>
      </button>
      <button
        v-if="speechSupported"
        class="read-btn"
        type="button"
        :class="{ reading }"
        @click.stop="toggleRead"
      >{{ reading ? '⏹ 停止朗读' : '🔊 朗读全文' }}</button>
    </div>

    <template v-if="folded">
      <p class="excerpt" @click="folded = false">{{ excerpt }}…</p>
    </template>
    <template v-else>
      <div class="content">{{ content }}</div>
      <p v-if="longText" class="fold-tip" @click="folded = true">▲ 收起大段案情</p>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from "vue"
import { isTtsSupported, speak, stop, isSpeaking } from "@/utils/tts"

const props = defineProps<{ content: string }>()

const folded = ref(false)
const reading = ref(false)
const speechSupported = isTtsSupported()
const longText = computed(() => props.content.length > 180)
const excerpt = computed(() => props.content.slice(0, 90))

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
.narration-card {
  --card-bg-a: #eff6ff;
  --card-bg-b: #e0f2fe;
  --card-border: #0284c7;
  --title: #0369a1;
  --body: #0c4a6e;
  --muted: #64748b;

  background: linear-gradient(135deg, var(--card-bg-a) 0%, var(--card-bg-b) 100%);
  border: 2px solid var(--card-border);
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 12px;
  box-shadow: 0 2px 4px rgba(2, 132, 199, 0.1);
  animation: narration-in 0.3s ease;

  .narration-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;

    .fold-btn {
      display: flex;
      align-items: baseline;
      gap: 10px;
      border: none;
      background: none;
      padding: 0;
      cursor: pointer;
      text-align: left;

      .title {
        font-weight: 700;
        color: var(--title);
        font-size: 14px;
      }
      .fold-hint {
        font-size: 11px;
        color: var(--muted);
      }
    }

    .read-btn {
      flex-shrink: 0;
      border: 1px solid var(--card-border);
      background: rgba(255, 255, 255, 0.65);
      color: var(--title);
      border-radius: 999px;
      font-size: 11.5px;
      padding: 4px 10px;
      cursor: pointer;

      &:hover { background: rgba(255, 255, 255, 0.9); }
      &.reading {
        background: var(--card-border);
        color: #fff;
      }
    }
  }

  .excerpt {
    margin: 8px 0 0;
    font-size: 12.5px;
    line-height: 1.6;
    color: var(--body);
    cursor: pointer;
  }

  .content {
    margin-top: 8px;
    font-size: 13px;
    line-height: 1.7;
    color: var(--body);
    white-space: pre-line;
  }

  .fold-tip {
    margin: 6px 0 0;
    font-size: 11px;
    color: var(--muted);
    cursor: pointer;
    text-align: right;
  }
}

:global(html[data-theme="dark"]) .narration-card {
  --card-bg-a: #0e2036;
  --card-bg-b: #12324e;
  --card-border: #1e5aa8;
  --title: #7cc0ff;
  --body: #d3e6fb;
  --muted: #7d96ad;

  .read-btn {
    background: rgba(255, 255, 255, 0.08);
    border-color: #1e5aa8;
  }
}

@keyframes narration-in {
  from { opacity: 0.4; }
  to { opacity: 1; }
}
</style>
