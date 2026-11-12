"""The Vertex job spec, built without contacting Google Cloud."""

import io
import unittest
from contextlib import redirect_stderr

from cloud import train_job

BASE = ["--project", "p", "--bucket", "b", "--image", "r/trainer@sha256:" + "a" * 64,
        "--pairs", "gs://b/pairs.jsonl", "--run-id", "train-test"]


def spec(*extra):
    args = train_job.parse_args([*BASE, *extra])
    return train_job.worker_pool(args, "gs://b/training/train-test", "abc")[0]


class WorkerPoolTests(unittest.TestCase):
    def test_the_default_job_asks_for_one_t4(self):
        machine = spec()["machine_spec"]
        self.assertEqual(machine, {"machine_type": "n1-standard-4",
                                   "accelerator_type": "NVIDIA_TESLA_T4",
                                   "accelerator_count": 1})

    def test_a_cpu_job_names_no_accelerator(self):
        pool = spec("--accelerator-count", "0", "--machine-type", "n1-standard-16",
                    "--max-negatives", "2")
        self.assertEqual(pool["machine_spec"], {"machine_type": "n1-standard-16"})
        args = pool["container_spec"]["args"]
        self.assertEqual(args[args.index("--max-negatives") + 1], "2")
        self.assertNotIn("--no-amp", args)

    def test_no_amp_and_the_secret_path_reach_the_trainer(self):
        args = spec("--no-amp")["container_spec"]["args"]
        self.assertIn("--no-amp", args)
        self.assertIn("projects/p/secrets/wandb-api-key/versions/latest", args)

    def test_an_unpinned_image_or_negative_count_is_rejected(self):
        for bad in (["--image", "r/trainer:latest"], ["--accelerator-count", "-1"]):
            with self.assertRaises(SystemExit), redirect_stderr(io.StringIO()):
                train_job.parse_args([*BASE, *bad])


if __name__ == "__main__":
    unittest.main()
