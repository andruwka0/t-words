import { create } from 'zustand'
import type { MatchState, UserProfile } from '../types'

const STORAGE_KEY = 'words-profile'

function loadStoredProfile(): UserProfile | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

const storedProfile = loadStoredProfile()

type AppState = {
  profile: UserProfile | null
  playerRef: string | null
  matchId: number | null
  sessionId: string | null
  matchState: MatchState | null
  status: string
  typing: string | null
  setProfile: (profile: UserProfile | null) => void
  setMatch: (matchId: number, sessionId: string, playerRef: string) => void
  setMatchState: (state: MatchState) => void
  setStatus: (status: string) => void
  setTyping: (name: string | null) => void
  logout: () => void
}

export const useAppStore = create<AppState>((set) => ({
  profile: storedProfile,
  playerRef: storedProfile ? `user_${storedProfile.id}` : null,
  matchId: null,
  sessionId: null,
  matchState: null,
  status: 'idle',
  typing: null,
  setProfile: (profile) => {
    if (profile) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(profile))
      set({ profile, playerRef: `user_${profile.id}` })
      return
    }
    localStorage.removeItem(STORAGE_KEY)
    set({ profile: null, playerRef: null, matchId: null, sessionId: null, matchState: null })
  },
  setMatch: (matchId, sessionId, playerRef) => set({ matchId, sessionId, playerRef }),
  setMatchState: (matchState) => set({ matchState }),
  setStatus: (status) => set({ status }),
  setTyping: (typing) => set({ typing }),
  logout: () => {
    localStorage.removeItem(STORAGE_KEY)
    set({ profile: null, playerRef: null, matchId: null, sessionId: null, matchState: null, status: 'idle' })
  }
}))
