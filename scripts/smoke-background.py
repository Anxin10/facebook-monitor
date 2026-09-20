"""Real headless Chromium + synthetic Facebook DOM + SQLite; never contacts Facebook."""

import json
import logging
import sys
import tempfile
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
import sqlite3

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.sync_api import sync_playwright
from src.background_monitor import (
    BackgroundReader,
    RuntimeState,
    LoginRequired,
    BROWSER_CHANNEL,
)
from src.database import init_database, get_pending_notifications
from src.notifier import Notifier
from src.observation_store import BrowserStore


def main():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        db_path = str(root / "smoke.db")
        init_database(db_path)
        target = {
            "page_id": "123",
            "url": "https://www.facebook.com/example",
            "enabled": True,
        }
        config = {
            "storage": {"database": db_path},
            "targets": [target],
            "notifications": {
                "channels": [
                    {"id": "test", "backend": "apprise", "url_env": "SMOKE_URL"}
                ]
            },
        }
        store = BrowserStore(config)
        state = RuntimeState(db_path)
        reader = BackgroundReader(root / "profile", store, state)
        content = {
            "html": '<article role="article"><a href="/example/posts/one">time</a><div data-ad-preview="message">First post</div></article>'
        }
        with sync_playwright() as pw:
            context = pw.chromium.launch_persistent_context(
                str(root / "profile"), channel=BROWSER_CHANNEL, headless=True
            )
            try:
                context.route(
                    "**/*",
                    lambda route: route.fulfill(
                        content_type="text/html", body=content["html"]
                    ),
                )
                page = context.pages[0]
                first = reader.read_target(page, target)
                assert store.ingest(first)["inserted"] == 1
                assert get_pending_notifications(db_path) == []
                store.arm("123", True)
                content["html"] = (
                    content["html"]
                    .replace("/one", "/two")
                    .replace("First post", "Second post")
                )
                second = reader.read_target(page, target)
                assert store.ingest(second)["inserted"] == 1
                assert store.ingest(second)["inserted"] == 0
                assert len(get_pending_notifications(db_path)) == 1
                with patch.dict("os.environ", {"SMOKE_URL": "json://localhost"}), patch(
                    "src.notifier.apprise.Apprise"
                ) as client:
                    client.return_value.add.return_value = True
                    client.return_value.notify.return_value = True
                    Notifier(config, logging.getLogger("smoke")).send_pending()
                    client.return_value.notify.assert_called_once()
                assert get_pending_notifications(db_path) == []
                content["html"] = '<input name="email"><input name="pass">'
                try:
                    reader.read_target(page, target)
                except LoginRequired:
                    pass
                else:
                    raise AssertionError("Login form was not detected")
                with closing(sqlite3.connect(db_path)) as db:
                    assert db.execute("SELECT count(*) FROM items").fetchone()[0] == 2
            finally:
                context.close()
    print(
        json.dumps(
            {
                "headless_dom_to_sqlite_to_mock_notification": "passed",
                "facebook_live": "not_tested",
            }
        )
    )


if __name__ == "__main__":
    main()
