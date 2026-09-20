"""Quiet, bounded browser polling using an isolated persistent profile."""

import json
import os
import sqlite3
import time
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import psutil
from playwright.sync_api import Error as BrowserError
from playwright.sync_api import TimeoutError as BrowserTimeout
from playwright.sync_api import sync_playwright

from src.observation_store import page_key

PARSER = Path(__file__).with_name("post_parser.js").read_text(encoding="utf-8")
BROWSER_CHANNEL = "msedge" if os.name == "nt" else "chromium"
LOGIN_SELECTOR = 'input[name="email"], input[name="pass"], input[name="approvals_code"]'


def now():
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def instance_lock(runtime):
    """OS lock is released on crash; login and monitoring cannot share a profile."""
    runtime.mkdir(parents=True, exist_ok=True)
    with (runtime / "instance.lock").open("a+b") as handle:
        if os.fstat(handle.fileno()).st_size == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise RuntimeError(
                "Monitor/login already running; stop it before login"
            ) from None
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


class RuntimeState:
    def __init__(self, db_path):
        self.path = db_path
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS runtime_state (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )

    def get(self, key, default=None):
        with closing(sqlite3.connect(self.path)) as db:
            row = db.execute(
                "SELECT value FROM runtime_state WHERE key=?", (key,)
            ).fetchone()
        return json.loads(row[0]) if row else default

    def set(self, key, value):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(
                "INSERT INTO runtime_state VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, json.dumps(value, ensure_ascii=False)),
            )

    def snapshot(self):
        with closing(sqlite3.connect(self.path)) as db:
            return {
                key: json.loads(value)
                for key, value in db.execute("SELECT key,value FROM runtime_state")
            }


class LoginRequired(Exception):
    pass


class ReadUnavailable(Exception):
    pass


def login_required(page):
    path = urlsplit(page.url).path.lower()
    return (
        any(
            part in path
            for part in ("/login", "/checkpoint", "/two_step_verification", "/recover")
        )
        or page.locator(LOGIN_SELECTOR).first.is_visible()
    )


def measure_process_tree():
    """Point-in-time RSS sum, not a peak or physical-memory guarantee."""
    process = psutil.Process()
    memory = 0
    cpu = 0.0
    count = 0
    for child in [process, *process.children(recursive=True)]:
        try:
            memory += child.memory_info().rss
            times = child.cpu_times()
            cpu += times.user + times.system
            count += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return {
        "rss_mb_sample": round(memory / 1024**2, 1),
        "cpu_seconds_sample": round(cpu, 2),
        "process_count_sample": count,
    }


class BackgroundReader:
    def __init__(self, profile, store, state, factory=sync_playwright):
        self.profile = Path(profile)
        self.store = store
        self.state = state
        self.factory = factory

    def read_target(self, page, target):
        response = page.goto(
            target["url"], wait_until="domcontentloaded", timeout=20000
        )
        if login_required(page):
            raise LoginRequired()
        if response and response.status in {401, 403}:
            raise LoginRequired()
        if response and response.status >= 400:
            raise ReadUnavailable("http_error")
        try:
            if page_key(page.url) != page_key(target["url"]):
                raise ReadUnavailable("target_redirected")
        except ValueError:
            raise ReadUnavailable("target_redirected") from None
        page.evaluate(PARSER)
        try:
            page.wait_for_function(
                "target => !!document.querySelector('input[name=email], input[name=pass], input[name=approvals_code]') || FBMonitor.extract(document, target).length > 0",
                arg=target,
                timeout=15000,
            )
        except BrowserTimeout:
            if login_required(page):
                raise LoginRequired() from None
            raise ReadUnavailable("no_recognizable_posts") from None
        if login_required(page):
            raise LoginRequired()
        posts = page.evaluate("target => FBMonitor.extract(document, target)", target)
        if not posts:
            raise ReadUnavailable("no_recognizable_posts")
        return {"page_id": str(target["page_id"]), "page_url": page.url, "posts": posts}

    def poll(self):
        if self.state.get("login_required", True):
            self.state.set("phase", "login_required")
            return
        started = time.monotonic()
        self.state.set("phase", "checking")
        try:
            with self.factory() as playwright:
                context = playwright.chromium.launch_persistent_context(
                    str(self.profile),
                    channel=BROWSER_CHANNEL,
                    headless=True,
                    accept_downloads=False,
                    service_workers="block",
                    permissions=[],
                    viewport={"width": 1280, "height": 900},
                    timeout=20000,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                    ],
                    ignore_default_args=["--enable-automation"],
                )
                if hasattr(context, "add_init_script"):
                    context.add_init_script(
                        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
                    )
                try:
                    context.route(
                        "**/*",
                        lambda route: (
                            route.abort()
                            if route.request.resource_type in {"image", "media", "font"}
                            else route.continue_()
                        ),
                    )
                    page = context.pages[0] if context.pages else context.new_page()
                    for extra in context.pages[1:]:
                        extra.close()
                    context.on("page", lambda extra: extra.close())
                    page.on("dialog", lambda dialog: dialog.dismiss())
                    for target in self.store.targets:
                        if self.state.get("stop_requested", False):
                            break
                        page_id = str(target["page_id"])
                        attempt = now()
                        last_success = self.state.get("target:" + page_id, {}).get(
                            "last_success_at"
                        )
                        try:
                            result = self.store.ingest(self.read_target(page, target))
                            self.state.set(
                                "target:" + page_id,
                                {
                                    "status": "observed",
                                    "last_attempt_at": attempt,
                                    "last_success_at": now(),
                                    **result,
                                },
                            )
                        except LoginRequired:
                            self.state.set("login_required", True)
                            self.state.set(
                                "target:" + page_id,
                                {
                                    "status": "login_or_access_required",
                                    "last_attempt_at": attempt,
                                    "last_success_at": last_success,
                                },
                            )
                            break
                        except (ReadUnavailable, BrowserError, ValueError) as error:
                            self.state.set(
                                "target:" + page_id,
                                {
                                    "status": "unavailable",
                                    "last_attempt_at": attempt,
                                    "last_success_at": last_success,
                                    "reason": (
                                        str(error)
                                        if isinstance(error, ReadUnavailable)
                                        else type(error).__name__
                                    ),
                                },
                            )
                        self.state.set("resources", measure_process_tree())
                finally:
                    context.close()
        except BrowserError:
            # No headed fallback, no raw URL/credential-bearing browser exception logs.
            self.state.set(
                "browser_error",
                "Browser launch or context failed; check installation/profile",
            )
        else:
            self.state.set("browser_error", None)
        finally:
            self.state.set("cycle_seconds", round(time.monotonic() - started, 2))
            self.state.set(
                "phase",
                "login_required" if self.state.get("login_required", True) else "idle",
            )
            self.state.set("last_cycle_at", now())


def manual_login(profile, state, factory=sync_playwright):
    """Only this explicit user command is allowed to open a visible browser."""
    state.set("login_required", True)
    with factory() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(profile),
            channel=BROWSER_CHANNEL,
            headless=False,
            accept_downloads=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--no-default-browser-check",
            ],
            ignore_default_args=["--enable-automation"],
        )
        if hasattr(context, "add_init_script"):
            context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto("https://www.facebook.com/", wait_until="domcontentloaded")
            input(
                "請自行完成登入與驗證。完成後回到此終端機按 Enter（不要關閉瀏覽器）："
            )
            if login_required(page):
                raise LoginRequired("登入尚未完成")
            # A missing form is not proof of a valid session. The next read verifies access.
            state.set("login_required", False)
            state.set("phase", "login_saved_unverified")
            state.set("login_saved_at", now())
        finally:
            context.close()
