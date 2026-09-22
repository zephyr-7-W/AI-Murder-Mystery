import type { Character, StoryDetails } from "@/types/game"

/** 玩家卡关时给出的确定性弱提示（消耗提示点；仅用已解锁的公开信息） */
export function buildLocalHint(opts: {
  story: StoryDetails | null
  suspects: Character[]
  talkedNames: string[]
  lockedOwners: string[]
  guessesLeft: number
  boardCount: number
}): string {
  const { story, suspects, talkedNames, lockedOwners, guessesLeft, boardCount } = opts
  if (!story) return "先把剧情读一遍，再决定从谁开始聊。"

  if (talkedNames.length === 0) {
    return `从 ${story.location_found} 的目击者聊起最自然——先别问“案发时你在哪”，问问对方当晚的安排。`
  }
  if (lockedOwners.length > 0) {
    const names = [...new Set(lockedOwners)].slice(0, 2).join("、")
    return `线索还没挖完：继续和 ${names} 多聊几轮，追问细节（比如几点回房、见过谁）才会解锁下一条。`
  }
  if (boardCount === 0) {
    return `把已解锁的线索和可疑对话丢进🧩推理白板，试着给每个人画一条当晚的时间线。`
  }
  if (guessesLeft > 0) {
    const candidate = suspects[0]?.name
    return candidate ? `先不要急着指认。回看时间线：如果有人声称的位置和实际行踪对不上，那通常离真相不远。` : "整理好证据链就可以去指认了。"
  }
  return "机会快用完了：把最有把握的一条证据链写清楚，再提交指认。"
}
