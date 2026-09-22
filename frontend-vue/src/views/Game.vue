<template>
  <div class="game-wrapper">
    <header class="game-header">
      <div class="header-left">
        <button class="btn-back" @click="goBackHome" title="返回首页（自动存档）">🏠</button>
        <h1>🔍 Murder Mystery</h1>
        <span class="game-round">第{{ store.round }}局</span>
        <span v-if="lastSavedLabel" class="autosave">已自动存档 {{ lastSavedLabel }}</span>
      </div>
      <div class="header-right">
        <button class="icon-btn" :class="{ on: showEvidencePanel }" title="推理白板" @click="toggleBoard">
          🧩<span v-if="boardCount" class="badge">{{ boardCount }}</span>
        </button>
        <button class="icon-btn" :class="{ on: showInvestigationPanel }" title="现场调查：主动勘查地点与物品" @click="toggleInvestigation">🔎</button>
        <button class="icon-btn" :class="{ on: showTimelinePanel }" title="时间线视图：对照证词与行踪" @click="toggleTimeline">🕰️</button>
        <button class="icon-btn hint-btn" :class="{ empty: store.hintPoints <= 0 }" title="消耗 1 个提示点，获取一条微弱提示" @click="askHint">
          💡<span class="badge hint-count">{{ store.hintPoints }}</span>
        </button>
        <button class="icon-btn" :title="settings.sound ? '关闭音效' : '开启音效'" @click="settings.toggleSound()">{{ settings.sound ? '🔊' : '🔇' }}</button>
        <button class="icon-btn font-btn" :title="'切换字号（当前：' + settings.fontLabel + '）'" @click="settings.cycleFont()">字 {{ settings.fontLabel }}</button>
        <button class="icon-btn" :title="settings.dark ? '切换浅色主题' : '切换夜间主题'" @click="settings.toggleTheme()">{{ settings.dark ? '☀️' : '🌙' }}</button>
        <button class="help-btn" @click="showGuide = true">❓ 玩法</button>
        <button class="history-btn" @click="toggleHistory">📋 历史对局</button>
        <button class="new-btn" @click="goBackHome">＋ 新建对局</button>
      </div>
    </header>

    <div class="offline-banner" v-if="store.state.characters?.length && !store.serverAlive">
      ⚠️ 服务端暂未回应该局（可能已重启），当前只能查看本地存档；建议新建对局后再操作。
    </div>

    <div class="toast-layer">
      <TransitionGroup name="toast">
        <div v-for="t in toasts" :key="t.id" class="toast" :class="t.kind">{{ t.text }}</div>
      </TransitionGroup>
    </div>

    <div v-if="store.lastHint" class="hint-pop">
      <div class="hint-pop-head">
        <span>💡 侦探提示（已消耗 1 点）</span>
        <button title="关闭" @click="store.dismissHint()">✕</button>
      </div>
      <p>{{ store.lastHint }}</p>
    </div>

    <div class="game-container">
      <div v-if="showHistoryPanel" class="history-panel">
        <div class="history-head">
          <h3>📋 历史对局存档</h3>
          <button class="history-close" @click="showHistoryPanel = false">✕</button>
        </div>
        <div class="history-list">
          <div v-for="record in store.archives" :key="record.id" class="history-item" :class="{ active: record.id === store.activeId }">
            <div class="history-item-title">
              第{{ record.round }}局 · {{ record.environment || '未命名' }}
              <span v-if="record.id === store.activeId" class="current-flag">当前</span>
            </div>
            <div class="history-item-meta">
              <span class="res" :class="record.result ?? 'ongoing'">
                {{ record.result === 'win' ? '✓ 胜利' : record.result === 'lose' ? '✗ 失败' : '中断' }}
              </span>
              <span v-if="record.score" class="score">得分 {{ record.score.total }}</span>
              <span class="history-time">{{ fmtDate(record.endedAt ?? record.startedAt) }}</span>
            </div>
            <div class="history-actions">
              <button v-if="record.result === null" @click="reopenScenario(record)">♻️ 同剧本重开</button>
              <button v-else @click="viewArchive(record)">📖 复盘</button>
              <button class="danger" @click="removeArchive(record.id)">删除</button>
            </div>
          </div>
          <div v-if="store.archives.length === 0" class="history-empty">还没有可读取的旧对局。<br>每完成一局或中途开新局都会自动留档。</div>
        </div>
      </div>

      <aside class="left-panel">
        <section class="panel-card suspects-section">
          <div class="section-head">
            <h3>👥 嫌疑人</h3>
            <span class="legend">
              <span class="dot none"></span>未对话
              <span class="dot talked"></span>已对话
              <span class="dot focus"></span>重点怀疑
            </span>
          </div>
          <div class="suspects-list">
            <div
              v-for="(c, idx) in allCharacters"
              :key="c.name"
              class="suspect-item"
              :class="{ selected: store.state.selected_character_id === idx, victim: isVictim(c) }"
              @click="onSuspectClick(idx)"
            >
              <span class="suspect-dot" :class="statusDot(c)"></span>
              <span class="suspect-avatar">{{ isVictim(c) ? '⚫' : avatar(c) }}</span>
              <div class="suspect-info">
                <span class="suspect-name">{{ suspectNo(idx) ? suspectNo(idx) + '. ' : '' }}{{ c.name }}</span>
                <span class="suspect-sub">{{ roleText(c) }} · {{ statusText(c) }}</span>
                <span v-if="c.relation_to_victim && !isVictim(c)" class="suspect-relation">与受害者：{{ c.relation_to_victim }}</span>
              </div>
              <button v-if="!isVictim(c)" class="quick-talk" title="直接开始对话" @click.stop="quickTalk(idx)">💬</button>
            </div>
          </div>
        </section>

        <section class="panel-card clues-section">
          <div class="section-head">
            <h3>📌 线索</h3>
            <span class="legend"><span class="tag-legend">👁已查看</span><span class="tag-legend">❓怀疑</span><span class="tag-legend">🚫排除</span><span class="tag-legend">⭐🔴🟢</span></span>
          </div>

          <div class="clue-group" v-if="publicClues.length">
            <div class="clue-group-title">
              <span>📂 公开线索</span>
              <span class="count">{{ publicDone }}/{{ publicClues.length }} 已处理</span>
            </div>
            <ClueItemRow v-for="clue in publicClues" :key="clue.id" :clue="clue" />
          </div>

          <div v-for="group in investigationGroups" :key="group.name" class="clue-group">
            <div class="clue-group-title">
              <span>🔓 {{ group.name }} 调查解锁</span>
              <span class="count">{{ group.unlocked }}/{{ group.clues.length }} 已解锁</span>
            </div>
            <template v-for="clue in group.clues" :key="clue.id">
              <div v-if="clue.locked" class="clue-locked" @click="hintLocked(group.name)">
                🔒 与 {{ group.name }} 对话后可解锁 · 线索待调查
              </div>
              <ClueItemRow v-else :clue="clue" />
            </template>
          </div>

          <div v-if="store.clues.length === 0" class="clue-placeholder">开局后这里会生成线索档案。</div>
        </section>
      </aside>

      <main class="main-panel">
        <section class="scene-overview" v-if="store.state.story_details">
          <button class="scene-toggle" type="button" @click="settings.toggleSceneCollapsed()">
            <span class="scene-toggle-title">🕯️ 案情速览</span>
            <span class="scene-toggle-state">{{ settings.sceneCollapsed ? '展开 ▼' : '收起 ▲' }}</span>
          </button>
          <Transition name="scene">
            <div v-if="!settings.sceneCollapsed" key="grid" class="scene-grid">
              <div class="scene-card"><div class="scene-card-label">死者</div><div class="scene-card-value">{{ store.state.story_details.victim_name }}</div></div>
              <div class="scene-card"><div class="scene-card-label">时间</div><div class="scene-card-value">{{ store.state.story_details.time_of_death }}</div></div>
              <div class="scene-card"><div class="scene-card-label">地点</div><div class="scene-card-value">{{ store.state.story_details.location_found }}</div></div>
              <div class="scene-card"><div class="scene-card-label">作案工具</div><div class="scene-card-value">{{ store.state.story_details.murder_weapon }}</div></div>
            </div>
            <p v-else key="line" class="scene-collapsed">死者 {{ store.state.story_details.victim_name }} · {{ store.state.story_details.time_of_death }} · {{ store.state.story_details.location_found }} · 工具 {{ store.state.story_details.murder_weapon }}</p>
          </Transition>
        </section>

        <section class="dialogue-section">
          <Narration v-if="store.state.messages.length > 0" :content="store.state.messages[0].content" />

          <ChatPanel v-if="store.state.selected_character_id !== null && !store.state.result" />

          <VictimInfo
            v-else-if="showVictimPanel && store.state.victim_report"
            :content="store.state.victim_report"
            @close="showVictimPanel = false"
          />

          <div v-else-if="!showVictimPanel" class="dialogue-placeholder">
            <p v-if="guessAttemptLog.length">上次指认：{{ lastGuessLogText }}</p>
            <p>👈 点嫌疑人卡片看档案，或点 💬 直接开聊套话</p>
            <p class="dim">线索会按“公开 / 调查解锁”分组；与对应嫌疑人完成对话才会点亮 🔓 线索</p>
          </div>
        </section>

        <div v-if="store.aiBusy" class="ai-busy-chip">
          <span class="spinner"></span>
          {{ store.aiBusyLabel || 'AI 正在生成…' }}
        </div>

        <section class="action-buttons">
          <button class="btn-exit" @click="store.exitConversation()" :disabled="store.state.selected_character_id === null || !!store.state.result">
            🚪 退出对话
          </button>
          <button class="btn-guess" @click="openAccuse" :disabled="!!store.state.result || allSuspects.length === 0">
            🔪 指认凶手
          </button>
        </section>
      </main>
    </div>

    <SuspectDossier
      v-if="dossierName"
      :character="dossierCharacter!"
      @close="dossierName = null"
      @talk="talkFromDossier"
    />

    <GuessPanel
      v-if="showAccuse"
      :all-characters="allSuspects"
      @submit="onGuessSubmit"
      @cancel="showAccuse = false"
    />

    <EvidenceBoard v-if="showEvidencePanel" @close="showEvidencePanel = false" />

    <InvestigationPanel v-if="showInvestigationPanel" @close="showInvestigationPanel = false" />

    <TimelinePanel v-if="showTimelinePanel" @close="showTimelinePanel = false" />

    <GuideModal v-if="showGuide" @close="showGuide = false" />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue"
import { useGameStore } from "@/stores/useGameStore"
import { useSettingsStore } from "@/stores/useSettingsStore"
import { sendAction } from "@/api/gameSocket"
import type { ArchiveMeta, Character } from "@/types/game"
import { playUnlock } from "@/utils/sound"
import { isSpeaking, stop } from "@/utils/tts"
import Narration from "@/components/Narration.vue"
import ChatPanel from "@/components/ChatPanel.vue"
import VictimInfo from "@/components/VictimInfo.vue"
import SuspectDossier from "@/components/SuspectDossier.vue"
import GuessPanel from "@/components/GuessPanel.vue"
import ClueItemRow from "@/components/ClueItemRow.vue"
import EvidenceBoard from "@/components/EvidenceBoard.vue"
import InvestigationPanel from "@/components/InvestigationPanel.vue"
import TimelinePanel from "@/components/TimelinePanel.vue"
import GuideModal from "@/components/GuideModal.vue"

const store = useGameStore()
const settings = useSettingsStore()
const showHistoryPanel = ref(false)
const showVictimPanel = ref(false)
const dossierName = ref<string | null>(null)
const showAccuse = ref(false)
const lastSavedLabel = ref("")
const showEvidencePanel = ref(false)
const showInvestigationPanel = ref(false)
const showTimelinePanel = ref(false)
const showGuide = ref(false)
const toasts = ref<{ id: number; text: string; kind: string }[]>([])

const boardCount = computed(() => store.board.length)

const allCharacters = computed(() => store.state.characters ?? [])
const allSuspects = computed(() => allCharacters.value.filter((c) => c.role.toLowerCase() !== "victim"))

const publicClues = computed(() => store.clues.filter((c) => c.kind === "public"))
const publicDone = computed(() => publicClues.value.filter((c) => c.mark !== "").length)

const investigationGroups = computed(() =>
  allSuspects.value
    .map((suspect) => {
      const clues = store.clues.filter((c) => c.kind === "investigation" && c.owner === suspect.name)
      return { name: suspect.name, clues, unlocked: clues.filter((c) => !c.locked).length }
    })
    .filter((g) => g.clues.length > 0),
)

const dossierCharacter = computed<null | Character>(() => {
  if (!dossierName.value) return null
  return allCharacters.value.find((c) => c.name === dossierName.value) ?? null
})

function isVictim(c: Character): boolean {
  return c.role.toLowerCase() === "victim"
}
function roleText(c: Character): string {
  return isVictim(c) ? "受害者" : "嫌疑人"
}
function statusDot(c: Character): string {
  if (isVictim(c)) return "victim"
  const meta = store.suspects[c.name]
  if (meta?.focus) return "focus"
  if (meta?.talked) return "talked"
  return "none"
}
function statusText(c: Character): string {
  if (isVictim(c)) return "已故"
  const meta = store.suspects[c.name]
  if (!meta) return "未对话"
  if (meta.focus) return "重点怀疑 · 已对话"
  return meta.talked ? `已对话（${meta.exchanges} 回合）` : "未对话"
}
function avatar(c: Character): string {
  const code = Array.from(c.name).reduce((sum, ch) => sum + (ch.codePointAt(0) ?? 0), 0)
  return ["🕵️", "🎩", "🕶️", "🧣", "🪶", "🧢", "👒", "💼"][code % 8]
}

function suspectNo(idx: number): string {
  const before = allCharacters.value.slice(0, idx).filter((c) => c.role.toLowerCase() !== "victim").length
  return isVictim(allCharacters.value[idx]) ? "" : String(before + 1)
}

function onSuspectClick(idx: number) {
  const c = allCharacters.value[idx]
  if (!c) return
  if (isVictim(c)) {
    dossierName.value = null
    showVictimPanel.value = true
    store.setRoute(null)
    store.state.selected_character_id = null
    sendAction({ action: "inspect_victim", char_id: idx })
  } else {
    dossierName.value = c.name
  }
}

function quickTalk(idx: number) {
  showVictimPanel.value = false
  dossierName.value = null
  store.openConversation(idx)
}

function talkFromDossier() {
  const idx = allCharacters.value.findIndex((c) => c.name === dossierName.value)
  dossierName.value = null
  if (idx >= 0) quickTalk(idx)
}

function hintLocked(name: string) {
  // 锁定线索不响应复杂操作，仅给出提示
  // eslint-disable-next-line no-alert
  alert(`这条线索需要先与 ${name} 完成一轮对话调查。`)
}

function openAccuse() {
  if (store.state.result) return
  dossierName.value = null
  showVictimPanel.value = false
  showEvidencePanel.value = false
  showInvestigationPanel.value = false
  showTimelinePanel.value = false
  showGuide.value = false
  showAccuse.value = true
}

function toggleBoard() {
  showEvidencePanel.value = !showEvidencePanel.value
  if (showEvidencePanel.value) {
    showHistoryPanel.value = false
    showInvestigationPanel.value = false
    showTimelinePanel.value = false
  }
}

function toggleHistory() {
  showHistoryPanel.value = !showHistoryPanel.value
  if (showHistoryPanel.value) {
    showEvidencePanel.value = false
    showInvestigationPanel.value = false
    showTimelinePanel.value = false
  }
}

function toggleInvestigation() {
  showInvestigationPanel.value = !showInvestigationPanel.value
  if (showInvestigationPanel.value) {
    showHistoryPanel.value = false
    showEvidencePanel.value = false
    showTimelinePanel.value = false
  }
}

function toggleTimeline() {
  showTimelinePanel.value = !showTimelinePanel.value
  if (showTimelinePanel.value) {
    showHistoryPanel.value = false
    showEvidencePanel.value = false
    showInvestigationPanel.value = false
  }
}

function askHint() {
  const ok = store.askHint()
  if (!ok) {
    addToast(store.aiError || "提示点不足，暂时无法使用。", "hint")
    store.dismissAiError()
  }
}

interface ToastItem {
  id: number
  text: string
  kind: string
}

function addToast(text: string, kind = "info") {
  const item: ToastItem = { id: Date.now() + Math.floor(Math.random() * 1000), text, kind }
  toasts.value.push(item)
  window.setTimeout(() => {
    toasts.value = toasts.value.filter((t) => t.id !== item.id)
  }, 3800)
}

// ---------- 新线索解锁提示（含轻微音效） ----------
const seenUnlockTimestamps = new Set<number>()
watch(
  () => store.clues.map((c) => c.unlockedAt ?? 0).join(","),
  () => {
    const now = Date.now()
    for (const clue of store.clues) {
      if (!clue.unlockedAt || seenUnlockTimestamps.has(clue.unlockedAt)) continue
      seenUnlockTimestamps.add(clue.unlockedAt)
      if (now - clue.unlockedAt > 4000) continue
      if (settings.sound) playUnlock()
      const owner = clue.owner ? `「${clue.owner}」` : "对方"
      addToast(`🔓 新线索解锁：与 ${owner} 的对话让你发现了新线索`, "unlock")
    }
  },
)

// ---------- 长时间未操作的弱提示 ----------
let lastActivityAt = Date.now()
let lastHintAt = 0
let idleTimer: number | undefined

function pokeActivity() {
  lastActivityAt = Date.now()
}

function idleTip(): string {
  if (!store.state.characters?.length) return "👀 剧本生成中，稍等片刻，先别走开。"
  const talkedAny = Object.values(store.suspects).some((meta) => meta.talked)
  const unlockedAny = store.clues.some((c) => !c.locked)
  if (!talkedAny) {
    return "👀 试试点左侧“嫌疑人”卡片开始调查——真话往往藏在闲聊里。"
  }
  if (!unlockedAny) {
    return "👀 连续追问细节（时间 / 去向 / 与死者的关系），有效对话会解锁新线索。"
  }
  return "👀 记得把证据丢进 🧩 推理白板做笔记；线索齐了就去“指认凶手”。"
}

function checkIdle() {
  if (store.state.result) return
  if (Date.now() - lastActivityAt < 90_000) return
  if (Date.now() - lastHintAt < 60_000) return
  lastActivityAt = Date.now()
  lastHintAt = Date.now()
  addToast(idleTip(), "hint")
}

function onKeyDown() {
  pokeActivity()
}
function onPointerDown() {
  pokeActivity()
}

function onGuessSubmit(payload: { name: string; reason: string }) {
  const idx = store.suspectIndexByName(payload.name)
  if (idx === null) return
  if (!store.serverAlive) {
    // 服务端不在线时指认会“无响应”，先给明确反馈而不是让玩家干等
    store.aiError = "服务端未连接，暂时无法提交指认。请先启动后端；如只是后端重启过，新建一局即可继续。"
    addToast(store.aiError, "hint")
    return
  }
  store.recordGuess(payload.name, payload.reason)
  showAccuse.value = false
  // 推理理由一起交给后端：结算时会按真相链逐条比对（clueCoverage/reasoning/bonus）
  sendAction({ action: "make_guess", guess_idx: idx, reason: payload.reason })
}

const guessAttemptLog = computed(() => [...store.guessLog].reverse())
const lastGuessLogText = computed(() => {
  const last = guessAttemptLog.value[0]
  if (!last) return ""
  return `你指认了 ${last.suspectName}（剩余 ${store.state.num_guesses_left} 次机会）`
})

watch(
  () => [store.state.story_details, store.state.characters] as const,
  () => store.initCluesIfEmpty(),
)

watch(
  () => store.state.result,
  (value) => {
    if (value === "win" || value === "lose") {
      store.finalizeResult()
      store.saveNow()
      showAccuse.value = false
      showEvidencePanel.value = false
      showInvestigationPanel.value = false
      showTimelinePanel.value = false
      showGuide.value = false
      store.dismissHint()
      dossierName.value = null
      if (isSpeaking()) stop()
      lastSavedLabel.value = fmtClock()
      setTimeout(() => store.goResultPage(), 1200)
    }
  },
)

onMounted(() => {
  lastSavedLabel.value = fmtClock()
  const timer = window.setInterval(() => {
    lastSavedLabel.value = fmtClock()
  }, 30000)
  window.addEventListener("keydown", onKeyDown)
  window.addEventListener("pointerdown", onPointerDown)
  idleTimer = window.setInterval(checkIdle, 30000)
  if (!settings.guideSeen && !store.state.result) showGuide.value = true
  onUnmounted(() => {
    window.clearInterval(timer)
    window.clearInterval(idleTimer)
    window.removeEventListener("keydown", onKeyDown)
    window.removeEventListener("pointerdown", onPointerDown)
    if (isSpeaking()) stop()
  })
})

function fmtClock(): string {
  const d = new Date()
  const pad = (n: number) => String(n).padStart(2, "0")
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}
function fmtDate(ts: number): string {
  const d = new Date(ts)
  return `${d.getFullYear()}/${d.getMonth() + 1}/${d.getDate()} ${fmtTimeShort(d)}`
}
function fmtTimeShort(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0")
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function reopenScenario(record: ArchiveMeta) {
  showHistoryPanel.value = false
  // 同剧本重开 = 新对局 = 新后端 session，避免与旧局串号
  store.startServerGame(record.environment || "一座偏远的贵族乡间庄园", record.max_characters || 5)
}
function viewArchive(record: ArchiveMeta) {
  store.loadArchive(record)
  showHistoryPanel.value = false
}
function removeArchive(id: string) {
  if (store.activeId !== id) store.removeArchive(id)
}
function goBackHome() {
  showHistoryPanel.value = false
  showEvidencePanel.value = false
  showInvestigationPanel.value = false
  showTimelinePanel.value = false
  showGuide.value = false
  if (isSpeaking()) stop()
  store.backHome()
}
</script>

<style scoped lang="scss">
.game-wrapper {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: #eef1f5;
  position: relative;
}

.game-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: linear-gradient(135deg, #1f2937 0%, #374151 100%);
  color: white;
  padding: 12px 18px;
  z-index: 20;

  .header-left {
    display: flex;
    align-items: center;
    gap: 12px;

    h1 { margin: 0; font-size: 20px; font-weight: 800; }
    .btn-back {
      background: rgba(255,255,255,0.12);
      border: none; color: white; font-size: 17px;
      border-radius: 8px; padding: 6px 10px; cursor: pointer;
      &:hover { background: rgba(255,255,255,0.22); }
    }
    .game-round { background: #dc2626; padding: 2px 10px; border-radius: 999px; font-size: 12px; font-weight: 700; }
    .autosave { font-size: 11px; color: #9ca3af; }
  }

  .header-right { display: flex; gap: 10px; }
  .history-btn, .new-btn {
    background: rgba(255,255,255,0.12);
    border: 1px solid rgba(255,255,255,0.2);
    color: white; border-radius: 8px; padding: 7px 12px;
    font-size: 13px; cursor: pointer; font-weight: 600;
    &:hover { background: rgba(255,255,255,0.22); }
  }
}

.offline-banner {
  background: #fef2f2;
  color: #991b1b;
  font-size: 12px;
  padding: 8px 18px;
  border-bottom: 1px solid #fecaca;
}

.game-container {
  flex: 1;
  display: flex;
  gap: 14px;
  padding: 14px;
  overflow: hidden;
  position: relative;
}

.history-panel {
  position: absolute;
  right: 14px;
  top: 14px;
  bottom: 14px;
  width: 330px;
  z-index: 40;
  background: white;
  border-radius: 12px;
  box-shadow: 0 12px 40px rgba(15,23,42,0.25);
  padding: 14px;
  overflow-y: auto;

  .history-head { display: flex; justify-content: space-between; align-items: center; h3 { margin: 0; } .history-close { border: none; background: none; cursor: pointer; font-size: 15px; } }
  .history-list { margin-top: 10px; display: flex; flex-direction: column; gap: 8px; }
  .history-item {
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    padding: 10px;
    background: #fafafa;
    &.active { border-color: #f59e0b; }
    .history-item-title { font-weight: 700; font-size: 13px; color: #1f2937; display: flex; align-items: center; gap: 6px; }
    .current-flag { font-size: 10px; color: #92400e; background: #fef3c7; padding: 1px 6px; border-radius: 999px; }
    .history-item-meta { display: flex; gap: 10px; font-size: 11px; color: #6b7280; margin-top: 4px; align-items: center;
      .res.win { color: #059669; font-weight: 700; } .res.lose { color: #dc2626; font-weight: 700; } .res.ongoing { color: #f59e0b; font-weight: 700; }
    }
    .history-actions { display: flex; gap: 8px; margin-top: 8px;
      button { font-size: 12px; padding: 5px 9px; border-radius: 6px; border: 1px solid #d1d5db; background: white; cursor: pointer; &:hover { background: #eff6ff; } &.danger:hover { background: #fef2f2; color: #b91c1c; } }
    }
  }
  .history-empty { text-align: center; color: #9ca3af; font-size: 12px; margin-top: 20px; line-height: 1.8; }
}

.left-panel {
  width: 380px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
  overflow-y: auto;

  .panel-card { background: white; border-radius: 10px; padding: 12px; box-shadow: 0 1px 4px rgba(0,0,0,0.06); }
  .section-head { display: flex; justify-content: space-between; align-items: baseline; h3 { margin: 0; font-size: 15px; } }
  .legend { font-size: 10px; color: #9ca3af; display: flex; align-items: center; gap: 4px;
    .dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; margin-left: 4px;
      &.none { background: #d1d5db; } &.talked { background: #22c55e; } &.focus { background: #dc2626; } }
    .tag-legend { margin-left: 4px; }
  }

  .suspects-list { margin-top: 10px; display: flex; flex-direction: column; gap: 6px; }
  .suspect-item {
    display: flex; align-items: center; gap: 9px;
    padding: 8px 9px; border: 1px solid #e5e7eb; border-radius: 9px;
    background: #fafbfc; cursor: pointer; transition: 0.15s;
    &:hover { background: #f1f5f9; border-color: #cbd5e1; }
    &.selected { border-color: #f59e0b; background: #fffbeb; }
    &.victim { opacity: 0.85; }

    .suspect-dot { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0;
      &.none { background: #d1d5db; }
      &.talked { background: #22c55e; box-shadow: 0 0 0 2px rgba(34,197,94,0.2); }
      &.focus { background: #dc2626; box-shadow: 0 0 0 2px rgba(220,38,38,0.25); }
      &.victim { background: #374151; }
    }
    .suspect-avatar { font-size: 17px; }
    .suspect-info { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 1px;
      .suspect-name { font-size: 13px; font-weight: 700; color: #1f2937; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
      .suspect-sub { font-size: 11px; color: #64748b; }
      .suspect-relation { font-size: 10.5px; color: #b45309; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    }
    .quick-talk {
      border: 1px solid #bfdbfe; background: #eff6ff; border-radius: 8px;
      font-size: 15px; padding: 5px 7px; cursor: pointer;
      &:hover { background: #dbeafe; }
    }
  }

  .clues-section { flex: 1; overflow-y: auto; }
  .clue-group { margin-top: 12px; }
  .clue-group-title {
    display: flex; justify-content: space-between; align-items: center;
    font-size: 12.5px; font-weight: 700; color: #334155; margin-bottom: 6px;
    .count { font-size: 11px; color: #94a3b8; font-weight: 500; }
  }
  .clue-locked {
    border: 1px dashed #d1d5db; background: #f1f5f9; color: #94a3b8;
    border-radius: 8px; padding: 8px 10px; font-size: 12px; margin-bottom: 6px;
  }
  .clue-placeholder { color: #9ca3af; font-size: 12px; text-align: center; padding: 16px 0; }
}

.main-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 12px;
  overflow-y: auto;
  min-width: 0;

  .scene-overview { background: white; border-radius: 10px; padding: 12px; box-shadow: 0 1px 4px rgba(0,0,0,0.06);
    .scene-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }
    .scene-card { background: linear-gradient(135deg,#f0f9ff,#e0f2fe); border: 1px solid #bfdbfe; border-radius: 8px; padding: 10px; text-align: center;
      .scene-card-label { font-size: 11px; font-weight: 700; color: #0369a1; }
      .scene-card-value { font-size: 13px; color: #1e40af; font-weight: 600; word-break: break-word; }
    }
  }

  .dialogue-section {
    flex: 1; background: white; border-radius: 10px; padding: 12px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.08); overflow-y: auto;
    display: flex; flex-direction: column; min-height: 0;

    .dialogue-placeholder {
      margin: auto; text-align: center; color: #9ca3af;
      p { margin: 6px 0; font-size: 13px; }
      .dim { font-size: 12px; }
    }
  }

  .action-buttons { display: flex; gap: 10px; flex-shrink: 0;
    button { flex: 1; padding: 11px; border: none; border-radius: 8px; font-size: 14px; font-weight: 700; cursor: pointer; transition: 0.2s;
      &:disabled { opacity: 0.5; cursor: not-allowed; }
    }
    .btn-exit { background: #64748b; color: white; &:hover:not(:disabled) { background: #475569; } }
    .btn-guess { background: #dc2626; color: white; &:hover:not(:disabled) { background: #b91c1c; } }
  }
}

@media (max-width: 1100px) {
  .game-header { flex-direction: column; align-items: stretch; gap: 6px; }
  .header-right { flex-wrap: wrap; justify-content: flex-start; }
  .game-container { flex-direction: column; overflow-y: auto; }
  .left-panel { width: 100%; flex-direction: row; flex-wrap: wrap; }
  .left-panel .panel-card { flex: 1; min-width: 46%; }
  .main-panel { min-height: 62vh; }
  .scene-overview .scene-grid { grid-template-columns: repeat(2, 1fr); }

  :deep(.investigation-panel),
  :deep(.timeline-panel) {
    right: 10px;
    left: 10px;
    width: auto;
    max-width: none;
  }
  .history-panel { right: 10px; left: 10px; width: auto; }
  .hint-pop { bottom: 20px; }
}

@media (max-width: 640px) {
  .header-right .history-btn,
  .header-right .new-btn { font-size: 12px; padding: 6px 8px; }
  .left-panel .panel-card { min-width: 100%; }
  .scene-overview .scene-grid { grid-template-columns: 1fr; }
  .action-buttons button { font-size: 13px; padding: 9px; }
}

.header-right {
  flex-wrap: wrap;
  justify-content: flex-end;

  .icon-btn {
    position: relative;
    background: rgba(255, 255, 255, 0.1);
    border: 1px solid rgba(255, 255, 255, 0.18);
    color: #e5e7eb;
    border-radius: 8px;
    padding: 7px 10px;
    font-size: 14px;
    cursor: pointer;
    &:hover { background: rgba(255, 255, 255, 0.2); }
    &.on { background: rgba(167, 139, 250, 0.32); border-color: #a78bfa; }

    .badge {
      position: absolute;
      top: -5px;
      right: -5px;
      min-width: 16px;
      height: 16px;
      border-radius: 999px;
      background: #dc2626;
      color: #fff;
      font-size: 10px;
      line-height: 16px;
      text-align: center;
      padding: 0 4px;
    }
  }
  .font-btn {
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 0.5px;
  }
  .help-btn {
    background: rgba(255, 255, 255, 0.1);
    border: 1px solid rgba(255, 255, 255, 0.18);
    color: #e5e7eb;
    border-radius: 8px;
    padding: 7px 10px;
    font-size: 13px;
    cursor: pointer;
    &:hover { background: rgba(255, 255, 255, 0.2); }
  }
}

/* ---------- 案情速览折叠 ---------- */
.scene-overview {
  .scene-toggle {
    width: 100%;
    display: flex;
    align-items: center;
    justify-content: space-between;
    border: none;
    background: none;
    padding: 0 0 4px;
    cursor: pointer;

    .scene-toggle-title {
      font-size: 13.5px;
      font-weight: 800;
      color: #334155;
    }
    .scene-toggle-state {
      font-size: 11px;
      color: #94a3b8;
    }
  }
  .scene-collapsed {
    margin: 6px 0 0;
    font-size: 12px;
    color: #64748b;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    text-align: left;
  }
}

.scene-enter-active,
.scene-leave-active {
  transition: opacity 0.18s ease, transform 0.18s ease;
}
.scene-enter-from,
.scene-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}

/* ---------- 轻提示 Toast ---------- */
.toast-layer {
  position: fixed;
  left: 50%;
  bottom: 26px;
  transform: translateX(-50%);
  z-index: 120;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  pointer-events: none;

  .toast {
    max-width: min(520px, 90vw);
    background: #1f2937;
    color: #f9fafb;
    border: 1px solid #374151;
    border-radius: 10px;
    padding: 9px 16px;
    font-size: 13px;
    line-height: 1.6;
    box-shadow: 0 10px 30px rgba(0, 0, 0, 0.25);

    &.unlock {
      background: #052e16;
      border-color: #22c55e;
    }
    &.hint {
      background: #3a2a10;
      border-color: #f59e0b;
    }
  }
}

.toast-enter-active,
.toast-leave-active {
  transition: opacity 0.25s ease, transform 0.25s ease;
}
.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translateY(8px);
}

/* ---------- AI 生成中占位 / 提示浮层 ---------- */
.ai-busy-chip {
  display: flex;
  align-items: center;
  gap: 8px;
  align-self: flex-start;
  background: #1f2937;
  color: #f9fafb;
  font-size: 12px;
  line-height: 1.4;
  border: 1px solid #374151;
  border-radius: 999px;
  padding: 6px 14px;
  box-shadow: 0 6px 18px rgba(0, 0, 0, 0.18);
  animation: chip-in 0.18s ease;

  .spinner {
    width: 12px;
    height: 12px;
    border: 2px solid rgba(255, 255, 255, 0.3);
    border-top-color: #fff;
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
    flex-shrink: 0;
  }
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.hint-pop {
  position: fixed;
  left: 50%;
  transform: translateX(-50%);
  bottom: 84px;
  z-index: 100;
  width: min(560px, calc(100vw - 32px));
  background: #2b2210;
  color: #fef3c7;
  border: 1px solid #d97706;
  border-radius: 12px;
  padding: 12px 14px;
  box-shadow: 0 14px 38px rgba(0, 0, 0, 0.35);
  animation: hint-in 0.2s ease;

  .hint-pop-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    font-size: 13px;
    font-weight: 800;
    color: #fbbf24;
    button {
      border: none;
      background: rgba(255, 255, 255, 0.08);
      color: #fde68a;
      border-radius: 6px;
      width: 24px;
      height: 24px;
      cursor: pointer;
      &:hover { background: rgba(255, 255, 255, 0.18); }
    }
  }
  p {
    margin: 8px 0 0;
    font-size: 13px;
    line-height: 1.8;
    color: #fef3c7;
  }
}

.header-right .icon-btn.empty {
  opacity: 0.55;
}
.header-right .icon-btn .badge.hint-count {
  background: #d97706;
}

@keyframes hint-in {
  from { opacity: 0; transform: translate(-50%, 10px); }
  to { opacity: 1; transform: translate(-50%, 0); }
}

@keyframes chip-in {
  from { opacity: 0; transform: translateY(-4px); }
  to { opacity: 1; transform: translateY(0); }
}

/* ---------- 夜间主题 ---------- */
:global(html[data-theme="dark"]) .game-wrapper {
  background: #0e1116;

  .offline-banner {
    background: rgba(127, 29, 29, 0.28);
    color: #fecaca;
    border-bottom-color: #7f1d1d;
  }

  .history-panel {
    background: #181c24;
    border: 1px solid #2c323f;

    .history-head h3 { color: #e5e7eb; }
    .history-close { color: #9aa3b2; }
    .history-item {
      background: #1e232e;
      border-color: #2e3441;
      .history-item-title { color: #e5e7eb; }
      .history-time { color: #7d8698; }
      .history-actions button {
        background: #262c3a;
        border-color: #3a4152;
        color: #d7deea;
        &:hover { background: #2e3647; }
        &.danger:hover { background: #401f22; color: #fca5a5; }
      }
    }
    .history-empty { color: #6b7280; }
  }

  .panel-card {
    background: #181c24;
    box-shadow: none;

    .section-head h3 { color: #e8ecf3; }
    .legend { color: #8a93a5; }
  }

  .suspect-item {
    background: #1e232e;
    border-color: #2c323f;
    &:hover { background: #232a37; border-color: #3b4354; }
    &.selected { background: #2b2413; border-color: #d97706; }

    .suspect-name { color: #e5e7eb; }
    .suspect-sub { color: #9aa3b2; }
    .suspect-relation { color: #fcd34d; }
    .quick-talk {
      background: #172554;
      border-color: #1d4ed8;
      &:hover { background: #1e40af; }
    }
  }

  .clue-group-title { color: #cbd5e1; }
  .clue-locked {
    background: #1a1e28;
    border-color: #343b4c;
    color: #7d8698;
  }

  .scene-overview {
    background: #181c24;
    box-shadow: none;

    .scene-toggle .scene-toggle-title { color: #dbeafe; }
    .scene-toggle .scene-toggle-state { color: #7d8698; }
    .scene-collapsed { color: #aab6c8; }
    .scene-card {
      background: linear-gradient(135deg, #17233c 0%, #1b2f55 100%);
      border-color: #24406b;
      .scene-card-label { color: #7dd3fc; }
      .scene-card-value { color: #e0f2fe; }
    }
  }

  .dialogue-section {
    background: #191c24;
    box-shadow: none;

    .dialogue-placeholder {
      color: #7d8698;
      .dim { color: #6b7280; }
    }
  }
}
</style>
