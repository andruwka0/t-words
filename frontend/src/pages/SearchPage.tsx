import { useAppStore } from '../store/appStore'

export function SearchPage() {
  const { status } = useAppStore()

  return (
    <section className="panel">
      <h2>Подготовка матча</h2>
      <p>Статус: {status}</p>
      <p>Матч против бота стартует сразу после создания сессии.</p>
    </section>
  )
}
