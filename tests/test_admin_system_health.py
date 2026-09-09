import unittest
import asyncio
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from api.routes.admin import _cpu_health, _disk_health, system_health


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

    def test_cpu_health_reports_system_usage_and_status(self):
        with (
            patch("api.routes.admin._read_cpu_times", side_effect=[(1000, 800), (1100, 825)]),
            patch("api.routes.admin.time.sleep"),
            patch("api.routes.admin.os.cpu_count", return_value=2),
        ):
            self.assertEqual(
                {"status": "watch", "used_percent": 75.0, "cores": 2},
                _cpu_health(),
            )

    def test_cpu_health_marks_90_percent_critical(self):
        with (
            patch("api.routes.admin._read_cpu_times", side_effect=[(1000, 800), (1100, 810)]),
            patch("api.routes.admin.time.sleep"),
        ):
            self.assertEqual("critical", _cpu_health()["status"])

    def test_system_health_requires_admin_and_returns_no_file_details(self):
        request = SimpleNamespace(state=SimpleNamespace(is_admin=False))
        with self.assertRaises(HTTPException) as denied:
            asyncio.run(system_health(request))
        self.assertEqual(403, denied.exception.status_code)

        request.state.is_admin = True
        with (
            patch("api.routes.admin._disk_health", return_value={"status": "good"}),
            patch("api.routes.admin._cpu_health", return_value={"status": "watch"}),
        ):
            result = asyncio.run(system_health(request))
        self.assertEqual(
            {"disk": {"status": "good"}, "cpu": {"status": "watch"}},
            result,
        )


if __name__ == "__main__":
    unittest.main()
