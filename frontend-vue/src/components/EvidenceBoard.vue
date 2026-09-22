<template>
  <aside class="evidence-board">
    <header class="board-head">
      <div class="board-title">
        <h3>🧩 推理白板</h3>
        <span class="board-count">{{ store.board.length }} 条</span>
      </div>
      <button class="board-close" title="收起白板" @click="emit('close')">✕</button>
    </header>

    <p class="board-intro">把线索、对话摘录拖进来，或直接手写笔记，在这里拼出你的推理链。</p>

    <div class="board-add">
      <div
        class="drop-zone"
        :class="{ active: dropActive }"
        @dragover.prevent="onDragOver"
        @dragleave="onDragLeave"
        @drop.prevent="onDrop"
      >{{ dropActive ? '松开鼠标加入白板' : '📥 把线索 / 聊天摘录拖放到这里' }}</div>

      <div class="pick-row">
        <select v-model="pickId" @change="addPicked">
          <option value="" disabled>选择一条已解锁线索加入…</option>
          <option v-for="c in unlockedOptions" :key="c.id" :value="c.id">{{ c.text }}</option>
        </select>
        <button class="mini-btn" title="从剪贴板粘贴" @click="pasteClipboard">📋 粘贴</button>
      </div>

      <div class="note-row">
        <textarea
          v-model="draft"
          rows="2"
          maxlength="500"
          placeholder="手写你的推理笔记，Enter 新增"
          @keydown.enter.exact.prevent="addDraftNote"
        />
        <button class="btn-add-note" :disabled="!draft.trim()" @click="addDraftNote">＋ 加入笔记</button>
      </div>
    </div>

    <div class="board-list">
      <div v-if="sortedItems.length === 0" class="board-empty">
        白板还是空的。<br />线索悬停可点 📥 摘录，聊天气泡上也有 📌 按钮。
      </div>
      <div
        v-for="item in sortedItems"
        :key="item.id"
        class="board-item"
        :class="item.kind"
      >
        <div class="item-top">
          <span class="kind-tag">{{ kindLabel[item.kind] }}</span>
          <span v-if="item.source" class="item-source">{{ item.source }}</span>
          <span class="item-time">{{ fmtTime(item.at) }}</span>
        </div>
        <p class="item-text">{{ item.text }}</p>
        <div class="item-actions">
          <button class="remove" @click="store.removeBoardItem(item.id)">🗑 移除</button>
        </div>
      </div>
    </div>

    <footer class="board-foot">
      <span class="foot-hint">证据链越完整，最终指认的理由越有说服力。</span>
      <button class="btn-clear" @click="clearAll">{{ armed ? '再点一次确认清空' : '🧹 清空白板' }}</button>
    </footer>
  </aside>
</template>

<script setup lang="ts">
import { computed, ref } from "vue"
import { useGameStore } from "@/stores/useGameStore"
import type { BoardItem, ClueItem } from "@/types/game"

const store = useGameStore()
const emit = defineEmits<{ close: [] }>()

const draft = ref("")
const pickId = ref("")
const dropActive = ref(false)
const armed = ref(false)
let clearTimer: number | undefined

const kindLabel: Record<BoardItem["kind"], string> = {
  clue: "线索",
  quote: "对话摘录",
  note: "我的笔记",
}

const unlockedOptions = computed(() => store.clues.filter((c) => !c.locked))
const sortedItems = computed(() => [...store.board].sort((a, b) => b.at - a.at))

function clueSource(clue: ClueItem): string {
  return clue.kind === "public" ? "公开线索" : `调查线索·${clue.owner ?? ""}`
}

function add(kind: BoardItem["kind"], text: string, source?: string) {
  store.addBoardItem(kind, text, source)
}

function addPicked() {
  if (!pickId.value) return
  const clue = store.clueById(pickId.value)
  pickId.value = ""
  if (clue) add("clue", clue.text, clueSource(clue))
}

function addDraftNote() {
  const text = draft.value.trim()
  if (!text) return
  add("note", text, "手写笔记")
  draft.value = ""
}

async function pasteClipboard() {
  try {
    if (!navigator.clipboard?.readText) return
    const text = (await navigator.clipboard.readText()).trim()
    if (text) add("note", text, "剪贴板粘贴")
  } catch {
    // 剪贴板权限被拒时静默忽略，可在下方输入框直接 Ctrl+V
  }
}

function onDragOver() {
  dropActive.value = true
}
function onDragLeave() {
  dropActive.value = false
}
function onDrop(e: DragEvent) {
  dropActive.value = false
  const text = (e.dataTransfer?.getData("text/plain") ?? "").trim()
  if (!text) return
  const kind = e.dataTransfer?.getData("application/x-board-kind") === "clue" ? "clue" : "quote"
  const source = e.dataTransfer?.getData("application/x-board-source") || undefined
  add(kind, text, source)
}

function fmtTime(ts: number): string {
  const d = new Date(ts)
  const pad = (n: number) => String(n).padStart(2, "0")
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function clearAll() {
  if (!armed.value) {
    armed.value = true
    window.clearTimeout(clearTimer)
    clearTimer = window.setTimeout(() => (armed.value = false), 2600)
    return
  }
  armed.value = false
  window.clearTimeout(clearTimer)
  store.clearBoard()
}
</script>

<style scoped lang="scss">
.evidence-board {
  --panel-bg: #ffffff;
  --panel-2: #f8fafc;
  --panel-3: #f1f5f9;
  --text-1: #1f2937;
  --text-2: #475569;
  --text-3: #94a3b8;
  --border: #e2e8f0;
  --accent: #7c3aed;

  position: absolute;
  right: 14px;
  top: 14px;
  bottom: 14px;
  width: 360px;
  z-index: 45;
  background: var(--panel-bg);
  border-radius: 12px;
  box-shadow: 0 14px 44px rgba(15, 23, 42, 0.28);
  display: flex;
  flex-direction: column;
  padding: 14px;
  color: var(--text-1);
  animation: board-slide 0.18s ease;

  .board-head {
    display: flex;
    align-items: center;
    justify-content: space-between;

    .board-title {
      display: flex;
      align-items: baseline;
      gap: 8px;
      h3 { margin: 0; font-size: 16px; }
      .board-count { font-size: 11px; color: var(--text-3); }
    }
    .board-close {
      border: none;
      background: var(--panel-3);
      color: var(--text-2);
      border-radius: 50%;
      width: 26px;
      height: 26px;
      cursor: pointer;
      &:hover { background: #fee2e2; color: #b91c1c; }
    }
  }

  .board-intro { font-size: 11px; color: var(--text-3); margin: 8px 0 0; line-height: 1.5; }

  .board-add {
    margin-top: 10px;
    display: flex;
    flex-direction: column;
    gap: 7px;

    .drop-zone {
      border: 1.5px dashed var(--border);
      background: var(--panel-2);
      border-radius: 8px;
      color: var(--text-3);
      font-size: 12px;
      text-align: center;
      padding: 9px 6px;
      transition: 0.15s;
      &.active {
        border-color: var(--accent);
        background: rgba(124, 58, 237, 0.12);
        color: var(--accent);
      }
    }

    .pick-row {
      display: flex;
      gap: 6px;
      select {
        flex: 1;
        min-width: 0;
        border: 1px solid var(--border);
        background: var(--panel-bg);
        color: var(--text-1);
        border-radius: 7px;
        font-size: 11.5px;
        padding: 6px 8px;
      }
      .mini-btn {
        border: 1px solid var(--border);
        background: var(--panel-3);
        border-radius: 7px;
        font-size: 12px;
        padding: 0 9px;
        cursor: pointer;
        color: var(--text-2);
        &:hover { border-color: var(--accent); color: var(--accent); }
      }
    }

    .note-row {
      display: flex;
      flex-direction: column;
      gap: 6px;
      textarea {
        width: 100%;
        box-sizing: border-box;
        resize: none;
        border: 1px solid var(--border);
        border-radius: 7px;
        background: var(--panel-2);
        color: var(--text-1);
        font-size: 12px;
        line-height: 1.55;
        padding: 8px 9px;
        font-family: inherit;
        &:focus { outline: none; border-color: var(--accent); }
      }
      .btn-add-note {
        align-self: flex-end;
        background: var(--accent);
        color: #fff;
        border: none;
        border-radius: 7px;
        font-size: 12px;
        padding: 7px 13px;
        font-weight: 600;
        cursor: pointer;
        &:disabled { opacity: 0.45; cursor: not-allowed; }
      }
    }
  }

  .board-list {
    flex: 1;
    overflow-y: auto;
    margin-top: 10px;
    display: flex;
    flex-direction: column;
    gap: 8px;

    .board-empty {
      margin: auto;
      text-align: center;
      color: var(--text-3);
      font-size: 12px;
      line-height: 1.9;
    }

    .board-item {
      border: 1px solid var(--border);
      border-left: 3px solid #94a3b8;
      background: var(--panel-2);
      border-radius: 8px;
      padding: 8px 10px;
      animation: board-in 0.25s ease;

      &.clue { border-left-color: #0284c7; background: rgba(2, 132, 199, 0.07); }
      &.quote { border-left-color: #7c3aed; background: rgba(124, 58, 237, 0.07); }
      &.note { border-left-color: #d97706; background: rgba(217, 119, 6, 0.08); }

      .item-top {
        display: flex;
        align-items: center;
        gap: 7px;
        .kind-tag {
          font-size: 10px;
          font-weight: 700;
          padding: 1px 7px;
          border-radius: 999px;
          background: rgba(148, 163, 184, 0.22);
          color: var(--text-2);
          flex-shrink: 0;
        }
        .item-source {
          font-size: 10.5px;
          color: var(--text-3);
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
          flex: 1;
          min-width: 0;
        }
        .item-time { font-size: 10px; color: var(--text-3); flex-shrink: 0; }
      }

      .item-text {
        margin: 6px 0 4px;
        font-size: 12.5px;
        line-height: 1.65;
        color: var(--text-1);
        white-space: pre-line;
        word-break: break-word;
      }

      .item-actions {
        display: flex;
        justify-content: flex-end;
        .remove {
          border: none;
          background: transparent;
          color: var(--text-3);
          font-size: 11px;
          cursor: pointer;
          &:hover { color: #dc2626; }
        }
      }
    }
  }

  .board-foot {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    border-top: 1px solid var(--border);
    padding-top: 10px;
    margin-top: 10px;

    .foot-hint { font-size: 10.5px; color: var(--text-3); line-height: 1.5; }
    .btn-clear {
      flex-shrink: 0;
      border: 1px solid #fecaca;
      background: #fef2f2;
      color: #b91c1c;
      border-radius: 7px;
      font-size: 12px;
      padding: 7px 10px;
      cursor: pointer;
      &:hover { background: #fee2e2; }
    }
  }
}

html[data-theme="dark"] .evidence-board {
  --panel-bg: #191d26;
  --panel-2: #20242f;
  --panel-3: #2a2f3c;
  --text-1: #e5e7eb;
  --text-2: #cbd5e1;
  --text-3: #7d8698;
  --border: #343a4a;
}

@keyframes board-slide {
  from { opacity: 0; transform: translateX(10px); }
  to { opacity: 1; transform: translateX(0); }
}
@keyframes board-in {
  from { opacity: 0; transform: translateY(-4px); }
  to { opacity: 1; transform: translateY(0); }
}
</style>
