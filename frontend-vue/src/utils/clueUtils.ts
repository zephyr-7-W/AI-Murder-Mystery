import type { Character, ClueItem, ClueMark, ClueTag, StoryDetails } from "@/types/game"

let seq = 0
function nextId(): string {
  seq += 1
  return `id_${Date.now().toString(36)}_${seq.toString(36)}`
}

function norm(text: string): string {
  return text.replace(/[\s，。！？、：；“”"'（）()\-—–·.…]/g, "").toLowerCase()
}

/** 与后端 oracle 揭示放行做幂等匹配时共用的文本归一化 */
export function normText(text: string): string {
  return norm(text)
}

/** 按常见分隔拆分为线索句；拆不出多个时整体作为一条 */
export function splitClueText(text: string): string[] {
  if (!text) return []
  const parts = text
    .split(/[\n\r]+|、|；|;/g)
    .map((p) => p.trim())
    .filter(Boolean)
  if (parts.length > 1 && parts.length <= 20) return parts
  const byPunctuation = text.split(/[。！？!?]/).map((p) => p.trim()).filter(Boolean)
  if (byPunctuation.length > 1 && byPunctuation.length <= 20) return byPunctuation
  return [text.trim()].filter(Boolean)
}

function sentencesFrom(text: string): string[] {
  if (!text) return []
  return text
    .split(/[\n\r]+|[。！？!?；;]+/g)
    .map((s) => s.trim())
    .filter((s) => s.length >= 6)
}

/** 依据角色 + 案情确定性生成线索列表：
 *  公开线索来自 initial_clues；调查解锁线索从现场/目击/人物关系里提取，挂在对应嫌疑人名下，
 *  与“该嫌疑人对话”完成一回合后由 store 解锁。 */
export function buildClues(story: StoryDetails | null, characters: Character[] | null): ClueItem[] {
  if (!story) return []
  const suspects = (characters ?? []).filter((c) => c.role.toLowerCase() !== "victim")
  const clues: ClueItem[] = []

  for (const raw of splitClueText(story.initial_clues).slice(0, 14)) {
    clues.push({
      id: nextId(),
      text: raw,
      kind: "public",
      mark: "",
      tags: [],
      locked: false,
      expanded: false,
    })
  }

  const pool = sentencesFrom(
    [story.crime_scene_details, story.witnesses, story.npc_brief].join("\n"),
  )
  const usedNorm = new Set(clues.map((c) => norm(c.text)))
  const pickable = pool.filter((s) => !usedNorm.has(norm(s)))

  suspects.forEach((suspect) => {
    const hits: string[] = []
    for (const sentence of pickable) {
      if (hits.length >= 6) break
      if (sentence.includes(suspect.name) && !usedNorm.has(norm(sentence))) {
        hits.push(sentence)
        usedNorm.add(norm(sentence))
      }
    }
    const fallback: string[] = []
    for (const sentence of pickable) {
      if (fallback.length >= 6 - hits.length) break
      if (!usedNorm.has(norm(sentence))) {
        fallback.push(sentence)
        usedNorm.add(norm(sentence))
      }
    }
    const owned = [...hits, ...fallback]
    owned.slice(0, 6).forEach((text) => {
      clues.push({
        id: nextId(),
        text,
        kind: "investigation",
        owner: suspect.name,
        mark: "",
        tags: [],
        locked: true,
        expanded: false,
      })
    })
  })

  return clues
}

export function nextMark(mark: ClueMark): ClueMark {
  if (mark === "") return "viewed"
  if (mark === "viewed") return "suspected"
  if (mark === "suspected") return "excluded"
  return ""
}

export function markLabel(mark: ClueMark): string {
  if (mark === "viewed") return "已查看"
  if (mark === "suspected") return "怀疑"
  if (mark === "excluded") return "已排除"
  return "未标记"
}

export function markIcon(mark: ClueMark): string {
  if (mark === "viewed") return "👁"
  if (mark === "suspected") return "❓"
  if (mark === "excluded") return "🚫"
  return "○"
}

export function tagChar(tag: ClueTag): string {
  if (tag === "star") return "⭐"
  if (tag === "red") return "🔴"
  return "🟢"
}

export function toggleTag(tags: ClueTag[], tag: ClueTag): ClueTag[] {
  return tags.includes(tag) ? tags.filter((t) => t !== tag) : [...tags, tag]
}
