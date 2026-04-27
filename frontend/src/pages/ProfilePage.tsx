import { useEffect, useState } from 'react'
import { Navigate } from 'react-router-dom'
import { loadProfile, updateProfile } from '../services/api'
import { useAppStore } from '../store/appStore'
import type { UserProfile } from '../types'

export function ProfilePage() {
  const { profile, setProfile } = useAppStore()
  const [loginValue, setLoginValue] = useState(profile?.login ?? '')
  const [nickname, setNickname] = useState(profile?.nickname ?? '')
  const [currentPassword, setCurrentPassword] = useState('')
  const [password, setPassword] = useState('')
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    if (!profile) return
    loadProfile(profile.id)
      .then(next => {
        const typed = next as UserProfile
        setProfile(typed)
        setLoginValue(typed.login)
        setNickname(typed.nickname)
      })
      .catch(() => undefined)
  }, [])

  if (!profile) {
    return <Navigate to="/" replace />
  }

  async function saveProfile() {
    if (!profile) return
    setMessage('')
    setError('')
    try {
      const payload = {
        login: loginValue,
        nickname,
        current_password: currentPassword || undefined,
        password: password || undefined
      }
      const updated = await updateProfile(profile.id, payload) as UserProfile
      setProfile(updated)
      setCurrentPassword('')
      setPassword('')
      setMessage('Профиль обновлен')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не получилось обновить профиль')
    }
  }

  return (
    <section className="profile-grid">
      <div className="panel">
        <h2>{profile.nickname}</h2>
        <dl className="profile-list">
          <div><dt>ID</dt><dd>{profile.public_id}</dd></div>
          <div><dt>Логин</dt><dd>{profile.login}</dd></div>
          <div><dt>Очки</dt><dd>{profile.total_score}</dd></div>
          <div><dt>Арена</dt><dd>{profile.arena}</dd></div>
          <div><dt>Монеты</dt><dd>{profile.coins}</dd></div>
          <div><dt>Победы</dt><dd>easy {profile.bot_wins.easy} · medium {profile.bot_wins.medium} · hard {profile.bot_wins.hard}</dd></div>
          <div><dt>Лучшее слово</dt><dd>{profile.fastest_word_seconds ? `${profile.fastest_word_seconds.toFixed(2)} c` : 'пока нет'}</dd></div>
        </dl>
      </div>

      <div className="panel">
        <h2>Настройки</h2>
        <label>
          Логин
          <input value={loginValue} onChange={e => setLoginValue(e.target.value)} />
        </label>
        <label>
          Никнейм
          <input value={nickname} onChange={e => setNickname(e.target.value)} />
        </label>
        <label>
          Текущий пароль
          <input value={currentPassword} onChange={e => setCurrentPassword(e.target.value)} type="password" />
        </label>
        <label>
          Новый пароль
          <input value={password} onChange={e => setPassword(e.target.value)} type="password" />
        </label>
        {message && <p className="success">{message}</p>}
        {error && <p className="error">{error}</p>}
        <button onClick={saveProfile}>Сохранить</button>
      </div>

      <div className="panel achievements-panel">
        <h2>Достижения</h2>
        <div className="achievement-grid">
          {profile.achievements.map(item => (
            <article className={item.unlocked ? 'achievement unlocked' : 'achievement'} key={item.id}>
              <strong>{item.title}</strong>
              <span>{item.description}</span>
              <small>{item.unlocked ? 'Открыто' : `Прогресс: ${item.progress ?? 0}/${item.target}`}</small>
            </article>
          ))}
        </div>
      </div>
    </section>
  )
}
