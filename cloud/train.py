"""Contrastive adaptation of the BioClinical encoder, with experiment tracking.

Fine-tunes the frozen masked-language-model checkpoint that `BioClinicalProvider`
serves so that a trial search request lands near the criteria that answer it. The
objective pools through the provider's own `masked_mean_l2`, so a checkpoint trained
here is pooled exactly as it is queried.

    python -m cloud.train \
      --pairs artifacts/training/pairs.jsonl artifacts/training/pairs_llm.jsonl \
      --output artifacts/training/run \
      --epochs 3 --batch-size 16 --lr 2e-5 \
      --wandb-project trialmatch-ms3

The validation metrics are internal: held-out training trials, queries derived from
the corpus or written by an LLM. They are not the retrieval benchmark, whose 50 trials
never enter this module, and they say nothing about clinical accuracy.
"""

import argparse
import hashlib
import json
import math
import os
import random
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL = "thomas-sounack/BioClinical-ModernBERT-base"
REVISION = "c3648aa87af95837c809e6f0c5f85d08160db437"
POOLING = "attention-mask-mean-including-special-tokens-v1"
WORKFLOW_TYPE = "contrastive-encoder-finetune"
RELEASE_FILES = {"trials": "processed/trials.jsonl", "criteria": "processed/criteria.jsonl",
                 "manifest": "demo_manifest.json"}


class LeakageError(ValueError):
    """Training data touches the held-out retrieval benchmark, or mixes its own splits."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def gcs_blob(uri: str):
    from google.cloud import storage

    bucket, _, name = uri.removeprefix("gs://").partition("/")
    return storage.Client().bucket(bucket).blob(name)


def fetch(uri: str, directory: Path) -> Path:
    """Return a local path for a local or gs:// file."""
    if not uri.startswith("gs://"):
        return Path(uri)
    target = directory / hashlib.sha256(uri.encode()).hexdigest()[:12] / uri.rsplit("/", 1)[1]
    target.parent.mkdir(parents=True, exist_ok=True)
    gcs_blob(uri).download_to_filename(str(target))
    return target


def upload_tree(directory: Path, uri: str) -> None:
    for path in sorted(p for p in directory.rglob("*") if p.is_file()):
        gcs_blob(f"{uri.rstrip('/')}/{path.relative_to(directory).as_posix()}").upload_from_filename(
            str(path)
        )


def pairs_from_release(report_uri: str, directory: Path) -> tuple[Path, str]:
    """Build corpus-derived pairs from the release a pipeline run has just validated.

    Returns the pairs file and the release URI. The report must say PASSED, and every
    file is checked against the checksum its release recorded before it is used.
    """
    if not report_uri.endswith(".json"):
        report_uri = report_uri.rstrip("/") + "/validation.json"
    report = json.loads(gcs_blob(report_uri).download_as_text())
    if report.get("status") != "PASSED" or not str(report.get("release_uri", "")).startswith("gs://"):
        raise ValueError("Training requires a PASSED validation report naming its release")
    release = json.loads(gcs_blob(report["release_uri"]).download_as_text())
    local = {}
    for key in ("trials", "criteria", "manifest"):
        name = next(n for n in release["files"] if n.endswith(RELEASE_FILES[key]))
        item = release["files"][name]
        local[key] = directory / "release" / RELEASE_FILES[key]
        local[key].parent.mkdir(parents=True, exist_ok=True)
        gcs_blob(item["uri"]).download_to_filename(str(local[key]))
        if sha256_file(local[key]) != item["sha256"]:
            raise ValueError(f"Checksum mismatch in the validated release: {name}")
    output = directory / "release" / "pairs.jsonl"
    subprocess.run(
        [sys.executable, "-m", "cloud.train_pairs", "--trials", str(local["trials"]),
         "--criteria", str(local["criteria"]), "--manifest", str(local["manifest"]),
         "--output", str(output)],
        cwd=ROOT, check=True,
    )
    return output, report["release_uri"]


def load_pairs(path: Path) -> list[dict]:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    for row in rows:
        if not (row.get("query") and row.get("positive") and row.get("trial_id")):
            raise ValueError(f"{path}: a pair needs query, positive and trial_id")
        if row.get("split") not in {"train", "validation"}:
            raise ValueError(f"{path}: split must be train or validation")
        row.setdefault("negatives", [])
    return rows


def assert_no_leakage(pairs: list[dict], held_out: set[str]) -> None:
    """Abort unless the benchmark trials are absent and each trial sits in one split."""
    if not held_out:
        raise LeakageError("The held-out trial list is empty; refusing to train unchecked")
    leaked = sorted({p["trial_id"] for p in pairs} & held_out)
    if leaked:
        raise LeakageError(
            f"{len(leaked)} held-out benchmark trial(s) in the training pairs, e.g. {leaked[:3]}"
        )
    splits = {}
    for pair in pairs:
        if splits.setdefault(pair["trial_id"], pair["split"]) != pair["split"]:
            raise LeakageError(f"Trial {pair['trial_id']} appears in both splits")


def code_commit() -> str:
    if os.environ.get("CODE_COMMIT"):
        return os.environ["CODE_COMMIT"]
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=ROOT, capture_output=True, text=True, check=True,
        ).stdout.strip()
        return commit + ("-dirty" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        # Inside the image there is no Git; the build bakes the source content hash.
        version = os.environ.get("SOURCE_VERSION", "")
        return f"source-version:{version}" if version and version != "unknown" else "unknown"


def encode(model, tokenizer, texts, device, max_length, batch_size=64):
    """Inference embeddings through the serving pooling, ordered as given."""
    import torch

    from services.rag_workflow.embedding_providers import masked_mean_l2

    order = sorted(range(len(texts)), key=lambda i: len(texts[i]))
    out = [None] * len(texts)
    model.eval()
    with torch.inference_mode():
        for start in range(0, len(order), batch_size):
            chunk = order[start : start + batch_size]
            batch = tokenize(tokenizer, [texts[i] for i in chunk], max_length, device)
            vectors = masked_mean_l2(
                model(**batch).last_hidden_state.float(), batch["attention_mask"]
            )
            for i, vector in zip(chunk, vectors.cpu(), strict=True):
                out[i] = vector
    return torch.stack(out)


def tokenize(tokenizer, texts, max_length, device):
    batch = tokenizer(
        texts, padding=True, truncation=True, max_length=max_length, return_tensors="pt"
    )
    batch.pop("token_type_ids", None)
    return {key: value.to(device) for key, value in batch.items()}


def info_nce(model, tokenizer, rows, device, max_length, temperature):
    """InfoNCE over in-batch positives plus every mined hard negative in the batch.

    Candidates that are known not to be negatives for a row are masked out: text equal
    to its positive, and positives of other rows that asked the same query.
    """
    import torch

    from services.rag_workflow.embedding_providers import masked_mean_l2

    queries = [r["query"] for r in rows]
    candidates = [r["positive"] for r in rows] + [n for r in rows for n in r["negatives"]]
    batch = tokenize(tokenizer, queries + candidates, max_length, device)
    vectors = masked_mean_l2(model(**batch).last_hidden_state.float(), batch["attention_mask"])
    q, c = vectors[: len(rows)], vectors[len(rows) :]
    logits = q @ c.T / temperature
    blocked = torch.zeros_like(logits, dtype=torch.bool)
    for i, row in enumerate(rows):
        for j, text in enumerate(candidates):
            if j != i and (
                text == row["positive"] or (j < len(rows) and rows[j]["query"] == row["query"])
            ):
                blocked[i, j] = True
    logits = logits.masked_fill(blocked, float("-inf"))
    return torch.nn.functional.cross_entropy(logits, torch.arange(len(rows), device=device))


# Tried in order until the accelerator reproduces the CPU embeddings of the same weights.
ENCODER_VARIANTS = (
    {"attn_implementation": "sdpa"},
    {"attn_implementation": "sdpa", "reference_compile": False},
    {"attn_implementation": "eager", "reference_compile": False},
)
NUMERIC_TOLERANCE = 1e-3


def probe_embeddings(model, tokenizer, texts, device, max_length, half=False):
    """Pooled embeddings of one padded batch, with gradients off; `half` uses fp16 autocast."""
    import torch

    from services.rag_workflow.embedding_providers import masked_mean_l2

    model.eval()
    batch = tokenize(tokenizer, texts, max_length, device)
    with torch.inference_mode(), torch.autocast("cuda", dtype=torch.float16, enabled=half):
        hidden = model(**batch).last_hidden_state.float()
    return masked_mean_l2(hidden, batch["attention_mask"]).cpu()


def numeric_gap(vectors, reference) -> float:
    """Largest absolute difference from the reference; infinite if anything is not finite."""
    import torch

    if not torch.isfinite(vectors).all():
        return float("inf")
    return (vectors - reference).abs().max().item()


def load_encoder(args, device, tokenizer, probe, want_amp):
    """Load the encoder and prove the device computes what the CPU computes.

    A padded batch is embedded on CPU first. On an accelerator each attention variant is
    then checked against that reference, and the first that matches is used; mixed
    precision is kept only if it matches too. Training on a device that silently returns
    different or non-finite embeddings would produce a checkpoint that means nothing.
    """
    import torch
    from transformers import AutoModel

    def load(variant):
        return AutoModel.from_pretrained(
            args.model, revision=args.revision, trust_remote_code=False,
            torch_dtype=torch.float32, **variant,
        )

    model = load(ENCODER_VARIANTS[0])
    report = {"probe_texts": len(probe), "tolerance": NUMERIC_TOLERANCE, "attempts": []}
    if device == "cpu":
        return model, False, {**report, "variant": ENCODER_VARIANTS[0], "reference": "self"}
    reference = probe_embeddings(model, tokenizer, probe, "cpu", args.max_length)
    if not torch.isfinite(reference).all():
        raise RuntimeError("The CPU reference embeddings are not finite")
    for variant in ENCODER_VARIANTS:
        if report["attempts"]:
            model = load(variant)
        model = model.to(device)
        gap = numeric_gap(probe_embeddings(model, tokenizer, probe, device, args.max_length),
                          reference)
        report["attempts"].append({"variant": variant, "max_abs_gap_fp32": gap})
        print(json.dumps({"numerics": report["attempts"][-1]}), flush=True)
        if gap <= NUMERIC_TOLERANCE:
            break
        model = None  # Drop the rejected copy before loading the next variant.
    else:
        raise RuntimeError(f"No encoder variant matches the CPU reference on {device}: "
                           f"{json.dumps(report['attempts'])}")
    amp = False
    if want_amp:
        gap = numeric_gap(
            probe_embeddings(model, tokenizer, probe, device, args.max_length, half=True),
            reference)
        amp = gap <= 10 * NUMERIC_TOLERANCE
        report["max_abs_gap_fp16"] = gap
        print(json.dumps({"numerics": {"max_abs_gap_fp16": gap, "amp": amp}}), flush=True)
    return model, amp, {**report, "variant": variant, "reference": "cpu"}


def evaluate(model, tokenizer, pairs, device, args) -> dict:
    """Validation loss, plus Recall@10 and MRR@10 over the validation pairs' own pool."""
    import torch

    model.eval()
    losses = []
    with torch.inference_mode():
        for start in range(0, len(pairs), args.batch_size):
            rows = pairs[start : start + args.batch_size]
            losses.append(
                info_nce(model, tokenizer, rows, device, args.max_length, args.temperature).item()
                * len(rows)
            )
    relevant = {}
    for pair in pairs:
        relevant.setdefault(pair["query"], set()).add(pair["positive"])
    pool = sorted({p["positive"] for p in pairs} | {n for p in pairs for n in p["negatives"]})
    position = {text: i for i, text in enumerate(pool)}
    queries = sorted(relevant)
    scores = encode(model, tokenizer, queries, device, args.max_length) @ encode(
        model, tokenizer, pool, device, args.max_length
    ).T
    top = scores.topk(min(10, len(pool)), dim=1).indices.tolist()
    recall = mrr = 0.0
    for query, ranked in zip(queries, top, strict=True):
        wanted = {position[text] for text in relevant[query]}
        recall += len(wanted & set(ranked)) / len(wanted)
        mrr += next((1 / rank for rank, i in enumerate(ranked, 1) if i in wanted), 0.0)
    return {
        "val/loss": sum(losses) / len(pairs),
        "val/recall@10": recall / len(queries),
        "val/mrr@10": mrr / len(queries),
        "val/queries": len(queries),
        "val/pool": len(pool),
    }


def start_tracking(args, config: dict, directory: Path):
    """Start a W&B run; fall back to offline rather than fail the training job."""
    try:
        import wandb
    except ImportError:
        print("wandb is not installed; continuing without experiment tracking")
        return None
    if not os.environ.get("WANDB_API_KEY") and args.wandb_secret:
        try:
            from google.cloud import secretmanager

            payload = secretmanager.SecretManagerServiceClient().access_secret_version(
                name=args.wandb_secret
            )
            os.environ["WANDB_API_KEY"] = payload.payload.data.decode().strip()
        except Exception as exc:  # noqa: BLE001 - tracking must never stop training
            print(f"Could not read the W&B secret ({type(exc).__name__}); tracking offline")
    mode = os.environ.get("WANDB_MODE") or ("online" if os.environ.get("WANDB_API_KEY") else "offline")
    directory.mkdir(parents=True, exist_ok=True)
    options = {"project": args.wandb_project, "entity": args.wandb_entity or None,
                   "name": args.run_name or None, "config": config, "dir": str(directory),
                   "job_type": "train"}
    try:
        return wandb.init(mode=mode, **options)
    except Exception as exc:  # noqa: BLE001
        print(f"W&B {mode} start failed ({type(exc).__name__}); tracking offline")
        return wandb.init(mode="offline", **options)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--pairs", nargs="*", default=[],
                        help="One or more pair files, local paths or gs:// URIs")
    parser.add_argument("--validated-report", default="",
                        help="gs:// validation report of a pipeline run; pairs are built "
                             "from the release it validated and added to --pairs")
    parser.add_argument("--output", required=True, help="Local directory or gs:// prefix")
    parser.add_argument("--manifest", type=Path,
                        default=ROOT / "services/rag_workflow/examples/demo_manifest.json",
                        help="Benchmark manifest whose trial_ids must never be trained on")
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--revision", default=REVISION)
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--lr", type=float, default=2e-5)
    parser.add_argument("--weight-decay", type=float, default=0.01)
    parser.add_argument("--warmup-ratio", type=float, default=0.1)
    parser.add_argument("--temperature", type=float, default=0.05)
    parser.add_argument("--max-length", type=int, default=256,
                        help="Token budget per text during training; longer text is truncated")
    parser.add_argument("--max-negatives", type=int, default=4,
                        help="Hard negatives used per pair")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--device", default="auto", choices=["auto", "cuda", "mps", "cpu"])
    parser.add_argument("--no-amp", action="store_true",
                        help="Disable float16 autocast on CUDA")
    parser.add_argument("--limit", type=int, default=0,
                        help="Use only this many training pairs (smoke runs)")
    parser.add_argument("--wandb-project", default="trialmatch-ms3")
    parser.add_argument("--wandb-entity", default="")
    parser.add_argument("--run-name", default="")
    parser.add_argument("--wandb-secret", default="",
                        help="Secret Manager version holding the W&B API key, read at run time")
    parser.add_argument("--source-release", default="",
                        help="URI of the validated release.json the pairs were built from")
    parser.add_argument("--image-uri", default=os.environ.get("TRAINER_IMAGE_URI", ""),
                        help="Digest-pinned trainer image, recorded in the manifest")
    args = parser.parse_args(argv)
    if not args.pairs and not args.validated_report:
        parser.error("give --pairs, --validated-report, or both")
    return args


def main(argv=None):
    args = parse_args(argv)
    started = time.time()
    scratch = Path(tempfile.mkdtemp(prefix="trialmatch-train-"))
    remote = args.output.startswith("gs://")
    output = scratch / "output" if remote else Path(args.output)
    output.mkdir(parents=True, exist_ok=True)

    held_out = set(json.loads(args.manifest.read_text())["trial_ids"])
    sources, pairs = [], []
    inputs = [(uri, fetch(uri, scratch)) for uri in args.pairs]
    if args.validated_report:
        built, release_uri = pairs_from_release(args.validated_report, scratch)
        if args.source_release and args.source_release != release_uri:
            raise ValueError("--source-release differs from the release the report validated")
        args.source_release = release_uri
        inputs.insert(0, (f"built-from:{release_uri}", built))
    for uri, path in inputs:
        rows = load_pairs(path)
        sources.append({
            "uri": uri, "sha256": sha256_file(path), "pairs": len(rows),
            "train": sum(r["split"] == "train" for r in rows),
            "validation": sum(r["split"] == "validation" for r in rows),
        })
        pairs.extend(rows)
    assert_no_leakage(pairs, held_out)  # Before any model is loaded or any step is taken.
    for pair in pairs:
        pair["negatives"] = pair["negatives"][: args.max_negatives]
    train = [p for p in pairs if p["split"] == "train"]
    validation = [p for p in pairs if p["split"] == "validation"]
    random.Random(args.seed).shuffle(train)
    if args.limit:
        train = train[: args.limit]
    if not train or not validation:
        raise ValueError("Training needs at least one train pair and one validation pair")

    import torch
    import transformers
    from transformers import AutoTokenizer

    random.seed(args.seed)
    torch.manual_seed(args.seed)
    device = args.device
    if device == "auto":
        device = ("cuda" if torch.cuda.is_available()
                  else "mps" if torch.backends.mps.is_available() else "cpu")
    commit = code_commit()
    config = {
        **{k: (str(v) if isinstance(v, Path) else v) for k, v in vars(args).items()},
        "device": device, "amp": device == "cuda" and not args.no_amp, "pooling": POOLING, "normalization": "l2", "loss": "info-nce",
        "negatives": "in-batch positives and mined hard negatives",
        "workflow_type": WORKFLOW_TYPE, "code_commit": commit, "pair_files": sources,
        "train_pairs": len(train), "validation_pairs": len(validation),
        "held_out_trials": len(held_out),
        "torch": torch.__version__, "transformers": transformers.__version__,
    }
    print(json.dumps(config, indent=2))
    run = start_tracking(args, config, output)

    tokenizer = AutoTokenizer.from_pretrained(
        args.model, revision=args.revision, trust_remote_code=False
    )
    # Short and long texts in one batch, so padding and the local attention window are used.
    probe = [train[0]["query"], train[0]["positive"],
             " ".join(row["positive"] for row in train[:12]),
             " ".join(row["query"] for row in train[:40])]
    model, amp, numerics = load_encoder(args, device, tokenizer, probe,
                                        device == "cuda" and not args.no_amp)
    model = model.to(device)
    config.update(amp=amp, numerics=numerics)
    if run is not None:
        run.config.update({"amp": amp, "numerics": numerics}, allow_val_change=True)

    history = []

    def validate(epoch, step):
        metrics = {"epoch": epoch, **evaluate(model, tokenizer, validation, device, args)}
        history.append(metrics)
        print(json.dumps(metrics))
        if run is not None:
            run.log(metrics, step=step)
        return metrics

    baseline = validate(0, 0)  # The frozen checkpoint, through the same code path.
    if not math.isfinite(baseline["val/loss"]):
        raise RuntimeError("The frozen encoder's validation loss is not finite")

    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=args.weight_decay)
    steps_per_epoch = -(-len(train) // args.batch_size)
    total = steps_per_epoch * args.epochs
    warmup = max(1, int(total * args.warmup_ratio))
    scheduler = torch.optim.lr_scheduler.LambdaLR(
        optimizer,
        lambda s: (s + 1) / warmup if s < warmup else max(0.0, (total - s) / max(1, total - warmup)),
    )
    scaler = torch.amp.GradScaler("cuda", enabled=amp)
    shuffler = random.Random(args.seed)
    step = 0
    for epoch in range(1, args.epochs + 1):
        shuffler.shuffle(train)
        model.train()
        for start in range(0, len(train), args.batch_size):
            rows = train[start : start + args.batch_size]
            # Mixed precision runs the encoder in half precision; pooling and the loss
            # stay float32 because masked_mean_l2 receives hidden states cast with .float().
            with torch.autocast("cuda", dtype=torch.float16, enabled=amp):
                loss = info_nce(model, tokenizer, rows, device, args.max_length, args.temperature)
            if not torch.isfinite(loss):
                raise RuntimeError(f"Non-finite training loss at step {step}")
            scaler.scale(loss).backward()
            scaler.unscale_(optimizer)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            scaler.step(optimizer)
            scaler.update()
            scheduler.step()
            optimizer.zero_grad(set_to_none=True)
            step += 1
            if run is not None:
                run.log({"train/loss": loss.item(), "train/lr": scheduler.get_last_lr()[0],
                         "epoch": epoch}, step=step)
            if step % 20 == 0 or step == total:
                print(f"epoch {epoch} step {step}/{total} loss {loss.item():.4f}", flush=True)
        validate(epoch, step)

    model_dir = output / "model"
    model.save_pretrained(model_dir, safe_serialization=True)
    tokenizer.save_pretrained(model_dir)
    # One digest for the whole checkpoint: weights, config and tokenizer together. The
    # serving provider recomputes it with this same function before loading.
    from services.rag_workflow.embedding_providers import checkpoint_digest

    checkpoint, files = checkpoint_digest(model_dir)
    final = history[-1]
    tracking = {"mode": "disabled", "path": None, "url": None}
    if run is not None:
        offline = bool(run.settings._offline) if hasattr(run.settings, "_offline") else not run.url
        tracking = {
            "mode": "offline" if offline else "online",
            "path": "/".join(run.path) if isinstance(run.path, (list, tuple)) else run.path,
            "url": None if offline else run.url,
            "run_id": run.id,
        }
        run.summary.update({"checkpoint_sha256": checkpoint,
                            "baseline/val/recall@10": baseline["val/recall@10"],
                            "baseline/val/mrr@10": baseline["val/mrr@10"],
                            "baseline/val/loss": baseline["val/loss"]})
    artifact_uri = f"{args.output.rstrip('/')}/model" if remote else str(model_dir.resolve())
    manifest = {
        "schema_version": 1,
        "workflow_type": WORKFLOW_TYPE,
        "source_release_uri": args.source_release or None,
        "artifact_uri": artifact_uri,
        "artifact_sha256": checkpoint,
        "artifact_files": files,
        "base_model": {"name": args.model, "revision": args.revision},
        "pooling": POOLING,
        "normalization": "l2",
        "pair_files": sources,
        "config": config,
        "code_commit": commit,
        "image_uri": args.image_uri or None,
        "experiment": tracking,
        "validation": {
            "scope": "internal: held-out training trials, not the retrieval benchmark",
            "baseline_frozen": baseline,
            "epochs": history[1:],
            "recall@10_improved": final["val/recall@10"] > baseline["val/recall@10"],
        },
        "seed": args.seed,
        "duration_seconds": round(time.time() - started, 1),
    }
    (output / "training_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    if run is not None:
        run.finish()
    if remote:
        upload_tree(output, args.output)
    print(json.dumps({k: manifest[k] for k in
                      ("artifact_uri", "artifact_sha256", "experiment", "validation")}, indent=2))
    print(f"Training manifest: {args.output.rstrip('/')}/training_manifest.json")


if __name__ == "__main__":
    try:
        main()
    except LeakageError as exc:
        sys.exit(f"LEAKAGE: {exc}")
