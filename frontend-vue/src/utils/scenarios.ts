/** 内置剧本预设：切换环境即切换剧本，局号由 store 自动递增 */
export interface ScenarioPreset {
  id: string
  title: string
  env: string
  blurb: string
  tags: string[]
  defaultMax: number
}

export const SCENARIOS: ScenarioPreset[] = [
  {
    id: "manor",
    title: "雨夜乡间庄园",
    env: "一座偏远的贵族乡间庄园",
    blurb: "暴雨封路后庄园断电，每个人都想藏起昨晚的行踪。",
    tags: ["经典", "庄园", "雨夜"],
    defaultMax: 5,
  },
  {
    id: "train",
    title: "雪夜豪华列车",
    env: "暴雪中的豪华列车包厢",
    blurb: "包厢门反锁，尸体却出现在走廊尽头——乘客各执一词。",
    tags: ["密闭空间", "列车"],
    defaultMax: 5,
  },
  {
    id: "cruise",
    title: "远洋游轮晚宴",
    env: "豪华远洋游轮的晚宴厅",
    blurb: "晚宴散场后，船长在货舱甲板下发现了尸体。",
    tags: ["海上", "晚宴"],
    defaultMax: 5,
  },
  {
    id: "ski",
    title: "暴雪封山度假村",
    env: "暴雪封山的滑雪度假村",
    blurb: "缆车停运、公路中断，凶手的时间线同样被“冻结”。",
    tags: ["雪山", "困局"],
    defaultMax: 5,
  },
  {
    id: "lab",
    title: "药企总部之夜",
    env: "跨国药企的总部大楼",
    blurb: "新药发布会前夜，研发员坠楼，实验数据不翼而飞。",
    tags: ["商战", "高楼"],
    defaultMax: 6,
  },
  {
    id: "asylum",
    title: "废弃病院剧本店",
    env: "废弃精神病院改建的剧本店",
    blurb: "试营业第一晚的密室杀人，有人借“游戏”动了真刀。",
    tags: ["惊悚", "密室"],
    defaultMax: 5,
  },
]

export function scenarioByEnv(env: string): ScenarioPreset | undefined {
  return SCENARIOS.find((s) => s.env === env)
}
