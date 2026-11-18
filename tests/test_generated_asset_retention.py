from pathlib import Path
import os
import tempfile
import time
import unittest
from unittest.mock import patch
from deploy.generated_asset_retention import cleanup

class AssetRetentionTests(unittest.TestCase):
    def test_protects_graph_recent_unknown_and_symlink(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root);a=p/'frontend/dist/assets';a.mkdir(parents=True)
            html='<script src="/assets/current-12345678.js"></script>'
            (a.parent/'index.html').write_text(html)
            for name,text in {'current-12345678.js':'"child-12345678.js"','child-12345678.js':'', 'obsolete-12345678.js':'gone','recent-12345678.js':'new','evidence.json':'keep'}.items():
                f=a/name;f.write_text(text)
                if not name.startswith('recent'):os.utime(f,(time.time()-172800,)*2)
            (a/'link-12345678.js').symlink_to(a/'evidence.json')
            with patch('deploy.generated_asset_retention.subprocess.check_output',return_value=html):
                self.assertEqual(cleanup(p)['removed_bytes'],4)
                self.assertTrue((a/'obsolete-12345678.js').exists())
                cleanup(p,dry_run=False)
            self.assertFalse((a/'obsolete-12345678.js').exists())
            self.assertTrue((a/'child-12345678.js').exists())
            self.assertTrue((a/'evidence.json').exists())
            self.assertTrue((a/'recent-12345678.js').exists())

    def test_missing_protected_file_fails_closed(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root);a=p/'frontend/dist/assets';a.mkdir(parents=True)
            html='<script src="/assets/missing-12345678.js"></script>'
            (a.parent/'index.html').write_text(html)
            with patch('deploy.generated_asset_retention.subprocess.check_output',return_value=html):
                with self.assertRaises(ValueError):cleanup(p,dry_run=False)
