import type { ClueItem, ScoreBreakdown, StoryDetails } from "@/types/game"

function norm(text: string): string {
  return (text || "").replace(/[\s，。！？、：；“”"'（）()\-—–·.…]/g, "").toLowerCase()
}

/** 结算打分：
 *  线索完整度（已解锁/已查看线索占比）+ 推理理由关键词命中 + 指认正确加分。
 *  纯本地确定性计算，不调用大模型。 */
export function computeScore(opts: {
  story: StoryDetails | null
  clues: ClueItem[]
  reason: string
  guessName: string | null
  killerName: string
  guessesLeft: number
  maxGuesses: number
}): ScoreBreakdown {
  const { story, clues, reason, guessName, killerName, guessesLeft } = opts

  const unlocked = clues.filter((c) => !c.locked)
  const examined = clues.filter((c) => !c.locked && c.mark !== "")
  const total = Math.max(clues.length, 1)
  const clueCoverage = Math.min(
    100,
    Math.round(((examined.length * 0.7 + unlocked.length * 0.3) / total) * 100),
  )

  const reasonNorm = norm(reason)
  const terms: string[] = []
  if (killerName && killerName.length >= 2) terms.push(killerName)
  if (story?.victim_name && story.victim_name.length >= 2) terms.push(story.victim_name)
  if (story?.murder_weapon && story.murder_weapon.length >= 2) terms.push(story.murder_weapon)
  const time = story?.time_of_death?.match(/\d{1,2}[:：]?\d{0,2}/)?.[0]
  if (time) terms.push(time)

  let hit = 0
  for (const term of terms) {
    if (term && reasonNorm.includes(norm(term))) hit += 1
  }
  const lengthScore = reason.length >= 30 ? 40 : reason.length >= 12 ? 25 : reason.length >= 4 ? 10 : 0
  const termScore = terms.length ? Math.round((hit / Math.max(terms.length, 1)) * 60) : 0
  let reasoning = Math.min(100, lengthScore + termScore)
  if (!reason.trim()) reasoning = 0

  const correct = Boolean(guessName && norm(guessName) === norm(killerName))
  const bonus = (correct ? 15 : 0) + Math.max(0, guessesLeft) * 3
  const totalScore = Math.max(
    0,
    Math.min(100, Math.round(clueCoverage * 0.35 + reasoning * 0.5 + bonus)),
  )

  return {
    total: totalScore,
    clueCoverage,
    reasoning,
    bonus,
  }
}

export function gradeLabel(score: number): string {
  if (score >= 90) return "S · 名侦探"
  if (score >= 75) return "A · 老练刑警"
  if (score >= 60) return "B · 合格探员"
  if (score >= 40) return "C · 线索半解的见习生"
  return "D · 被凶手带偏的旁观者"
}
