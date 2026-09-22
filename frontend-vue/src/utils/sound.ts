/** 轻量 WebAudio 合成音效，不依赖任何音频资源文件 */
let audioCtx: AudioContext | null = null

function getCtx(): AudioContext | null {
  try {
    const AC =
      window.AudioContext ??
      (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
    if (!AC) return null
    if (!audioCtx) audioCtx = new AC()
    if (audioCtx.state === "suspended") void audioCtx.resume()
    return audioCtx
  } catch {
    return null
  }
}

function tone(
  freq: number,
  delay: number,
  duration: number,
  type: OscillatorType = "sine",
  volume = 0.045,
) {
  const ctx = getCtx()
  if (!ctx) return
  const osc = ctx.createOscillator()
  const gain = ctx.createGain()
  osc.type = type
  osc.frequency.value = freq
  const t0 = ctx.currentTime + delay
  gain.gain.setValueAtTime(0, t0)
  gain.gain.linearRampToValueAtTime(volume, t0 + 0.01)
  gain.gain.exponentialRampToValueAtTime(0.0001, t0 + duration)
  osc.connect(gain)
  gain.connect(ctx.destination)
  osc.start(t0)
  osc.stop(t0 + duration + 0.05)
}

/** 通用按钮点击：短促清脆的提示音 */
export function playClick() {
  tone(620, 0, 0.07, "triangle", 0.03)
}

/** 发送消息 */
export function playSend() {
  tone(520, 0, 0.08, "sine", 0.04)
  tone(780, 0.06, 0.1, "sine", 0.035)
}

/** 收到 NPC 新回复：轻柔的两声提示 */
export function playMessage() {
  tone(660, 0, 0.14, "sine", 0.045)
  tone(880, 0.1, 0.2, "sine", 0.04)
}

/** 解锁新线索：上行三连音 */
export function playUnlock() {
  tone(523.25, 0, 0.13, "sine", 0.05)
  tone(659.25, 0.1, 0.13, "sine", 0.05)
  tone(783.99, 0.2, 0.22, "sine", 0.045)
}

/** 错误 / 操作被拦截：低鸣提示 */
export function playError() {
  tone(220, 0, 0.16, "sawtooth", 0.028)
  tone(180, 0.07, 0.2, "sawtooth", 0.028)
}
