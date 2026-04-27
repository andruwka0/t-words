CREATE TABLE IF NOT EXISTS users (
  id SERIAL PRIMARY KEY,
  username VARCHAR(64) UNIQUE NOT NULL,
  login VARCHAR(64) UNIQUE,
  nickname VARCHAR(64),
  password_hash VARCHAR(256),
  public_id VARCHAR(36) UNIQUE,
  coins INTEGER DEFAULT 0,
  fastest_word_seconds FLOAT,
  easy_bot_wins INTEGER DEFAULT 0,
  medium_bot_wins INTEGER DEFAULT 0,
  hard_bot_wins INTEGER DEFAULT 0,
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ratings (
  id SERIAL PRIMARY KEY,
  user_id INTEGER UNIQUE REFERENCES users(id),
  value INTEGER DEFAULT 1500,
  deviation INTEGER DEFAULT 350,
  volatility VARCHAR(16) DEFAULT '0.06'
);

CREATE TABLE IF NOT EXISTS matches (
  id SERIAL PRIMARY KEY,
  mode VARCHAR(32) DEFAULT 'duel',
  dictionary_pack VARCHAR(32) DEFAULT 'basic',
  winner_id INTEGER REFERENCES users(id),
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS match_participants (
  id SERIAL PRIMARY KEY,
  match_id INTEGER REFERENCES matches(id),
  user_id INTEGER REFERENCES users(id),
  participant_ref VARCHAR(64) NOT NULL,
  participant_type VARCHAR(16) DEFAULT 'human',
  score INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS appeals (
  id SERIAL PRIMARY KEY,
  match_id INTEGER REFERENCES matches(id),
  player_ref VARCHAR(64) NOT NULL,
  word VARCHAR(64) NOT NULL,
  reason TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS dictionary_words (
  id SERIAL PRIMARY KEY,
  pack VARCHAR(32) NOT NULL,
  word VARCHAR(64) NOT NULL,
  tags VARCHAR(128) DEFAULT ''
);
