<template>
  <div class="modal-mask" @click.self="emit('close')">
    <div class="dossier">
      <header class="dossier-head">
        <div class="avatar">{{ avatar }}</div>
        <div class="head-meta">
          <h3>{{ character.name }}</h3>
          <div class="tags">
            <span class="tag role">{{ roleText }}</span>
            <span class="tag" :class="meta.talked ? 'ok' : 'muted'">{{ meta.talked ? '已对话' : '未对话' }}</span>
            <button
              class="focus-btn"
              :class="{ active: meta.focus }"
              @click.stop="store.toggleFocus(character.name)"
            >{{ meta.focus ? '🔴 重点怀疑' : '标为重点怀疑' }}</button>
          </div>
        </div>
        <button class="close" @click="emit('close')">✕</button>
      </header>

      <div class="dossier-body">
        <section class="section">
          <h4>
            🪪 人物背景
            <button
              v-if="speechSupported"
              class="mini-tts"
              :class="{ reading: readingBg }"
              @click.stop="toggleReadBg"
            >{{ readingBg ? '⏹' : '🔊' }} 朗读</button>
          </h4>
          <p class="body-text">{{ character.backstory || '暂无更多背景描述。' }}</p>
        </section>

        <section class="section">
          <h4>🔗 与受害者关系</h4>
          <p class="body-text">{{ character.relation_to_victim || '与受害者关系尚未明确。' }}</p>
        </section>

        <section class="section">
          <h4>🕐 时间线与不在场证明</h4>
          <div v-if="story" class="case-timeline">
            <p>· 公开案发时间：{{ story.time_of_death }}，地点：{{ story.location_found }}</p>
            <p v-if="story.cause_of_death">· 死因：{{ story.cause_of_death }}（{{ story.murder_weapon }}）</p>
            <p class="hint-text">—— {{ character.name }} 的个人行踪与不在场证明需要你通过对话逐步套取，这里会随聊天记录沉淀：</p>
            <ul v-if="timelineNotes.length" class="timeline-notes">
              <li v-for="(n, i) in timelineNotes" :key="i">“{{ n }}”</li>
            </ul>
            <p v-else class="hint-text">（尚未掌握其个人时间线）</p>
          </div>
        </section>

        <section class="section">
          <h4>📌 名下线索 <span class="count">{{ unlockedClues.length }}/{{ ownedClues.length }}</span></h4>
          <div v-if="ownedClues.length" class="owned-clues">
            <div
              v-for="clue in ownedClues"
              :key="clue.id"
              class="owned-clue"
              :class="{ locked: clue.locked }"
            >
              <span class="lock">{{ clue.locked ? '🔒' : '🔓' }}</span>
              <span v-if="!clue.locked" class="txt">{{ clue.text }}</span>
              <span v-else class="placeholder">待调查 · 在对话里问中关键细节才会解锁</span>
            </div>
          </div>
          <p v-else class="hint-text">暂无独立线索条目。</p>
        </section>

        <section v-if="quoteNotes.length" class="section">
          <h4>🗒️ 对话摘录</h4>
          <ul class="quote-notes">
            <li v-for="(n, i) in quoteNotes" :key="i">{{ n }}</li>
          </ul>
        </section>
      </div>

      <footer class="dossier-foot">
        <button class="btn-ghost" @click="emit('close')">关闭</button>
        <button class="btn-talk" @click="emit('talk')">💬 开始对话调查</button>
      </footer>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from "vue"
import { useGameStore } from "@/stores/useGameStore"
import type { Character } from "@/types/game"
import { isSpeaking, isTtsSupported, speak, stop } from "@/utils/tts"

const props = defineProps<{ character: Character }>()
const emit = defineEmits<{ close: []; talk: [] }>()
const store = useGameStore()

const meta = computed(() => {
  const value = store.suspects[props.character.name]
  return value ?? { name: props.character.name, role: props.character.role, talked: false, focus: false, exchanges: 0 }
})
const story = computed(() => store.state.story_details)

const avatar = computed(() => {
  const code = Array.from(props.character.name).reduce((sum, ch) => sum + (ch.codePointAt(0) ?? 0), 0)
  return ["🕵️", "🎩", "🕶️", "🧣", "🪶", "🧢", "👒", "💼"][code % 8]
})
const roleText = computed(() => (props.character.role.toLowerCase() === "victim" ? "受害者" : "嫌疑人"))

const ownedClues = computed(() =>
  store.clues.filter((c) => c.owner === props.character.name),
)
const unlockedClues = computed(() => ownedClues.value.filter((c) => !c.locked))

const quoteNotes = computed(() => (store.notes[props.character.name] ?? []).slice(-6).reverse())
const timelineNotes = computed(() => quoteNotes.value.filter((n) => /时间|几点|回房|出来|出门|在场|看见|看到|来了|走了/.test(n)).slice(0, 4))

const speechSupported = isTtsSupported()
const readingBg = ref(false)
function toggleReadBg() {
  if (readingBg.value) {
    readingBg.value = false
    stop()
    return
  }
  readingBg.value = true
  speak(props.character.backstory, {
    onEnd: () => {
      readingBg.value = false
    },
  })
}

onBeforeUnmount(() => {
  if (isSpeaking()) stop()
})
</script>

<style scoped lang="scss">
.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 60;
  padding: 20px;
}

.dossier {
  width: min(560px, 96vw);
  max-height: 86vh;
  background: white;
  border-radius: 14px;
  display: flex;
  flex-direction: column;
  box-shadow: 0 20px 50px rgba(0, 0, 0, 0.25);
  overflow: hidden;

  .dossier-head {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 14px 16px;
    background: linear-gradient(135deg, #1e293b, #334155);
    color: white;

    .avatar {
      font-size: 30px;
    }

    .head-meta {
      flex: 1;
      h3 { margin: 0; font-size: 18px; }
      .tags {
        display: flex;
        align-items: center;
        gap: 6px;
        margin-top: 4px;
        flex-wrap: wrap;

        .tag {
          font-size: 11px;
          border-radius: 999px;
          padding: 2px 8px;
          background: rgba(255, 255, 255, 0.15);
          &.ok { background: #059669; }
          &.muted { background: #64748b; }
        }

        .focus-btn {
          border: none;
          background: transparent;
          color: #fca5a5;
          font-size: 11px;
          cursor: pointer;
          padding: 2px 6px;
          &.active { color: #f87171; font-weight: 700; }
        }
      }
    }

    .close {
      background: rgba(255,255,255,0.15);
      border: none;
      color: white;
      width: 28px;
      height: 28px;
      border-radius: 50%;
      cursor: pointer;
    }
  }

  .dossier-body {
    flex: 1;
    overflow-y: auto;
    padding: 12px 16px;

    .section {
      margin-bottom: 14px;

      h4 {
        margin: 0 0 6px;
        font-size: 13px;
        color: #334155;
        display: flex;
        align-items: center;
        gap: 6px;

        .mini-tts {
          border: 1px solid #c4b5fd;
          background: #f5f3ff;
          color: #6d28d9;
          border-radius: 999px;
          font-size: 10.5px;
          padding: 2px 8px;
          cursor: pointer;
          &:hover { background: #ede9fe; }
          &.reading { background: #6d28d9; color: #fff; }
        }

        .count { color: #94a3b8; font-weight: 500; }
      }

      .body-text {
        margin: 0;
        font-size: 13px;
        line-height: 1.6;
        color: #374151;
        white-space: pre-line;
        word-break: break-word;
      }

      .case-timeline {
        font-size: 12.5px;
        color: #475569;
        line-height: 1.6;

        p { margin: 3px 0; }
        .hint-text { color: #94a3b8; }
        .timeline-notes {
          padding-left: 18px;
          margin: 6px 0;
          li { color: #7c3aed; margin: 4px 0; }
        }
      }

      .owned-clues {
        display: flex;
        flex-direction: column;
        gap: 5px;

        .owned-clue {
          display: flex;
          gap: 6px;
          font-size: 12.5px;
          padding: 6px 8px;
          border-radius: 6px;
          background: #f8fafc;
          border: 1px solid #e2e8f0;
          color: #334155;
          line-height: 1.5;

          .lock { flex-shrink: 0; }
          .txt { word-break: break-word; }
          .placeholder { font-style: italic; }

          &.locked {
            color: #94a3b8;
            background: #f1f5f9;
            border-style: dashed;
          }
        }
      }

      .quote-notes {
        margin: 0;
        padding-left: 16px;
        li { font-size: 12.5px; color: #6d28d9; margin: 5px 0; }
      }
    }
  }

  .dossier-foot {
    display: flex;
    justify-content: flex-end;
    gap: 10px;
    padding: 12px 16px;
    border-top: 1px solid #e5e7eb;

    button {
      border: none;
      padding: 9px 18px;
      border-radius: 8px;
      font-size: 13px;
      font-weight: 600;
      cursor: pointer;
    }
    .btn-ghost { background: #f1f5f9; color: #475569; }
    .btn-talk { background: #2563eb; color: white; }
  }
}

:global(html[data-theme="dark"]) .dossier {
  background: #181c25;

  .dossier-body {
    h4 { color: #d7deea; }
    .count { color: #7d8698; }
    .body-text { color: #d1d7e2; }
    .case-timeline {
      color: #b6bfcd;
      .hint-text { color: #8a93a5; }
      .timeline-notes li { color: #c4b5fd; }
    }
    .owned-clues .owned-clue {
      background: #20242f;
      border-color: #323848;
      color: #d7deea;
      &.locked {
        color: #7d8698;
        background: #1a1e28;
      }
    }
    .quote-notes li { color: #c4b5fd; }
  }

  .dossier-foot {
    border-top-color: #2e3441;
    .btn-ghost { background: #2a2f3c; color: #cbd5e1; }
    .btn-talk { background: #1d4ed8; }
  }
}
</style>
