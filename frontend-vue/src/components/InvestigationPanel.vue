<template>
  <aside class="investigation-panel">
    <header class="panel-head">
      <div class="panel-title">
        <h3>🔎 现场调查</h3>
        <span class="panel-sub">共 {{ investigations.length }} 条调查记录</span>
      </div>
      <button class="panel-close" title="收起" @click="emit('close')">✕</button>
    </header>

    <div v-if="store.aiBusy" class="busy-line">
      <span class="busy-dot"></span>
      {{ store.aiBusyLabel || 'AI 正在生成调查结果…' }}
    </div>
    <div v-if="store.aiError" class="panel-error">
      {{ store.aiError }}
      <button @click="store.dismissAiError()">知道了</button>
    </div>

    <div class="targets-title">选择要主动调查的对象</div>
    <div class="target-grid">
      <button
        v-for="item in targets"
        :key="item.id"
        class="target-card"
        :class="{ done: item.done }"
        :disabled="store.aiBusy"
        @click="investigate(item)"
      >
        <span class="target-icon">{{ item.icon }}</span>
        <span class="target-name">{{ item.label }}</span>
        <span class="target-state">{{ item.done ? '✓ 已调查' : '调查' }}</span>
      </button>
      <p v-if="targets.length === 0" class="empty-hint">剧情还没生成，先开始一局游戏。</p>
    </div>

    <div class="records-title">📋 调查记录</div>
    <div class="record-list">
      <div v-if="investigations.length === 0" class="record-empty">
        还没有调查记录。<br />主动调查现场与物品，会得到对话里套不出的隐藏信息。
      </div>
      <div v-for="item in investigations" :key="item.id" class="record-item">
        <div class="record-top">
          <span class="record-target">🔍 {{ item.target }}</span>
          <span class="record-src">{{ item.source === 'local' ? '离线整理' : '现场勘察' }}</span>
          <span class="record-time">{{ fmtClock(item.at) }}</span>
        </div>
        <p class="record-text">{{ item.text }}</p>
        <div class="record-actions">
          <button @click="pinRecord(item)">📌 存入白板</button>
          <button class="danger" @click="store.removeInvestigation(item.id)">删除</button>
        </div>
      </div>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { computed } from "vue"
import { useGameStore } from "@/stores/useGameStore"
import { buildInvestigationTargets, type InvestigationTarget } from "@/utils/investigation"
import type { InvestigationRecord } from "@/types/game"

const store = useGameStore()
const emit = defineEmits<{ close: [] }>()

const investigations = computed(() => [...store.investigations].reverse())
const targets = computed<InvestigationTarget[]>(() =>
  buildInvestigationTargets(
    store.state.story_details,
    store.state.characters ?? [],
    store.investigations.map((i) => i.target),
  ),
)

function investigate(item: InvestigationTarget) {
  store.investigateTarget(item.target)
}

function pinRecord(item: InvestigationRecord) {
  store.addBoardItem("clue", item.text, `现场调查·${item.target}`)
}

function fmtClock(ts: number): string {
  const d = new Date(ts)
  const pad = (n: number) => String(n).padStart(2, "0")
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`
}
</script>

<style scoped lang="scss">
.investigation-panel {
  --panel-bg: #ffffff;
  --panel-2: #f6f8fb;
  --panel-3: #eef2f7;
  --text-1: #1f2937;
  --text-2: #475569;
  --muted: #8a93a5;
  --border: #e2e8f0;
  --accent: #b45309;

  position: absolute;
  right: 14px;
  top: 14px;
  bottom: 14px;
  width: 390px;
  z-index: 46;
  background: var(--panel-bg);
  border-radius: 12px;
  box-shadow: 0 14px 44px rgba(15, 23, 42, 0.28);
  display: flex;
  flex-direction: column;
  padding: 14px;
  color: var(--text-1);
  animation: panel-slide 0.18s ease;

  .panel-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    .panel-title {
      display: flex;
      align-items: baseline;
      gap: 8px;
      h3 { margin: 0; font-size: 16px; }
      .panel-sub { font-size: 11px; color: var(--muted); }
    }
    .panel-close {
      border: none;
      background: var(--panel-3);
      border-radius: 50%;
      width: 26px;
      height: 26px;
      cursor: pointer;
      color: var(--text-2);
      &:hover { background: #fee2e2; color: #b91c1c; }
    }
  }

  .busy-line {
    display: flex;
    align-items: center;
    gap: 7px;
    margin-top: 10px;
    font-size: 12px;
    color: var(--accent);
    background: rgba(180, 83, 9, 0.1);
    border: 1px solid rgba(217, 119, 6, 0.35);
    border-radius: 8px;
    padding: 8px 10px;
    .busy-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: var(--accent);
      animation: pulse 0.9s infinite;
    }
  }

  .panel-error {
    margin-top: 10px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 8px;
    background: #fef2f2;
    border: 1px solid #fecaca;
    color: #991b1b;
    border-radius: 8px;
    font-size: 12px;
    padding: 7px 9px;
    button {
      flex-shrink: 0;
      border: 1px solid #fca5a5;
      background: #fff;
      color: #b91c1c;
      border-radius: 6px;
      font-size: 11px;
      padding: 2px 7px;
      cursor: pointer;
    }
  }

  .targets-title,
  .records-title {
    margin: 12px 0 7px;
    font-size: 12.5px;
    font-weight: 800;
    color: var(--text-1);
  }

  .target-grid {
    display: flex;
    flex-direction: column;
    gap: 6px;
    .empty-hint { font-size: 12px; color: var(--muted); }

    .target-card {
      display: flex;
      align-items: center;
      gap: 8px;
      width: 100%;
      text-align: left;
      border: 1px solid var(--border);
      background: var(--panel-2);
      border-radius: 8px;
      padding: 8px 10px;
      cursor: pointer;
      font-size: 12.5px;
      color: var(--text-1);
      transition: 0.15s;

      &:hover:not(:disabled) {
        border-color: var(--accent);
        background: rgba(180, 83, 9, 0.08);
      }
      &:disabled { opacity: 0.55; cursor: wait; }
      &.done {
        opacity: 0.75;
        .target-state { color: #059669; font-weight: 700; }
      }
      .target-icon { font-size: 16px; }
      .target-name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
      .target-state { font-size: 11px; color: var(--muted); flex-shrink: 0; }
    }
  }

  .record-list {
    flex: 1;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 8px;
    margin-top: 4px;

    .record-empty {
      margin: auto;
      text-align: center;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.9;
    }

    .record-item {
      border: 1px solid var(--border);
      border-left: 3px solid #d97706;
      background: rgba(217, 119, 6, 0.06);
      border-radius: 8px;
      padding: 9px 10px;
      animation: item-in 0.22s ease;

      .record-top {
        display: flex;
        align-items: center;
        gap: 7px;
        font-size: 11px;
        color: var(--muted);
        .record-target { font-weight: 800; color: var(--accent); flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .record-time { flex-shrink: 0; }
      }
      .record-text {
        margin: 6px 0 5px;
        font-size: 12.5px;
        line-height: 1.7;
        color: var(--text-1);
        white-space: pre-line;
        word-break: break-word;
      }
      .record-actions {
        display: flex;
        justify-content: flex-end;
        gap: 6px;
        button {
          border: 1px solid #e2c28a;
          background: #fff8ec;
          color: #92400e;
          border-radius: 6px;
          font-size: 11px;
          padding: 3px 8px;
          cursor: pointer;
          &:hover { background: #fef3c7; }
          &.danger { border-color: #fecaca; background: #fef2f2; color: #b91c1c; }
        }
      }
    }
  }
}

html[data-theme="dark"] .investigation-panel {
  --panel-bg: #181c24;
  --panel-2: #20242f;
  --panel-3: #2a2f3c;
  --text-1: #e5e7eb;
  --text-2: #cbd5e1;
  --muted: #7d8698;
  --border: #343a4a;

  .panel-error {
    background: rgba(127, 29, 29, 0.22);
    border-color: #7f1d1d;
    color: #fecaca;
    button { background: #20242f; border-color: #b91c1c; color: #fca5a5; }
  }
  .record-item {
    background: rgba(217, 119, 6, 0.09);
    .record-actions button {
      border-color: #a16207;
      background: rgba(255, 255, 255, 0.06);
      color: #fcd34d;
    }
  }
}

@keyframes panel-slide {
  from { opacity: 0; transform: translateX(12px); }
  to { opacity: 1; transform: translateX(0); }
}
@keyframes item-in {
  from { opacity: 0; transform: translateY(-3px); }
  to { opacity: 1; transform: translateY(0); }
}
@keyframes pulse {
  0%, 100% { opacity: 0.35; }
  50% { opacity: 1; }
}
</style>
