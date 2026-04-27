import { Link } from 'react-router-dom'
import { useAppStore } from '../store/appStore'

export function ResultPage() {
  const { matchState, playerRef } = useAppStore()
  const winner = matchState?.winner_ref
  const isWinner = Boolean(winner && playerRef && winner === playerRef)

  return (
    <section className="panel">
      <h2>{isWinner ? 'Победа' : 'Матч завершен'}</h2>
      <p>Итоговый счет:</p>
      <pre>{JSON.stringify(matchState?.scores ?? {}, null, 2)}</pre>
      <p>Слова: {(matchState?.used_words ?? []).join(', ') || 'нет данных'}</p>
      <Link className="button-link" to="/">Сыграть еще</Link>
    </section>
  )
}
