<template>
  <div class="chat-panel">
    <div class="chat-header" v-if="activeCharacter">
      <div class="npc-head">
        <span class="npc-avatar">{{ avatarEmoji }}</span>
        <div class="npc-meta">
          <span class="npc-name">{{ activeCharacter.name }}</span>
          <span class="npc-status">{{ statusText }}</span>
        </div>
      </div>
      <span class="hint">像聊天一样套话，线索常常藏在随口的一句话里</span>
    </div>

    <div ref="historyRef" class="chat-history">
      <div v-if="transcript.length === 0" class="chat-empty">
        还没有对话记录。试着先聊聊近况，再慢慢绕到案情。
      </div>
      <div v-for="msg in transcript" :key="msg.id" class="msg" :class="msg.role">
        <div v-if="msg.role === 'system'" class="msg-system-inner">
          {{ msg.content }}
          <span v-if="msg.ts" class="ts light">{{ fmt(msg.ts) }}</span>
        </div>
        <template v-else>
          <div
            class="bubble"
            draggable="true"
            title="按住可拖到推理白板"
            @dragstart="onDragMsg($event, msg)"
          >
            <div class="bubble-text">{{ msg.content }}</div>
            <div class="bubble-meta">
              <span class="speaker">{{ msg.role === 'npc' ? activeCharacter?.name : '你' }}</span>
              <span class="meta-right">
                <button
                  class="pin-btn"
                  title="摘录到推理白板"
                  @click.stop="pinMessage(msg)"
                >📌</button>
                <span class="ts">{{ msg.ts ? fmt(msg.ts) : '' }}</span>
              </span>
            </div>
          </div>
        </template>
      </div>
      <div v-if="showTyping" class="msg npc typing-wrap">
        <div class="bubble typing-bubble">
          <span class="dots"><i></i><i></i><i></i></span>
          <span class="typing-text">{{ activeCharacter?.name }} 正在想怎么接话…</span>
        </div>
      </div>
    </div>

    <div v-if="store.aiError" class="ai-error">
      <span class="err-text">{{ store.aiError }}</span>
      <button class="err-dismiss" @click="store.dismissAiError()">知道了</button>
    </div>

    <div v-if="store.coaxHint" class="coax-hint">💬 {{ store.coaxHint }}</div>

    <div class="input-area">
      <textarea
        v-model="store.draftInput"
        rows="1"
        placeholder="输入你想说的话，Enter 发送，Shift+Enter 换行"
        @keydown.enter.exact.prevent="send"
        @keydown="autoGrow"
      />
      <div class="input-buttons">
        <button
          class="btn-ai"
          type="button"
          title="AI 顺着当前话题，帮你把一句能问出线索的话直接发出去"
          :disabled="!activeCharacter || store.aiBusy"
          @click="autoAsk"
        >🤖 AI帮我提问</button>
        <button class="btn-send" type="button" @click="send" :disabled="!canSend">发送</button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from "vue"
import { useGameStore } from "@/stores/useGameStore"
import { useSettingsStore } from "@/stores/useSettingsStore"
import { playMessage, playSend } from "@/utils/sound"
import type { BubbleMessage } from "@/types/game"

const store = useGameStore()
const settings = useSettingsStore()
const historyRef = ref<HTMLDivElement | null>(null)
let lastSeenId: string | undefined

const activeCharacter = computed(() => {
  const chars = store.state.characters ?? []
  const id = store.state.selected_character_id
  return id === null ? null : chars[id] ?? null
})
const transcript = computed(() => store.getTranscript(activeCharacter.value?.name ?? null))

const canSend = computed(() => (store.draftInput ?? "").trim().length > 0)
const showTyping = computed(
  () =>
    store.aiBusy &&
    transcript.value[transcript.value.length - 1]?.role === "player" &&
    activeCharacter.value !== null,
)

const avatarEmoji = computed(() => {
  const name = activeCharacter.value?.name ?? ""
  const code = name ? Array.from(name).reduce((sum, ch) => sum + ch.codePointAt(0)!, 0) : 0
  const faces = ["🕵️", "🎩", "🕶️", "🧣", "🪶", "🧢", "👒", "💼"]
  return faces[code % faces.length]
})

const statusText = computed(() => {
  const meta = activeCharacter.value ? store.suspects[activeCharacter.value.name] : undefined
  if (!meta) return "尚未对话"
  if (meta.talked) return `已对话 · ${meta.exchanges} 回合`
  return "尚未对话"
})

function fmt(ts?: number): string {
  if (!ts) return ""
  const d = new Date(ts)
  const pad = (n: number) => String(n).padStart(2, "0")
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function onDragMsg(e: DragEvent, msg: BubbleMessage) {
  e.dataTransfer?.setData("text/plain", msg.content)
  e.dataTransfer?.setData("application/x-board-kind", "quote")
  const source = msg.role === "npc" ? (activeCharacter.value?.name ?? "NPC") : "你（玩家）"
  e.dataTransfer?.setData("application/x-board-source", source)
}

function pinMessage(msg: BubbleMessage) {
  const source = msg.role === "npc" ? (activeCharacter.value?.name ?? "NPC") : "你（玩家）"
  store.addBoardItem("quote", msg.content, source)
}

function autoGrow() {
  const el = historyRef.value?.parentElement?.querySelector("textarea") as HTMLTextAreaElement | null
  if (!el) return
  el.style.height = "auto"
  el.style.height = `${Math.min(el.scrollHeight, 140)}px`
}

async function scrollBottom() {
  await nextTick()
  if (historyRef.value) historyRef.value.scrollTop = historyRef.value.scrollHeight
}

watch(() => transcript.value.length, scrollBottom)
watch(() => store.draftInput, autoGrow)
watch(showTyping, (on) => {
  if (on) void scrollBottom()
})

// 切换对话对象时，只同步“已见最后一条”而不播报历史记录
watch(
  () => activeCharacter.value?.name,
  () => {
    const messages = transcript.value
    lastSeenId = messages[messages.length - 1]?.id
  },
)

watch(
  () => transcript.value.length,
  () => {
    const messages = transcript.value
    const last = messages[messages.length - 1]
    if (!last || last.id === lastSeenId) return
    lastSeenId = last.id
    if (last.role === "npc" && settings.sound) playMessage()
  },
)

function send() {
  if (!canSend.value) return
  const text = (store.draftInput ?? "").trim()
  store.draftInput = ""
  if (settings.sound) playSend()
  store.sendPlayerMessage(text)
}

// “AI 帮我提问”：交给后端按当前话题拟句 + oracle 预检，点击即代玩家直接发出
function autoAsk() {
  if (!activeCharacter.value || store.aiBusy) return
  if (settings.sound) playSend()
  store.autoAsk()
}

onMounted(() => {
  const messages = transcript.value
  lastSeenId = messages[messages.length - 1]?.id
})
</script>

<style scoped lang="scss">
.chat-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;

  .chat-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding-bottom: 10px;
    border-bottom: 1px solid #e5e7eb;
    margin-bottom: 8px;

    .npc-head {
      display: flex;
      align-items: center;
      gap: 8px;

      .npc-avatar {
        width: 34px;
        height: 34px;
        border-radius: 50%;
        background: #eef2ff;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        font-size: 18px;
      }

      .npc-meta {
        display: flex;
        flex-direction: column;

        .npc-name {
          font-size: 15px;
          font-weight: 700;
          color: #1f2937;
        }
        .npc-status {
          font-size: 11px;
          color: #059669;
        }
      }
    }

    .hint {
      font-size: 11px;
      color: #9ca3af;
      text-align: right;
    }
  }

  .chat-history {
    flex: 1;
    overflow-y: auto;
    padding: 6px 2px 6px 0;
    display: flex;
    flex-direction: column;
    gap: 6px;

    .chat-empty {
      margin: auto;
      color: #9ca3af;
      font-size: 13px;
      text-align: center;
    }

    .msg {
      &.player {
        align-self: flex-end;
        max-width: 78%;
      }
      &.npc {
        align-self: flex-start;
        max-width: 82%;
      }
      &.system {
        align-self: center;
        width: 92%;
      }
    }

    .bubble {
      background: white;
      border: 1px solid #e5e7eb;
      border-radius: 12px;
      padding: 8px 11px;
      font-size: 13px;
      line-height: 1.55;
      color: #1f2937;
      word-break: break-word;

      .bubble-meta {
        display: flex;
        justify-content: space-between;
        gap: 10px;
        margin-top: 4px;

        .speaker {
          font-size: 11px;
          font-weight: 600;
          color: #6b7280;
        }
        .ts {
          font-size: 10px;
          color: #9ca3af;
        }
      }
    }

    .msg.player .bubble {
      background: #2563eb;
      border-color: #2563eb;
      color: white;
      border-bottom-right-radius: 3px;

      .bubble-meta .speaker { color: #dbeafe; }
      .bubble-meta .ts { color: #bfdbfe; }
    }

    .msg.npc .bubble {
      background: #f0fdf4;
      border-color: #86efac;
      border-bottom-left-radius: 3px;

      .bubble-meta .speaker { color: #047857; }
      .bubble-meta .ts { color: #6ee7b7; }
    }

    .msg-system-inner {
      font-size: 12px;
      color: #6b7280;
      background: #f3f4f6;
      border-radius: 8px;
      padding: 6px 10px;
      text-align: center;

      .ts.light { margin-left: 6px; font-size: 10px; }
    }
  }

  .suggestion-box {
    border: 1px dashed #c4b5fd;
    background: #f5f3ff;
    border-radius: 8px;
    padding: 8px 10px;
    margin-bottom: 8px;
    max-height: 150px;
    overflow-y: auto;

    .suggestion-title {
      font-size: 12px;
      color: #6d28d9;
      font-weight: 600;
      margin-bottom: 6px;
    }

    .suggestion-chip {
      display: block;
      width: 100%;
      text-align: left;
      font-size: 12px;
      color: #4c1d95;
      background: white;
      border: 1px solid #ddd6fe;
      border-radius: 6px;
      padding: 6px 8px;
      margin-bottom: 5px;
      cursor: pointer;

      &:hover {
        background: #ede9fe;
      }

      .sg-tag {
        display: inline-block;
        margin-right: 6px;
        font-size: 10px;
        font-weight: 700;
        line-height: 1;
        padding: 3px 6px;
        border-radius: 4px;
        background: #ede9fe;
        color: #6d28d9;
        vertical-align: middle;
      }
    }

    .suggestion-close {
      font-size: 11px;
      color: #6d28d9;
      background: none;
      border: none;
      cursor: pointer;
    }
  }

  .input-area {
    display: flex;
    flex-direction: column;
    gap: 8px;
    border-top: 1px solid #e5e7eb;
    padding-top: 10px;
    margin-top: 8px;

    textarea {
      width: 100%;
      box-sizing: border-box;
      resize: none;
      border: 1px solid #cbd5e1;
      border-radius: 8px;
      padding: 9px 12px;
      font-size: 13px;
      line-height: 1.5;
      font-family: inherit;
      max-height: 140px;
      overflow-y: auto;

      &:focus {
        outline: none;
        border-color: #0284c7;
        box-shadow: 0 0 0 3px rgba(2, 132, 199, 0.1);
      }
    }

    .input-buttons {
      display: flex;
      justify-content: flex-end;
      gap: 8px;
    }

    button {
      padding: 8px 14px;
      border: none;
      border-radius: 8px;
      font-weight: 600;
      font-size: 12px;
      cursor: pointer;
      transition: all 0.2s;

      &:disabled {
        opacity: 0.5;
        cursor: not-allowed;
      }
    }

    .btn-send {
      background: #0284c7;
      color: white;

      &:hover:not(:disabled) {
        background: #0369a1;
      }
    }

    .btn-ai {
      background: #7c3aed;
      color: white;

      &:hover:not(:disabled) {
        background: #6d28d9;
      }
    }
  }

  .bubble {
    animation: bubble-in 0.22s ease;

    .meta-right {
      display: inline-flex;
      align-items: center;
      gap: 6px;

      .pin-btn {
        display: none;
        align-items: center;
        justify-content: center;
        border: 1px solid #cbd5e1;
        background: #f8fafc;
        border-radius: 5px;
        font-size: 10px;
        line-height: 1;
        padding: 2px 5px;
        cursor: pointer;
        color: #475569;
        &:hover { background: #eef2ff; border-color: #7c3aed; }
      }
    }

    &:hover .pin-btn {
      display: inline-flex;
    }
  }
}

:global(html[data-theme="dark"]) .chat-panel {
  .chat-header { border-bottom-color: #2e3441; }
  .npc-avatar { background: #262b3a; }
  .npc-name { color: #f1f5f9; }
  .hint { color: #6b7280; }
  .chat-empty { color: #64748b; }

  .bubble {
    background: #242a37;
    border-color: #333b4b;
    color: #e5e7eb;

    .bubble-meta {
      .speaker { color: #aab4c4; }
      .ts { color: #7d8698; }
      .pin-btn { background: #2e3441; border-color: #454e60; color: #cbd5e1; }
    }
  }

  .msg.player .bubble {
    background: #1d4ed8;
    border-color: #1d4ed8;
    color: #fff;
    .bubble-meta .speaker { color: #dbeafe; }
    .bubble-meta .ts { color: #bfdbfe; }
  }

  .msg.npc .bubble {
    background: #0e3323;
    border-color: #166534;
    color: #e7f6ee;
    .bubble-meta .speaker { color: #6ee7b7; }
    .bubble-meta .ts { color: #4ade80; }
  }

  .msg-system-inner {
    color: #cbd5e1;
    background: #232837;
  }

  .suggestion-box {
    border-color: #4c1d95;
    background: #1f1a33;
    .suggestion-title { color: #c4b5fd; }
    .suggestion-chip {
      color: #ddd6fe;
      background: #282240;
      border-color: #3a3154;
      &:hover { background: #332a50; }

      .sg-tag {
        display: inline-block;
        margin-right: 6px;
        font-size: 10px;
        font-weight: 700;
        line-height: 1;
        padding: 3px 6px;
        border-radius: 4px;
        background: #3a3154;
        color: #c4b5fd;
        vertical-align: middle;
      }
    }
    .suggestion-close { color: #a78bfa; }
  }

  .input-area {
    border-top-color: #2e3441;
    textarea {
      background: #1a1e28;
      border-color: #3a4152;
      color: #e5e7eb;
      &::placeholder { color: #64748b; }
    }
  }
}

@keyframes bubble-in {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: translateY(0); }
}

.suggestion-hint {
  margin-bottom: 8px;
  background: #eef2ff;
  border: 1px dashed #c7d2fe;
  color: #4338ca;
  border-radius: 8px;
  padding: 8px 10px;
  font-size: 12px;
  line-height: 1.6;
}

.ai-error {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 8px;
  background: #fef2f2;
  border: 1px solid #fecaca;
  color: #991b1b;
  border-radius: 8px;
  padding: 7px 10px;
  font-size: 12px;

  .err-text { line-height: 1.5; }
  .err-dismiss {
    flex-shrink: 0;
    border: 1px solid #fca5a5;
    background: #fff;
    color: #b91c1c;
    border-radius: 6px;
    font-size: 11px;
    padding: 3px 8px;
    cursor: pointer;
  }
}

.coax-hint {
  margin-bottom: 8px;
  background: #fffbeb;
  border: 1px solid #fcd34d;
  color: #92400e;
  border-radius: 8px;
  padding: 7px 10px;
  font-size: 12px;
  line-height: 1.6;
  animation: bubble-in 0.2s ease;
}

.typing-wrap {
  .typing-bubble {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    background: #f8fafc;
    border-color: #e5e7eb;
    color: #64748b;

    .dots {
      display: inline-flex;
      gap: 3px;
      i {
        width: 5px;
        height: 5px;
        border-radius: 50%;
        background: #94a3b8;
        animation: dot-blink 1.1s infinite ease-in-out;
        &:nth-child(2) { animation-delay: 0.16s; }
        &:nth-child(3) { animation-delay: 0.32s; }
      }
    }
    .typing-text { font-size: 11.5px; }
  }
}

html[data-theme="dark"] .suggestion-hint {
  background: rgba(79, 70, 229, 0.12);
  border-color: #3730a3;
  color: #c7d2fe;
}

html[data-theme="dark"] .ai-error {
  background: rgba(127, 29, 29, 0.24);
  border-color: #7f1d1d;
  color: #fecaca;
  .err-dismiss {
    background: #1a1e28;
    border-color: #b91c1c;
    color: #fca5a5;
  }
}

html[data-theme="dark"] .coax-hint {
  background: rgba(120, 90, 20, 0.18);
  border-color: #a16207;
  color: #fde68a;
}

@keyframes dot-blink {
  0%, 60%, 100% { opacity: 0.35; transform: translateY(0); }
  30% { opacity: 1; transform: translateY(-2px); }
}
</style>
