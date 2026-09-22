import type { BubbleMessage, Character, InvestigationRecord, StoryDetails } from "@/types/game"

export interface ParsedTime {
  display: string
  minutes: number | null
}

export interface TimelineRow {
  id: string
  kind: "anchor" | "testimony" | "investigation" | "note"
  label: string
  timeDisplay: string
  minutes: number | null
  speaker: string
  text: string
  sourceMessageId?: string
}

const TIMEISH = /(?:[:：]?\d{1,2}\s*[点时]|凌晨|清晨|早上|上午|中午|午后|下午|傍晚|晚上|夜里|夜晚|半夜|深夜|昨晚|那晚|当天)/

function cleanClock(text: string): ParsedTime | null {
  const m = text.match(/(\d{1,2})[:：](\d{1,2})/)
  if (m) {
    const hours = Number(m[1])
    const mins = Number(m[2])
    if (hours <= 24 && mins < 60) {
      return { display: `${String(hours).padStart(2, "0")}:${String(mins).padStart(2, "0")}`, minutes: hours * 60 + mins }
    }
  }
  return null
}

const SEGMENTS: Array<{ regex: RegExp; offset: number }> = [
  { regex: /凌晨\s*(\d{1,2})/, offset: 0 },
  { regex: /清晨\s*(\d{1,2})/, offset: 6 },
  { regex: /早上\s*(\d{1,2})/, offset: 7 },
  { regex: /上午\s*(\d{1,2})/, offset: 9 },
  { regex: /中午\s*(\d{1,2})/, offset: 12 },
  { regex: /午后\s*(\d{1,2})/, offset: 13 },
  { regex: /下午\s*(\d{1,2})/, offset: 13 },
  { regex: /傍晚\s*(\d{1,2})/, offset: 18 },
  { regex: /晚上\s*(\d{1,2})/, offset: 19 },
  { regex: /夜里\s*(\d{1,2})/, offset: 21 },
  { regex: /夜晚\s*(\d{1,2})/, offset: 21 },
  { regex: /半夜\s*(\d{1,2})/, offset: 24 },
  { regex: /深夜\s*(\d{1,2})/, offset: 23 },
]

function cleanChinese(text: string): ParsedTime | null {
  for (const seg of SEGMENTS) {
    const m = text.match(seg.regex)
    if (m) {
      const hours = Number(m[1])
      if (hours >= 1 && hours <= 24) {
        const withHalf = text.slice(m.index ?? 0).match(/(\d{1,2})\s*[点时]\s*(?:(\d{1,2})\s*分?|(半)|(一刻)|(三刻))?/)
        const minute = withHalf ? Number(withHalf[2] ?? (withHalf[3] ? 30 : withHalf[4] ? 15 : withHalf[5] ? 45 : 0)) : 0
        return { display: `${String(hours).padStart(2, "0")}:${String(minute).padStart(2, "0")}`, minutes: (hours + seg.offset) * 60 + minute }
      }
    }
  }
  const bare = text.match(/(\d{1,2})\s*点\s*(?:(\d{1,2})\s*分?|(半)|(一刻))?/)
  if (bare) {
    const hours = Number(bare[1])
    const minute = Number(bare[2] ?? (bare[3] ? 30 : bare[4] ? 15 : 0))
    if (hours >= 1 && hours <= 24) {
      return { display: `${String(hours).padStart(2, "0")}:${String(minute).padStart(2, "0")}`, minutes: hours * 60 + minute }
    }
  }
  return null
}

export function parseTimeIn(text: string): ParsedTime | null {
  if (!text) return null
  return cleanClock(text) ?? cleanChinese(text)
}

function short(text: string, max = 140): string {
  const clean = (text ?? "").replace(/\s+/g, " ").trim()
  return clean.length > max ? `${clean.slice(0, max)}…` : clean
}

function timeish(text: string): boolean {
  return TIMEISH.test(text)
}

export interface TimelineBuildOptions {
  story: StoryDetails | null
  characters: Character[]
  chats: Record<string, BubbleMessage[]>
  investigations: InvestigationRecord[]
  timelineNotes: string[]
}

export function buildTimelineRows(opts: TimelineBuildOptions): TimelineRow[] {
  const rows: TimelineRow[] = []
  const { story, characters, chats, investigations, timelineNotes } = opts

  if (story) {
    const deathTime = parseTimeIn(story.time_of_death)
    rows.push({
      id: "anchor-death",
      kind: "anchor",
      label: "死亡时间",
      timeDisplay: (deathTime?.display ?? story.time_of_death) || "不详",
      minutes: deathTime?.minutes ?? null,
      speaker: "案情基准",
      text: `${story.victim_name} 被发现死于 ${story.location_found}，死因：${story.cause_of_death || "待确认"}（${story.murder_weapon}）。`,
    })
    const sceneTime = parseTimeIn(story.crime_scene_details)
    if (sceneTime) {
      rows.push({
        id: "anchor-scene",
        kind: "anchor",
        label: "现场",
        timeDisplay: sceneTime.display,
        minutes: sceneTime.minutes,
        speaker: "案情基准",
        text: short(story.crime_scene_details),
      })
    }
    if (story.witnesses && timeish(story.witnesses)) {
      rows.push({
        id: "anchor-witness",
        kind: "anchor",
        label: "目击记录",
        timeDisplay: parseTimeIn(story.witnesses)?.display ?? "—",
        minutes: parseTimeIn(story.witnesses)?.minutes ?? null,
        speaker: "案情基准",
        text: short(story.witnesses),
      })
    }
  }

  for (const character of characters) {
    const name = character.name
    const messages = chats[name] ?? []
    for (const msg of messages) {
      if (msg.role !== "npc") continue
      if (!timeish(msg.content)) continue
      const parsed = parseTimeIn(msg.content)
      rows.push({
        id: `msg-${msg.id}`,
        kind: "testimony",
        label: parsed ? "证词" : "行踪",
        timeDisplay: parsed?.display ?? "—",
        minutes: parsed?.minutes ?? null,
        speaker: name,
        text: short(msg.content),
        sourceMessageId: msg.id,
      })
    }
  }

  for (const inv of investigations) {
    const parsed = parseTimeIn(inv.text)
    rows.push({
      id: `inv-${inv.id}`,
      kind: "investigation",
      label: "现场调查",
      timeDisplay: parsed?.display ?? "—",
      minutes: parsed?.minutes ?? null,
      speaker: inv.target,
      text: short(inv.text),
    })
  }

  timelineNotes.forEach((note, index) => {
    const parsed = parseTimeIn(note)
    rows.push({
      id: `note-${index}-${note.length}`,
      kind: "note",
      label: "我的笔记",
      timeDisplay: parsed?.display ?? "—",
      minutes: parsed?.minutes ?? null,
      speaker: "我",
      text: short(note),
    })
  })

  const order: Record<TimelineRow["kind"], number> = { anchor: 0, investigation: 1, testimony: 2, note: 3 }
  return rows.sort((a, b) => {
    const am = a.minutes ?? 9999
    const bm = b.minutes ?? 9999
    if (am !== bm) return am - bm
    return order[a.kind] - order[b.kind]
  })
}

export interface ContradictionGroup {
  timeDisplay: string
  rows: TimelineRow[]
  reason: string
}

/** 弱启发：同一时间点有不同说话人的“行踪/证词”时，提示可能存在矛盾 */
export function findContradictionGroups(rows: TimelineRow[]): ContradictionGroup[] {
  const groups = new Map<string, TimelineRow[]>()
  for (const row of rows) {
    if (row.kind !== "testimony" || row.minutes === null) continue
    const key = String(row.minutes)
    const list = groups.get(key) ?? []
    list.push(row)
    groups.set(key, list)
  }
  const result: ContradictionGroup[] = []
  for (const [minutesKey, list] of groups.entries()) {
    const speakers = new Set(list.map((r) => r.speaker))
    if (speakers.size >= 2) {
      result.push({
        timeDisplay: list[0].timeDisplay,
        rows: [...list],
        reason: `多名证人对 ${list[0].timeDisplay} 前后的行踪说法不同，值得交叉追问。`,
      })
    }
    void minutesKey
  }
  return result
}
