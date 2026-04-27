export type MatchState = {
  session_id: string
  current_letter: string
  used_words: string[]
  scores: Record<string, number>
  turn_order: string[]
  turn_index: number
  turn_started_at: number
  status?: string
  winner_ref?: string
  finish_reason?: string
  participants: { id: string; type: 'human' | 'bot'; name?: string }[]
}

export type WsEvent = { type: string; payload?: any }

export type Achievement = {
  id: string
  title: string
  description: string
  unlocked: boolean
  progress: number | null
  target: number
}

export type UserProfile = {
  id: number
  public_id: string
  login: string
  nickname: string
  username: string
  total_score: number
  arena: string
  coins: number
  fastest_word_seconds: number | null
  bot_wins: Record<'easy' | 'medium' | 'hard', number>
  achievements: Achievement[]
}
