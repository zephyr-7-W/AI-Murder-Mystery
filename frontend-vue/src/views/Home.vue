<template>
  <div class="home">
    <ReadingControls />
    <h1>🕵️ Murder Mystery</h1>
    <p class="subtitle">AI 剧本杀 · 每位嫌疑人都有自己的秘密与底线</p>

    <div v-if="resumeAvailable" class="resume-card">
      <div class="resume-head">
        <span class="resume-title">📌 检测到进行中的对局</span>
        <span v-if="latestActive" class="resume-meta">第{{ latestActive.round }}局 · {{ latestActive.state.environment || latestActive.environment }}</span>
      </div>
      <div class="resume-buttons">
        <button class="btn-continue" @click="continueGame">▶ 继续上一局</button>
        <button class="btn-discard" @click="showConfirm = true">开始新对局（覆盖存档）</button>
      </div>
    </div>

    <div class="scenario-block">
      <div class="scenario-head">
        <h2>🎬 选择剧本</h2>
        <span class="round-preview">将开启 第 {{ nextRound }} 局</span>
      </div>
      <div class="scenario-grid">
        <button
          v-for="s in SCENARIOS"
          :key="s.id"
          type="button"
          class="scenario-card"
          :class="{ picked: pickedId === s.id }"
          @click="pickScenario(s)"
        >
          <span class="sc-title">{{ s.title }}</span>
          <span v-if="pickedId === s.id" class="sc-check">✓</span>
          <p class="sc-blurb">{{ s.blurb }}</p>
          <span class="sc-env">{{ s.env }}</span>
          <span class="sc-tags"><i v-for="tag in s.tags" :key="tag">{{ tag }}</i></span>
        </button>
      </div>
    </div>

    <div class="form-wrap">
      <div class="form-head">
        <h2>⚙️ 自定义 / 快速开始</h2>
        <span class="round-preview">将开启 第 {{ nextRound }} 局</span>
      </div>
      <div class="item">
        <label>故事场景环境</label>
        <input v-model="env" placeholder="例如：贵族庄园 / 远洋游轮" @input="syncPickedFromEnv"/>
      </div>
      <div class="item">
        <label>人物总数</label>
        <input v-model.number="maxChar" type="number" min="3" max="8"/>
        <p class="item-hint">每局剧本都由 AI 现场生成，换环境等于换一个全新剧本；未完成的对局会自动存进历史。</p>
      </div>
      <button class="btn-start" @click="startGame">开始游戏</button>
    </div>

    <div v-if="finishedRounds.length" class="archive-list">
      <h2>📋 已完成的旧对局</h2>
      <div class="archive-row" v-for="item in finishedRounds" :key="item.id" @click="viewFinished(item)">
        <span class="round">第{{ item.round }}局</span>
        <span class="res" :class="item.result">{{ item.result === 'win' ? '✓ 胜利' : '✗ 失败' }}</span>
        <span v-if="item.score" class="score">得分 {{ item.score.total }}</span>
        <span class="time">{{ fmtDate(item.endedAt ?? item.startedAt) }}</span>
      </div>
    </div>

    <div v-if="showConfirm" class="confirm-mask" @click.self="showConfirm = false">
      <div class="confirm-box">
        <p>开始新对局会覆盖当前进行中的存档（未完成的一局会自动存入历史）。</p>
        <div class="row">
          <button class="btn-ghost" @click="showConfirm = false">取消</button>
          <button class="btn-danger" @click="forceStart">确认覆盖</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue"
import { useGameStore } from "@/stores/useGameStore"
import { connectWebSocket, sendAction, sessionIdFor } from "@/api/gameSocket"
import type { ArchiveMeta, GameSave } from "@/types/game"
import { SCENARIOS, scenarioByEnv, type ScenarioPreset } from "@/utils/scenarios"
import ReadingControls from "@/components/ReadingControls.vue"

const gameStore = useGameStore()
const env = ref("一座偏远的贵族乡间庄园")
const maxChar = ref(5)
const showConfirm = ref(false)
const pickedId = ref<string>("manor")

function loadActive(): GameSave | null {
  try {
    const raw = localStorage.getItem("ai-murder-active-v1")
    if (!raw) return null
    const parsed = JSON.parse(raw) as GameSave
    return parsed && parsed.state ? parsed : null
  } catch {
    return null
  }
}

const activeSave = ref<GameSave | null>(null)
const latestActive = computed(() => activeSave.value)
const resumeAvailable = computed(() => Boolean(activeSave.value && !activeSave.value!.state.result))
const finishedRounds = computed(() =>
  [...gameStore.archives].filter((a) => a.result !== null).reverse(),
)
const nextRound = computed(() => gameStore.nextRoundNumber())

onMounted(() => {
  activeSave.value = loadActive()
})

function startGame() {
  if (resumeAvailable.value && !showConfirm.value) {
    showConfirm.value = true
    return
  }
  forceStart()
}

function pickScenario(sc: ScenarioPreset) {
  pickedId.value = sc.id
  env.value = sc.env
  maxChar.value = sc.defaultMax
}

function syncPickedFromEnv() {
  pickedId.value = scenarioByEnv(env.value)?.id ?? ""
}

function forceStart() {
  showConfirm.value = false
  // 开新局 = 独立后端 session（局号自动递增，见 startServerGame）
  gameStore.startServerGame(env.value, maxChar.value)
}

function continueGame() {
  const save = activeSave.value
  if (!save) return
  gameStore.applySave(save)
  gameStore.goGamePage()
  connectWebSocket(sessionIdFor(save.id))
  setTimeout(() => sendAction({ action: "select_character", char_id: null }), 300)
  setTimeout(() => gameStore.markServerPingFailed(), 2800)
}

function viewFinished(item: ArchiveMeta) {
  gameStore.loadArchive(item)
  connectWebSocket(sessionIdFor(item.save?.id || item.id))
}

function fmtDate(ts: number): string {
  const d = new Date(ts)
  const pad = (n: number) => String(n).padStart(2, "0")
  return `${d.getFullYear()}/${pad(d.getMonth() + 1)}/${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}
</script>

<style scoped lang="scss">
.home {
  max-width: 920px;
  margin: 4rem auto;
  text-align: center;
  padding: 0 16px;

  h1 { font-size: 40px; margin-bottom: 4px; }
  .subtitle { color: #9ca3af; font-size: 13px; }

  .resume-card {
    margin-top: 26px;
    background: #fffbeb;
    border: 1px solid #fcd34d;
    border-radius: 12px;
    padding: 14px;
    text-align: left;

    .resume-head { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 6px;
      .resume-title { font-weight: 800; color: #92400e; font-size: 14px; }
      .resume-meta { font-size: 12px; color: #b45309; }
    }
    .resume-buttons { margin-top: 12px; display: flex; gap: 10px;
      button { padding: 9px 14px; border-radius: 8px; font-size: 13px; font-weight: 700; cursor: pointer; border: none; }
      .btn-continue { background: #2563eb; color: white; }
      .btn-discard { background: white; border: 1px solid #f59e0b; color: #b45309; }
    }
  }

  .form-wrap {
    margin-top: 30px;
    background: white;
    border-radius: 12px;
    padding: 20px;
    box-shadow: 0 2px 10px rgba(0,0,0,0.06);

    .form-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      flex-wrap: wrap;
      margin-bottom: 14px;
      h2 { margin: 0; font-size: 16px; color: #334155; }
    }

    .item { margin-bottom: 14px; text-align: left;
      label { display: block; margin-bottom: 5px; font-size: 13px; font-weight: 600; color: #374151; }
      input { width: 100%; box-sizing: border-box; padding: 10px; font-size: 15px; border: 1px solid #cbd5e1; border-radius: 8px; }
      .item-hint { margin: 6px 0 0; font-size: 11.5px; color: #9ca3af; line-height: 1.6; }
    }
    .btn-start { width: 100%; padding: 12px; background: #2563eb; color: white; border: none; border-radius: 9px; font-size: 15px; font-weight: 800; cursor: pointer; &:hover { background: #1d4ed8; } }
  }

  .scenario-block {
    margin-top: 26px;
    text-align: left;

    .scenario-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      margin-bottom: 10px;
      h2 { margin: 0; font-size: 17px; color: #334155; }
    }

    .round-preview {
      font-size: 12px;
      font-weight: 700;
      color: #b45309;
      background: #fffbeb;
      border: 1px solid #fcd34d;
      border-radius: 999px;
      padding: 3px 10px;
    }

    .scenario-grid {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 10px;
    }

    .scenario-card {
      position: relative;
      display: flex;
      flex-direction: column;
      align-items: flex-start;
      gap: 6px;
      text-align: left;
      background: white;
      border: 1px solid #e2e8f0;
      border-radius: 10px;
      padding: 12px;
      cursor: pointer;
      transition: 0.16s;
      font-family: inherit;

      &:hover { border-color: #93c5fd; box-shadow: 0 4px 14px rgba(37, 99, 235, 0.1); transform: translateY(-1px); }
      &.picked { border-color: #2563eb; background: #eff6ff; box-shadow: 0 4px 16px rgba(37, 99, 235, 0.16); }

      .sc-title { font-size: 14px; font-weight: 800; color: #1e293b; padding-right: 20px; }
      .sc-check {
        position: absolute;
        top: 10px;
        right: 10px;
        width: 18px;
        height: 18px;
        border-radius: 50%;
        background: #2563eb;
        color: #fff;
        font-size: 11px;
        line-height: 18px;
        text-align: center;
      }
      .sc-blurb { margin: 0; font-size: 12px; color: #64748b; line-height: 1.6; flex: 1; }
      .sc-env { font-size: 11px; color: #475569; background: #f1f5f9; border-radius: 6px; padding: 2px 7px; }
      .sc-tags { display: flex; gap: 4px; flex-wrap: wrap;
        i { font-style: normal; font-size: 10.5px; color: #6d28d9; background: #f5f3ff; border: 1px solid #ede9fe; border-radius: 999px; padding: 1px 7px; }
      }
    }
  }

  .archive-list { margin-top: 28px; text-align: left; background: white; border-radius: 10px; padding: 14px;
    h2 { margin: 0 0 10px; font-size: 15px; color: #334155; }
    .archive-row { display: flex; align-items: center; gap: 10px; padding: 8px; border-bottom: 1px dashed #e5e7eb; cursor: pointer; font-size: 13px;
      &:hover { background: #f8fafc; }
      .round { font-weight: 700; }
      .res.win { color: #059669; font-weight: 700; } .res.lose { color: #dc2626; font-weight: 700; }
      .score { color: #7c3aed; }
      .time { margin-left: auto; color: #9ca3af; font-size: 11px; }
    }
  }

  .confirm-mask { position: fixed; inset: 0; background: rgba(15,23,42,0.4); display: flex; align-items: center; justify-content: center; z-index: 80; }
  .confirm-box { background: white; border-radius: 12px; padding: 22px; max-width: 420px; text-align: center;
    p { font-size: 14px; color: #374151; line-height: 1.7; }
    .row { display: flex; justify-content: center; gap: 12px; margin-top: 10px;
      button { padding: 9px 18px; border: none; border-radius: 8px; cursor: pointer; font-weight: 700; }
      .btn-ghost { background: #f1f5f9; color: #475569; }
      .btn-danger { background: #dc2626; color: white; }
    }
  }
}

:global(html[data-theme="dark"]) .home {
  h1 { color: #f3f4f6; }
  .subtitle { color: #9ca3af; }

  .resume-card {
    background: rgba(180, 140, 30, 0.14);
    border-color: #a16207;
    .resume-title { color: #fcd34d; }
    .resume-meta { color: #fbbf24; }
    .btn-continue { background: #1d4ed8; }
    .btn-discard { background: #262b3a; border-color: #a16207; color: #fbbf24; }
  }

  .form-wrap {
    background: #181c24;
    box-shadow: none;
    .item label { color: #cbd5e1; }
    .item input {
      background: #10141c;
      border-color: #343b4c;
      color: #e5e7eb;
    }
  }

  .archive-list {
    background: #181c24;
    h2 { color: #cbd5e1; }
    .archive-row {
      border-bottom-color: #2e3441;
      color: #d7deea;
      &:hover { background: #20242f; }
      .time { color: #7d8698; }
    }
  }

  .confirm-mask { background: rgba(5, 8, 12, 0.65); }
  .confirm-box {
    background: #1a1e28;
    border: 1px solid #2e3441;
    p { color: #d7deea; }
    .btn-ghost { background: #2a2f3c; color: #cbd5e1; }
  }
}

:global(html[data-theme="dark"]) .home {
  .scenario-block {
    .scenario-head h2 { color: #cbd5e1; }
    .scenario-card {
      background: #181c24;
      border-color: #2e3441;
      &:hover { border-color: #3b82f6; box-shadow: 0 4px 14px rgba(37, 99, 235, 0.16); }
      &.picked { background: #172554; border-color: #3b82f6; }
      .sc-title { color: #e5e7eb; }
      .sc-blurb { color: #9aa3b2; }
      .sc-env { background: #20242f; color: #cbd5e1; }
      .sc-tags i { background: #221a3d; border-color: #4c1d95; color: #c4b5fd; }
    }
  }
  .form-wrap .form-head h2 { color: #cbd5e1; }
}

@media (max-width: 760px) {
  .home .scenario-block .scenario-grid { grid-template-columns: repeat(2, 1fr); }
  .home .scenario-block .scenario-head,
  .home .form-wrap .form-head { flex-direction: column; align-items: flex-start; }
}

@media (max-width: 480px) {
  .home .scenario-block .scenario-grid { grid-template-columns: 1fr; }
}
</style>
