import { useEffect, useMemo, useRef, useState } from 'react'
import { useAppStore } from '../../store/appStore'

export function MatchBoard({
  playerRef,
  onSubmit,
  onAppeal
}: {
  playerRef: string
  onSubmit: (word: string, responseSeconds: number) => void
  onAppeal: (reason: string) => void
}) {
  const [word, setWord] = useState('')
  const turnStartedRef = useRef(Date.now())
  const { matchState, typing } = useAppStore()

  useEffect(() => {
    if (matchState?.turn_started_at) {
      turnStartedRef.current = matchState.turn_started_at * 1000
    }
  }, [matchState?.turn_started_at, matchState?.turn_index])

  const names = useMemo(() => {
    const pairs = matchState?.participants.map(p => [p.id, p.name ?? p.id]) ?? []
    return Object.fromEntries(pairs)
  }, [matchState?.participants])

  if (!matchState) return null

  const currentTurn = matchState.turn_order[matchState.turn_index]
  const isMyTurn = currentTurn === playerRef

  function submit() {
    const cleanWord = word.trim()
    if (!cleanWord || !isMyTurn) return
    const responseSeconds = Math.max(0.1, (Date.now() - turnStartedRef.current) / 1000)
    onSubmit(cleanWord, responseSeconds)
    setWord('')
  }

  return (
    <section className="panel match-panel">
      <div className="match-topline">
        <div>
          <h2>Матч</h2>
          <p>Текущая буква: <b>{matchState.current_letter}</b></p>
        </div>
        <div className={isMyTurn ? 'turn-badge active' : 'turn-badge'}>
          {isMyTurn ? 'Ваш ход' : `Ходит ${names[currentTurn] ?? currentTurn}`}
        </div>
      </div>

      <div className="score-grid">
        {matchState.turn_order.map(ref => (
          <div className="score-cell" key={ref}>
            <span>{names[ref] ?? ref}</span>
            <strong>{matchState.scores[ref] ?? 0}</strong>
          </div>
        ))}
      </div>

      <p className="typing-line">{typing ? `${names[typing] ?? typing} печатает...` : 'Ожидаем слово'}</p>

      <div className="word-row">
        <input
          value={word}
          onChange={e => setWord(e.target.value)}
          onKeyDown={e => {
            if (e.key === 'Enter') submit()
          }}
          disabled={!isMyTurn}
          placeholder={isMyTurn ? 'Введите слово' : 'Ждем ход соперника'}
        />
        <button disabled={!isMyTurn} onClick={submit}>Отправить</button>
        <button className="secondary" onClick={() => onAppeal('Слово должно быть принято')}>Апелляция</button>
      </div>

      <div className="words-list">
        {matchState.used_words.length === 0 && <span>Слова появятся здесь</span>}
        {matchState.used_words.map((item, index) => <span key={`${item}-${index}`}>{item}</span>)}
      </div>
    </section>
  )
}
