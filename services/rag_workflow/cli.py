"""Run from the TrialMatch repository root: python -m services.rag_workflow.cli."""

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

from .config import Settings
from .data import DataStore
from .index import VectorIndex
from .providers import GeminiProvider, ProviderError, save_json
from .schemas import ScreenRequest, ScreenResponse
from .workflow import ScreeningWorkflow


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode", choices=["offline", "live"], help="Explicitly select offline or live"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("inspect-data")
    manifest = commands.add_parser("make-manifest")
    manifest.add_argument("--trial-count", type=int, default=50)
    commands.add_parser("build-index")
    commands.add_parser("index-status", help="Verify current source, manifest, and vector checksum")
    export = commands.add_parser(
        "export-index", help="Export a portable vector snapshot; no GCP calls"
    )
    export.add_argument("--output", type=Path, required=True)
    restore = commands.add_parser("restore-index", help="Restore a matching snapshot; no GCP calls")
    restore.add_argument("--input", type=Path, required=True)
    schema = commands.add_parser("export-schema")
    schema.add_argument("--output", type=Path, required=True)
    screen = commands.add_parser("screen")
    source = screen.add_mutually_exclusive_group(required=True)
    source.add_argument("--patient-id")
    source.add_argument(
        "--patient-file", type=Path, help="One normalized patient JSON object, not a FHIR Bundle"
    )
    screen.add_argument("--question", required=True)
    screen.add_argument("--top-k", type=int, default=3)
    screen.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    settings = Settings()
    if args.mode:
        settings = replace(settings, mode=args.mode)
    try:
        if args.command == "export-schema":
            save_json(
                args.output,
                {
                    "request": ScreenRequest.model_json_schema(),
                    "response": ScreenResponse.model_json_schema(),
                },
            )
            print(f"Wrote {args.output}")
            return 0
        store = DataStore(settings)
        if args.command == "inspect-data":
            print(
                json.dumps(
                    {
                        "patients": len(store.patients),
                        "trials": len(store.trials),
                        "criteria": sum(map(len, store.criteria.values())),
                        "source_sha256": store.hashes,
                    },
                    indent=2,
                )
            )
        elif args.command == "make-manifest":
            if not 1 <= args.trial_count <= 100:
                parser.error("--trial-count must be between 1 and 100")
            manifest = store.create_manifest(args.trial_count)
            print(
                f"Wrote {settings.manifest_path}: {len(manifest['trial_ids'])} trials, {len(manifest['patient_ids'])} patients"
            )
        elif args.command == "build-index":
            settings = replace(settings, mode="live")
            index = VectorIndex(settings, store, store.manifest())
            try:
                result = index.build()
            except ProviderError as exc:
                if exc.code != "MISSING_PROVIDER":
                    raise
                provider = GeminiProvider(settings)
                try:
                    index.provider = provider
                    result = index.build()
                finally:
                    provider.close()
            print(json.dumps(result, indent=2))
        elif args.command in {"index-status", "export-index", "restore-index"}:
            index = VectorIndex(settings, store, store.manifest())
            if args.command == "index-status":
                result = index.status()
            elif args.command == "export-index":
                result = index.export(args.output)
            else:
                result = index.restore(args.input)
            print(json.dumps(result, indent=2))
        else:
            request = ScreenRequest(
                patient_id=args.patient_id,
                patient=json.loads(args.patient_file.read_text()) if args.patient_file else None,
                question=args.question,
                top_k=args.top_k,
            )
            response = ScreeningWorkflow(settings).screen(request)
            if args.output:
                save_json(args.output, response.model_dump(mode="json"))
                print(
                    f"Wrote {args.output}: {response.result_status}, {len(response.candidate_trials)} candidates"
                )
            else:
                print(response.model_dump_json(indent=2))
            return 1 if response.result_status in {"ERROR", "PARTIAL"} else 0
        return 0
    except (ValueError, TypeError, KeyError, FileNotFoundError, ProviderError) as exc:
        print(
            json.dumps({"error": getattr(exc, "code", type(exc).__name__), "message": str(exc)}),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
