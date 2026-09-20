"""Validated observations and transactional notification outbox."""

import json
import re
import sqlite3
from contextlib import closing
from urllib.parse import parse_qs, urlsplit


def page_key(value):
    """Only accept a Facebook Page root, never a feed or a post URL."""
    url = urlsplit(value)
    if url.scheme != "https" or url.netloc != "www.facebook.com":
        raise ValueError("Expected a https://www.facebook.com Page URL")
    path = url.path.strip("/")
    if path == "profile.php":
        key = parse_qs(url.query).get("id", [""])[0]
        if key.isdigit():
            return key
    elif re.fullmatch(r"[A-Za-z0-9.]+", path) and path.lower() not in {
        "home.php",
        "login",
        "login.php",
        "watch",
        "reel",
        "reels",
        "groups",
        "marketplace",
        "gaming",
        "notifications",
        "friends",
        "stories",
        "search",
    }:
        return path.lower()
    raise ValueError("Expected a Page root URL")


def post_identity(value, target):
    url = urlsplit(value)
    if url.scheme != "https" or url.netloc != "www.facebook.com":
        raise ValueError("Invalid post host")
    match = re.fullmatch(r"/([A-Za-z0-9.]+)/posts/([A-Za-z0-9]+)/?", url.path)
    if match and match[1].lower() in {page_key(target["url"]), str(target["page_id"])}:
        return match[2], f"https://www.facebook.com/{match[1]}/posts/{match[2]}"
    query = parse_qs(url.query)
    post_id = query.get("story_fbid", [""])[0]
    owner = query.get("id", [""])[0]
    if (
        url.path in {"/permalink.php", "/story.php"}
        and owner == str(target["page_id"])
        and re.fullmatch(r"[A-Za-z0-9]+", post_id)
    ):
        return (
            post_id,
            f"https://www.facebook.com/permalink.php?story_fbid={post_id}&id={owner}",
        )
    raise ValueError("Post does not belong to configured Page")


class BrowserStore:
    def __init__(self, config):
        self.config = config
        self.path = config.get("storage", {}).get("database", "monitor.sqlite3")
        self.targets = [t for t in config.get("targets", []) if t.get("enabled")]
        for target in self.targets:
            page_key(target["url"])
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS browser_state (
                page_id TEXT PRIMARY KEY, armed INTEGER NOT NULL DEFAULT 0,
                last_seen_at TEXT, observed_count INTEGER NOT NULL DEFAULT 0)"""
            )

    def target(self, page_id):
        for target in self.targets:
            if str(target["page_id"]) == page_id:
                return target
        raise ValueError("Unknown or disabled target")

    def status(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.row_factory = sqlite3.Row
            states = {
                r["page_id"]: dict(r) for r in db.execute("SELECT * FROM browser_state")
            }
        return [
            {
                "page_id": str(t["page_id"]),
                "url": t["url"],
                **states.get(
                    str(t["page_id"]),
                    {"armed": 0, "last_seen_at": None, "observed_count": 0},
                ),
            }
            for t in self.targets
        ]

    def arm(self, page_id, armed):
        self.target(page_id)
        if type(armed) is not bool:
            raise ValueError("armed must be boolean")
        with closing(sqlite3.connect(self.path)) as db, db:
            row = db.execute(
                "SELECT observed_count FROM browser_state WHERE page_id=?", (page_id,)
            ).fetchone()
            if not row or row[0] == 0:
                raise ValueError(
                    "Observe at least one post before enabling notifications"
                )
            db.execute(
                "UPDATE browser_state SET armed=? WHERE page_id=?",
                (int(armed), page_id),
            )

    def ingest(self, payload):
        if not isinstance(payload, dict):
            raise ValueError("Expected an object")
        page_id = payload.get("page_id")
        target = self.target(page_id)
        if page_key(payload.get("page_url", "")) != page_key(target["url"]):
            raise ValueError("Wrong Page URL")
        posts = payload.get("posts")
        if not isinstance(posts, list) or not 1 <= len(posts) <= 50:
            raise ValueError("Expected 1 to 50 posts")
        validated = []
        for post in posts:
            if not isinstance(post, dict) or not isinstance(post.get("url"), str):
                raise ValueError("Invalid post")
            identity, url = post_identity(post["url"], target)
            summary = post.get("summary", "")
            if not isinstance(summary, str) or len(summary) > 4000:
                raise ValueError("Invalid summary")
            validated.append((identity, url, summary))
        inserted = 0
        with closing(sqlite3.connect(self.path, timeout=10)) as db, db:
            # Serialize baseline, deduplication and outbox insertion in one transaction.
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT OR IGNORE INTO browser_state(page_id) VALUES (?)", (page_id,)
            )
            armed = db.execute(
                "SELECT armed FROM browser_state WHERE page_id=?", (page_id,)
            ).fetchone()[0]
            for identity, url, summary in validated:
                result = db.execute(
                    """INSERT OR IGNORE INTO items
                    (page_id,content_type,content_id,summary,url,raw_data)
                    VALUES (?,'post',?,?,?,?)""",
                    (
                        page_id,
                        identity,
                        "[瀏覽器首次看見；非發文時間] " + summary,
                        url,
                        json.dumps({"source": "browser"}),
                    ),
                )
                if not result.rowcount:
                    continue
                inserted += 1
                if armed:
                    for channel in self.config.get("notifications", {}).get(
                        "channels", []
                    ):
                        db.execute(
                            """INSERT OR IGNORE INTO notifications
                            (page_id,content_type,content_id,channel_id,backend)
                            VALUES (?,'post',?,?,?)""",
                            (page_id, identity, channel["id"], channel["backend"]),
                        )
            db.execute(
                """UPDATE browser_state SET last_seen_at=strftime('%Y-%m-%dT%H:%M:%SZ','now'),
                observed_count=(SELECT count(*) FROM items WHERE page_id=? AND content_type='post')
                WHERE page_id=?""",
                (page_id, page_id),
            )
        return {"inserted": inserted, "armed": bool(armed)}
