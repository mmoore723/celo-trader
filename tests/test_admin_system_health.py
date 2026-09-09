import unittest
import asyncio
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from api.routes.admin import _disk_health, system_health


class AdminSystemHealthTests(unittest.TestCase):
    def test_disk_health_reports_good_without_walking_or_changing_files(self):
        with patch("api.routes.admin.shutil.disk_usage", return_value=(1000, 570, 430)):
            self.assertEqual(
                {
                    "status": "good",
                    "used_percent": 57.0,
                    "free_bytes": 430,
                    "total_bytes": 1000,
                },
                _disk_health("/safe"),
            )

    def test_disk_health_thresholds(self):
        with patch("api.routes.admin.shutil.disk_usage", return_value=(1000, 800, 200)):
            self.assertEqual("watch", _disk_health("/safe")["status"])
        with patch("api.routes.admin.shutil.disk_usage", return_value=(1000, 900, 100)):
            self.assertEqual("critical", _disk_health("/safe")["status"])

    def test_system_health_requires_admin_and_returns_no_file_details(self):
        request = SimpleNamespace(state=SimpleNamespace(is_admin=False))
        with self.assertRaises(HTTPException) as denied:
            asyncio.run(system_health(request))
        self.assertEqual(403, denied.exception.status_code)

        request.state.is_admin = True
        with patch("api.routes.admin._disk_health", return_value={"status": "good"}):
            result = asyncio.run(system_health(request))
        self.assertEqual({"disk": {"status": "good"}}, result)


if __name__ == "__main__":
    unittest.main()
