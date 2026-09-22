import type { GameAction, GameState, WsMessage } from "@/types/game"

/**
 * WebSocket 网关
 *
 * 1. 每个对局（activeId）对应一个独立后端 session，刷新/换局不会串号；
 * 2. 15s 心跳 ping：服务端有状态就回执整局最新状态（做增量续接），无状态回 pong；
 * 3. 断线自动指数退避重连，不再“掉线一次就丢一局”；
 * 4. 最后一条“还没等到回执”的动作会在重连后补发一次，避免“发出去没回话”。
 */

const LEGACY_SESSION_KEY = "ai-murder-ws-session"
const HEARTBEAT_MS = 15_000

let ws: WebSocket | null = null
const pendingActions: GameAction[] = []
let currentSessionId = ""
let manualClose = false

let heartbeatTimer: number | null = null
let reconnectTimer: number | null = null
let reconnectAttempts = 0

let onMessageCb: ((msg: WsMessage<GameState>) => void) | null = null
let onCloseCb: (() => void) | null = null

// 最后一条“期待服务端回执”的动作；断线时标记为重连后补发一次
let lastAction: GameAction | null = null
let awaitingAck = false
let resendOnReconnect = false

/** 由对局 activeId 派生稳定的后端 session id（URL 安全） */
export function sessionIdFor(gameId: string): string {
  const clean = (gameId || "").replace(/[^A-Za-z0-9_-]/g, "")
  return clean ? `mm-${clean}` : ""
}

/** 兼容旧版：读取曾经存进 localStorage 的固定 session（仅作兜底） */
function legacySessionId(): string {
  try {
    return localStorage.getItem(LEGACY_SESSION_KEY) ?? ""
  } catch {
    return ""
  }
}

export function getSessionId(): string {
  return currentSessionId || legacySessionId()
}

export function setSessionId(id: string) {
  if (id) currentSessionId = id
}

function stopHeartbeat() {
  if (heartbeatTimer !== null) {
    window.clearInterval(heartbeatTimer)
    heartbeatTimer = null
  }
}

function startHeartbeat() {
  stopHeartbeat()
  heartbeatTimer = window.setInterval(() => {
    if (ws && ws.readyState === WebSocket.OPEN) {
      try {
        ws.send(JSON.stringify({ action: "ping" }))
      } catch {
        // 忽略瞬时发送错误，交给 onclose 重连
      }
    }
  }, HEARTBEAT_MS)
}

function clearReconnect() {
  if (reconnectTimer !== null) {
    window.clearTimeout(reconnectTimer)
    reconnectTimer = null
  }
}

function scheduleReconnect() {
  if (manualClose || reconnectTimer !== null) return
  const delay = Math.min(30_000, 1_000 * 2 ** reconnectAttempts)
  reconnectAttempts += 1
  reconnectTimer = window.setTimeout(() => {
    reconnectTimer = null
    connectWebSocket()
  }, delay)
}

function flushPendingActions() {
  if (!ws || ws.readyState !== WebSocket.OPEN) return
  while (pendingActions.length > 0) {
    const action = pendingActions.shift()
    if (action) {
      if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(action))
    }
  }
}

function isAckMessage(type: string): boolean {
  return (
    type === "state_update" ||
    type === "game_init" ||
    type === "game_over" ||
    type === "action_ack" ||
    type === "action_error"
  )
}

/** 幂等 id：同一动作在断线补发时复用同一个 id，服务端据此去重 */
function nextClientMsgId(): string {
  return Date.now().toString(36) + "_" + Math.random().toString(36).slice(2, 10)
}

export function connectWebSocket(sessionId?: string) {
  const target = sessionId || currentSessionId || legacySessionId() || ""
  // 明确指定了不同的对局 session：先断开旧连接再建新连接
  if (sessionId && currentSessionId && sessionId !== currentSessionId && ws) {
    stopHeartbeat()
    clearReconnect()
    ws.onclose = null
    try {
      ws.close()
    } catch {
      // ignore
    }
    ws = null
    pendingActions.length = 0
    resendOnReconnect = false
    awaitingAck = false
    manualClose = false
  }
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
    if (target) currentSessionId = target
    return
  }
  if (!target) return
  currentSessionId = target
  manualClose = false
  reconnectAttempts = 0
  clearReconnect()

  ws = new WebSocket(`ws://127.0.0.1:8000/ws/game/${currentSessionId}`)

  ws.onopen = () => {
    flushPendingActions()
    if (resendOnReconnect && lastAction && ws && ws.readyState === WebSocket.OPEN) {
      try {
        ws.send(JSON.stringify(lastAction))
      } catch {
        // ignore
      }
    }
    resendOnReconnect = false
    startHeartbeat()
  }

  ws.onmessage = (event) => {
    let payload: WsMessage<GameState> | null = null
    try {
      payload = JSON.parse(event.data) as WsMessage<GameState>
    } catch {
      return
    }
    if (!payload) return
    if (isAckMessage(payload.type)) {
      awaitingAck = false
      lastAction = null
    }
    if (onMessageCb) onMessageCb(payload)
  }

  ws.onclose = () => {
    stopHeartbeat()
    ws = null
    if (!manualClose) {
      if (awaitingAck && lastAction) resendOnReconnect = true
      awaitingAck = false
      scheduleReconnect()
    }
    if (onCloseCb) onCloseCb()
  }

  ws.onerror = () => {
    // 浏览器随后会触发 onclose，交由 onclose 统一重连
  }
}

export function sendAction(action: GameAction) {
  const wrapped: GameAction = {
    ...action,
    client_msg_id: action.client_msg_id ?? nextClientMsgId(),
  }
  lastAction = wrapped
  awaitingAck = true
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    pendingActions.push(wrapped)
    if (!ws || ws.readyState === WebSocket.CLOSED) connectWebSocket()
    return
  }
  ws.send(JSON.stringify(wrapped))
}

export function setMessageCallback(cb: (msg: WsMessage<GameState>) => void) {
  onMessageCb = cb
}

export function setCloseCallback(cb: () => void) {
  onCloseCb = cb
}

export function disconnect() {
  manualClose = true
  pendingActions.length = 0
  lastAction = null
  awaitingAck = false
  resendOnReconnect = false
  stopHeartbeat()
  clearReconnect()
  if (ws) {
    ws.onclose = null
    try {
      ws.close()
    } catch {
      // ignore
    }
    ws = null
  }
}
