import asyncio
import html
import os
import re
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ChatAction, ChatType
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
from telethon import TelegramClient

from telegram_utils import (
    extract_urls,
    fetch_pages,
    generate_with_openrouter,
    is_daily_digest,
    preserve_telethon_text_links,
    utf16_offset_to_py_index,
)


load_dotenv()

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_API_ID = int(os.environ["TELEGRAM_API_ID"])
TELEGRAM_API_HASH = os.environ["TELEGRAM_API_HASH"]

TELETHON_SESSION = os.getenv("TELETHON_SESSION") or str(
    Path.home() / ".local" / "share" / "telegram-gemini-summary-bot" / "telegram_user_session"
)
ALLOWED_USER_IDS = {
    int(value.strip())
    for value in os.getenv("ALLOWED_USER_IDS", "").split(",")
    if value.strip()
}
ALLOWED_CHAT_IDS = {
    int(value.strip())
    for value in os.getenv("ALLOWED_CHAT_IDS", "").split(",")
    if value.strip()
}
ALLOWED_CHANNEL_USERNAMES = {
    value.strip().lower().lstrip("@")
    for value in os.getenv("ALLOWED_CHANNEL_USERNAMES", "").split(",")
    if value.strip()
}

POST_URL_RE = re.compile(r"https?://t\.me/(?:s/)?([^/\s]+)/(\d+)")

Path(TELETHON_SESSION).parent.mkdir(parents=True, exist_ok=True)
telegram_client = TelegramClient(TELETHON_SESSION, TELEGRAM_API_ID, TELEGRAM_API_HASH)


def parse_telegram_post_url(text: str) -> Optional[tuple[str, int]]:
    match = POST_URL_RE.search(text)
    if not match:
        return None
    return match.group(1), int(match.group(2))


def access_control_enabled() -> bool:
    return True


def is_allowed_update(update: Update) -> bool:
    if not access_control_enabled():
        return True

    user = update.effective_user
    chat = update.effective_chat

    if user and user.id in ALLOWED_USER_IDS:
        return True

    if chat and chat.id in ALLOWED_CHAT_IDS:
        return True

    if chat and chat.username and chat.username.lower() in ALLOWED_CHANNEL_USERNAMES:
        return True

    return False


def is_allowed_source_channel(channel: str) -> bool:
    if not ALLOWED_CHANNEL_USERNAMES:
        return True
    return channel.lower().lstrip("@") in ALLOWED_CHANNEL_USERNAMES


def is_channel_post_comment_target(message) -> bool:
    chat = message.chat

    if chat.type == ChatType.PRIVATE:
        return True

    if chat.type in {ChatType.GROUP, ChatType.SUPERGROUP}:
        return bool(getattr(message, "is_automatic_forward", False))

    return False


def preserve_bot_text_links(message) -> str:
    text = message.text or message.caption or ""
    entities = message.entities or message.caption_entities or []

    replacements = []
    for entity in entities:
        if entity.type == "text_link" and entity.url:
            start = utf16_offset_to_py_index(text, entity.offset)
            end = utf16_offset_to_py_index(text, entity.offset + entity.length)
            label = message.parse_entity(entity)
            replacements.append(
                (
                    start,
                    end,
                    f"[{label}]({entity.url})",
                )
            )

    for start, end, replacement in sorted(replacements, reverse=True):
        text = text[:start] + replacement + text[end:]

    return text


async def fetch_telegram_post_text(channel: str, message_id: int) -> str:
    message = await telegram_client.get_messages(channel, ids=message_id)

    if not message or not message.message:
        raise ValueError("I could not find text in that Telegram post.")

    return preserve_telethon_text_links(message.message, message.entities)


async def summarize_post(text: str) -> str:
    prompt = f"""
Process this NEW Telegram channel post.

1. SOURCE HANDLING:
- Read the actual post content and any fetched linked-page content.
- If the post is an X/Twitter or fxtwitter link, use the tweet text, author, and linked article as the primary source.
- Do not summarize based solely on an attached image.

2. TONE & STYLE:
- Write a clear, professional 3-5 sentence summary in standard, formal Persian (Farsi).
- Use a neutral, professional news-briefing tone. Do not use slang, colloquial expressions, or casual address terms (no "داش", "رفیق", "داداش", "آبجی", "مشتی", or similar).
- Keep it accurate, engaging, and informative.
- Include the most important details: who/what happened, why it happened, key numbers, dates, names, consequences, and any important caveats.
- Never use profanity, insults, or disrespectful language.

3. SIGNATURE:
- End the summary with this exact signature on a real standalone new line:
--ایجنت ایران بیتکوین

4. WHY IT MATTERS:
- After the summary, add one final short sentence in the same professional Persian style explaining why this post matters.
- Start that sentence naturally with "چرا اهمیت دارد؟" or "اهمیت این خبر در این است که".
- Keep this before the signature.

5. EXCLUSIONS:
- If the content is a 24-hour daily digest, return exactly: SKIP_DAILY_DIGEST

6. OUTPUT FORMAT:
[3-5 sentences of professional Farsi summary with important details]
[1 sentence explaining why it matters]
--ایجنت ایران بیتکوین

7. DO NOT INCLUDE:
- Do not include URLs.
- Do not include Markdown links.
- Do not include explanations, labels, or headers.

Content:
{text}
""".strip()

    return await generate_with_openrouter(prompt)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed_update(update):
        return

    await update.message.reply_text(
        "Send me a Telegram post URL or a message with a link. "
        "I will open the link and write a short colloquial Farsi summary with the channel signature."
    )


async def set_language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed_update(update):
        return

    await update.message.reply_text(
        "This bot is configured for short colloquial Iranian Farsi summaries."
    )


async def whoami(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat = update.effective_chat

    user_id = user.id if user else "none"
    chat_id = chat.id if chat else "none"
    chat_username = f"@{chat.username}" if chat and chat.username else "none"

    await update.effective_message.reply_text(
        f"user_id: {user_id}\nchat_id: {chat_id}\nchat_username: {chat_username}"
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Telegram channel comments are messages in the linked discussion group.
    # Ignore direct channel posts so the bot never creates a separate channel post.
    message = update.message
    if not message:
        return

    if not is_allowed_update(update):
        return

    if not is_channel_post_comment_target(message):
        return

    await message.chat.send_action(ChatAction.TYPING)

    incoming_text = message.text or message.caption or ""
    post_ref = parse_telegram_post_url(incoming_text)

    try:
        if post_ref:
            channel, message_id = post_ref
            if not is_allowed_source_channel(channel):
                await message.reply_text("That source channel is not allowed.")
                return
            source_text = await fetch_telegram_post_text(channel, message_id)
        else:
            source_text = preserve_bot_text_links(message).strip()

        if not source_text:
            await message.reply_text("Please send a Telegram post URL or a message with a link.")
            return

        if is_daily_digest(source_text):
            return

        urls = extract_urls(source_text)
        if urls:
            page_parts = await fetch_pages(urls)
            summary_input = "\n\n".join(page_parts)
        else:
            summary_input = source_text

        if is_daily_digest(summary_input):
            return

        summary = await summarize_post(summary_input)
        if summary.strip() == "SKIP_DAILY_DIGEST":
            return

        # Telegram messages are limited to 4096 chars. Leave room for formatting.
        for chunk_start in range(0, len(summary), 3900):
            chunk = summary[chunk_start : chunk_start + 3900]
            await message.reply_text(chunk, disable_web_page_preview=True)

    except Exception as exc:
        await message.reply_text(f"Could not summarize that message: {html.escape(str(exc))}")


async def post_init(app: Application) -> None:
    await telegram_client.start()


async def post_shutdown(app: Application) -> None:
    await telegram_client.disconnect()


def main() -> None:
    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("lang", set_language))
    app.add_handler(CommandHandler("whoami", whoami))
    app.add_handler(MessageHandler(filters.TEXT | filters.CaptionRegex(r".+"), handle_message))

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
