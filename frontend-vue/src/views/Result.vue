<template>
  <div class="result-page">
    <ReadingControls />
    <div class="verdict" :class="store.state.result">
      <div v-if="store.state.result === 'win'" class="win"><h1>🎉 调查成功！你抓住了真凶</h1></div>
      <div v-else class="lose"><h1>❌ 调查失败，真凶就在你眼前溜走了</h1></div>

      <p class="killer-name">
        真正凶手：<b>{{ killerName }}</b>
      </p>
      <p v-if="store.myGuessName" class="my-guess">
        你的最终指认：{{ store.myGuessName }}
        <span v-if="store.state.result === 'win'"> ✓</span>
        <span v-else> ✗</span>
      </p>
    </div>

    <div v-if="store.score" class="score-card">
      <div class="score-big">
        <div class="score-num">{{ store.score.total }}</div>
        <div class="score-grade">{{ gradeLabel(store.score.total) }}</div>
      </div>
      <div class="score-bars">
        <div class="bar-row"><span>线索收集完整度</span><div class="bar"><i :style="{ width: store.score.clueCoverage + '%' }"></i></div><b>{{ store.score.clueCoverage }}</b></div>
        <div class="bar-row"><span>推理理由质量</span><div class="bar"><i :style="{ width: store.score.reasoning + '%' }"></i></div><b>{{ store.score.reasoning }}</b></div>
        <div class="bar-row"><span>指认与试错奖励</span><div class="bar"><i :style="{ width: Math.min(100, store.score.bonus) + '%' }"></i></div><b>+{{ store.score.bonus }}</b></div>
      </div>
      <p class="clue-stat">📌 线索：{{ unlockedCount }}/{{ totalClues }} 已解锁，其中 {{ markedCount }} 条已查看/标记</p>
      <div
        v-if="keyFound.length || keyMissed.length || serverFeedback"
        class="judge-box"
      >
        <div v-if="keyFound.length" class="judge-part">
          <h4>✅ 你抓到了这些关键点</h4>
          <ul><li v-for="(point, i) in keyFound" :key="'f' + i">{{ point }}</li></ul>
        </div>
        <div v-if="keyMissed.length" class="judge-part">
          <h4>🔍 还漏掉了这些决定性细节</h4>
          <ul><li v-for="(point, i) in keyMissed" :key="'m' + i">{{ point }}</li></ul>
        </div>
        <p v-if="serverFeedback" class="judge-feedback">💬 {{ serverFeedback }}</p>
      </div>
    </div>

    <div v-if="store.reason" class="reason-box">
      <h3>🧠 你提交的推理理由</h3>
      <p>{{ store.reason }}</p>
    </div>

    <div v-if="store.guessLog.length" class="guess-history">
      <h3>🗳️ 指认记录</h3>
      <div v-for="(g, i) in store.guessLog" :key="i" class="guess-item">
        <span class="idx">第 {{ i + 1 }} 次</span>
        <span class="name">→ {{ g.suspectName }}</span>
        <span v-if="g.correct === false && i === store.guessLog.length - 1 && store.state.result === 'lose'" class="wrong">指认错误</span>
        <span v-if="i === store.guessLog.length - 1 && store.state.result === 'win'" class="right">指认正确 ✓</span>
      </div>
    </div>

    <div class="recap-wrap">
      <button class="recap-toggle" @click="showRecap = !showRecap">📖 {{ showRecap ? '收起案情复盘' : '查看完整真相复盘' }}</button>
      <div v-if="showRecap && story" class="recap-box">
        <h3>📜 真相复盘</h3>
        <div class="recap-line"><span class="k">受害者</span><span class="v">{{ victim?.name || story.victim_name }}</span></div>
        <div class="recap-line"><span class="k">案发时间</span><span class="v">{{ story.time_of_death }}</span></div>
        <div class="recap-line"><span class="k">发现地点</span><span class="v">{{ story.location_found }}</span></div>
        <div class="recap-line"><span class="k">作案工具</span><span class="v">{{ story.murder_weapon }}（{{ story.cause_of_death }}）</span></div>
        <div class="recap-line"><span class="k">犯罪现场</span><span class="v">{{ story.crime_scene_details }}</span></div>
        <div class="recap-line"><span class="k">目击与线索</span><span class="v">{{ story.witnesses }}<template v-if="story.initial_clues"><br>{{ story.initial_clues }}</template></span></div>
        <div class="recap-line recap-story"><span class="k">作案过程</span><span class="v">{{ story.murder_process }}</span></div>
        <div class="recap-line"><span class="k">真凶</span><span class="v">{{ killerName }}</span></div>
        <div class="recap-line"><span class="k">涉案人员</span>
          <span class="v">
            <span v-for="(c, i) in suspects" :key="c.name">{{ c.name }}{{ c.relation_to_victim ? '（' + c.relation_to_victim + '）' : '' }}<template v-if="i < suspects.length - 1">、</template></span>
          </span>
        </div>
        <div class="recap-line"><span class="k">人物关系</span><span class="v">{{ story.npc_brief }}</span></div>
      </div>
    </div>

    <div class="next-round-box">
      <h3>🔁 再来一局</h3>
      <div class="env-row">
        <label>剧本场景</label>
        <input v-model="nextEnv" />
        <span class="env-switch" @click="randomEnv">🎲 换一个</span>
      </div>
      <div class="max-row">
        <label>人物数</label>
        <input v-model.number="nextMax" type="number" min="3" max="8" />
      </div>
      <div class="actions">
        <button class="btn-next" @click="nextRound">🚀 用这套设定再来一局</button>
        <button class="btn-home" @click="backHome">🏠 返回首页</button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from "vue"
import { useGameStore } from "@/stores/useGameStore"
import { gradeLabel } from "@/utils/scoring"
import ReadingControls from "@/components/ReadingControls.vue"

const store = useGameStore()
const showRecap = ref(false)
const nextEnv = ref(store.state.environment || "一座偏远的贵族乡间庄园")
const nextMax = ref(store.state.max_characters || 5)

const story = computed(() => store.state.story_details)
const victim = computed(() => (store.state.characters ?? []).find((c) => c.role.toLowerCase() === "victim"))
const suspects = computed(() => (store.state.characters ?? []).filter((c) => c.role.toLowerCase() !== "victim"))
const killerName = computed(() => store.state.killer_name ?? "")
const totalClues = computed(() => store.clues.length)
const unlockedCount = computed(() => store.clues.filter((c) => !c.locked).length)
const markedCount = computed(() => store.clues.filter((c) => !c.locked && c.mark !== "").length)
const serverResultData = computed(() => store.state.result_data)
const keyFound = computed(() => serverResultData.value?.keyPointsFound ?? [])
const keyMissed = computed(() => serverResultData.value?.keyPointsMissed ?? [])
const serverFeedback = computed(() => serverResultData.value?.feedback ?? "")

const envSamples = [
  "一座偏远的贵族乡间庄园",
  "豪华远洋游轮的晚宴厅",
  "暴雪封山的滑雪度假村",
  "老式豪华列车包厢",
  "废弃精神病院改建的剧本店",
  "跨国药企的总部大楼",
]

function randomEnv() {
  const others = envSamples.filter((e) => e !== nextEnv.value)
  nextEnv.value = others[Math.floor(Math.random() * others.length)]
}

function nextRound() {
  const environment = (nextEnv.value || "一座偏远的贵族乡间庄园").trim()
  const max_characters = Math.max(3, Math.min(8, Math.round(nextMax.value || 5)))
  // 再来一局 = 新对局 = 独立后端 session（见 store.startServerGame）
  store.startServerGame(environment, max_characters)
}

function backHome() {
  store.backHome()
}
</script>

<style scoped lang="scss">
.result-page {
  max-width: 720px;
  margin: 0 auto;
  padding: 28px 16px 60px;
  text-align: center;

  .verdict {
    .win h1 { color: #059669; }
    .lose h1 { color: #dc2626; }
    .killer-name { font-size: 20px; margin-top: 14px; color: #374151; }
    .my-guess { color: #7c3aed; font-weight: 600; }
  }

  .score-card {
    margin: 22px auto 0;
    background: linear-gradient(135deg, #f5f3ff, #ede9fe);
    border: 1px solid #ddd6fe;
    border-radius: 14px;
    padding: 18px;
    text-align: left;

    .score-big { display: flex; align-items: baseline; gap: 12px;
      .score-num { font-size: 52px; font-weight: 900; color: #6d28d9; }
      .score-grade { font-size: 18px; font-weight: 700; color: #7c3aed; }
    }
    .score-bars { margin-top: 10px; display: flex; flex-direction: column; gap: 6px;
      .bar-row { display: grid; grid-template-columns: 150px 1fr 40px; align-items: center; gap: 10px; font-size: 12px; color: #4c1d95;
        .bar { height: 8px; background: #ddd6fe; border-radius: 999px; overflow: hidden;
          i { display: block; height: 100%; background: linear-gradient(90deg, #8b5cf6, #6d28d9); }
        }
      }
    }
    .clue-stat { margin: 10px 0 0; font-size: 12px; color: #6d28d9; }

    .judge-box {
      margin-top: 12px;
      border-top: 1px dashed #c4b5fd;
      padding-top: 10px;
      font-size: 12px;
      color: #5b21b6;
      .judge-part + .judge-part { margin-top: 8px; }
      h4 { margin: 0 0 4px; font-size: 12px; color: #7c3aed; }
      ul { margin: 0; padding-left: 16px; li { margin: 2px 0; line-height: 1.6; } }
      .judge-feedback { margin: 8px 0 0; color: #4c1d95; line-height: 1.7; }
    }
  }

  .reason-box {
    margin: 16px auto 0;
    max-width: 640px;
    background: #eff6ff;
    border: 1px solid #bfdbfe;
    border-radius: 10px;
    padding: 12px 16px;
    text-align: left;
    h3 { margin: 0 0 6px; font-size: 14px; color: #1d4ed8; }
    p { margin: 0; font-size: 13px; line-height: 1.8; color: #1e3a8a; white-space: pre-line; }
  }

  .guess-history {
    margin: 16px auto 0;
    max-width: 640px;
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 10px;
    padding: 10px 14px;
    text-align: left;
    h3 { margin: 0 0 8px; font-size: 13px; color: #334155; }
    .guess-item { font-size: 13px; color: #475569; padding: 3px 0;
      .wrong { color: #dc2626; font-weight: 700; }
      .right { color: #059669; font-weight: 700; }
    }
  }

  .recap-wrap { margin-top: 20px; }
  .recap-toggle {
    padding: 9px 20px;
    background: #1f2937;
    color: white;
    border: none;
    border-radius: 8px;
    font-weight: 700;
    cursor: pointer;
  }
  .recap-box {
    margin: 12px auto 0;
    max-width: 680px;
    text-align: left;
    background: #f0fdf4;
    border: 1px solid #bbf7d0;
    border-radius: 12px;
    padding: 18px;

    h3 { margin: 0 0 12px; color: #166534; }
    .recap-line { display: flex; gap: 10px; padding: 5px 0; font-size: 13px; line-height: 1.7;
      .k { flex-shrink: 0; width: 76px; color: #166534; font-weight: 700; }
      .v { flex: 1; color: #1f2937; word-break: break-word; }
    }
    .recap-story { margin-top: 6px; padding: 10px 12px; background: #dcfce7; border-radius: 8px; }
  }

  .next-round-box {
    margin: 26px auto 0;
    max-width: 620px;
    background: white;
    border: 1px solid #e5e7eb;
    border-radius: 14px;
    padding: 18px;
    box-shadow: 0 4px 16px rgba(0,0,0,0.06);
    text-align: left;

    h3 { margin: 0 0 12px; font-size: 16px; }
    .env-row, .max-row { display: flex; align-items: center; gap: 10px; margin-bottom: 10px;
      label { width: 70px; font-size: 13px; font-weight: 600; color: #475569; }
      input { flex: 1; padding: 9px; border: 1px solid #cbd5e1; border-radius: 8px; font-size: 14px; }
      .env-switch { font-size: 12px; color: #7c3aed; cursor: pointer; font-weight: 600; }
    }
    .actions { display: flex; gap: 10px; margin-top: 14px;
      button { flex: 1; padding: 12px; border: none; border-radius: 9px; font-weight: 800; font-size: 14px; cursor: pointer; }
      .btn-next { background: #2563eb; color: white; &:hover { background: #1d4ed8; } }
      .btn-home { background: #f1f5f9; color: #334155; }
    }
  }
}

:global(html[data-theme="dark"]) .result-page {
  h1 { color: #f3f4f6; }
  .killer-name { color: #cbd5e1; }

  .score-card {
    background: linear-gradient(135deg, #241f38 0%, #2b2346 100%);
    border-color: #4c1d95;
    .score-num { color: #c4b5fd; }
    .score-grade { color: #a78bfa; }
    .score-bars .bar-row {
      color: #ddd6fe;
      .bar { background: #3a3154; }
    }
    .clue-stat { color: #a78bfa; }
    .judge-box {
      border-top-color: #4c1d95;
      color: #ddd6fe;
      h4 { color: #a78bfa; }
      .judge-feedback { color: #c4b5fd; }
    }
  }

  .reason-box {
    background: #12233d;
    border-color: #1d4ed8;
    h3 { color: #93c5fd; }
    p { color: #bfdbfe; }
  }

  .guess-history {
    background: #181c24;
    border-color: #2e3441;
    h3 { color: #d7deea; }
    .guess-item { color: #b6bfcd; }
  }

  .recap-box {
    background: #0e2a1e;
    border-color: #166534;
    h3 { color: #6ee7b7; }
    .recap-line {
      .k { color: #6ee7b7; }
      .v { color: #d1fae5; }
    }
    .recap-story { background: rgba(22, 101, 52, 0.35); }
  }

  .next-round-box {
    background: #181c24;
    border-color: #2e3441;
    box-shadow: none;
    h3 { color: #e5e7eb; }
    .env-row, .max-row {
      label { color: #9aa3b2; }
      input {
        background: #10141c;
        border-color: #343b4c;
        color: #e5e7eb;
      }
    }
    .actions .btn-home { background: #2a2f3c; color: #cbd5e1; }
  }
}
</style>
