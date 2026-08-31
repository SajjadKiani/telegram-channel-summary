# Telegram Gemini Summary Bot

Private Telegram bot that reads allowed Telegram channel posts, opens links in the post, and replies with a colloquial Iranian Farsi summary using Gemini.

## Features

- Deny-by-default allowlist for users, chats, and source channel usernames.
- Replies only to automatic channel-post forwards in linked discussion groups, so the output appears as a channel comment.
- Ignores normal discussion messages.
- Skips 24-hour daily digest posts.
- Excludes URLs from generated summaries.
- Keeps Telethon session files outside the repo by default.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and set your private values:

```env
TELEGRAM_BOT_TOKEN=...
TELEGRAM_API_ID=...
TELEGRAM_API_HASH=...
GEMINI_API_KEY=...
```

Access is denied unless allowlists are set:

```env
ALLOWED_USER_IDS=your_telegram_user_id
ALLOWED_CHAT_IDS=your_discussion_group_chat_id
ALLOWED_CHANNEL_USERNAMES=your_channel_username
```

Run:

```bash
./run.sh
```

On first run, Telethon may ask you to log in to the Telegram user account that has access to the channels you want to summarize.

## Channel Comments

Telegram comments are messages in a channel's linked discussion group. To comment under channel posts:

1. Link a discussion group to the channel.
2. Add the bot to that discussion group.
3. Allow the discussion group ID in `ALLOWED_CHAT_IDS`.
4. Allow the source channel username in `ALLOWED_CHANNEL_USERNAMES`.

The bot ignores direct channel-post updates, so it does not create separate channel posts.
