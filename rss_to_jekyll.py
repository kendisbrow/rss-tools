#!/usr/bin/env python3
import argparse
import feedparser
import requests
from bs4 import BeautifulSoup
from slugify import slugify
from datetime import datetime
from pathlib import Path
import hashlib
import yaml
import re
from urllib.parse import urlparse


# ------------------------------------------------------------
#  CLEANERS & HELPERS
# ------------------------------------------------------------

def clean_content(text: str) -> str:
    """Remove Acast footer and other boilerplate."""
    if not text:
        return text

    # Remove the full Acast footer block including <hr>, <p>, and link
    text = re.sub(
        r"<hr\s*/?>\s*<p[^>]*>\s*Hosted on Acast\..*?acast\.com/privacy.*?</p>",
        "",
        text,
        flags=re.IGNORECASE | re.DOTALL
    )

    # Catch simpler variants
    text = re.sub(
        r"Hosted on Acast\..*?acast\.com/privacy.*?(</p>)?",
        "",
        text,
        flags=re.IGNORECASE | re.DOTALL
    )

    # Clean up leftover blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def episode_link_block(url: str, title: str) -> str:
    """Clickable CTA block appended to the end of the content."""
    # return f"\n\n\n\nSee this and all our episodes here: [{title}]({url})\n" 
    return f" "

def compute_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_existing_hash(filepath: Path) -> str | None:
    if not filepath.exists():
        return None

    try:
        text = filepath.read_text(encoding="utf-8")
        if text.startswith("---"):
            _, fm, _ = text.split("---", 2)
            data = yaml.safe_load(fm)
            return data.get("content_hash")
    except Exception:
        pass

    return None


# ------------------------------------------------------------
#  CONTENT EXTRACTION
# ------------------------------------------------------------

def fetch_full_content(url: str, title: str) -> str:
    """Scrape webpage content as a last resort."""
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()

        title_lower = title.lower()
        candidates = soup.find_all(string=lambda s: s and title_lower in s.lower())

        for c in candidates:
            parent = c.find_parent(["article", "section", "div"])
            if parent:
                return parent.get_text("\n", strip=True)

        article = soup.find("article")
        if article:
            return article.get_text("\n", strip=True)

        return soup.get_text("\n", strip=True)

    except Exception as e:
        return f"Error fetching full content: {e}"


def get_episode_content(entry, url, title):
    """
    Priority:
    1. content:encoded (full HTML)
    2. description (HTML or text)
    3. scraped HTML from webpage
    """
    # 1. Full content from RSS
    if "content" in entry and entry.content:
        value = entry.content[0].get("value")
        if value:
            return value.strip()

    # 2. Description from RSS
    description = entry.get("description") or entry.get("summary")
    if description:
        return description.strip()

    # 3. Scrape webpage
    return fetch_full_content(url, title)


# ------------------------------------------------------------
#  METADATA EXTRACTION
# ------------------------------------------------------------

def extract_tags(entry) -> list[str]:
    tags = []
    if "tags" in entry:
        for t in entry.tags:
            if "term" in t:
                tags.append(t.term)
    return tags


def extract_audio_url(entry) -> str | None:
    enclosures = entry.get("enclosures") or []
    if enclosures:
        return enclosures[0].get("href")
    return None


def extract_duration(entry) -> str | None:
    duration = entry.get("itunes_duration") or entry.get("itunes:duration")
    if duration:
        return str(duration)
    return None


def extract_acast_episode_id(entry):
    """Extract Acast GUID-based episode ID."""
    guid = entry.get("guid") or entry.get("id")
    if isinstance(guid, dict):
        guid = guid.get("value")

    if not guid:
        return None

    if guid.startswith("acast:"):
        return guid.split("acast:")[1]

    return None


def extract_acast_embed(entry):
    """Generate Acast embed URL from the episode link."""
    link = entry.get("link", "")
    if "acast.com" not in link:
        return None

    parts = urlparse(link).path.strip("/").split("/")

    # Expect: [show-slug, "episodes", episode-slug]
    if len(parts) >= 3 and parts[1] == "episodes":
        show_slug = parts[0]
        episode_slug = parts[2]
        return f"https://embed.acast.com/{show_slug}/{episode_slug}"

    return None

def extract_episode_number(entry):
    """Extract episode number from <itunes:episode>."""
    ep = entry.get("itunes_episode") or entry.get("itunes:episode")
    if ep is None:
        return None
    try:
        return int(ep)
    except ValueError:
        return str(ep)


def extract_season_number(entry):
    """Extract season number from <itunes:season>."""
    season = entry.get("itunes_season") or entry.get("itunes:season")
    if season is None:
        return None
    try:
        return int(season)
    except ValueError:
        return str(season)



# ------------------------------------------------------------
#  POST CREATION
# ------------------------------------------------------------

def create_jekyll_post(entry, output_dir: Path, sync: bool):
    title = entry.get("title", "Untitled")
    link = entry.get("link", "")
    published_parsed = entry.get("published_parsed")

    if published_parsed:
        date = datetime(*published_parsed[:6])
    else:
        date = datetime.utcnow()

    slug = slugify(title)
    filename = f"{date.strftime('%Y-%m-%d')}-{slug}.md"
    filepath = output_dir / filename

    # --- Content pipeline ---
    raw_content = get_episode_content(entry, link, title)
    full_content = clean_content(raw_content)
    full_content += episode_link_block(link, title)

    # --- Hashing for sync mode ---
    content_hash = compute_hash(full_content)
    existing_hash = load_existing_hash(filepath)

    if existing_hash == content_hash:
        print(f"• Skipped (unchanged): {filename}")
        return

    if existing_hash and not sync:
        print(f"• Skipped (exists, sync disabled): {filename}")
        return

    # --- Front matter ---
 

    front_matter = {
    "layout": "episode",
    "title": title,
    "date": date.isoformat(),
    "original_link": link,
    "audio_url": extract_audio_url(entry),
    "duration": extract_duration(entry),
    "episode_id": extract_acast_episode_id(entry),
    "embed_url": extract_acast_embed(entry),
    "season_number": extract_season_number(entry),     # ← NEW
    "episode_number": extract_episode_number(entry),   # ← NEW
    "tags": extract_tags(entry),
    "content_hash": content_hash,
}


    fm_text = "---\n" + yaml.safe_dump(front_matter, sort_keys=False) + "---\n\n"
    markdown = fm_text + full_content + "\n"

    filepath.write_text(markdown, encoding="utf-8")

    if existing_hash:
        print(f"✓ Updated: {filename}")
    else:
        print(f"✓ Created: {filename}")


# ------------------------------------------------------------
#  FEED PROCESSING
# ------------------------------------------------------------

def process_feed(feed_url: str, output_dir: Path, limit: int | None, sync: bool):
    feed = feedparser.parse(feed_url)
    output_dir.mkdir(parents=True, exist_ok=True)

    count = 0
    for entry in feed.entries:
        if limit and count >= limit:
            break

        create_jekyll_post(entry, output_dir, sync)
        count += 1


# ------------------------------------------------------------
#  CLI
# ------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Convert a podcast RSS feed into Jekyll-ready Markdown episodes."
    )
    parser.add_argument("feed_url", help="URL of the RSS feed")
    parser.add_argument(
        "-o", "--output",
        default="_posts",
        help="Output directory (default: _posts)"
    )
    parser.add_argument(
        "-n", "--limit",
        type=int,
        help="Limit number of episodes to import"
    )
    parser.add_argument(
        "--sync",
        action="store_true",
        help="Sync mode: update changed episodes and skip unchanged ones"
    )

    args = parser.parse_args()
    output_dir = Path(args.output)

    process_feed(args.feed_url, output_dir, args.limit, args.sync)


if __name__ == "__main__":
    main()