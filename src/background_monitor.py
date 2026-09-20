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


def is_within_active_hours(config, now_dt=None):
    """檢查指定時間是否在允許巡邏的時段內 (例如 08:00 - 21:00)"""
    posts_config = (
        config.get("posts", {})
        if isinstance(config, dict)
        else getattr(config, "posts_config", {})
    )
    active_hours = posts_config.get("active_hours")
    if not active_hours or not active_hours.get("enabled", True):
        return True, now_dt, None

    start_str = active_hours.get("start", "08:00")
    end_str = active_hours.get("end", "21:00")
    tz_name = active_hours.get("timezone", "Asia/Taipei")

    from zoneinfo import ZoneInfo
    from datetime import datetime as dt_cls, time, timedelta

    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = timezone.utc

    if now_dt is None:
        now_dt = dt_cls.now(tz)
    elif now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=timezone.utc).astimezone(tz)
    else:
        now_dt = now_dt.astimezone(tz)

    start_h, start_m = map(int, start_str.split(":"))
    end_h, end_m = map(int, end_str.split(":"))
    start_time = time(start_h, start_m)
    end_time = time(end_h, end_m)

    current_time = now_dt.time()
    today_start = dt_cls.combine(now_dt.date(), start_time, tzinfo=tz)

    if start_time <= current_time <= end_time:
        return True, now_dt, None

    if current_time > end_time:
        next_start = today_start + timedelta(days=1)
    else:
        next_start = today_start

    return False, now_dt, next_start


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
        page.wait_for_timeout(1500)
        page.mouse.wheel(0, 500)
        page.wait_for_timeout(1000)
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

    def poll(self, force=False):
        if not force:
            within, _, next_start = is_within_active_hours(self.store.config)
            if not within:
                self.state.set("phase", "idle_outside_active_hours")
                if next_start:
                    self.state.set("next_active_at", next_start.isoformat())
                return
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


def parse_cookie_data(raw: str):
    """Parse cookie from JSON array or 'key=value;' header string."""
    raw = raw.strip()
    if not raw:
        raise ValueError("Cookie 資料不可為空")
    if raw.startswith("["):
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                result = []
                for item in data:
                    if "name" in item and "value" in item:
                        domain = item.get("domain", ".facebook.com")
                        if not domain.startswith("."):
                            domain = f".{domain}"
                        result.append({
                            "name": str(item["name"]),
                            "value": str(item["value"]),
                            "domain": domain,
                            "path": item.get("path", "/"),
                        })
                if result:
                    return result
        except Exception:
            pass

    result = []
    parts = [p.strip() for chunk in raw.split("\n") for p in chunk.split(";") if p.strip()]
    for part in parts:
        if "=" in part:
            name, val = part.split("=", 1)
            name = name.strip()
            val = val.strip()
            if name:
                result.append({
                    "name": name,
                    "value": val,
                    "domain": ".facebook.com",
                    "path": "/",
                })
    if not result:
        raise ValueError("無法解析出有效的 Cookie 鍵值對")
    return result


def import_cookies(profile, state, cookie_raw: str, factory=sync_playwright):
    """Import user-provided cookie string or JSON directly into the browser profile."""
    cookies = parse_cookie_data(cookie_raw)
    state.set("login_required", True)
    with factory() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(profile),
            channel=BROWSER_CHANNEL,
            headless=True,
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
            context.add_cookies(cookies)
            page = context.pages[0] if context.pages else context.new_page()
            page.goto("https://www.facebook.com/", wait_until="domcontentloaded")
            if login_required(page):
                raise LoginRequired("匯入的 Cookie 無法通過 Facebook 登入驗證（可能已失效或缺少 c_user/xs）")
            state.set("login_required", False)
            state.set("phase", "login_saved_unverified")
            state.set("login_saved_at", now())
        finally:
            context.close()

