import type { UserProfile } from '../types'

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000'

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(options?.headers ?? {})
    }
  })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new Error(data.detail ?? 'request_failed')
  }
  return data
}

export async function getProfile(username: string) {
  return fetch(`${API_BASE}/profile/${username}`, { method: 'POST' }).then(r => r.json())
}

export async function register(payload: { login: string; password: string; nickname: string }): Promise<UserProfile> {
  return request<UserProfile>('/auth/register', {
    method: 'POST',
    body: JSON.stringify(payload)
  })
}

export async function login(payload: { login: string; password: string }): Promise<UserProfile> {
  return request<UserProfile>('/auth/login', {
    method: 'POST',
    body: JSON.stringify(payload)
  })
}

export async function loadProfile(userId: number): Promise<UserProfile> {
  return request<UserProfile>(`/profile/id/${userId}`)
}

export async function updateProfile(
  userId: number,
  payload: { login?: string; nickname?: string; current_password?: string; password?: string }
) {
  return request<UserProfile>(`/profile/id/${userId}`, {
    method: 'PUT',
    body: JSON.stringify(payload)
  })
}

export async function startMatchmaking(payload: { user_id: number; dictionary_pack: string; mode: string; bot_level: string }) {
  return request<{ match_id: number; session_id: string; player_ref: string }>('/matchmaking/start', {
    method: 'POST',
    body: JSON.stringify(payload)
  })
}

export async function loadHistory() {
  return fetch(`${API_BASE}/matches/history`).then(r => r.json())
}

export async function sendAppeal(payload: { match_id: number; player_ref: string; word: string; reason: string }) {
  return request('/appeals', {
    method: 'POST',
    body: JSON.stringify(payload)
  })
}
