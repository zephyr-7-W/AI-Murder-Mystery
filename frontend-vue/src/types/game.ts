/** 和后端 Pydantic 模型严格对齐 */
export interface Character {
  role: string
  name: string
  backstory: string
  persona?: string
  relation_to_victim: string
}

export interface StoryDetails {
  victim_name: string
  time_of_death: string
  location_found: string
  murder_weapon: string
  cause_of_death: string
  crime_scene_details: string
  witnesses: string
  initial_clues: string
  npc_brief: string
  murder_process: string
}

/** 后端历史遗留的骨架快照字段（暂未使用，保留兼容） */
export interface RoleSkeletonSnapshot {
  role_id: string
  role_name: string
  role_type: string
  turn_index: number
  exposure_level: number
  leak_hits: number
  mode: string
  last_player_message: string
  last_npc_message: string
  notable_topics: string[]
  knowledge_boundary: string[]
  bottom_lines: string[]
  visible_notes: string[]
}

/** 服务端下发的原始消息 */
export interface ChatMessage {
  type: "human" | "ai"
  content: string
  /** 服务端消息序号（本局从 1 起）；多端/重连按它做幂等续接 */
  seq?: number
  ts?: number
}

/** 前端本地展示用的气泡消息（区分发言方） */
export type BubbleRole = "player" | "npc" | "system"

export interface BubbleMessage {
  id: string
  role: BubbleRole
  content: string
  ts?: number
  speaker?: string
}

/** 线索标记：已查看 / 怀疑 / 已排除 */
export type ClueMark = "" | "viewed" | "suspected" | "excluded"
/** 线索标签：⭐ 🔴 🟢 */
export type ClueTag = "star" | "red" | "green"

export interface ClueItem {
  id: string
  text: string
  kind: "public" | "investigation"
  /** 调查解锁线索的归属嫌疑人（public 类型为空） */
  owner?: string
  mark: ClueMark
  tags: ClueTag[]
  locked: boolean
  unlockedAt?: number
  expanded: boolean
}

export interface SuspectMeta {
  name: string
  role: string
  /** 是否已进行过对话调查 */
  talked: boolean
  /** 是否为重点怀疑对象 */
  focus: boolean
  /** 有效问答回合数（玩家问题 + NPC 回答算 1 回合） */
  exchanges: number
}

/** 推理白板条目：线索 / 对话摘录 / 手写笔记 */
export interface BoardItem {
  id: string
  kind: "clue" | "quote" | "note"
  text: string
  source?: string
  at: number
}

/** 现场调查记录（后端 AI 生成或本地兜底） */
export interface InvestigationRecord {
  id: string
  target: string
  text: string
  at: number
  source: "ai" | "local"
}

/** 时间线标记：statement id -> 标记类型 */
export type TimelineMark = "important" | "suspect"
export type TimelineMarks = Record<string, TimelineMark>

export interface GuessRecord {
  at: number
  suspectName: string
  correct: boolean
  reason: string
}

export interface ScoreBreakdown {
  /** 综合得分 0-100 */
  total: number
  /** 线索收集完整度 0-100 */
  clueCoverage: number
  /** 推理理由得分 0-100 */
  reasoning: number
  /** 指认正确等加分项 */
  bonus: number
}

/** 服务端已放行的结构化揭示（重连后据此幂等点亮线索） */
export interface RevealLogItem {
  id?: string
  owner: string
  text: string
  exposed_at?: number
}

export interface GameState {
  environment: string
  max_characters: number
  characters: Character[] | null
  role_skeletons: RoleSkeletonSnapshot[]
  story_details: StoryDetails | null
  messages: ChatMessage[]
  /** 服务端真相 oracle 已放行的揭示（增量/幂等同步线索解锁） */
  reveal_log?: RevealLogItem[]
  selected_character_id: number | null
  num_guesses_left: number
  result: "win" | "lose" | null
  killer_name?: string
  victim_report?: string
  /** 服务端最新消息序号（配合增量同步 / 断线续接） */
  server_seq?: number
  /** 后端结算评分（game_over 时附带） */
  result_data?: {
    total: number
    clueCoverage: number
    reasoning: number
    bonus: number
    grade?: string
    keyPointsFound?: string[]
    keyPointsMissed?: string[]
    feedback?: string
  }
  guess_name?: string
  reason?: string
  hint_points?: number
}

/** 单局完整存档（localStorage），用于刷新续玩 / 历史读取 */
export interface GameSave {
  v: number
  id: string
  round: number
  savedAt: number
  environment: string
  max_characters: number
  state: GameState
  clues: ClueItem[]
  chats: Record<string, BubbleMessage[]>
  notes: Record<string, string[]>
  board: BoardItem[]
  hintPoints: number
  investigations: InvestigationRecord[]
  timelineMarks: TimelineMarks
  timelineNotes: string[]
  suspects: Record<string, SuspectMeta>
  draftInput: string
  guessLog: GuessRecord[]
  score: ScoreBreakdown | null
  reason: string
  myGuessName: string | null
}

/** 历史对局元信息（localStorage 存档列表） */
export interface ArchiveMeta {
  id: string
  round: number
  startedAt: number
  endedAt?: number
  environment: string
  max_characters: number
  result: "win" | "lose" | null
  killerName?: string
  myGuessName?: string | null
  score?: ScoreBreakdown | null
  save: GameSave
}

/** websocket 下发消息类型 */
export type WsMsgType = "game_init" | "state_update" | "game_over" | "pong" | "action_ack" | "action_error"
export interface WsMessage<T = any> {
  type: WsMsgType
  data: T
}

/** websocket 发送动作 */
export type GameAction = {
  /** 客户端消息 id：断线重连补发 lastAction 时，服务端按它去重，避免同一句被回两遍 */
  client_msg_id?: string
} & (
  | { action: "start_game"; environment: string; max_characters: number }
  | { action: "select_character"; char_id: number | null }
  | { action: "inspect_victim"; char_id: number }
  | { action: "player_message"; text: string }
  | { action: "make_guess"; guess_idx: number; reason?: string }
  | { action: "auto_ask" }
  | { action: "investigate"; target: string }
  | { action: "ask_hint" }
  | {
      action: "confront"
      /** 要找谁对质（嫌疑人下标） */
      target_idx: number
      /** 这句话最初是谁说的（可选，用于后端登记矛盾） */
      source_idx?: number | null
      source_text?: string
      context_text?: string
    }
)
