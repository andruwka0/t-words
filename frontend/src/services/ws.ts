import type { WsEvent } from '../types'

export function connectMatchWS(sessionId: string, playerRef: string, onEvent: (e: WsEvent) => void) {
  const wsBase = (import.meta.env.VITE_WS_BASE ?? 'ws://localhost:8000').replace(/\/$/, '')
  const ws = new WebSocket(`${wsBase}/ws/match/${sessionId}/${playerRef}`)
  ws.onmessage = (msg) => onEvent(JSON.parse(msg.data))
  return ws
}
