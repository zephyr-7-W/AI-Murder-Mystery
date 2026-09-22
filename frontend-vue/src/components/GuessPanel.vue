<template>
  <div class="accuse-mask" @click.self="emit('cancel')">
    <div class="accuse-modal">
      <header class="accuse-head">
        <div>
          <h3>🔪 最终指认</h3>
          <p class="sub">选一名嫌疑人并写下你的推理依据，提交后立刻结算。</p>
        </div>
        <button class="close" @click="emit('cancel')">✕</button>
      </header>

      <div class="body">
        <label class="field-label">指认谁是真凶？</label>
        <div class="suspect-grid">
          <button
            v-for="(c, idx) in suspectList"
            :key="c.name"
            class="suspect-chip"
            :class="{ selected: selectedIdx === idx }"
            @click="pick(idx)"
          >
            <span class="dot" :class="dotClass(c)"></span>
            <span class="nm">{{ c.name }}</span>
            <span v-if="c.relation_to_victim" class="rel">{{ c.relation_to_victim }}</span>
          </button>
        </div>

        <label class="field-label">你的推理理由（写出你的证据链会显著提高得分）</label>
        <textarea
          v-model="reason"
          rows="4"
          maxlength="400"
          placeholder="例：他自称在二楼看书，但鞋印和烛台位置都对不上……"
        />
        <div class="helper-line">
          <span>{{ reason.length }}/400</span>
          <span v-if="validation" class="error-text">{{ validation }}</span>
        </div>
      </div>

      <footer class="foot">
        <span class="attempts">剩余指认机会：{{ store.state.num_guesses_left }}</span>
        <button class="btn-cancel" @click="emit('cancel')">再想想</button>
        <button class="btn-submit" :disabled="!canSubmit" @click="submit">提交指认</button>
      </footer>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from "vue"
import { useGameStore } from "@/stores/useGameStore"
import type { Character } from "@/types/game"

const props = defineProps<{ allCharacters: Character[] }>()
const emit = defineEmits<{ submit: [{ name: string; reason: string }]; cancel: [] }>()
const store = useGameStore()

const selectedIdx = ref<number | null>(null)
const reason = ref("")
const validation = ref("")

const suspectList = computed(() =>
  props.allCharacters.filter((c) => c.role.toLowerCase() !== "victim"),
)

const canSubmit = computed(() => selectedIdx.value !== null && reason.value.trim().length >= 4)

function dotClass(c: Character): string {
  const meta = store.suspects[c.name]
  if (meta?.focus) return "focus"
  if (meta?.talked) return "talked"
  return "none"
}

function pick(idx: number) {
  selectedIdx.value = idx
  validation.value = ""
}

function submit() {
  const target = selectedIdx.value === null ? null : suspectList.value[selectedIdx.value]
  if (!target) {
    validation.value = "请先选择一名嫌疑人。"
    return
  }
  if (reason.value.trim().length < 4) {
    validation.value = "请至少写一句你的推理理由，理由会参与打分。"
    return
  }
  emit("submit", { name: target.name, reason: reason.value.trim() })
}
</script>

<style scoped lang="scss">
.accuse-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 70;
  padding: 18px;
}

.accuse-modal {
  width: min(560px, 96vw);
  background: white;
  border-radius: 14px;
  box-shadow: 0 20px 50px rgba(0,0,0,0.28);
  display: flex;
  flex-direction: column;
  overflow: hidden;

  .accuse-head {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    padding: 16px 18px 10px;
    border-bottom: 1px solid #fee2e2;

    h3 { margin: 0; color: #991b1b; font-size: 17px; }
    .sub { margin: 4px 0 0; font-size: 12px; color: #9ca3af; }
    .close { background: none; border: none; font-size: 16px; color: #6b7280; cursor: pointer; }
  }

  .body {
    padding: 14px 18px;
    overflow-y: auto;
    max-height: 50vh;

    .field-label {
      display: block;
      font-size: 13px;
      font-weight: 700;
      color: #374151;
      margin: 10px 0 6px;
    }

    .suspect-grid {
      display: flex;
      flex-direction: column;
      gap: 6px;

      .suspect-chip {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 8px 12px;
        border: 1px solid #e5e7eb;
        background: #f9fafb;
        border-radius: 8px;
        cursor: pointer;
        text-align: left;
        font-size: 13px;

        &:hover { border-color: #fca5a5; background: #fef2f2; }
        &.selected { border-color: #dc2626; background: #fef2f2; box-shadow: 0 0 0 2px rgba(220,38,38,0.12); }

        .dot {
          width: 9px; height: 9px; border-radius: 50%; flex-shrink: 0;
          &.focus { background: #dc2626; }
          &.talked { background: #22c55e; }
          &.none { background: #d1d5db; }
        }
        .nm { font-weight: 700; color: #1f2937; }
        .rel { font-size: 11px; color: #9ca3af; }
      }
    }

    textarea {
      width: 100%;
      box-sizing: border-box;
      border: 1px solid #cbd5e1;
      border-radius: 8px;
      padding: 10px;
      font-size: 13px;
      line-height: 1.6;
      resize: vertical;
      font-family: inherit;

      &:focus { outline: none; border-color: #dc2626; }
    }

    .helper-line {
      display: flex;
      justify-content: space-between;
      margin-top: 4px;
      font-size: 11px;
      color: #9ca3af;

      .error-text { color: #dc2626; font-weight: 600; }
    }
  }

  .foot {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 12px 18px;
    border-top: 1px solid #e5e7eb;

    .attempts { flex: 1; font-size: 12px; color: #b45309; }

    button {
      padding: 9px 18px;
      border-radius: 8px;
      border: none;
      font-size: 13px;
      font-weight: 600;
      cursor: pointer;
    }
    .btn-cancel { background: #f3f4f6; color: #374151; }
    .btn-submit {
      background: #dc2626;
      color: white;
      &:disabled { opacity: 0.5; cursor: not-allowed; }
    }
  }
}

:global(html[data-theme="dark"]) .accuse-modal {
  background: #1a1e28;

  .accuse-head {
    border-bottom-color: #332f2f;
    h3 { color: #fca5a5; }
    .close { color: #9aa3b2; }
  }
  .body {
    .field-label { color: #cbd5e1; }
    .suspect-chip {
      background: #20242f;
      border-color: #343b4c;
      &:hover { border-color: #ef4444; background: #2a1618; }
      &.selected { border-color: #dc2626; background: #3a1216; }
      .nm { color: #e5e7eb; }
      .rel { color: #7d8698; }
    }
    textarea {
      background: #10141c;
      border-color: #343b4c;
      color: #e5e7eb;
    }
  }
  .foot {
    border-top-color: #2e3441;
    .attempts { color: #fbbf24; }
    .btn-cancel { background: #2a2f3c; color: #cbd5e1; }
  }
}
</style>
