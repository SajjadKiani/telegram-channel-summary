import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient

load_dotenv()

TELEGRAM_API_ID = int(os.environ["TELEGRAM_API_ID"])
TELEGRAM_API_HASH = os.environ["TELEGRAM_API_HASH"]
TELETHON_SESSION = os.getenv("TELETHON_SESSION") or str(
    Path.home() / ".local" / "share" / "telegram-gemini-summary-bot" / "telegram_user_session"
)


async def main() -> None:
    Path(TELETHON_SESSION).parent.mkdir(parents=True, exist_ok=True)
    client = TelegramClient(TELETHON_SESSION, TELEGRAM_API_ID, TELEGRAM_API_HASH)

    await client.start()
    me = await client.get_me()

    print(f"Logged in as {me.first_name} (@{me.username}), id={me.id}.")
    print(f"Session saved at: {TELETHON_SESSION}.session")

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
