# Telegram OpenRouter Summary Bot

Private Telegram bot that reads allowed Telegram channel posts, opens links in the post, and replies with a colloquial Iranian Farsi summary using an LLM via OpenRouter.

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
OPENROUTER_API_KEY=...
OPENROUTER_MODEL=openai/gpt-4o-mini
```

Get an API key at [openrouter.ai/keys](https://openrouter.ai/keys). `OPENROUTER_MODEL` can be any
model slug OpenRouter supports (e.g. `google/gemini-2.5-flash`, `anthropic/claude-3.5-haiku`).

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

## Folder Digest (`channel_digest.py`)

A separate script that logs in with your own Telegram account (via Telethon) and posts one
daily digest per channel from a Telegram folder you've already set up.

1. In the Telegram app, create a **folder** and add the channels you want summarized to it.
2. Create (or pick) a destination channel/chat, and make sure your account can post there.
3. In `.env`, set:

```env
DIGEST_FOLDER_NAME=your_folder_name
DIGEST_TARGET_CHAT=your_target_channel_username_or_id
DIGEST_HOURS=24
```

4. Run it:

```bash
.venv/bin/python channel_digest.py
```

On first run it will prompt you to log in to your Telegram account (same as `bot.py`) if no
Telethon session exists yet at `TELETHON_SESSION`.

For each channel in the folder, it pulls new posts (see below), merges them, and asks the
OpenRouter model for a single combined professional Farsi digest, then sends it to
`DIGEST_TARGET_CHAT` with a header linking back to the source channel. Channels with no new
posts are skipped.

It tracks the last processed message per channel in `digest_state.json` (saved next to your
Telethon session). The first run per channel falls back to the last `DIGEST_HOURS` hours; every
run after that only picks up messages newer than the last run, so it's safe to run it as often as
you like without re-sending duplicate digests.

To run it automatically, schedule it with cron, e.g. once a day:

```cron
0 9 * * * cd /path/to/channel-summary && .venv/bin/python channel_digest.py >> digest.log 2>&1
```

Or see [Docker](#docker) below for a containerized loop instead of cron.

## Docker

Build and run both `bot.py` and `channel_digest.py` as containers:

```bash
cp .env.example .env   # fill in your values first
docker compose build
```

The `bot` and `digest` services each get their **own** Telethon session file
(`/data/bot_session` and `/data/digest_session`, in the shared `telegram_data` volume) so the two
processes never touch the same SQLite session file at once — sharing one session across processes
causes login corruption.

Log in once per service (interactive — you'll be prompted for phone/code/2FA same as locally):

```bash
docker compose run --rm bot python telethon_login.py
docker compose run --rm digest python telethon_login.py
```

Then start everything:

```bash
docker compose up -d
```

- `bot` runs `bot.py` continuously (long-polling), restarting automatically.
- `digest` runs `digest_loop.sh`, which calls `channel_digest.py` then sleeps. The sleep interval
  defaults to `DIGEST_HOURS` (in seconds); override it independently with `DIGEST_LOOP_SECONDS` in
  `.env` if you want the loop to run more often than the summarization window (safe, thanks to the
  per-channel state tracking above).

Check logs with `docker compose logs -f bot` / `docker compose logs -f digest`.
