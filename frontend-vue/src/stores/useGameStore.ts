import { defineStore } from "pinia"
import type {
  ArchiveMeta,
  BoardItem,
  BubbleMessage,
  Character,
  ChatMessage,
  ClueItem,
  ClueMark,
  ClueTag,
  GameSave,
  GameState,
  GuessRecord,
  InvestigationRecord,
  RevealLogItem,
  ScoreBreakdown,
  SuspectMeta,
  TimelineMarks,
  WsMessage,
} from "@/types/game"
import { buildClues, markLabel, normText, toggleTag } from "@/utils/clueUtils"
import { computeScore } from "@/utils/scoring"
import { buildLocalHint } from "@/utils/hints"
import { buildLocalInvestigation } from "@/utils/investigation"
import { findRelevantClue } from "@/utils/questionGate"
import { connectWebSocket, sendAction, sessionIdFor } from "@/api/gameSocket"

const ACTIVE_KEY = "ai-murder-active-v1"
const ARCHIVES_KEY = "ai-murder-archives-v1"
const SAVE_VERSION = 1
export const MAX_GUESSES = 3
export const DEFAULT_HINT_POINTS = 3

let bubbleSeq = 0
function bubbleId(): string {
  bubbleSeq += 1
  return `b${Date.now().toString(36)}_${bubbleSeq.toString(36)}`
}
function randomId(): string {
  return `g${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`
}
function emptyState(): GameState {
  return {
    environment: "",
    max_characters: 5,
    characters: null,
    role_skeletons: [],
    story_details: null,
    messages: [],
    selected_character_id: null,
    num_guesses_left: MAX_GUESSES,
    result: null,
  }
}

function loadJSON<T>(key: string): T | null {
  try {
    const raw = localStorage.getItem(key)
    if (!raw) return null
    return JSON.parse(raw) as T
  } catch {
    return null
  }
}
function saveJSON(key: string, value: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch {
    // localStorage 不可用时静默降级
  }
}

function normName(name: string): string {
  return (name || "").replace(/\s+/g, "").toLowerCase()
}

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}

export const useGameStore = defineStore("game", {
  state: () => ({
    page: "home" as "home" | "game" | "result",
    round: 0,
    activeId: "",
    state: emptyState(),
    clues: [] as ClueItem[],
    chats: {} as Record<string, BubbleMessage[]>,
    notes: {} as Record<string, string[]>,
    board: [] as BoardItem[],
    hintPoints: DEFAULT_HINT_POINTS,
    investigations: [] as InvestigationRecord[],
    timelineMarks: {} as TimelineMarks,
    timelineNotes: [] as string[],
    aiBusy: false,
    aiBusyLabel: "",
    aiError: "",
    lastHint: null as string | null,
    _aiTimer: 0,
    coaxHint: "",
    _coaxTimer: 0,
    suspects: {} as Record<string, SuspectMeta>,
    draftInput: "",
    guessLog: [] as GuessRecord[],
    score: null as ScoreBreakdown | null,
    reason: "",
    myGuessName: null as string | null,
    serverAlive: false,
    waitingResume: false,
    routeName: null as string | null,
    lastChatName: null as string | null,
    serverMsgIndex: 0,
    resultSeen: false,
    archives: (loadJSON<ArchiveMeta[]>(ARCHIVES_KEY) ?? []) as ArchiveMeta[],
  }),

  actions: {
    // ---------- 存档 ----------
    snapshot(): GameSave {
      return {
        v: SAVE_VERSION,
        id: this.activeId || randomId(),
        round: this.round,
        savedAt: Date.now(),
        environment: this.state.environment,
        max_characters: this.state.max_characters,
        state: clone(this.state),
        clues: clone(this.clues),
        chats: clone(this.chats),
        notes: clone(this.notes),
        board: clone(this.board),
        hintPoints: this.hintPoints,
        investigations: clone(this.investigations),
        timelineMarks: clone(this.timelineMarks),
        timelineNotes: clone(this.timelineNotes),
        suspects: clone(this.suspects),
        draftInput: this.draftInput,
        guessLog: clone(this.guessLog),
        score: clone(this.score),
        reason: this.reason,
        myGuessName: this.myGuessName,
      }
    },

    saveNow() {
      saveJSON(ACTIVE_KEY, this.snapshot())
    },

    persistArchives() {
      saveJSON(ARCHIVES_KEY, this.archives)
    },

    applySave(save: GameSave, toResultPage = false) {
      this.activeId = save.id
      this.round = save.round
      this.state = clone(save.state)
      this.clues = clone(save.clues)
      this.chats = clone(save.chats)
      this.notes = clone(save.notes)
      this.board = clone(save.board ?? [])
      this.hintPoints = save.hintPoints ?? DEFAULT_HINT_POINTS
      this.investigations = clone(save.investigations ?? [])
      this.timelineMarks = clone(save.timelineMarks ?? {})
      this.timelineNotes = clone(save.timelineNotes ?? [])
      this.aiBusy = false
      this.aiBusyLabel = ""
      this.aiError = ""
      this.lastHint = null
      this.coaxHint = ""
      this._coaxTimer = 0
      this.suspects = clone(save.suspects)
      this.draftInput = save.draftInput ?? ""
      this.guessLog = clone(save.guessLog ?? [])
      this.score = clone(save.score ?? null)
      this.reason = save.reason ?? ""
      this.myGuessName = save.myGuessName ?? null
      this.routeName = null
      this.lastChatName = null
      const restoredMessages = this.state.messages ?? []
      const restoredMaxSeq = restoredMessages.reduce(
        (max, message) => Math.max(max, Number(message.seq) || 0),
        0,
      )
      this.serverMsgIndex = restoredMaxSeq > 0 ? restoredMaxSeq : restoredMessages.length
      this.resultSeen = Boolean(this.state.result)
      this.serverAlive = false
      this.waitingResume = !this.state.result
      this.page = toResultPage || this.state.result ? "result" : "game"
      this.ensureSuspectEntries()
    },

    /** App 启动时调用：有进行中存档则恢复到对局 */
    bootstrap(): boolean {
      const save = loadJSON<GameSave>(ACTIVE_KEY)
      if (!save || !save.state) return false
      this.applySave(save)
      return true
    },

    // ---------- 新对局 / 导航 ----------
    nextRoundNumber(): number {
      const maxRound = this.archives.reduce((max, item) => Math.max(max, item.round), 0)
      return Math.max(this.round, maxRound) + 1
    },

    archiveCurrentIfMissing() {
      const exists = this.archives.some((a) => a.id === this.activeId)
      if (exists || !this.state.characters?.length) return
      this.archives.push({
        id: this.activeId,
        round: this.round,
        startedAt: Date.now(),
        endedAt: Date.now(),
        environment: this.state.environment,
        max_characters: this.state.max_characters,
        result: this.state.result ?? null,
        killerName: this.state.killer_name,
        myGuessName: this.myGuessName,
        score: this.score,
        save: this.snapshot(),
      })
      this.persistArchives()
    },

    startNewRound(environment: string, maxCharacters: number) {
      this.archiveCurrentIfMissing()
      this.round = this.nextRoundNumber()
      this.activeId = randomId()
      this.state = { ...emptyState(), environment, max_characters: maxCharacters }
      this.clues = []
      this.chats = {}
      this.notes = {}
      this.board = []
      this.hintPoints = DEFAULT_HINT_POINTS
      this.investigations = []
      this.timelineMarks = {}
      this.timelineNotes = []
      this.aiBusy = false
      this.aiBusyLabel = ""
      this.aiError = ""
      this.lastHint = null
      this.coaxHint = ""
      this._coaxTimer = 0
      this.suspects = {}
      this.draftInput = ""
      this.guessLog = []
      this.score = null
      this.reason = ""
      this.myGuessName = null
      this.routeName = null
      this.lastChatName = null
      this.serverMsgIndex = 0
      this.resultSeen = false
      this.serverAlive = false
      this.waitingResume = false
      this.page = "game"
      this.saveNow()
    },

    backHome() {
      this.saveNow()
      this.page = "home"
    },

    goGamePage() {
      this.page = "game"
    },
    goResultPage() {
      this.page = "result"
    },

    // ---------- 新建服务端对局 / 时间线对质 / 服务端揭示 ----------
    startServerGame(environment: string, maxCharacters: number) {
      // 换局 = 换一个独立后端 session，刷新、重连都回到同一局，不会串号
      this.startNewRound(environment, maxCharacters)
      const sessionId = sessionIdFor(this.activeId)
      if (sessionId) connectWebSocket(sessionId)
      sendAction({ action: "start_game", environment, max_characters: maxCharacters })
    },

    charIndexByName(name: string): number | null {
      const chars = this.state.characters ?? []
      const resolved = this.resolveName(name)
      if (!resolved) return null
      const index = chars.findIndex((c) => c.name === resolved)
      return index >= 0 ? index : null
    },

    /** 时间线一键“对质”：切到对应嫌疑人并自动发送一句追问
     *  后端在线时走 confront 动作（服务端比对证词、登记矛盾、强制解锁）；
     *  离线时退回本地拼句后 player_message。
     */
    confrontSuspect(
      idx: number,
      questionText: string,
      sourceIdx?: number | null,
      sourceText?: string,
    ) {
      const chars = this.state.characters ?? []
      const char = chars[idx]
      const clean = (questionText ?? "").trim()
      if (!char || char.role.toLowerCase() === "victim" || !clean) return
      this.clearCoax()
      if (this.serverAlive) {
        this.setRoute(this.resolveName(char.name))
        this.state.selected_character_id = idx
        this.saveNow()
        sendAction({
          action: "confront",
          target_idx: idx,
          source_idx: sourceIdx ?? null,
          source_text: sourceText ?? "",
          context_text: clean,
        })
        return
      }
      const sameChat =
        this.routeName === this.resolveName(char.name) ||
        this.selectedSuspectName() === char.name
      if (sameChat) {
        this.sendPlayerMessage(clean)
        return
      }
      this.openConversation(idx)
      // 切换对话对象后自动发出追问（等 select 落定，避免消息串台）
      window.setTimeout(() => {
        const nowChatting =
          this.state.selected_character_id === idx ||
          this.routeName === this.resolveName(char.name)
        if (nowChatting) this.sendPlayerMessage(clean)
      }, 400)
    },

    /** 服务端 reveal_log 同步：点亮 / 补充对应锁定线索（幂等，重连安全） */
    applyRevealLog(log: RevealLogItem[]) {
      if (!Array.isArray(log) || log.length === 0) return
      let changed = false
      for (const entry of log) {
        const text = (entry.text ?? "").trim()
        if (!text) continue
        const owner = this.resolveName(entry.owner) ?? entry.owner
        const exposedAt = Number(entry.exposed_at) || Date.now()
        const found = this.clues.find(
          (c) =>
            c.kind === "investigation" &&
            c.owner === owner &&
            c.locked &&
            normText(c.text) === normText(text),
        )
        if (found) {
          found.locked = false
          found.unlockedAt = exposedAt
          changed = true
          continue
        }
        const alreadyUnlocked = this.clues.some(
          (c) =>
            c.kind === "investigation" &&
            c.owner === owner &&
            normText(c.text) === normText(text) &&
            !c.locked,
        )
        if (alreadyUnlocked) continue
        this.clues.push({
          id: randomId(),
          text,
          kind: "investigation",
          owner,
          mark: "",
          tags: [],
          locked: false,
          unlockedAt: exposedAt,
          expanded: false,
        })
        changed = true
      }
      if (changed) {
        this.clearCoax()
        this.saveNow()
      }
    },

    // ---------- 服务端消息 ----------
    updateServerMessage(msg: WsMessage<GameState>) {
      const data = msg.data
      if (!data) return

      // 动作失败：回结构化错误（code/message），不再“页面没反应 / 直接掉线”
      if (msg.type === "action_error") {
        const errCode = String((data as unknown as { code?: string }).code ?? "")
        const errText = String((data as unknown as { message?: string }).message ?? "").trim()
        this.finishAiWait()
        this.serverAlive = true
        if (errCode === "no_game" && this.waitingResume) {
          // 服务端确实没有这一局（如换机器/清库），保留本地快照并提示离线
          this.waitingResume = false
          this.serverAlive = false
          return
        }
        if (errText) {
          this.aiError = errText
          this.saveNow()
        }
        return
      }

      // 服务端已无该局（例如进程重启后空回包），保留本地快照
      const serverHasGame = Array.isArray(data.characters) && data.characters.length > 0
      if (!serverHasGame && (this.state.characters?.length ?? 0) > 0) {
        if (this.waitingResume) {
          this.waitingResume = false
          this.serverAlive = false
        }
        return
      }
      this.serverAlive = true
      this.waitingResume = false

      const prevGuesses = this.state.num_guesses_left
      let nextState: GameState = {
        ...this.state,
        ...clone(data),
        role_skeletons: this.state.role_skeletons,
      }
      // 防御：对局已结束但收到的是“剥掉作案过程”的 state_update（如旧版/交叉连接的心跳）时，
      // 保留本地已收到的完整真相，避免结算页“作案过程”被覆盖成空白
      const serverStory = data.story_details
      const serverStoryStripped = !serverStory?.murder_process
      const localStoryHasMurder = Boolean(this.state.story_details?.murder_process)
      if (this.state.result && serverStoryStripped && localStoryHasMurder) {
        nextState.story_details = {
          ...(serverStory ?? {}),
          murder_process: this.state.story_details?.murder_process ?? "",
        } as GameState["story_details"]
      }
      this.state = nextState
      if (this.state.characters?.length) this.ensureSuspectEntries()
      // 服务端 reveal_log 幂等同步：对话解锁的新内容要真正点亮左侧 / 档案里的线索
      //（此前遗漏调用导致“聊了却一直不解锁”的观感）
      if (Array.isArray(data.reveal_log) && data.reveal_log.length > 0) {
        this.applyRevealLog(data.reveal_log)
      }
      this.syncServerMessages()

      // 提示点数以服务端回执为准（ask_hint 每次回执都带 hint_points，重连重放不会重复扣）
      if (typeof data.hint_points === "number") {
        this.hintPoints = Math.max(0, Math.round(data.hint_points))
      }
      // 结算时同步后端评分与指认信息（game_over 附带 result_data / reason / guess_name）
      if (msg.type === "game_over") {
        if (typeof data.reason === "string" && data.reason) this.reason = data.reason
        if (data.guess_name) this.myGuessName = data.guess_name
        if (data.result_data) this.state.result_data = clone(data.result_data)
      }
      // 服务器裁决：扣次数但未结束 => 把最近一次指认标记为错误
      if (!this.state.result && data.num_guesses_left < prevGuesses) {
        const last = this.guessLog[this.guessLog.length - 1]
        if (last) last.correct = false
      }
      this.finishAiWait()
      this.saveNow()
    },

    /** 把服务端全量 messages 增量规整进“分角色聊天记录”。
     *  服务端每条消息带 seq：只处理“大于已见序号”的增量，
     *  心跳 / 重连回显整局消息时不会把历史气泡重复拼一遍。
     */
    syncServerMessages() {
      const messages = (this.state.messages ?? []) as ChatMessage[]
      if (!Array.isArray(messages) || messages.length === 0) return
      const hasSeq = messages.some((m) => Number.isInteger(m.seq) && Number(m.seq) > 0)
      if (!hasSeq) {
        // 旧存档兼容：没有 seq 时退回按数组下标推进
        while (this.serverMsgIndex < messages.length) {
          this.routeServerMessage(messages[this.serverMsgIndex])
          this.serverMsgIndex += 1
        }
        return
      }
      const pending = messages
        .filter((m) => Number.isInteger(m.seq) && Number(m.seq) > this.serverMsgIndex)
        .sort((a, b) => Number(a.seq) - Number(b.seq))
      for (const message of pending) {
        this.routeServerMessage(message)
      }
      const newMax = pending.reduce(
        (max, message) => Math.max(max, Number(message.seq) || 0),
        this.serverMsgIndex,
      )
      this.serverMsgIndex = newMax
    },

    resolveName(raw: string): string | null {
      const chars = this.state.characters ?? []
      if (!raw) return null
      const key = normName(raw)
      const found = chars.find((c) => normName(c.name) === key)
      return found?.name ?? null
    },

    routeServerMessage(msg: ChatMessage) {
      const text = (msg.content ?? "").trim()
      if (!text) return

      if (msg.type === "human") {
        if (text === "退出对话") {
          const target = this.routeName ?? this.lastChatName
          this.lastChatName = target
          this.routeName = null
        } else if (this.routeName) {
          // 发送时本地已乐观追加一条玩家消息，服务端回显相同内容则去重
          const chat = this.ensureChat(this.routeName)
          const last = chat[chat.length - 1]
          const duplicated =
            last && last.role === "player" && last.content === text &&
            Date.now() - (last.ts ?? 0) < 20000
          if (!duplicated) this.appendBubble(this.routeName, "player", text)
        }
        return
      }

      // AI 消息
      const investigate = text.match(/^【现场调查·(.+?)】\s*([\s\S]*)$/)
      if (investigate) {
        const target = investigate[1].trim()
        const body = investigate[2].trim() || text
        this.investigations = this.investigations.filter((i) => i.target !== target)
        this.investigations.push({
          id: randomId(),
          target,
          text: body.slice(0, 800),
          at: Date.now(),
          source: "ai",
        })
        if (this.investigations.length > 24) {
          this.investigations.splice(0, this.investigations.length - 24)
        }
        this.saveNow()
        return
      }
      const hint = text.match(/^【提示】\s*([\s\S]*)$/)
      if (hint) {
        this.lastHint = hint[1].trim() || text
        this.saveNow()
        return
      }
      const intro = text.match(/^你和\s*(.+?)\s*自然地聊了起来/)
      if (intro) {
        const name = this.resolveName(intro[1])
        if (name) {
          this.routeName = name
          this.appendBubble(name, "system", text)
        }
        return
      }
      const prefix = text.match(/^(.{1,16}?)\s*[:：]\s*/)
      if (prefix) {
        const name = this.resolveName(prefix[1])
        if (name) {
          this.routeName = name
          this.appendBubble(name, "npc", text.slice(prefix[0].length))
          this.recordExchange(name)
          return
        }
      }
      if (this.routeName) {
        this.appendBubble(this.routeName, "system", text)
      } else if (this.lastChatName) {
        // 无法归位到角色气泡时，至少让它出现在最近聊过的角色聊天里，不静默丢弃
        this.appendBubble(this.lastChatName, "system", text)
      }
    },

    ensureSuspectEntries() {
      const chars = this.state.characters ?? []
      for (const c of chars) {
        if (!this.suspects[c.name]) {
          this.suspects[c.name] = { name: c.name, role: c.role, talked: false, focus: false, exchanges: 0 }
        }
      }
    },

    ensureChat(name: string): BubbleMessage[] {
      if (!this.chats[name]) this.chats[name] = []
      return this.chats[name]
    },

    appendBubble(name: string, role: "player" | "npc" | "system", content: string) {
      const target = this.resolveName(name) ?? name
      const chat = this.ensureChat(target)
      chat.push({ id: bubbleId(), role, content, ts: Date.now(), speaker: role === "npc" ? target : undefined })
      if (role === "npc") {
        this.ensureSuspectEntries()
        const meta = this.suspects[target] ?? { name: target, role: "", talked: false, focus: false, exchanges: 0 }
        meta.talked = true
        this.suspects[target] = meta
        const noteList = this.notes[target] ?? []
        noteList.push(content)
        this.notes[target] = noteList.slice(-8)
      }
      if (this.chats[target].length > 400) {
        this.chats[target].splice(0, this.chats[target].length - 400)
      }
    },

    /** NPC 完成一次回答：不管问什么都会接话；只有问题与某条锁定线索内容相关才解锁它 */
    recordExchange(name: string) {
      const meta = this.suspects[name]
      if (meta) {
        meta.exchanges += 1
        meta.talked = true
      }

      // 服务端在线时，解锁以服务端 reveal_log 为准；本地打分只作离线兜底
      if (this.serverAlive) {
        this.saveNow()
        return
      }

      // 触发这句回答的玩家消息（该对话里最近一条玩家气泡）
      const list = this.chats[name] ?? []
      let question = ""
      for (let index = list.length - 1; index >= 0; index -= 1) {
        const item = list[index]
        if (item.role === "player") {
          question = item.content
          break
        }
      }

      const ts = Date.now()
      const story = this.state.story_details
      const lockedHere = this.clues.filter(
        (c) => c.kind === "investigation" && c.owner === name && c.locked,
      )
      const matched = lockedHere.length
        ? findRelevantClue(
            question,
            lockedHere,
            {
              victim: story?.victim_name,
              weapon: story?.murder_weapon,
              location: story?.location_found,
              suspects: (this.state.characters ?? []).map((c) => c.name),
            },
          )
        : null

      if (matched) {
        matched.locked = false
        matched.unlockedAt = ts
        this.clearCoax()
      } else {
        const remainingElsewhere = this.clues.some(
          (c) => c.kind === "investigation" && c.locked,
        )
        if (lockedHere.length > 0) {
          this.coaxOnce(name, "dig")
        } else if (remainingElsewhere) {
          this.coaxOnce(name, "switch")
        } else {
          this.clearCoax()
        }
      }
      this.saveNow()
    },

    /** 闲聊不推进调查时的轻提示（几秒后自动消失，不写入聊天与存档） */
    clearCoax() {
      window.clearTimeout(this._coaxTimer)
      this._coaxTimer = 0
      this.coaxHint = ""
    },

    coaxOnce(name: string, mode: "dig" | "switch") {
      const digTips = [
        `他回了话，但线索还没松动——把问题问到点子上：那晚的时间、地点，或跟他有关的某样东西。`,
        `“${name}”有一搭没一搭地应着。想让他说漏嘴，试着把话题往某条线索上引。`,
        `追问要带“钩子”：具体的时间、地点、人物关系或某件物品，答完才可能掉落新线索。`,
      ]
      const switchTips = [
        `“${name}”这边能挖的好像都挖完了，试试换一个还没深聊的嫌疑人。`,
        `和“${name}”再聊下去暂时问不出新东西了，去别人那里问问当晚的情况吧。`,
      ]
      const pool = mode === "dig" ? digTips : switchTips
      this.coaxHint = pool[Math.floor(Math.random() * pool.length)]
      window.clearTimeout(this._coaxTimer)
      this._coaxTimer = window.setTimeout(() => {
        this.coaxHint = ""
      }, 8000)
    },

    selectedSuspectName(): string | null {
      const chars = this.state.characters ?? []
      const id = this.state.selected_character_id
      if (id === null || !chars[id]) return null
      return chars[id].name
    },

    /** 从左侧列表点选嫌疑人：记录本地路由并发起对话 */
    openConversation(idx: number) {
      const chars = this.state.characters ?? []
      const target = chars[idx]
      if (!target || target.role.toLowerCase() === "victim") return
      this.setRoute(target.name)
      this.state.selected_character_id = idx
      this.saveNow()
      sendAction({ action: "select_character", char_id: idx })
    },

    exitConversation() {
      const target = this.routeName ?? this.lastChatName
      this.lastChatName = target
      this.routeName = null
      sendAction({ action: "player_message", text: "EXIT" })
    },

    sendPlayerMessage(text: string) {
      const clean = (text ?? "").trim()
      if (!clean) return
      this.clearCoax()
      const target = this.routeName ?? this.selectedSuspectName()
      if (!target) return
      this.routeName = target
      this.lastChatName = target
      this.appendBubble(target, "player", clean)
      this.ensureSuspectEntries()
      if (!this.serverAlive) {
        // 没有可用后端时给出明确提示，避免玩家以为“对方不回答”
        const chat = this.chats[target]
        const last = chat?.[chat.length - 1]
        const alreadyNoticed =
          last?.role === "system" && last.content.includes("服务端未连接")
        if (!alreadyNoticed) {
          this.appendBubble(
            target,
            "system",
            "⚠️ 服务端未连接，NPC 暂时回应不了。请先启动后端；如果只是后端重启过，回首页用「＋ 新建对局」重新开一局即可继续。",
          )
        }
      }
      this.saveNow()
      if (this.serverAlive) this.beginAiWait("对方正在组织回应…")
      sendAction({ action: "player_message", text: clean })
    },

    /** “AI 帮我提问”：交给后端按当前对话拟句 + oracle 预检，点击即代玩家直接发出 */
    autoAsk() {
      const target = this.routeName ?? this.selectedSuspectName()
      if (!target) return
      if (this.aiBusy) return
      this.clearCoax()
      this.routeName = target
      this.lastChatName = target
      this.ensureSuspectEntries()
      if (!this.serverAlive) {
        this.aiError = "服务端未连接，“AI 帮我提问”需要后端生成问题。请先启动后端；自动重连后重试即可。"
        return
      }
      this.beginAiWait("🤖 我正顺着刚才的话，帮你想一句能问出线索的话…")
      sendAction({ action: "auto_ask" })
    },

    // ---------- 对话路由（UI 事件） ----------
    setRoute(name: string | null) {
      this.clearCoax()
      this.routeName = name ? this.resolveName(name) : null
      if (name) this.lastChatName = this.resolveName(name)
    },

    getTranscript(name: string | null): BubbleMessage[] {
      if (!name) return []
      const resolved = this.resolveName(name)
      return this.chats[resolved ?? name] ?? []
    },

    markServerPingFailed() {
      if (this.waitingResume) {
        this.waitingResume = false
        this.serverAlive = false
      }
    },

    // ---------- 线索操作 ----------
    initCluesIfEmpty() {
      if (this.clues.length === 0 && this.state.story_details && this.state.characters?.length) {
        this.clues = buildClues(this.state.story_details, this.state.characters)
        this.saveNow()
      }
    },

    clueById(id: string): ClueItem | undefined {
      return this.clues.find((c) => c.id === id)
    },

    cycleClueMark(id: string) {
      const clue = this.clueById(id)
      if (!clue) return
      const order: ClueMark[] = ["", "viewed", "suspected", "excluded"]
      const next = order[(order.indexOf(clue.mark) + 1) % order.length]
      clue.mark = next
      this.saveNow()
    },

    setClueMark(id: string, mark: ClueMark) {
      const clue = this.clueById(id)
      if (!clue) return
      clue.mark = mark
      this.saveNow()
    },

    toggleClueTag(id: string, tag: ClueTag) {
      const clue = this.clueById(id)
      if (!clue) return
      clue.tags = toggleTag(clue.tags, tag)
      this.saveNow()
    },

    setClueExpanded(id: string, expanded: boolean) {
      const clue = this.clueById(id)
      if (clue) clue.expanded = expanded
    },

    insertDraftText(text: string) {
      this.draftInput = this.draftInput ? `${this.draftInput}\n${text}` : text
    },

    // ---------- 推理白板 ----------
    addBoardItem(kind: BoardItem["kind"], text: string, source?: string) {
      const clean = (text ?? "").trim()
      if (!clean) return
      this.board.push({
        id: randomId(),
        kind,
        text: clean.slice(0, 600),
        source: source?.slice(0, 40) || undefined,
        at: Date.now(),
      })
      if (this.board.length > 120) {
        this.board.splice(0, this.board.length - 120)
      }
      this.saveNow()
    },

    removeBoardItem(id: string) {
      const before = this.board.length
      this.board = this.board.filter((item) => item.id !== id)
      if (before !== this.board.length) this.saveNow()
    },

    clearBoard() {
      if (this.board.length === 0) return
      this.board = []
      this.saveNow()
    },

    // ---------- AI 等待 / 错误提示 ----------
    beginAiWait(label = "AI 正在生成…") {
      window.clearTimeout(this._aiTimer)
      this.aiBusy = true
      this.aiBusyLabel = label
      this.aiError = ""
      // 服务端长时间无响应时给出友好提示，避免界面无反馈
      this._aiTimer = window.setTimeout(() => {
        if (this.aiBusy) {
          this.aiBusy = false
          this.aiBusyLabel = ""
          this.aiError = "AI 暂时没有回应，请稍后再试，或检查服务连接。"
        }
      }, 26000)
    },

    finishAiWait() {
      window.clearTimeout(this._aiTimer)
      this._aiTimer = 0
      this.aiBusy = false
      this.aiBusyLabel = ""
    },

    dismissAiError() {
      this.aiError = ""
    },

    // ---------- 现场调查 ----------
    investigateTarget(target: string) {
      if (!target || this.aiBusy) return
      if (this.serverAlive) {
        this.beginAiWait(`正在勘查「${target}」…`)
        sendAction({ action: "investigate", target })
        return
      }
      // 离线 / 服务不可用时使用本地确定性兜底，保证不卡死
      const text = buildLocalInvestigation(
        this.state.story_details,
        this.state.characters ?? [],
        target,
      )
      this.investigations = this.investigations.filter((i) => i.target !== target)
      this.investigations.push({
        id: randomId(),
        target,
        text,
        at: Date.now(),
        source: "local",
      })
      this.saveNow()
    },

    removeInvestigation(id: string) {
      if (!id) return
      this.investigations = this.investigations.filter((item) => item.id !== id)
      this.saveNow()
    },

    // ---------- 提示系统（消耗提示点） ----------
    askHint() {
      if (this.hintPoints <= 0) {
        this.aiError = "提示点已用完。完成更多调查会重新积攒，先别急着放弃。"
        return false
      }
      if (this.aiBusy) return false
      if (this.serverAlive) {
        // 在线扣点以服务端回执的 hint_points 为准（断线重放不会重复扣）
        this.beginAiWait("正在翻查案卷给你一个提示…")
        sendAction({ action: "ask_hint" })
        return true
      }
      // 离线兜底：本地扣点并给出确定性提示，保证功能不哑火
      this.hintPoints -= 1
      this.saveNow()
      this.lastHint = buildLocalHint({
        story: this.state.story_details,
        suspects: (this.state.characters ?? []).filter(
          (c) => c.role.toLowerCase() !== "victim",
        ),
        talkedNames: Object.values(this.suspects)
          .filter((m) => m.talked)
          .map((m) => m.name),
        lockedOwners: [
          ...new Set(
            this.clues
              .filter((c) => c.locked && c.owner)
              .map((c) => c.owner as string),
          ),
        ],
        guessesLeft: this.state.num_guesses_left,
        boardCount: this.board.length,
      })
      return true
    },

    dismissHint() {
      this.lastHint = null
    },

    // ---------- 时间线标注 ----------
    toggleTimelineMark(rowId: string, mark: "important" | "suspect") {
      if (!rowId) return
      if (this.timelineMarks[rowId] === mark) {
        delete this.timelineMarks[rowId]
      } else {
        this.timelineMarks[rowId] = mark
      }
      this.saveNow()
    },

    addTimelineNote(text: string) {
      const clean = (text ?? "").trim()
      if (!clean) return
      this.timelineNotes.push(clean.slice(0, 300))
      if (this.timelineNotes.length > 30) {
        this.timelineNotes.splice(0, this.timelineNotes.length - 30)
      }
      this.saveNow()
    },

    removeTimelineNote(index: number) {
      if (index >= 0 && index < this.timelineNotes.length) {
        this.timelineNotes.splice(index, 1)
        this.saveNow()
      }
    },

    // ---------- 嫌疑人状态 ----------
    toggleFocus(name: string) {
      const resolved = this.resolveName(name)
      if (!resolved) return
      this.ensureSuspectEntries()
      const meta = this.suspects[resolved]
      if (meta) meta.focus = !meta.focus
      this.saveNow()
    },

    suspectIndexByName(name: string): number | null {
      const chars = this.state.characters ?? []
      const resolved = this.resolveName(name)
      if (!resolved) return null
      const index = chars.findIndex((c) => c.name === resolved)
      if (index < 0) return null
      const nonVictims = chars.filter((c) => c.role.toLowerCase() !== "victim")
      const indexInSuspects = nonVictims.findIndex((c) => c.name === resolved)
      return indexInSuspects
    },

    /** 后端结算评分 -> 本地展示结构；旧存档缺 result_data 时返回 null 走本地兜底 */
    scoreFromServer(
      resultData: GameState["result_data"] | undefined | null,
    ): ScoreBreakdown | null {
      if (!resultData || typeof resultData.total !== "number") return null
      const clamp = (value: unknown): number => {
        const numberValue = Number(value)
        return Number.isFinite(numberValue)
          ? Math.max(0, Math.min(100, Math.round(numberValue)))
          : 0
      }
      return {
        total: clamp(resultData.total),
        clueCoverage: clamp(resultData.clueCoverage),
        reasoning: clamp(resultData.reasoning),
        bonus: Math.max(0, Math.round(Number(resultData.bonus) || 0)),
      }
    },

    // ---------- 指认 / 结算 ----------
    recordGuess(suspectName: string, reasonText: string) {
      this.reason = reasonText
      this.myGuessName = suspectName
      this.guessLog.push({ at: Date.now(), suspectName, correct: false, reason: reasonText })
      this.saveNow()
    },

    finalizeResult() {
      if (this.resultSeen || !this.state.result) return
      const killerName = this.state.killer_name ?? ""
      const correct = Boolean(this.myGuessName && normName(this.myGuessName) === normName(killerName))
      const lastLog = this.guessLog[this.guessLog.length - 1]
      if (lastLog) lastLog.correct = correct
      const serverScore = this.scoreFromServer(this.state.result_data)
      this.score =
        serverScore ??
        computeScore({
          story: this.state.story_details,
          clues: this.clues,
          reason: this.reason,
          guessName: this.myGuessName,
          killerName,
          guessesLeft: this.state.num_guesses_left,
          maxGuesses: MAX_GUESSES,
        })
      this.resultSeen = true

      const exists = this.archives.some((a) => a.id === this.activeId)
      if (!exists) {
        this.archives.push({
          id: this.activeId,
          round: this.round,
          startedAt: Date.now(),
          endedAt: Date.now(),
          environment: this.state.environment,
          max_characters: this.state.max_characters,
          result: this.state.result,
          killerName,
          myGuessName: this.myGuessName,
          score: this.score,
          save: this.snapshot(),
        })
      }
      this.persistArchives()
      this.saveNow()
    },

    // ---------- 历史对局管理 ----------
    loadArchive(archive: ArchiveMeta) {
      this.applySave(archive.save, archive.result !== null)
    },

    removeArchive(id: string) {
      this.archives = this.archives.filter((a) => a.id !== id)
      this.persistArchives()
    },

    markLabel(mark: ClueMark): string {
      return markLabel(mark)
    },
  },
})

export type { Character }
