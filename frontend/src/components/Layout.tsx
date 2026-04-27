import { Link } from 'react-router-dom'
import { useAppStore } from '../store/appStore'

export function Layout({ children }: { children: React.ReactNode }) {
  const { profile, logout } = useAppStore()

  return (
    <div className="shell">
      <header>
        <div>
          <h1>Words Arena</h1>
          <p>{profile ? `${profile.nickname} · очки ${profile.total_score} · ${profile.arena}` : 'Войдите, чтобы начать матч'}</p>
        </div>
        <nav>
          <Link to="/">Главная</Link>
          <Link to="/history">История</Link>
          {profile && <Link to="/profile">Профиль</Link>}
          {profile && <button className="link-button" onClick={logout}>Выйти</button>}
        </nav>
      </header>
      <main>{children}</main>
    </div>
  )
}
