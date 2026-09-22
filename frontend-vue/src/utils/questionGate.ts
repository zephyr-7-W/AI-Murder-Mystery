/**
 * 线索解锁判定：NPC 对任何提问都会照常回答；
 * 只有当玩家问出的问题与某条“锁定线索”的内容相关时，才点亮那一条线索。
 *
 * 相关度 = 主题命中（时间/行踪/物证/关系/目击……） + 专名命中（死者/工具/地点/人名）
 *          + 字面 n-gram 重叠，取分最高的一条解锁；分太低说明只是闲聊，不解锁。
 */

export interface ProbeContext {
  victim?: string
  weapon?: string
  location?: string
  suspects?: string[]
}

const TOPIC_RULES: Array<[string, RegExp]> = [
  // 时间 / 不在场证明
  ["time", /几[点时]|\d{1,2}\s*[:：点]|时间|时分|凌晨|清晨|早上|上午|中午|午后|下午|傍晚|晚上|夜里|半夜|深夜|当晚|那晚|昨晚|前天|几点|点半|钟|整晚|一晚上/],
  // 行踪 / 地点
  ["whereabouts", /在哪|在哪里|去哪|去哪儿|出门|离开|回来|回房|待在|房间|走廊|门口|大厅|客厅|书房|厨房|卧室|车库|花园|院子|阳台|地下室|现场|楼下|楼上|甲板|车厢|包厢|里屋|后院|别处/],
  // 作案工具 / 血迹 / 指纹
  ["weapon", /凶器|烛台|刀|匕首|手枪|枪|绳索|丝巾|毒|药|针筒|注射|杯子|玻璃|锤子|扳手|铁棒|斧头|血|指纹|脚印|毛发|伤口|利刃|钝器/],
  // 物品 / 私人物证
  ["object", /抽屉|柜子|书桌|桌子|床底|衣橱|皮箱|箱子|信封|纸条|日记|照片|钥匙|怀表|手机|戒指|项链|遗物|信|遗书|账本|船票|车票|票据|收据|发票/],
  // 死亡 / 案发
  ["death", /死|尸体|遇害|身亡|被杀|出事|案发|命案|害死|被害|血迹|致命伤|死因/],
  // 关系 / 动机
  ["relation", /关系|认识|熟悉|朋友|同事|上司|下属|恋人|情侣|夫妻|兄妹|姐弟|父母|兄弟|对手|仇人|情敌|债|欠|借钱|遗嘱|继承|家产|钱|房产|股份|合同|威胁|勒索|敲诈|秘密|隐瞒|说谎|撒谎|骗|动机|为什么|为何|恨|讨厌|嫉妒|过节|矛盾/],
  // 目击 / 证词
  ["witness", /看见|看到|听到|听见|发现|目击|路过|经过|注意到|遇到|撞见|听见|证词|说法/],
]

/** 常用虚词产生的二元组，避免“什么/怎么/你们”之类造成误匹配 */
const STOP_BIGRAMS = new Set([
  "什么", "怎么", "那个", "这个", "一个", "不是", "你们", "他们", "我们",
  "自己", "时候", "知道", "觉得", "还是", "没有", "然后", "现在", "还有",
  "真的", "今天", "明天", "因为", "如果", "但是", "所以", "而且", "可以",
  "可能", "应该", "就是", "这样", "那样", "那么", "的话", "到底", "究竟",
])

function cleanText(raw: string): string {
  return (raw ?? "")
    .replace(/[\s，。！？、；：“”"'‘’（）()\-—–·.…【】《》]+/g, "")
    .toLowerCase()
}

export function topicsOf(raw: string): Set<string> {
  const text = cleanText(raw)
  const topics = new Set<string>()
  for (const [id, regex] of TOPIC_RULES) {
    if (regex.test(text)) topics.add(id)
  }
  return topics
}

/** 命中的专名（死者/工具/地点/嫌疑人姓名） */
export function entityHits(raw: string, ctx: ProbeContext): string[] {
  const text = cleanText(raw)
  const hits: string[] = []
  const push = (term?: string) => {
    const clean = term ? cleanText(term) : ""
    if (clean.length >= 2 && text.includes(clean)) hits.push(clean)
  }
  push(ctx.victim)
  push(ctx.weapon)
  push(ctx.location)
  for (const name of ctx.suspects ?? []) push(name)
  return hits
}

function bigramsOf(raw: string): Set<string> {
  const text = cleanText(raw)
  const grams = new Set<string>()
  for (let index = 0; index < text.length - 1; index += 1) {
    grams.add(text.slice(index, index + 2))
  }
  return grams
}

/**
 * 从候选锁定线索里挑出与玩家问题最相关的一条。
 * 相关分 < 2（只有几个泛泛的词）视为闲聊，返回 null 表示不解锁。
 */
export function findRelevantClue<T extends { text: string }>(
  question: string,
  candidates: T[],
  ctx: ProbeContext,
): T | null {
  const qText = (question ?? "").trim()
  if (!qText || candidates.length === 0) return null

  const qTopics = topicsOf(qText)
  const qEntities = entityHits(qText, ctx)
  const qBigrams = bigramsOf(qText)

  let best: T | null = null
  let bestScore = 0

  for (const candidate of candidates) {
    const clueText = (candidate.text ?? "").trim()
    if (!clueText) continue

    const cTopics = topicsOf(clueText)
    const cEntities = entityHits(clueText, ctx)

    let topicIntersect = 0
    for (const topic of qTopics) {
      if (cTopics.has(topic)) topicIntersect += 1
    }

    let entityIntersect = 0
    for (const entity of qEntities) {
      if (cEntities.includes(entity)) entityIntersect += 1
    }

    const cBigrams = bigramsOf(clueText)
    let sharedBigrams = 0
    for (const gram of qBigrams) {
      if (cBigrams.has(gram) && !STOP_BIGRAMS.has(gram)) sharedBigrams += 1
    }

    const score = topicIntersect * 2 + entityIntersect * 3 + Math.min(sharedBigrams, 3)
    if (score > bestScore) {
      bestScore = score
      best = candidate
    }
  }

  return bestScore >= 2 ? best : null
}
