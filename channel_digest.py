import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.tl.functions.messages import GetDialogFiltersRequest
from telethon.tl.types import Channel, PeerChannel, PeerChat, PeerUser

from telegram_utils import (
    extract_urls,
    fetch_pages,
    generate_with_openrouter,
    is_daily_digest,
    preserve_telethon_text_links,
)


load_dotenv()

TELEGRAM_API_ID = int(os.environ["TELEGRAM_API_ID"])
TELEGRAM_API_HASH = os.environ["TELEGRAM_API_HASH"]
DIGEST_FOLDER_NAME = os.environ["DIGEST_FOLDER_NAME"]
DIGEST_TARGET_CHAT = os.environ["DIGEST_TARGET_CHAT"]

DIGEST_HOURS = int(os.getenv("DIGEST_HOURS", "24"))
TELETHON_SESSION = os.getenv("TELETHON_SESSION") or str(
    Path.home() / ".local" / "share" / "telegram-gemini-summary-bot" / "telegram_user_session"
)

Path(TELETHON_SESSION).parent.mkdir(parents=True, exist_ok=True)
client = TelegramClient(TELETHON_SESSION, TELEGRAM_API_ID, TELEGRAM_API_HASH)

STATE_FILE = Path(TELETHON_SESSION).parent / "digest_state.json"


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state))


def _parse_chat_identifier(value: str):
    value = value.strip()

    if not value.lstrip("-").isdigit():
        return value.lstrip("@")

    if value.startswith("-100"):
        return PeerChannel(int(value[4:]))

    numeric = int(value)
    if numeric < 0:
        return PeerChat(-numeric)

    return PeerUser(numeric)


async def resolve_target_chat(value: str):
    # Telethon can only resolve a bare numeric ID's access hash if it has
    # already seen that chat, so warm the entity cache from dialogs first.
    try:
        return await client.get_entity(_parse_chat_identifier(value))
    except ValueError:
        await client.get_dialogs()
        return await client.get_entity(_parse_chat_identifier(value))


def _filter_title(dialog_filter) -> str:
    title = getattr(dialog_filter, "title", "")
    return getattr(title, "text", title) or ""


async def get_folder_channels(folder_name: str) -> list[Channel]:
    result = await client(GetDialogFiltersRequest())
    filters = getattr(result, "filters", result)

    for dialog_filter in filters:
        if _filter_title(dialog_filter).strip().lower() != folder_name.strip().lower():
            continue

        channels = []
        for peer in getattr(dialog_filter, "include_peers", []):
            try:
                entity = await client.get_entity(peer)
            except Exception:
                continue
            if isinstance(entity, Channel) and entity.broadcast:
                channels.append(entity)
        return channels

    raise ValueError(f"No Telegram folder named {folder_name!r} found in this account.")


async def collect_recent_posts(entity: Channel, since: datetime, min_id: int) -> tuple[str, int]:
    posts = []
    max_id = min_id

    # min_id > 0 means we already know where we left off last run, so pull
    # everything newer regardless of the time window. min_id == 0 (first run
    # for this channel, or state file missing) falls back to the time window.
    async for message in client.iter_messages(entity, limit=300, min_id=min_id):
        if min_id == 0 and (not message.date or message.date < since):
            break

        max_id = max(max_id, message.id)

        text = (message.message or "").strip()
        if not text or is_daily_digest(text):
            continue
        posts.append(preserve_telethon_text_links(text, message.entities))

    posts.reverse()
    return "\n\n---\n\n".join(posts), max_id


async def summarize_channel_digest(channel_title: str, posts_text: str) -> str:
    urls = extract_urls(posts_text)
    linked_context = ""
    if urls:
        pages = await fetch_pages(urls)
        linked_context = "\n\n" + "\n\n".join(pages)

    prompt = f"""
Process the last {DIGEST_HOURS} hours of posts from the Telegram channel "{channel_title}".
The posts are separated by "---" below, oldest first.

1. SOURCE HANDLING:
- Read all the posts and any fetched linked-page content together.
- Merge related posts instead of repeating the same news twice.
- Do not summarize based solely on an attached image.

2. TONE & STYLE:
- Write ONE combined 5-9 sentence digest in standard, formal Persian (Farsi) covering the most important stories from this channel today.
- Use a neutral, professional news-briefing tone. Do not use slang, colloquial expressions, or casual address terms (no "داش", "رفیق", "داداش", "آبجی", "مشتی", or similar).
- Keep it accurate, engaging, and informative.
- Include the most important details across the posts: who/what happened, why it happened, key numbers, dates, names, consequences, and any important caveats.
- Never use profanity, insults, or disrespectful language.

3. SIGNATURE:
- End the digest with this exact signature on a real standalone new line:
--ایجنت ایران بیتکوین

4. WHY IT MATTERS:
- After the digest, add one final short sentence in the same professional Persian style explaining why today's news from this channel matters.
- Start that sentence naturally with "چرا اهمیت دارد؟" or "اهمیت این خبر در این است که".
- Keep this before the signature.

5. EXCLUSIONS:
- If there is no real news in the posts (e.g. only ads, stickers, or empty chatter), return exactly: SKIP_EMPTY_DIGEST

6. OUTPUT FORMAT:
[5-9 sentences of professional Farsi digest with important details from across the posts]
[1 sentence explaining why it matters]
--ایجنت ایران بیتکوین

7. DO NOT INCLUDE:
- Do not include URLs.
- Do not include Markdown links.
- Do not include explanations, labels, or headers.

Posts:
{posts_text}{linked_context}
""".strip()

    return await generate_with_openrouter(prompt)


async def send_digest(target_entity, source_channel: Channel, title: str, summary: str) -> None:
    if source_channel.username:
        header = f"📌 [{title}](https://t.me/{source_channel.username})"
    else:
        header = f"📌 {title}"

    message = f"{header}\n\n{summary}"

    for chunk_start in range(0, len(message), 3900):
        chunk = message[chunk_start : chunk_start + 3900]
        await client.send_message(target_entity, chunk, link_preview=False)


async def main() -> None:
    await client.start()

    target_entity = await resolve_target_chat(DIGEST_TARGET_CHAT)

    since = datetime.now(timezone.utc) - timedelta(hours=DIGEST_HOURS)
    channels = await get_folder_channels(DIGEST_FOLDER_NAME)
    state = load_state()

    for entity in channels:
        title = entity.title or (f"@{entity.username}" if entity.username else str(entity.id))
        channel_key = str(entity.id)
        min_id = state.get(channel_key, 0)

        try:
            posts_text, max_id = await collect_recent_posts(entity, since, min_id)

            # Save progress before summarizing/sending so a re-run (or a
            # crash mid-loop) never re-digests messages we already saw.
            if max_id > min_id:
                state[channel_key] = max_id
                save_state(state)

            if not posts_text:
                continue

            summary = await summarize_channel_digest(title, posts_text)
            if summary.strip() in {"SKIP_EMPTY_DIGEST", "SKIP_DAILY_DIGEST"}:
                continue

            await send_digest(target_entity, entity, title, summary)
        except Exception as exc:
            print(f"Failed to digest channel {title!r}: {exc}")

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
