"""Run the browser receiver and notification scheduler."""

import logging
import threading

from dotenv import load_dotenv
from src.browser_receiver import BrowserStore, load_pairing_token, make_server
from src.config import Config
from src.database import init_database
from src.scheduler import Scheduler


def main():
    load_dotenv()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    logger = logging.getLogger(__name__)
    config = Config()
    if config.posts_config.get("source") != "browser":
        raise ValueError('Set posts.source to "browser"')
    init_database(config.storage_config.get("database", "monitor.sqlite3"))
    server = make_server(BrowserStore(config), load_pairing_token())
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    logger.info(
        "Browser receiver: http://127.0.0.1:8765; pairing token: browser-token.local"
    )
    if not config.notifications_config.get("channels"):
        logger.warning(
            "No notification channels configured; observations will only be stored"
        )
    try:
        Scheduler(config, logger).run()
    finally:
        server.shutdown()
        server.server_close()
        worker.join()


if __name__ == "__main__":
    main()
