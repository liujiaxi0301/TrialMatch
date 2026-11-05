"""Optional real DVC + Git history test, using a temporary LOCAL remote only."""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


@unittest.skipUnless(
    importlib.util.find_spec("dvc") and shutil.which("git"), "Install versioning group"
)
class DvcSnapshotTests(unittest.TestCase):
    def test_old_pointer_recovers_original_bytes_from_local_remote(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = root / "repository"
            repository.mkdir()
            env = {
                **os.environ,
                "DVC_SITE_CACHE_DIR": str(root / "site-cache"),
                "DVC_NO_ANALYTICS": "1",
            }

            def run(*args):
                result = subprocess.run(
                    args,
                    check=False,
                    cwd=repository,
                    env=env,
                    text=True,
                    capture_output=True,
                    timeout=30,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result.stdout

            def dvc(*args):
                return run(sys.executable, "-m", "dvc", *args)

            run("git", "init", "--quiet")
            dvc("init", "--quiet")
            dvc("config", "core.analytics", "false")
            dvc("remote", "add", "--default", "local-test", str(root / "remote"))
            snapshot = repository / "index.json"
            # Tiny data-versioning fixture, not patient data or a model-generated vector.
            original = b'{"fixture_version":1,"embedding":[0.25,0.75]}\n'
            snapshot.write_bytes(original)
            dvc("add", "index.json")
            dvc("push")  # Copies to the temporary local directory, never a cloud service.
            run("git", "add", ".dvc", ".dvcignore", ".gitignore", "index.json.dvc")
            run(
                "git",
                "-c",
                "user.name=Snapshot Test",
                "-c",
                "user.email=test@example.invalid",
                "-c",
                "commit.gpgsign=false",
                "-c",
                "core.hooksPath=/dev/null",
                "commit",
                "--quiet",
                "-m",
                "Track snapshot fixture v1",
            )
            original_pointer = (repository / "index.json.dvc").read_bytes()
            snapshot.write_text('{"fixture_version":2,"embedding":[0.5,0.5]}\n')
            dvc("add", "index.json")
            self.assertNotEqual((repository / "index.json.dvc").read_bytes(), original_pointer)
            dvc("push")
            # Select the older Git pointer, remove only this disposable workspace/cache,
            # and recover from remote storage rather than an existing local cache.
            run("git", "restore", "--source=HEAD", "--", "index.json.dvc")
            snapshot.unlink()
            shutil.rmtree(repository / ".dvc/cache")
            dvc("pull", "index.json.dvc")
            self.assertEqual(snapshot.read_bytes(), original)
            self.assertEqual(json.loads(dvc("status", "--json")), {})


if __name__ == "__main__":
    unittest.main()
