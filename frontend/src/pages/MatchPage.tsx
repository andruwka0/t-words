import { useEffect, useRef } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { MatchBoard } from '../features/match/MatchBoard'
import { sendAppeal } from '../services/api'
import { connectMatchWS } from '../services/ws'
import { useAppStore } from '../store/appStore'

export function MatchPage() {
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectRef = useRef(0)
  const nav = useNavigate()
  const { sessionId, playerRef, matchId, setMatchState, setTyping, setStatus, matchState } = useAppStore()

  useEffect(() => {
    if (!sessionId || !playerRef) return

    const connect = () => {
      wsRef.current = connectMatchWS(sessionId, playerRef, (evt) => {
        if (evt.type === 'match_update' || evt.type === 'bot_replaced') setMatchState(evt.payload)
        if (evt.type === 'typing') setTyping(evt.payload.player)
        if (evt.type === 'match_finished') {
          if (evt.payload?.turn_order) setMatchState(evt.payload)
          setStatus('finished')
          nav('/result')
        }
      })
      wsRef.current.onclose = () => {
        if (reconnectRef.current < 3) {
          reconnectRef.current += 1
          setStatus(`reconnecting_${reconnectRef.current}`)
          setTimeout(connect, 1000)
        }
      }
    }

    connect()
    return () => wsRef.current?.close()
  }, [sessionId, playerRef, nav, setMatchState, setTyping, setStatus])

  if (!sessionId || !playerRef) {
    return <Navigate to="/" replace />
  }

  const submitWord = (word: string, responseSeconds: number) => {
    wsRef.current?.send(JSON.stringify({ type: 'word_submit', payload: { word, response_seconds: responseSeconds } }))
  }

  const appeal = async (reason: string) => {
    if (!matchId || !matchState?.used_words.length) return
    await sendAppeal({ match_id: matchId, player_ref: playerRef, word: matchState.used_words.at(-1) ?? '', reason })
  }

  return <MatchBoard playerRef={playerRef} onSubmit={submitWord} onAppeal={appeal} />
}
