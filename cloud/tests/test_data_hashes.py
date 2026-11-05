"""Detect input changes without sending any data to real cloud storage."""

import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from cloud import release, tasks
from cloud.tests import test_release as fixtures


class InputHashTests(unittest.TestCase):
    def test_all_seven_inputs_and_ignored_index_affect_fingerprint(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in release.FILES:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(name.encode())
            hashes = release.input_hashes(root)
            self.assertEqual(set(hashes), set(release.FILES))
            self.assertEqual(
                release.data_fingerprint(hashes),
                release.data_fingerprint(dict(reversed(list(hashes.items())))),
            )
            index = root / release.FILES[-1]
            index.write_bytes(b"updated index snapshot")
            changed = release.input_hashes(root)
            self.assertNotEqual(release.data_fingerprint(hashes), release.data_fingerprint(changed))
            with self.assertRaisesRegex(ValueError, "current.json"):
                release.check_input_hashes(changed, hashes)

    def test_missing_files_and_incomplete_or_invalid_hash_records_fail(self):
        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(ValueError, "raw.dvc"):
            release.input_hashes(Path(directory))
        valid = dict.fromkeys(release.FILES, "a" * 64)
        for hashes in ({}, dict(valid, unexpected="a" * 64), dict(valid, **{release.FILES[-1]: "bad"})):
            with self.subTest(hashes=hashes), self.assertRaises(ValueError):
                release.data_fingerprint(hashes)


class CheckedPublicationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        for name in release.FILES:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(name.encode())
        self.hashes = release.input_hashes(self.root)
        self.target = release.target_from_build(
            fixtures.build_result(), fixtures.VERSION, fixtures.REGISTRY, fixtures.BUCKET, self.hashes,
        )
        self.target_path = self.root / "release_target.json"
        release.save_target(self.target_path, self.target)
        self.objects = {}
        self.enterContext(patch.object(tasks, "ROOT", self.root))
        self.enterContext(redirect_stdout(io.StringIO()))
        self.blob = self.enterContext(patch.object(
            tasks, "blob", side_effect=lambda uri: fixtures.MemoryBlob(self.objects, uri),
        ))

    def publish(self, target=None):
        target = target or self.target
        with patch("sys.argv", [
            "tasks", "publish", "--output=" + target["release_uri"].removesuffix("/release.json"),
            "--image=" + target["workflow_image"], "--release-target=" + str(self.target_path),
        ]):
            tasks.main()

    def test_unchanged_inputs_publish_and_republish_identically(self):
        self.publish()
        saved = self.objects.copy()
        self.publish()
        self.assertEqual(self.objects, saved)
        manifest = json.loads(self.objects[self.target["release_uri"]])
        self.assertEqual({name: item["sha256"] for name, item in manifest["files"].items()}, self.hashes)

    def test_changed_or_missing_input_stops_before_any_storage_call(self):
        for name in release.FILES:
            for change in ("modified", "deleted"):
                with self.subTest(name=name, change=change):
                    path = self.root / name
                    original = path.read_bytes()
                    if change == "modified":
                        path.write_bytes(original + b" changed")
                    else:
                        path.unlink()
                    with self.assertRaises((ValueError, FileNotFoundError)) as error:
                        self.publish()
                    self.assertIn(Path(name).name, str(error.exception))
                    self.blob.assert_not_called()
                    self.assertEqual(self.objects, {})
                    path.write_bytes(original)

    def test_upload_uses_checked_copy_when_original_changes_during_upload(self):
        index = self.root / release.FILES[-1]
        original = index.read_bytes()

        def mutate_original(uri):
            index.write_bytes(b"changed after validation")
            return fixtures.MemoryBlob(self.objects, uri)

        self.blob.side_effect = mutate_original
        self.publish()
        manifest = json.loads(self.objects[self.target["release_uri"]])
        index_uri = manifest["files"][release.FILES[-1]]["uri"]
        self.assertEqual(self.objects[index_uri], original)
        self.assertNotEqual(index.read_bytes(), original)
        self.assertEqual(hashlib.sha256(self.objects[index_uri]).hexdigest(), self.hashes[release.FILES[-1]])

    def test_new_data_gets_distinct_release_even_with_same_source_and_image(self):
        self.publish()
        old_objects = self.objects.copy()
        (self.root / release.FILES[-1]).write_bytes(b"new version of ignored snapshot")
        updated = release.target_from_build(
            fixtures.build_result(build_id="build-B"), fixtures.VERSION, fixtures.REGISTRY,
            fixtures.BUCKET, release.input_hashes(self.root),
        )
        self.assertEqual(updated["source_version"], self.target["source_version"])
        self.assertEqual(updated["workflow_image"], self.target["workflow_image"])
        self.assertNotEqual(updated["release_uri"], self.target["release_uri"])
        release.save_target(self.target_path, updated)
        self.publish(updated)
        self.assertEqual({uri: self.objects[uri] for uri in old_objects}, old_objects)

    def test_mismatched_image_address_or_fingerprint_cannot_publish(self):
        for bad in (
            dict(self.target, workflow_image="example/workflow:wrong"),
            dict(self.target, release_uri="gs://other/release.json"),
        ):
            with self.subTest(target=bad), self.assertRaises(ValueError):
                self.publish(bad)
            self.blob.assert_not_called()
        release.save_target(self.target_path, dict(self.target, data_fingerprint="0" * 64))
        with self.assertRaises(ValueError):
            self.publish()
        self.blob.assert_not_called()


if __name__ == "__main__":
    unittest.main()
