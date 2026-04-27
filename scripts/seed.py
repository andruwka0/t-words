import asyncio
import json
import sys
from pathlib import Path

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db import Base, SessionLocal, engine


async def main() -> None:
    packs = json.loads((ROOT / 'app/data/packs.json').read_text(encoding='utf-8'))

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with SessionLocal() as db:
        await db.execute(text("INSERT INTO users(username) VALUES ('demo') ON CONFLICT(username) DO NOTHING"))
        await db.execute(
            text(
                "INSERT INTO ratings(user_id, value, deviation, volatility) "
                "SELECT id,1500,350,'0.06' FROM users WHERE username='demo' "
                "ON CONFLICT(user_id) DO NOTHING"
            )
        )
        for pack, words in packs.items():
            for word in words:
                await db.execute(
                    text("INSERT INTO dictionary_words(pack, word, tags) VALUES (:pack,:word,'')"),
                    {'pack': pack, 'word': word},
                )
        await db.commit()


if __name__ == '__main__':
    asyncio.run(main())
