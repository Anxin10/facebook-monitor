"""Browser ingestion: atomic outbox, baseline, ownership and HTTP boundary."""

import http.client
import json
import sqlite3
from contextlib import closing
import tempfile
import threading
import unittest
import logging
from unittest.mock import patch
from pathlib import Path

from src.browser_receiver import BrowserStore, make_server, page_key, post_identity
from src.database import init_database, get_pending_notifications
from src.notifier import Notifier


class TestBrowserReceiver(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "test.db")
        self.target = {
            "page_id": "123",
            "url": "https://www.facebook.com/example",
            "enabled": True,
        }
        self.config = {
            "storage": {"database": self.path},
            "targets": [self.target],
            "notifications": {"channels": [{"id": "test", "backend": "apprise"}]},
        }
        init_database(self.path)
        self.store = BrowserStore(self.config)

    def payload(self, identity="one"):
        return {
            "page_id": "123",
            "page_url": self.target["url"],
            "posts": [
                {
                    "url": f"https://www.facebook.com/example/posts/{identity}?tracking=1",
                    "summary": "hello",
                }
            ],
        }

    def test_explicit_baseline_and_restart_dedup(self):
        self.assertEqual(self.store.ingest(self.payload())["inserted"], 1)
        self.assertEqual(get_pending_notifications(self.path), [])
        self.store.arm("123", True)
        self.store.ingest(self.payload())
        self.store.ingest(self.payload("two"))
        restarted = BrowserStore(self.config)
        self.assertEqual(restarted.ingest(self.payload("two"))["inserted"], 0)
        pending = get_pending_notifications(self.path)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["content_id"], "two")
        self.assertIsNone(pending[0]["published_at"])

    def test_empty_batch_does_not_establish_baseline(self):
        payload = self.payload()
        payload["posts"] = []
        with self.assertRaises(ValueError):
            self.store.ingest(payload)
        with self.assertRaises(ValueError):
            self.store.arm("123", True)

    def test_ownership_and_batch_validation_before_write(self):
        payload = self.payload()
        payload["posts"].append({"url": "https://www.facebook.com/other/posts/42"})
        with self.assertRaises(ValueError):
            self.store.ingest(payload)
        with closing(sqlite3.connect(self.path)) as db, db:
            self.assertEqual(db.execute("SELECT count(*) FROM items").fetchone()[0], 0)
        payload = self.payload()
        payload["page_url"] = "https://www.facebook.com/other"
        with self.assertRaises(ValueError):
            self.store.ingest(payload)

    def test_pause_records_without_notifying(self):
        self.store.ingest(self.payload())
        self.store.arm("123", True)
        self.store.arm("123", False)
        self.store.ingest(self.payload("two"))
        self.store.arm("123", True)
        self.store.ingest(self.payload("two"))
        self.assertEqual(get_pending_notifications(self.path), [])

    def test_observed_post_reaches_existing_notifier(self):
        self.config["notifications"]["channels"][0]["url_env"] = "TEST_APPRISE_URL"
        self.store.ingest(self.payload())
        self.store.arm("123", True)
        self.store.ingest(self.payload("two"))
        with patch.dict("os.environ", {"TEST_APPRISE_URL": "json://localhost"}), patch(
            "src.notifier.apprise.Apprise"
        ) as client:
            client.return_value.add.return_value = True
            client.return_value.notify.return_value = True
            Notifier(self.config, logging.getLogger("test")).send_pending()
            client.return_value.notify.assert_called_once()
        self.assertEqual(get_pending_notifications(self.path), [])

    def test_outbox_failure_rolls_back_item(self):
        self.store.ingest(self.payload())
        self.store.arm("123", True)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(
                "CREATE TRIGGER reject_notification BEFORE INSERT ON notifications BEGIN SELECT RAISE(ABORT,'test'); END"
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.ingest(self.payload("two"))
        with closing(sqlite3.connect(self.path)) as db, db:
            self.assertEqual(db.execute("SELECT count(*) FROM items").fetchone()[0], 1)

    def test_url_normalization(self):
        self.assertEqual(page_key("https://www.facebook.com/profile.php?id=123"), "123")
        for url in [
            "https://evil.test/example",
            "https://www.facebook.com/",
            "https://www.facebook.com/groups/1",
        ]:
            with self.assertRaises(ValueError):
                page_key(url)
        identity, url = post_identity(
            "https://www.facebook.com/story.php?story_fbid=abc&id=123&tracking=1",
            self.target,
        )
        self.assertEqual(identity, "abc")
        self.assertNotIn("tracking", url)

    def test_http_auth_validation_and_delivery(self):
        token = "x" * 40
        server = make_server(self.store, token, port=0)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:

            def request(method, path, body=None, headers=None):
                conn = http.client.HTTPConnection(
                    "127.0.0.1", server.server_port, timeout=3
                )
                try:
                    conn.request(method, path, body, headers or {})
                    result = conn.getresponse()
                    return result.status, json.loads(result.read())
                finally:
                    conn.close()

            self.assertEqual(request("GET", "/status")[0], 401)
            headers = {
                "Authorization": "Bearer " + token,
                "Content-Type": "application/json",
            }
            self.assertEqual(
                request(
                    "GET",
                    "/status",
                    headers={**headers, "Origin": "https://www.facebook.com"},
                )[0],
                403,
            )
            self.assertEqual(
                request("GET", "/status", headers={**headers, "Host": "evil.test"})[0],
                403,
            )
            self.assertEqual(request("POST", "/observations", "[]", headers)[0], 400)
            self.assertEqual(
                request("POST", "/observations", json.dumps(self.payload()), headers)[
                    0
                ],
                200,
            )
            self.assertEqual(
                request(
                    "POST",
                    "/arm",
                    json.dumps({"page_id": "123", "armed": True}),
                    headers,
                )[0],
                200,
            )
            self.assertEqual(
                request(
                    "POST", "/observations", json.dumps(self.payload("two")), headers
                )[0],
                200,
            )
            self.assertEqual(len(get_pending_notifications(self.path)), 1)
        finally:
            server.shutdown()
            server.server_close()
            worker.join()
