"""Training guards that need no model download: leakage, pair loading and pooling."""

import hashlib
import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from cloud import train

MANIFEST = Path(train.ROOT / "services/rag_workflow/examples/demo_manifest.json")


def pair(trial_id, split="train", **extra):
    return {"query": "Find trials of metformin.", "positive": "Taking metformin.",
            "negatives": ["No pacemaker."], "trial_id": trial_id, "split": split, **extra}


class LeakageTests(unittest.TestCase):
    def setUp(self):
        self.held_out = set(json.loads(MANIFEST.read_text())["trial_ids"])

    def test_the_benchmark_universe_is_fifty_trials(self):
        self.assertEqual(len(self.held_out), 50)

    def test_clean_pairs_pass(self):
        train.assert_no_leakage([pair("NCT00000000"), pair("NCT00000001", "validation")],
                                self.held_out)

    def test_a_demo_trial_aborts(self):
        demo = min(self.held_out)
        with self.assertRaisesRegex(train.LeakageError, "held-out benchmark"):
            train.assert_no_leakage([pair("NCT00000000"), pair(demo)], self.held_out)

    def test_a_trial_in_both_splits_aborts(self):
        with self.assertRaisesRegex(train.LeakageError, "both splits"):
            train.assert_no_leakage(
                [pair("NCT00000000"), pair("NCT00000000", "validation")], self.held_out
            )

    def test_an_empty_held_out_list_aborts(self):
        with self.assertRaises(train.LeakageError):
            train.assert_no_leakage([pair("NCT00000000")], set())

    def test_main_stops_on_a_demo_trial_before_loading_a_model(self):
        demo = min(self.held_out)
        with tempfile.TemporaryDirectory() as directory:
            pairs = Path(directory) / "pairs.jsonl"
            pairs.write_text("\n".join(json.dumps(p) for p in (
                pair("NCT00000000"), pair("NCT00000001", "validation"), pair(demo))) + "\n")
            with self.assertRaises(train.LeakageError), redirect_stderr(io.StringIO()):
                train.main(["--pairs", str(pairs), "--output", str(Path(directory) / "run")])
            self.assertFalse((Path(directory) / "run/model").exists())


class PairLoadingTests(unittest.TestCase):
    def test_a_pair_without_a_split_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pairs.jsonl"
            path.write_text(json.dumps(pair("NCT00000000", split="test")) + "\n")
            with self.assertRaisesRegex(ValueError, "split"):
                train.load_pairs(path)


class ReleasePairTests(unittest.TestCase):
    """Pairs built inside the pipeline come only from a validated, checksummed release."""

    def blobs(self, objects):
        def blob(uri):
            def download_to_filename(path):
                Path(path).write_bytes(objects[uri])

            return SimpleNamespace(download_as_text=lambda: objects[uri].decode(),
                                   download_to_filename=download_to_filename)

        return patch.object(train, "gcs_blob", side_effect=blob)

    def test_a_report_that_did_not_pass_is_rejected(self):
        objects = {"gs://run/report/validation.json": json.dumps({"status": "FAILED"}).encode()}
        with tempfile.TemporaryDirectory() as directory, self.blobs(objects), \
                self.assertRaisesRegex(ValueError, "PASSED"):
            train.pairs_from_release("gs://run/report", Path(directory))

    def test_a_release_file_with_the_wrong_checksum_is_rejected(self):
        release = {"files": {
            f"services/x/{name}": {"uri": f"gs://run/processed/{key}", "sha256": "0" * 64}
            for key, name in train.RELEASE_FILES.items()}}
        objects = {
            "gs://run/report/validation.json": json.dumps(
                {"status": "PASSED", "release_uri": "gs://run/processed/release.json"}).encode(),
            "gs://run/processed/release.json": json.dumps(release).encode(),
            **{f"gs://run/processed/{key}": b"changed" for key in train.RELEASE_FILES},
        }
        with tempfile.TemporaryDirectory() as directory, self.blobs(objects), \
                self.assertRaisesRegex(ValueError, "Checksum mismatch"):
            train.pairs_from_release("gs://run/report", Path(directory))

    def test_pairs_are_built_from_the_validated_release(self):
        files = {key: (train.ROOT / name).read_bytes() for key, name in {
            "trials": "services/trial_ingestion/data/processed/trials.jsonl",
            "criteria": "services/trial_ingestion/data/processed/criteria.jsonl",
            "manifest": "services/rag_workflow/examples/demo_manifest.json"}.items()}
        release = {"files": {
            f"services/x/{train.RELEASE_FILES[key]}": {
                "uri": f"gs://run/processed/{key}",
                "sha256": hashlib.sha256(content).hexdigest()}
            for key, content in files.items()}}
        objects = {
            "gs://run/report/validation.json": json.dumps(
                {"status": "PASSED", "release_uri": "gs://run/processed/release.json"}).encode(),
            "gs://run/processed/release.json": json.dumps(release).encode(),
            **{f"gs://run/processed/{key}": content for key, content in files.items()},
        }
        with tempfile.TemporaryDirectory() as directory, self.blobs(objects):
            path, uri = train.pairs_from_release("gs://run/report", Path(directory))
            pairs = train.load_pairs(path)
        self.assertEqual(uri, "gs://run/processed/release.json")
        self.assertGreater(len(pairs), 1000)
        train.assert_no_leakage(pairs, set(json.loads(files["manifest"])["trial_ids"]))


@unittest.skipUnless(importlib.util.find_spec("torch"), "Install the optional embeddings group")
class PoolingTests(unittest.TestCase):
    """The training objective must pool exactly as BioClinicalProvider serves."""

    def setUp(self):
        import torch

        torch.manual_seed(0)
        self.torch = torch
        self.hidden = torch.randn(3, 5, 768)
        self.mask = torch.tensor([[1, 1, 1, 1, 1], [1, 1, 1, 0, 0], [1, 0, 0, 0, 0]])
        hidden, mask = self.hidden, self.mask

        class Tokenizer:
            def __call__(self, texts, **_):
                rows = [i % 3 for i in range(len(texts))]
                return {"input_ids": torch.tensor(rows).unsqueeze(1).repeat(1, 5),
                        "attention_mask": mask[rows]}

        class Model:
            config = SimpleNamespace(hidden_size=768)

            def __call__(self, **batch):
                return SimpleNamespace(last_hidden_state=hidden[batch["input_ids"][:, 0]])

            def eval(self):
                return self

        self.tokenizer, self.model = Tokenizer(), Model()

    def test_training_encode_matches_the_provider(self):
        from services.rag_workflow.config import Settings
        from services.rag_workflow.embedding_providers import BioClinicalProvider

        with tempfile.TemporaryDirectory() as directory:
            provider = BioClinicalProvider(Settings(
                embedding_provider="bioclinical", embedding_model="test-encoder",
                embedding_revision="a" * 40, dimension=768, artifacts=Path(directory),
            ))
            provider.tokenizer, provider.model = self.tokenizer, self.model
            texts = ["aaa", "bb", "c"]  # Distinct lengths; encode() sorts by length.
            served = self.torch.tensor(provider.embed_many(texts))
        # encode() batches shortest first, so feed it the order that maps row i to mask i.
        trained = train.encode(self.model, self.tokenizer, ["x", "x", "x"], "cpu", 16)
        self.assertLess((served - trained).abs().max().item(), 1e-6)

    def test_pooling_is_the_masked_mean_including_every_unmasked_token(self):
        from services.rag_workflow.embedding_providers import masked_mean_l2

        pooled = masked_mean_l2(self.hidden, self.mask)
        expected = self.torch.nn.functional.normalize(self.hidden[1, :3].mean(0), dim=0)
        self.assertLess((pooled[1] - expected).abs().max().item(), 1e-6)
        self.assertLess((pooled.norm(dim=1) - 1).abs().max().item(), 1e-6)

    def test_known_false_negatives_are_masked_from_the_loss(self):
        rows = [pair("NCT1"), pair("NCT2")]  # Same query and same positive text.
        loss = train.info_nce(self.model, self.tokenizer, rows[:1], "cpu", 16, 0.05)
        both = train.info_nce(self.model, self.tokenizer, rows, "cpu", 16, 0.05)
        self.assertTrue(self.torch.isfinite(loss) and self.torch.isfinite(both))


if __name__ == "__main__":
    unittest.main()
