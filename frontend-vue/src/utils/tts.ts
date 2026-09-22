/** 基于浏览器 speechSynthesis 的朗读辅助（中文） */
export function isTtsSupported(): boolean {
  return typeof window !== "undefined" && "speechSynthesis" in window
}

export function speak(text: string, opts?: { onEnd?: () => void }) {
  stop()
  const clean = (text ?? "").trim()
  if (!clean) {
    opts?.onEnd?.()
    return
  }
  if (!isTtsSupported()) {
    opts?.onEnd?.()
    return
  }
  const utterance = new SpeechSynthesisUtterance(clean)
  utterance.lang = "zh-CN"
  utterance.rate = 0.95
  utterance.pitch = 1
  utterance.onend = () => {
    opts?.onEnd?.()
  }
  utterance.onerror = () => {
    opts?.onEnd?.()
  }
  window.speechSynthesis.speak(utterance)
}

export function stop() {
  if (isTtsSupported()) window.speechSynthesis.cancel()
}

export function isSpeaking(): boolean {
  return isTtsSupported() && window.speechSynthesis.speaking
}
