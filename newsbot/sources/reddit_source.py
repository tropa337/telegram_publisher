from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import praw

from ..ai import is_relevant_topic, prettify_text
from ..config import (HOURS_BACK, REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET,
                      REDDIT_LIMIT, REDDIT_SUBS, REDDIT_USER_AGENT)
from ..filters import looks_like_trash
from ..types import NewsItem

reddit: Optional[praw.Reddit] = None
if REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET:
    reddit = praw.Reddit(
        client_id=REDDIT_CLIENT_ID,
        client_secret=REDDIT_CLIENT_SECRET,
        user_agent=REDDIT_USER_AGENT,
    )


def fetch_reddit_news(state: Dict) -> List[NewsItem]:
    if reddit is None:
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=HOURS_BACK)
    result: List[NewsItem] = []

    for sub_name in REDDIT_SUBS:
        print(f"📡 Reddit: r/{sub_name}")
        last_ts = state.get("reddit_last_ts", {}).get(sub_name, 0.0)
        max_ts = last_ts

        subreddit = reddit.subreddit(sub_name)
        for post in subreddit.new(limit=REDDIT_LIMIT):
            created_dt = datetime.utcfromtimestamp(post.created_utc).replace(tzinfo=timezone.utc)

            if created_dt < cutoff:
                continue

            if post.created_utc <= last_ts:
                continue

            if post.is_self and post.selftext:
                full_text = post.title + "\n\n" + post.selftext
            else:
                full_text = post.title

            text = full_text.strip()
            if looks_like_trash(text):
                print(f"  [-] Reddit {post.id} — мусор")
                continue

            if not is_relevant_topic(text):
                print(f"  [-] Reddit {post.id} — не по теме (AI)")
                continue

            try:
                pretty = prettify_text(text)
            except Exception as e:
                print(f"  [!] Ошибка Mistral Reddit: {e}")
                continue

            url = f"https://reddit.com{post.permalink}"

            item = NewsItem(
                source=f"reddit:r/{sub_name}",
                text=(
                    f"{pretty}\n\n"
                    f"<i>Джерело: Reddit — r/{sub_name}</i>\n{url}"
                ),
                created_at=created_dt,
                source_link=url,
                media=None,
            )
            result.append(item)

            if post.created_utc > max_ts:
                max_ts = post.created_utc

        state.setdefault("reddit_last_ts", {})
        if max_ts > last_ts:
            state["reddit_last_ts"][sub_name] = max_ts

    return result
