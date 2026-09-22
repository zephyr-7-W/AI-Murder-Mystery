<template>
  <aside class="timeline-panel">
    <header class="tp-head">
      <div class="tp-title">
        <h3>🕰️ 时间线视图</h3>
        <span class="tp-sub">{{ allRows.length }} 条记录 · {{ contradictions.length }} 处疑似矛盾</span>
      </div>
      <button class="tp-close" title="收起" @click="emit('close')">✕</button>
    </header>

    <div v-if="!store.state.story_details" class="tp-empty">
      剧情还没生成，先开始一局游戏。
    </div>

    <template v-else>
      <div v-if="contradictions.length" class="tp-contradictions">
        <div class="tp-con-head">🚩 疑似矛盾 · 同一时间点说法对不上</div>
        <div v-for="(group, gi) in contradictions" :key="gi" class="tp-con-item">
          <div class="tp-con-time">{{ group.timeDisplay }} 前后</div>
          <ul>
            <li v-for="row in group.rows" :key="row.id">
              <b>{{ row.speaker }}</b><span>{{ row.text }}</span>
            </li>
          </ul>
          <div class="tp-con-reason">💡 {{ group.reason }}</div>
        </div>
      </div>

      <div class="tp-toolbar">
        <div class="tp-filter">
          <button
            v-for="f in filters"
            :key="f.key"
            :class="{ on: filter === f.key }"
            @click="filter = f.key"
          >{{ f.label }}</button>
        </div>
        <span class="tp-legend">⭐ 重点 · 🚩 存疑</span>
      </div>

      <div class="tp-list">
        <div v-if="visibleRows.length === 0" class="tp-empty">
          还没有能放进时间线的记录。<br />和嫌疑人聊出行踪、去「现场调查」后会自动整理到这里。
        </div>
        <div
          v-for="row in visibleRows"
          :key="row.id"
          class="tp-row"
          :class="[row.kind, { marked: !!markOf(row) }]"
        >
          <div class="tp-time">{{ row.timeDisplay }}</div>
          <div class="tp-body">
            <div class="tp-meta">
              <span class="tp-chip" :class="row.kind">{{ kindLabel(row.kind) }}</span>
              <span class="tp-speaker">{{ row.speaker }}</span>
            </div>
            <p class="tp-text">{{ row.text }}</p>
            <div class="tp-actions">
              <button
                v-if="canConfront(row)"
                class="tp-mark confront"
                title="带着这句证词去找该嫌疑人追问"
                @click="onConfront(row)"
              >🎯 对质</button>
              <button
                class="tp-mark"
                :class="{ on: markOf(row) === 'important' }"
                @click="toggle(row, 'important')"
              >⭐ 重点</button>
              <button
                class="tp-mark flag"
                :class="{ on: markOf(row) === 'suspect' }"
                @click="toggle(row, 'suspect')"
              >🚩 存疑</button>
            </div>
          </div>
        </div>
      </div>

      <div class="tp-note-box">
        <div class="tp-note-title">
          📝 我的时间线备注
          <button class="tp-collapse" @click="noteCollapsed = !noteCollapsed">
            {{ noteCollapsed ? '展开' : '收起' }}
          </button>
        </div>
        <template v-if="!noteCollapsed">
          <div class="tp-note-input">
            <input
              v-model="noteText"
              placeholder="写下对不上的时间点，例如：管家说 21:00 在书房，但有人见他去过后院"
              @keydown.enter.prevent="addNote"
            />
            <button :disabled="!noteText.trim()" @click="addNote">添加</button>
          </div>
          <div v-if="store.timelineNotes.length === 0" class="tp-note-empty">还没有备注。</div>
          <div v-for="(note, index) in store.timelineNotes" :key="index" class="tp-note-item">
            <span>{{ note }}</span>
            <button class="tp-del" title="删除" @click="store.removeTimelineNote(index)">✕</button>
          </div>
        </template>
      </div>
    </template>
  </aside>
</template>

<script setup lang="ts">
import { computed, ref } from "vue"
import { useGameStore } from "@/stores/useGameStore"
import {
  buildTimelineRows,
  findContradictionGroups,
  type TimelineRow,
} from "@/utils/timeline"

const store = useGameStore()
const emit = defineEmits<{ close: [] }>()

type FilterKey = TimelineRow["kind"] | "all"
const filters: Array<{ key: FilterKey; label: string }> = [
  { key: "all", label: "全部" },
  { key: "anchor", label: "案情" },
  { key: "testimony", label: "证词/行踪" },
  { key: "investigation", label: "现场调查" },
  { key: "note", label: "我的笔记" },
]

const filter = ref<FilterKey>("all")
const noteText = ref("")
const noteCollapsed = ref(false)

function buildOptions() {
  return {
    story: store.state.story_details,
    characters: store.state.characters ?? [],
    chats: store.chats,
    investigations: store.investigations,
    timelineNotes: store.timelineNotes,
  }
}

const allRows = computed(() => buildTimelineRows(buildOptions()))
const contradictions = computed(() => findContradictionGroups(allRows.value))
const visibleRows = computed(() =>
  filter.value === "all"
    ? allRows.value
    : allRows.value.filter((row) => row.kind === filter.value),
)

function kindLabel(kind: TimelineRow["kind"]): string {
  return {
    anchor: "案情基准",
    testimony: "证词/行踪",
    investigation: "现场调查",
    note: "我的笔记",
  }[kind]
}

function markOf(row: TimelineRow): string | undefined {
  return store.timelineMarks[row.id]
}

function toggle(row: TimelineRow, mark: "important" | "suspect") {
  store.toggleTimelineMark(row.id, mark)
}

function shortQuote(text: string, max = 26): string {
  const clean = (text ?? "").replace(/[“”「」]/g, "").replace(/\s+/g, " ").trim()
  return clean.length > max ? clean.slice(0, max) + "…" : clean
}

/** 只对“某位活着的嫌疑人说过的证词”提供一键对质 */
function canConfront(row: TimelineRow): boolean {
  if (row.kind !== "testimony") return false
  return store.charIndexByName(row.speaker) !== null
}

function peersOf(row: TimelineRow): TimelineRow[] {
  if (row.minutes === null) return []
  return allRows.value.filter(
    (r) =>
      r.id !== row.id &&
      r.kind === "testimony" &&
      r.minutes !== null &&
      r.minutes === row.minutes &&
      r.speaker !== row.speaker,
  )
}

/** 一键对质：切到该嫌疑人并自动发一句“揪着矛盾追问”的话 */
function onConfront(row: TimelineRow) {
  if (!canConfront(row)) return
  const idx = store.charIndexByName(row.speaker)
  if (idx === null) return
  const peers = peersOf(row)
  const peer = peers[0]
  const peerIdx = peer ? store.charIndexByName(peer.speaker) : null
  let question: string
  if (peers.length > 0 && peer) {
    question =
      `等一下——${row.timeDisplay}前后，${peer.speaker}说「${shortQuote(peer.text)}」，` +
      `而你刚才说的是「${shortQuote(row.text)}」。你俩的说法对不上，当时你到底在哪、和谁在一起？`
  } else {
    question =
      `你刚才提到「${shortQuote(row.text)}」，可我觉得细节对不上——` +
      `${row.timeDisplay}前后你到底在哪、和谁在一起，能再仔细说一遍吗？`
  }
  store.confrontSuspect(idx, question, peerIdx, peer?.text ?? "")
  emit("close")
}

function addNote() {
  const text = (noteText.value ?? "").trim()
  if (!text) return
  store.addTimelineNote(text)
  noteText.value = ""
}
</script>

<style scoped lang="scss">
.timeline-panel {
  --tp-bg: #ffffff;
  --tp-2: #f6f8fb;
  --tp-3: #eef2f7;
  --tp-text: #1f2937;
  --tp-sub: #64748b;
  --tp-muted: #8a93a5;
  --tp-border: #e2e8f0;
  --tp-accent: #6d28d9;
  --tp-warn: #b45309;

  position: absolute;
  right: 14px;
  top: 14px;
  bottom: 14px;
  width: 470px;
  max-width: calc(100vw - 28px);
  z-index: 47;
  background: var(--tp-bg);
  border-radius: 12px;
  box-shadow: 0 14px 44px rgba(15, 23, 42, 0.28);
  display: flex;
  flex-direction: column;
  padding: 14px;
  color: var(--tp-text);
  animation: tp-slide 0.18s ease;

  .tp-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;

    .tp-title {
      display: flex;
      align-items: baseline;
      gap: 8px;
      min-width: 0;
      h3 { margin: 0; font-size: 16px; white-space: nowrap; }
      .tp-sub { font-size: 11px; color: var(--tp-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    }
    .tp-close {
      border: none;
      background: var(--tp-3);
      border-radius: 50%;
      width: 26px;
      height: 26px;
      cursor: pointer;
      color: var(--tp-sub);
      &:hover { background: #fee2e2; color: #b91c1c; }
    }
  }

  .tp-empty {
    margin: auto;
    text-align: center;
    color: var(--tp-muted);
    font-size: 12px;
    line-height: 1.9;
    padding: 20px 8px;
  }

  .tp-contradictions {
    margin: 10px 0;
    border: 1px solid #fecaca;
    background: #fef2f2;
    border-radius: 8px;
    padding: 9px 10px;

    .tp-con-head { font-size: 12px; font-weight: 800; color: #b91c1c; }
    .tp-con-item {
      margin-top: 8px;
      border-top: 1px dashed #fecaca;
      padding-top: 7px;
      .tp-con-time { font-size: 11.5px; font-weight: 800; color: #991b1b; }
      ul {
        margin: 5px 0 0;
        padding-left: 16px;
        li { font-size: 12px; color: #7f1d1d; line-height: 1.6;
          b { margin-right: 4px; }
          span { word-break: break-word; }
        }
      }
      .tp-con-reason { margin-top: 5px; font-size: 11.5px; color: #b45309; }
    }
  }

  .tp-toolbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    flex-wrap: wrap;
    margin-bottom: 8px;

    .tp-filter {
      display: flex;
      gap: 5px;
      flex-wrap: wrap;
      button {
        border: 1px solid var(--tp-border);
        background: var(--tp-2);
        color: var(--tp-sub);
        font-size: 11.5px;
        border-radius: 999px;
        padding: 4px 10px;
        cursor: pointer;
        &.on { background: var(--tp-accent); border-color: var(--tp-accent); color: #fff; }
      }
    }
    .tp-legend { font-size: 10.5px; color: var(--tp-muted); }
  }

  .tp-list {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 7px;
    border-top: 1px solid var(--tp-border);
    padding-top: 9px;

    .tp-row {
      display: flex;
      gap: 8px;
      border: 1px solid var(--tp-border);
      background: var(--tp-2);
      border-radius: 9px;
      padding: 8px 10px;
      transition: 0.15s;

      &.marked { box-shadow: 0 0 0 1px var(--tp-warn); }
      &.anchor { border-left: 3px solid #2563eb; }
      &.testimony { border-left: 3px solid #059669; }
      &.investigation { border-left: 3px solid #d97706; }
      &.note { border-left: 3px solid #a855f7; }

      .tp-time {
        flex-shrink: 0;
        width: 58px;
        font-size: 12px;
        font-weight: 800;
        color: var(--tp-accent);
        text-align: right;
        padding-top: 2px;
      }
      .tp-body { flex: 1; min-width: 0; }
      .tp-meta {
        display: flex;
        align-items: center;
        gap: 6px;
        .tp-chip {
          font-size: 10px;
          border-radius: 4px;
          padding: 1px 6px;
          font-weight: 700;
          &.anchor { background: #dbeafe; color: #1d4ed8; }
          &.testimony { background: #d1fae5; color: #047857; }
          &.investigation { background: #fef3c7; color: #b45309; }
          &.note { background: #f3e8ff; color: #7e22ce; }
        }
        .tp-speaker { font-size: 12px; font-weight: 700; color: var(--tp-sub); }
      }
      .tp-text {
        margin: 4px 0 6px;
        font-size: 12.5px;
        line-height: 1.65;
        color: var(--tp-text);
        word-break: break-word;
      }
      .tp-actions {
        display: flex;
        gap: 6px;
        .tp-mark {
          font-size: 10.5px;
          border: 1px solid var(--tp-border);
          background: #fff;
          color: var(--tp-sub);
          border-radius: 999px;
          padding: 2px 9px;
          cursor: pointer;
          &:hover { border-color: #f59e0b; }
          &.on { background: #fef3c7; border-color: #f59e0b; color: #b45309; font-weight: 700; }
          &.flag.on { background: #fee2e2; border-color: #ef4444; color: #b91c1c; }
          &.confront { background: #f0fdfa; border-color: #5eead4; color: #0f766e; font-weight: 700; }
          &.confront:hover { background: #ccfbf1; border-color: #14b8a6; }
        }
      }
    }
  }

  .tp-note-box {
    margin-top: 9px;
    border-top: 1px solid var(--tp-border);
    padding-top: 8px;
    max-height: 32%;
    overflow-y: auto;

    .tp-note-title {
      display: flex;
      align-items: center;
      justify-content: space-between;
      font-size: 12.5px;
      font-weight: 800;
      color: var(--tp-text);
      .tp-collapse {
        border: none;
        background: var(--tp-3);
        color: var(--tp-sub);
        font-size: 11px;
        border-radius: 6px;
        padding: 3px 8px;
        cursor: pointer;
      }
    }
    .tp-note-input {
      display: flex;
      gap: 6px;
      margin-top: 7px;
      input {
        flex: 1;
        min-width: 0;
        border: 1px solid var(--tp-border);
        background: var(--tp-2);
        color: var(--tp-text);
        border-radius: 7px;
        padding: 7px 9px;
        font-size: 12px;
      }
      button {
        flex-shrink: 0;
        border: none;
        background: var(--tp-accent);
        color: #fff;
        border-radius: 7px;
        padding: 0 12px;
        font-size: 12px;
        cursor: pointer;
        &:disabled { opacity: 0.5; cursor: not-allowed; }
      }
    }
    .tp-note-empty { margin-top: 6px; font-size: 11px; color: var(--tp-muted); }
    .tp-note-item {
      display: flex;
      align-items: flex-start;
      gap: 6px;
      margin-top: 6px;
      background: #faf5ff;
      border: 1px solid #e9d5ff;
      border-radius: 7px;
      padding: 6px 8px;
      font-size: 12px;
      color: #6b21a8;
      line-height: 1.5;
      span { flex: 1; word-break: break-word; }
      .tp-del {
        border: none;
        background: none;
        color: #a855f7;
        cursor: pointer;
        font-size: 11px;
        flex-shrink: 0;
        &:hover { color: #b91c1c; }
      }
    }
  }
}

:global(html[data-theme="dark"]) .timeline-panel {
  --tp-bg: #181c24;
  --tp-2: #20242f;
  --tp-3: #2a2f3c;
  --tp-text: #e5e7eb;
  --tp-sub: #cbd5e1;
  --tp-muted: #7d8698;
  --tp-border: #343a4a;

  .tp-close:hover { background: #3f1d22; color: #fca5a5; }
  .tp-contradictions {
    background: rgba(127, 29, 29, 0.2);
    border-color: #7f1d1d;
    .tp-con-head { color: #fca5a5; }
    .tp-con-item {
      border-top-color: #7f1d1d;
      .tp-con-time { color: #fecaca; }
      ul li { color: #fecaca; }
      .tp-con-reason { color: #fcd34d; }
    }
  }
  .tp-row {
    background: #1e232e;
    border-color: #2c323f;
    .tp-meta .tp-chip {
      &.anchor { background: #172554; color: #93c5fd; }
      &.testimony { background: #064e3b; color: #6ee7b7; }
      &.investigation { background: #3a2a10; color: #fcd34d; }
      &.note { background: #2e1065; color: #d8b4fe; }
    }
    .tp-text { color: #e5e7eb; }
    .tp-actions .tp-mark {
      background: #262c3a;
      border-color: #3a4152;
      color: #aab4c4;
      &.on { background: #3a2a10; border-color: #f59e0b; color: #fcd34d; }
      &.flag.on { background: #3f1d22; border-color: #ef4444; color: #fecaca; }
      &.confront { background: #0f2b29; border-color: #14b8a6; color: #99f6e4; font-weight: 700; }
      &.confront:hover { background: #0e3f3a; }
    }
  }
  .tp-note-box {
    .tp-note-title { color: #e5e7eb; }
    .tp-note-input input {
      background: #10141c;
      border-color: #3a4152;
      color: #e5e7eb;
    }
    .tp-note-item {
      background: #241a38;
      border-color: #4c1d95;
      color: #ddd6fe;
    }
  }
}

@keyframes tp-slide {
  from { opacity: 0; transform: translateX(14px); }
  to { opacity: 1; transform: translateX(0); }
}
</style>
