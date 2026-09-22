import type { Character, StoryDetails } from "@/types/game"

export interface InvestigationTarget {
  id: string
  label: string
  /** 与 backend 约定使用的目标词 */
  target: string
  icon: string
  done: boolean
}

/** 从案情中推导可主动调查的现场/物品列表 */
export function buildInvestigationTargets(
  story: StoryDetails | null,
  characters: Character[],
  doneTargets: string[],
): InvestigationTarget[] {
  const targets: InvestigationTarget[] = []
  if (!story) return targets

  const push = (id: string, label: string, target: string, icon: string) => {
    if (!target.trim()) return
    targets.push({ id, label, target, icon, done: doneTargets.includes(target) })
  }

  push("scene", `勘查现场 · ${story.location_found}`, `${story.location_found}现场`, "🏚️")
  push("weapon", `检查凶器 · ${story.murder_weapon}`, `${story.murder_weapon}`, "🗡️")
  push("victim-room", `死者房间 · ${story.victim_name}`, `${story.victim_name}的房间`, "🕯️")
  push("clues", "翻查档案 · 初步线索", "初步线索档案", "📂")

  for (const c of characters) {
    if (c.role.toLowerCase() === "victim") continue
    push(`sus-${c.name}`, `${c.name}的房间`, `${c.name}的房间`, "🚪")
  }
  return targets
}

/** 服务离线 / 无 AI 时的确定性兜底文案，保证“现场调查”始终可玩 */
export function buildLocalInvestigation(
  story: StoryDetails | null,
  characters: Character[],
  target: string,
): string {
  if (!story) return "还没有可调查的对象，请先开始一局游戏。"
  const suspect = characters.find(
    (c) => c.name && target.includes(c.name) && c.role.toLowerCase() !== "victim",
  )

  if (target.includes("现场")) {
    return `你在 ${story.location_found} 又仔细转了一圈：${story.crime_scene_details}。整理下来，${story.initial_clues || "暂时没有更多发现。"}`
  }
  if (target.includes("房间")) {
    if (suspect) {
      return `${suspect.name} 的房间收拾得过于整齐，衣帽间却有一双沾着泥的鞋。他自称${story.time_of_death}前后都在房内——可桌上的怀表停在${story.time_of_death}，指针周围有擦拭过的痕迹。（离线线索）`
    }
    return `你在 ${target} 找到一封没来得及寄出的信和几枚硬币：${story.victim_name} 似乎早就预感到自己会出事，把某件东西托付给了信中提到的人。（离线线索）`
  }
  if (target.includes("凶器") || target.includes(story.murder_weapon)) {
    return `你再次检查 ${story.murder_weapon}：${story.cause_of_death}。${story.initial_clues ? `结合现场痕迹来看，${story.initial_clues}` : "上面的指纹被仔细擦过，只有一处不起眼的毛边。"}（离线线索）`
  }
  return `你把资料重新摊开：${story.npc_brief}。${story.initial_clues || "暂时没有新发现。"}（离线线索）`
}
