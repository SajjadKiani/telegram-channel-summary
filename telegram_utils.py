import asyncio
import os
import re

import httpx
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from telethon.tl.types import MessageEntityTextUrl

load_dotenv()

MAX_LINKS = int(os.getenv("MAX_LINKS", "3"))
MAX_PAGE_CHARS = int(os.getenv("MAX_PAGE_CHARS", "18000"))

OPENROUTER_API_KEY = os.environ["OPENROUTER_API_KEY"]
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

URL_RE = re.compile(r"https?://[^\s<>)\]]+")
DAILY_DIGEST_RE = re.compile(
    r"(خلاصه\s+اخبار\s*(?:۲۴|24)\s*ساعت\s+گذشته|24[-\s]?hour\s+daily\s+digest|daily\s+digest)",
    re.IGNORECASE,
)


def is_daily_digest(text: str) -> bool:
    return bool(DAILY_DIGEST_RE.search(text))


def utf16_offset_to_py_index(text: str, offset: int) -> int:
    utf16_units = 0

    for index, char in enumerate(text):
        if utf16_units >= offset:
            return index
        utf16_units += 2 if ord(char) > 0xFFFF else 1

    return len(text)


def preserve_telethon_text_links(text: str, entities) -> str:
    if not entities:
        return text

    replacements = []
    for entity in entities:
        if isinstance(entity, MessageEntityTextUrl):
            start = utf16_offset_to_py_index(text, entity.offset)
            end = utf16_offset_to_py_index(text, entity.offset + entity.length)
            label = text[start:end]
            replacements.append((start, end, f"[{label}]({entity.url})"))

    for start, end, replacement in sorted(replacements, reverse=True):
        text = text[:start] + replacement + text[end:]

    return text


def extract_urls(text: str) -> list[str]:
    urls = []
    seen = set()

    for url in URL_RE.findall(text):
        clean_url = url.rstrip(".,;:!?\"'")
        if "t.me/" in clean_url:
            continue
        if clean_url not in seen:
            urls.append(clean_url)
            seen.add(clean_url)

    return urls[:MAX_LINKS]


def normalize_fetch_url(url: str) -> str:
    if "://x.com/" in url:
        return url.replace("://x.com/", "://fxtwitter.com/", 1)
    if "://twitter.com/" in url:
        return url.replace("://twitter.com/", "://fxtwitter.com/", 1)
    return url


def extract_readable_page_text(url: str) -> str:
    fetch_url = normalize_fetch_url(url)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "KHTML, like Gecko Chrome/120.0 Safari/537.36"
        )
    }

    with httpx.Client(follow_redirects=True, timeout=20, headers=headers) as client:
        response = client.get(fetch_url)
        response.raise_for_status()

    content_type = response.headers.get("content-type", "")
    if "text/html" not in content_type and "application/xhtml+xml" not in content_type:
        raise ValueError("The link did not return a readable HTML page.")

    soup = BeautifulSoup(response.text, "html.parser")

    for tag in soup(["script", "style", "noscript", "svg", "form", "nav", "footer", "aside"]):
        tag.decompose()

    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    description_tag = soup.find("meta", attrs={"name": "description"})
    description = description_tag.get("content", "").strip() if description_tag else ""

    article = soup.find("article") or soup.find("main") or soup.body or soup
    page_text = article.get_text("\n", strip=True)
    page_text = re.sub(r"\n{3,}", "\n\n", page_text)

    parts = [part for part in (title, description, page_text) if part]
    return "\n\n".join(parts)[:MAX_PAGE_CHARS]


async def fetch_pages(urls: list[str]) -> list[str]:
    pages = []

    for index, url in enumerate(urls, start=1):
        try:
            page_text = await asyncio.to_thread(extract_readable_page_text, url)
            if page_text:
                pages.append(f"Linked page {index}:\n{page_text}")
        except Exception as exc:
            pages.append(f"Linked page {index}: Could not read this page. Reason: {exc}")

    return pages


def _generate_with_openrouter_sync(prompt: str) -> str:
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [{"role": "user", "content": prompt}],
    }

    with httpx.Client(timeout=60) as client:
        response = client.post(OPENROUTER_URL, headers=headers, json=payload)
        response.raise_for_status()

    data = response.json()
    choices = data.get("choices") or []
    if not choices:
        raise ValueError(f"OpenRouter returned no choices: {data}")

    return choices[0]["message"]["content"].strip()


async def generate_with_openrouter(prompt: str) -> str:
    return await asyncio.to_thread(_generate_with_openrouter_sync, prompt)
