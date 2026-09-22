<template>
  <div class="guide-mask" @click.self="done">
    <div class="guide-card">
      <header class="guide-head">
        <h3>🕵️ 破案流程速览</h3>
        <button class="guide-close" title="关闭" @click="done">✕</button>
      </header>

      <div class="guide-body">
        <p class="guide-lead">你是一名侦探，刚接到一桩离奇命案。按下面的节奏一步步接近真相：</p>
        <ol class="guide-steps">
          <li>
            <b>① 与嫌疑人对话</b>
            <span>点左侧卡片看完整档案，或按 💬 直接开聊。他们各有秘密与底线，话里有真有假。</span>
          </li>
          <li>
            <b>② 收集并解锁线索</b>
            <span>有效对话会解锁“调查线索”；把可疑的线索点开做标记（怀疑 / 排除 / ⭐），方便复盘。</span>
          </li>
          <li>
            <b>③ 在白板整理推理</b>
            <span>把线索与对话摘录丢进 🧩 推理白板，随手记时间线和疑点——别只靠脑子记。</span>
          </li>
          <li>
            <b>④ 最终指认凶手</b>
            <span>证据链成型后点 🔪 指认凶手，写下你的推理理由。系统会按线索完整度与理由质量打分。</span>
          </li>
        </ol>
        <p class="guide-note">小提示：每个 NPC 只在“聊得自然”时透露信息。追问矛盾之处，秘密会自己露馅。</p>
      </div>

      <footer class="guide-foot">
        <label class="guide-once">
          <input v-model="skipNext" type="checkbox" />
          之后不再自动弹出
        </label>
        <button class="guide-start" @click="done">开始调查 →</button>
      </footer>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from "vue"
import { useSettingsStore } from "@/stores/useSettingsStore"

const settings = useSettingsStore()
const skipNext = ref(true)
const emit = defineEmits<{ close: [] }>()

function done() {
  if (skipNext.value) settings.markGuideSeen()
  emit("close")
}
</script>

<style scoped lang="scss">
.guide-mask {
  position: fixed;
  inset: 0;
  z-index: 90;
  background: rgba(10, 12, 18, 0.62);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 18px;
  animation: guide-fade 0.18s ease;
}

.guide-card {
  --panel-bg: #ffffff;
  --panel-2: #f6f7fb;
  --text-1: #1f2937;
  --text-2: #475569;
  --muted: #8b93a7;
  --border: #e2e8f0;

  width: min(560px, 96vw);
  max-height: 90vh;
  overflow-y: auto;
  background: var(--panel-bg);
  border-radius: 16px;
  box-shadow: 0 24px 60px rgba(0, 0, 0, 0.35);
  display: flex;
  flex-direction: column;
  animation: guide-in 0.24s ease;

  .guide-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 16px 18px 10px;
    h3 { margin: 0; font-size: 18px; }
    .guide-close {
      background: var(--panel-2);
      border: 1px solid var(--border);
      color: var(--muted);
      border-radius: 50%;
      width: 28px;
      height: 28px;
      cursor: pointer;
      &:hover { color: #dc2626; }
    }
  }

  .guide-body {
    padding: 4px 18px 8px;
    .guide-lead { font-size: 13px; color: var(--text-2); margin: 4px 0 12px; }
    .guide-steps {
      margin: 0;
      padding: 0;
      list-style: none;
      display: flex;
      flex-direction: column;
      gap: 10px;

      li {
        background: var(--panel-2);
        border: 1px solid var(--border);
        border-radius: 10px;
        padding: 10px 12px;
        display: flex;
        flex-direction: column;
        gap: 3px;
        b { font-size: 13.5px; color: var(--text-1); }
        span { font-size: 12.5px; line-height: 1.65; color: var(--text-2); }
      }
    }
    .guide-note {
      margin: 12px 0 0;
      font-size: 12px;
      line-height: 1.7;
      color: #92400e;
      background: #fffbeb;
      border: 1px solid #fde68a;
      border-radius: 8px;
      padding: 8px 10px;
    }
  }

  .guide-foot {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 12px 18px 16px;
    .guide-once {
      font-size: 12px;
      color: var(--muted);
      display: flex;
      align-items: center;
      gap: 6px;
      cursor: pointer;
    }
    .guide-start {
      background: #1f2937;
      color: #fff;
      border: none;
      border-radius: 9px;
      padding: 10px 20px;
      font-size: 13.5px;
      font-weight: 700;
      cursor: pointer;
      &:hover { background: #111827; }
    }
  }
}

html[data-theme="dark"] .guide-card {
  --panel-bg: #1a1e28;
  --panel-2: #232835;
  --text-1: #e5e7eb;
  --text-2: #c3cad6;
  --muted: #7d8698;
  --border: #343b4c;

  .guide-note {
    color: #fcd34d;
    background: rgba(180, 130, 20, 0.16);
    border-color: rgba(217, 180, 60, 0.4);
  }
  .guide-start {
    background: #6d28d9;
    &:hover { background: #5b21b6; }
  }
}

@keyframes guide-fade {
  from { opacity: 0; }
  to { opacity: 1; }
}
@keyframes guide-in {
  from { opacity: 0; transform: translateY(10px) scale(0.98); }
  to { opacity: 1; transform: translateY(0) scale(1); }
}
</style>
