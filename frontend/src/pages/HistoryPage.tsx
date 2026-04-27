import { useEffect, useState } from 'react'
import { loadHistory } from '../services/api'

export function HistoryPage() {
  const [rows, setRows] = useState<any[]>([])

  useEffect(() => {
    loadHistory().then(setRows)
  }, [])

  return (
    <section className="panel">
      <h2>История матчей</h2>
      <ul className="history-list">
        {rows.map(row => (
          <li key={row.id}>
            <span>#{row.id}</span>
            <span>{row.mode}</span>
            <span>{row.dictionary_pack}</span>
            <span>{row.winner_name ? `победил ${row.winner_name}` : 'без победителя'}</span>
          </li>
        ))}
      </ul>
    </section>
  )
}
