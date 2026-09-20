"""Dedicated background browser monitor; visible UI only for explicit login."""

import argparse
import json
import logging
import os
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

from dotenv import load_dotenv

from src.background_monitor import (
    BackgroundReader,
    RuntimeState,
    import_cookies,
    instance_lock,
    is_within_active_hours,
    manual_login,
    now,
)
from src.config import Config
from src.database import init_database
from src.notifier import Notifier
from src.observation_store import BrowserStore

ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / ".runtime.local"


def configure_logging():
    RUNTIME.mkdir(exist_ok=True)
    handler = RotatingFileHandler(
        RUNTIME / "monitor.log", maxBytes=2 * 1024**2, backupCount=3, encoding="utf-8"
    )
    logging.basicConfig(
        level=logging.INFO,
        handlers=[handler],
        format="%(asctime)s %(levelname)s %(message)s",
    )
    return logging.getLogger(__name__)


def run_monitor(reader, state, notifier, interval, once=False, config=None):
    state.set("stop_requested", False)
    state.set("pid", os.getpid())
    state.set("started_at", now())
    next_check = 0.0
    next_notify = 0.0
    next_heartbeat = 0.0
    try:
        while not state.get("stop_requested", False):
            current = time.monotonic()
            if current >= next_heartbeat:
                state.set("heartbeat_at", now())
                next_heartbeat = current + 15
            if current >= next_check:
                if not once and config:
                    within, now_local, next_start = is_within_active_hours(config)
                    if not within:
                        state.set("phase", "idle_outside_active_hours")
                        if next_start:
                            state.set("next_active_at", next_start.isoformat())
                            wait_seconds = min(60.0, max(5.0, (next_start - now_local).total_seconds()))
                            next_check = time.monotonic() + wait_seconds
                        else:
                            next_check = time.monotonic() + 60.0
                        if time.monotonic() >= next_notify:
                            notifier.send_pending()
                            next_notify = time.monotonic() + 30
                        time.sleep(1)
                        continue
                reader.poll(force=once)
                # Delay from completion, never overlap or catch up after sleep.
                next_check = time.monotonic() + interval
            if state.get("stop_requested", False):
                break
            if time.monotonic() >= next_notify:
                notifier.send_pending()
                next_notify = time.monotonic() + 30
            if once:
                break
            time.sleep(1)
    finally:
        state.set("phase", "stopped")
        state.set("stopped_at", now())
        state.set("pid", None)


def main():
    parser = argparse.ArgumentParser(description="Background Facebook observations")
    parser.add_argument(
        "command",
        nargs="?",
        default="run",
        choices=["run", "check", "login", "import-cookie", "import-sheets", "status", "stop", "enable", "pause"],
    )
    parser.add_argument("page_id", nargs="?")
    args = parser.parse_args()
    os.chdir(ROOT)
    load_dotenv(ROOT / ".env")
    logger = configure_logging()
    config = Config()
    if config.posts_config.get("source") != "background_browser":
        raise ValueError("posts.source must be background_browser")
    interval = config.posts_config.get("interval_seconds", 300)
    if not isinstance(interval, int) or interval < 60:
        raise ValueError("interval_seconds must be an integer >= 60")
    db_path = config.storage_config.get("database", "monitor.sqlite3")
    init_database(db_path)
    store = BrowserStore(config)
    state = RuntimeState(db_path)
    if args.command == "status":
        try:
            with instance_lock(RUNTIME):
                active = False
        except RuntimeError:
            active = True
        print(
            json.dumps(
                {
                    "process_active": active,
                    "runtime": state.snapshot(),
                    "targets": store.status(),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    if args.command == "stop":
        state.set("stop_requested", True)
        return
    if args.command == "import-sheets":
        from scripts.import_sheets import import_sheets
        custom_urls = [args.page_id] if args.page_id else None
        import_sheets(custom_urls)
        return
    if args.command in {"enable", "pause"}:
        if not args.page_id:
            parser.error("enable/pause requires page_id")
        store.arm(args.page_id, args.command == "enable")
        return
    with instance_lock(RUNTIME):
        if args.command == "login":
            manual_login(RUNTIME / "profile", state)
            return
        if args.command == "import-cookie":
            cookie_file = ROOT / "cookie.txt"
            if cookie_file.exists() and cookie_file.stat().st_size > 0:
                raw = cookie_file.read_text(encoding="utf-8").strip()
                print("從 cookie.txt 讀取 Cookie 中...")
            elif os.environ.get("FB_COOKIE"):
                raw = os.environ.get("FB_COOKIE").strip()
                print("從環境變數 FB_COOKIE 讀取 Cookie 中...")
            else:
                print("請貼上您的 Facebook Cookie（格式如 c_user=...; xs=... 或 JSON 陣列），完成後按 Enter：")
                raw = input().strip()
            import_cookies(RUNTIME / "profile", state, raw)
            print("✅ 成功匯入 Cookie 並通過 Facebook 登入驗證！")
            return
        if not store.targets:
            raise ValueError("No enabled targets")
        if not config.notifications_config.get("channels"):
            logger.warning("No notification channels: observations only")
        reader = BackgroundReader(RUNTIME / "profile", store, state)
        run_monitor(
            reader,
            state,
            Notifier(config, logger),
            interval,
            once=args.command == "check",
            config=config,
        )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as error:
        # Quiet launch must never trigger a dialog or expose raw browser/session data.
        logging.getLogger(__name__).error("Monitor stopped: %s", type(error).__name__)
        if sys.stderr is not None:
            print(
                "執行失敗："
                + type(error).__name__
                + "；請查看 .runtime.local/monitor.log",
                file=sys.stderr,
            )
        raise SystemExit(1)
