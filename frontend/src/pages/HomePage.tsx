import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { login, register, startMatchmaking } from '../services/api'
import { useAppStore } from '../store/appStore'
import type { UserProfile } from '../types'

type AuthMode = 'login' | 'register'

export function HomePage() {
  const [authMode, setAuthMode] = useState<AuthMode>('login')
  const [loginValue, setLoginValue] = useState('')
  const [nickname, setNickname] = useState('')
  const [password, setPassword] = useState('')
  const [pack, setPack] = useState('basic')
  const [bot, setBot] = useState('medium')
  const [error, setError] = useState('')
  const [isBusy, setIsBusy] = useState(false)
  const { profile, setProfile, setMatch, setStatus } = useAppStore()
  const nav = useNavigate()

  async function submitAuth() {
    setError('')
    setIsBusy(true)
    try {
      const nextProfile = authMode === 'register'
        ? await register({ login: loginValue, password, nickname }) as UserProfile
        : await login({ login: loginValue, password }) as UserProfile
      setProfile(nextProfile)
      setPassword('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не получилось войти')
    } finally {
      setIsBusy(false)
    }
  }

  async function play() {
    if (!profile) return
    setError('')
    setIsBusy(true)
    try {
      setStatus('searching')
      nav('/search')
      const started = await startMatchmaking({
        user_id: profile.id,
        dictionary_pack: pack,
        mode: 'bot',
        bot_level: bot
      }) as { match_id: number; session_id: string; player_ref: string }
      setMatch(started.match_id, started.session_id, started.player_ref)
      setStatus('started')
      nav('/match')
    } catch (err) {
      setStatus('idle')
      setError(err instanceof Error ? err.message : 'Матч не стартовал')
      nav('/')
    } finally {
      setIsBusy(false)
    }
  }

  if (!profile) {
    return (
      <section className="auth-grid">
        <div className="panel">
          <h2>{authMode === 'login' ? 'Вход в профиль' : 'Новый профиль'}</h2>
          <div className="segmented">
            <button className={authMode === 'login' ? 'active' : ''} onClick={() => setAuthMode('login')}>Вход</button>
            <button className={authMode === 'register' ? 'active' : ''} onClick={() => setAuthMode('register')}>Регистрация</button>
          </div>
          <label>
            Логин
            <input value={loginValue} onChange={e => setLoginValue(e.target.value)} placeholder="player-login" />
          </label>
          {authMode === 'register' && (
            <label>
              Никнейм
              <input value={nickname} onChange={e => setNickname(e.target.value)} placeholder="Имя в игре" required minLength={2} />
            </label>
          )}
          <label>
            Пароль
            <input value={password} onChange={e => setPassword(e.target.value)} type="password" placeholder="••••" />
          </label>
          {error && <p className="error">{error}</p>}
          <button disabled={isBusy} onClick={submitAuth}>{authMode === 'login' ? 'Войти' : 'Создать профиль'}</button>
        </div>
        <div className="panel muted-panel">
          <h2>Профиль игрока</h2>
          <p>После входа игра привяжет матчи, монеты, скорость слов и победы над ботами к вашему ID.</p>
        </div>
      </section>
    )
  }

  return (
    <section className="panel">
      <div className="hero-line">
        <div>
          <h2>Привет, {profile.nickname}</h2>
          <p>ID профиля: {profile.public_id}</p>
        </div>
        <button disabled={isBusy} onClick={play}>Играть</button>
      </div>
      {error && <p className="error">{error}</p>}
      <div className="settings-grid">
        <label>
          Словарь
          <select value={pack} onChange={e => setPack(e.target.value)}>
            <option value="basic">basic</option>
            <option value="slang">slang</option>
          </select>
        </label>
        <label>
          Уровень бота
          <select value={bot} onChange={e => setBot(e.target.value)}>
            <option value="easy">Начальный</option>
            <option value="medium">Средний</option>
            <option value="hard">Сложный</option>
          </select>
        </label>
      </div>
      <div className="stat-strip">
        <span>{profile.coins} монет</span>
        <span>{profile.bot_wins.easy + profile.bot_wins.medium + profile.bot_wins.hard} побед над ботами</span>
        <span>{profile.fastest_word_seconds ? `${profile.fastest_word_seconds.toFixed(2)} c лучшее слово` : 'Скорость пока не замерена'}</span>
      </div>
    </section>
  )
}
