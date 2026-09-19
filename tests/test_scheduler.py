"""排程器隔離測試。"""

import unittest
from unittest.mock import Mock

from src.scheduler import Scheduler


class TestScheduler(unittest.TestCase):
    def test_instances_do_not_share_jobs(self):
        config = {
            "posts": {"source": "browser"},
            "stories": {"enabled": False},
        }

        first = Scheduler(config, Mock())
        second = Scheduler(config, Mock())

        self.assertIsNot(first.scheduler, second.scheduler)
        self.assertEqual(len(first.scheduler.jobs), 1)
        self.assertEqual(len(second.scheduler.jobs), 1)

        first.scheduler.clear()
        self.assertEqual(first.scheduler.jobs, [])
        self.assertEqual(len(second.scheduler.jobs), 1)


if __name__ == "__main__":
    unittest.main()
