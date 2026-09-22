<template>
  <div
    class="clue-row"
    :class="[clue.mark, { unlocked: clue.kind === 'investigation' && !clue.locked }]"
    :data-tags="clue.tags.join(' ')"
    draggable="true"
    title="可拖入右侧推理白板"
    @dragstart="onDragStart"
  >
    <div class="clue-main" @click="store.setClueExpanded(clue.id, !clue.expanded)">
      <span class="mark-icon">{{ markIcon(clue.mark) }}</span>
      <span class="clue-snippet">{{ clue.text }}</span>
      <span class="chevron">{{ clue.expanded ? '▲' : '▼' }}</span>
    </div>

    <div v-if="clue.expanded" class="clue-detail">
      <p class="clue-full">{{ clue.text }}</p>
      <div class="clue-toolbar">
        <button
          class="tool"
          :title="'标记：' + markLabel(clue.mark)"
          @click="store.cycleClueMark(clue.id)"
        >{{ markLabel(clue.mark) }} {{ markIcon(clue.mark) }}</button>

        <button
          v-for="tag in allTags"
          :key="tag"
          class="tool tag"
          :class="{ on: clue.tags.includes(tag) }"
          @click="store.toggleClueTag(clue.id, tag)"
        >{{ tagChar(tag) }}</button>

        <span class="spacer"></span>
        <button class="tool" @click="copyText(clue.text)">{{ copied ? '✓ 已复制' : '📋 复制' }}</button>
        <button class="tool insert" @click="store.insertDraftText(clue.text)">📝 插入聊天</button>
        <button class="tool board" @click="addToBoard" title="摘录到推理白板">🧩 白板</button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from "vue"
import { useGameStore } from "@/stores/useGameStore"
import type { ClueItem, ClueTag } from "@/types/game"
import { markIcon, markLabel, tagChar } from "@/utils/clueUtils"

const props = defineProps<{ clue: ClueItem }>()
const store = useGameStore()
const copied = ref(false)
const allTags: ClueTag[] = ["star", "red", "green"]

function addToBoard() {
  const source = props.clue.kind === "public" ? "公开线索" : `调查线索·${props.clue.owner ?? ""}`
  store.addBoardItem("clue", props.clue.text, source)
}

function onDragStart(e: DragEvent) {
  const source = props.clue.kind === "public" ? "公开线索" : `调查线索·${props.clue.owner ?? ""}`
  e.dataTransfer?.setData("text/plain", props.clue.text)
  e.dataTransfer?.setData("application/x-board-kind", "clue")
  e.dataTransfer?.setData("application/x-board-source", source)
}

function copyText(text: string) {
  const done = () => {
    copied.value = true
    setTimeout(() => (copied.value = false), 1500)
  }
  if (navigator.clipboard?.writeText) {
    navigator.clipboard.writeText(text).then(done).catch(() => fallbackCopy(text))
  } else {
    fallbackCopy(text)
  }
}

function fallbackCopy(text: string) {
  try {
    const el = document.createElement("textarea")
    el.value = text
    document.body.appendChild(el)
    el.select()
    document.execCommand("copy")
    document.body.removeChild(el)
    copied.value = true
    setTimeout(() => (copied.value = false), 1500)
  } catch {
    // ignore
  }
}
</script>

<style scoped lang="scss">
.clue-row {
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #f9fafb;
  overflow: hidden;
  animation: clue-pop 0.35s ease;
  cursor: grab;
  &:active { cursor: grabbing; }

  &.viewed { border-left: 3px solid #3b82f6; }
  &.suspected { border-left: 3px solid #f59e0b; background: #fffbeb; }
  &.excluded { border-left: 3px solid #9ca3af; opacity: 0.6; }
  &.unlocked { border-left: 3px solid #16a34a; background: #f0fdf4; }

  .clue-main {
    display: flex;
    align-items: flex-start;
    gap: 6px;
    padding: 8px 9px;
    cursor: pointer;

    .mark-icon { flex-shrink: 0; font-size: 12px; }
    .clue-snippet {
      flex: 1;
      font-size: 12px;
      line-height: 1.5;
      color: #374151;
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
      word-break: break-word;
    }
    .chevron { flex-shrink: 0; font-size: 9px; color: #9ca3af; }
  }

  .clue-detail {
    border-top: 1px dashed #e2e8f0;
    padding: 8px 9px;

    .clue-full {
      margin: 0 0 8px;
      font-size: 12.5px;
      line-height: 1.7;
      color: #1f2937;
      word-break: break-word;
      white-space: pre-line;
    }

    .clue-toolbar {
      display: flex;
      align-items: center;
      gap: 6px;
      flex-wrap: wrap;

      .spacer { flex: 1; }
      .tool {
        border: 1px solid #d1d5db;
        background: white;
        border-radius: 6px;
        font-size: 11px;
        padding: 4px 7px;
        color: #4b5563;
        cursor: pointer;

        &:hover { border-color: #2563eb; color: #1d4ed8; }

        &.tag.on { background: #fef9c3; border-color: #eab308; }
        &.insert { background: #eff6ff; border-color: #93c5fd; color: #1d4ed8; }
        &.board { background: #f5f3ff; border-color: #c4b5fd; color: #6d28d9; }
      }
    }
  }
}

:global(html[data-theme="dark"]) .clue-row {
  background: #20242e;
  border-color: #2e3441;

  &.suspected { background: #332a12; border-left-color: #f59e0b; }
  &.unlocked { background: #0f2e1e; border-left-color: #22c55e; }
  &.viewed { border-left-color: #3b82f6; }
  &.excluded { border-left-color: #6b7280; }

  .clue-snippet { color: #d7dce5; }
  .clue-full { color: #e5e7eb; }
  .clue-detail { border-top-color: #2e3441; }
  .chevron { color: #6b7280; }

  .tool {
    background: #242a37;
    border-color: #3a4152;
    color: #cbd5e1;
    &:hover { border-color: #60a5fa; color: #93c5fd; }
    &.tag.on { background: #463b12; border-color: #ca8a04; }
    &.insert { background: #172554; border-color: #1d4ed8; color: #93c5fd; }
    &.board { background: #251f3d; border-color: #6d28d9; color: #c4b5fd; }
  }
}

@keyframes clue-pop {
  0% { opacity: 0; transform: translateY(-3px) scale(0.99); }
  100% { opacity: 1; transform: translateY(0) scale(1); }
}
</style>
