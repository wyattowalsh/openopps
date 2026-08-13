"""CLI entrypoint for openopps_kaggle."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from openopps_kaggle.constants import (
    DATASET_ID,
    DB_FILE,
    DEFAULT_DATASET_DIR,
    DEFAULT_EXAMPLES_DIR,
    DEFAULT_MANAGER_DIR,
    DEFAULT_STARTER_DIR,
)
from openopps_kaggle.bundle.disk import MIN_FREE_BYTES_FOR_EXPORT, require_disk_headroom
from openopps_kaggle._core import (
    _prune_private_evidence_files,
    _prune_private_upload_files,
    _read_json,
    _stage_public_upload_dir,
    _stage_runtime_generator_dir,
    _update_live_file_metadata,
    _wait_live_dataset_ready,
    _write_data_artifacts,
    _write_dataset_image,
    _write_example_notebooks,
    _write_json,
    _write_manager_notebook,
    _write_snapshot_quality_report,
    _write_starter_notebook,
    _remove_dataset_notebooks,
    dataset_metadata,
)


def main(argv: list[str] | None = None) -> None:
    if argv is None:
        argv = sys.argv[1:]
    if argv and argv[0] == "publication":
        from openopps_kaggle.publication import main as publication_main

        raise SystemExit(publication_main(argv[1:]))

    parser = argparse.ArgumentParser(
        description="Generate Kaggle dataset metadata from OpenOpps package models.",
        prog="openopps_kaggle",
    )
    subparsers = parser.add_subparsers(dest="command")

    generate = subparsers.add_parser("generate", help="Generate Kaggle metadata/bundle.")
    _add_generate_arguments(generate)

    verify_notebooks = subparsers.add_parser(
        "verify-notebooks",
        help="Verify pulled Kaggle public notebook bundles.",
    )
    verify_notebooks.add_argument("pull_root", type=Path)

    verify_readback = subparsers.add_parser(
        "verify-readback",
        help="Verify live OpenOppsDB readback through KaggleHub.",
    )
    verify_readback.add_argument("--dataset", default="wyattowalsh/openoppsdb")
    verify_readback.add_argument("--version", type=int, default=None)
    verify_readback.add_argument("--skip-sqlite", action="store_true")

    _add_generate_arguments(parser)

    args = parser.parse_args(argv)
    if args.command == "verify-notebooks":
        from openopps_kaggle.verify_notebooks import main as verify_main

        raise SystemExit(verify_main([str(args.pull_root)]))
    if args.command == "verify-readback":
        from openopps_kaggle.verify_readback import main as readback_main

        # verify_readback.main parses option flags only (no subcommand token).
        readback_argv: list[str] = []
        if args.dataset:
            readback_argv.extend(["--dataset", args.dataset])
        if args.version is not None:
            readback_argv.extend(["--version", str(args.version)])
        if args.skip_sqlite:
            readback_argv.append("--skip-sqlite")
        readback_main(readback_argv)
        return

    _run_generate(args)


def _add_generate_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_DATASET_DIR)
    parser.add_argument("--manager-dir", type=Path, default=DEFAULT_MANAGER_DIR)
    parser.add_argument("--starter-dir", type=Path, default=DEFAULT_STARTER_DIR)
    parser.add_argument("--examples-dir", type=Path, default=DEFAULT_EXAMPLES_DIR)
    parser.add_argument("--skip-notebooks", action="store_true")
    parser.add_argument("--stage-runtime-generator-dir", type=Path, default=None)
    parser.add_argument("--data-db", type=Path, default=None)
    parser.add_argument("--mutate-data-db-for-upload", action="store_true")
    parser.add_argument("--sync-metrics", type=Path, default=None)
    parser.add_argument("--status-json", type=Path, default=None)
    parser.add_argument("--coverage-json", type=Path, default=None)
    parser.add_argument("--quality-report", type=Path, default=None)
    parser.add_argument("--prune-private-upload-files", action="store_true")
    parser.add_argument("--stage-public-upload-dir", type=Path, default=None)
    parser.add_argument("--update-live-file-metadata", action="store_true")
    parser.add_argument("--live-file-metadata-browser-cookies", action="store_true")
    parser.add_argument("--live-file-metadata-kaggle-auth", action="store_true")
    parser.add_argument(
        "--live-file-metadata-sqlite-timeout-seconds", type=float, default=120.0
    )
    parser.add_argument(
        "--live-file-metadata-sqlite-poll-seconds", type=float, default=15.0
    )
    parser.add_argument("--wait-live-dataset-ready", action="store_true")
    parser.add_argument("--wait-live-dataset-min-version", type=int, default=None)
    parser.add_argument("--wait-live-dataset-timeout-seconds", type=float, default=1800.0)
    parser.add_argument("--wait-live-dataset-poll-seconds", type=float, default=30.0)
    parser.add_argument("--empty-snapshot-explanation", default=None)


def _run_generate(args: argparse.Namespace) -> None:
    if args.stage_runtime_generator_dir is not None:
        _stage_runtime_generator_dir(args.stage_runtime_generator_dir)
        return

    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    if args.data_db is not None:
        if args.prune_private_upload_files and args.quality_report is None:
            _prune_private_evidence_files(output_dir)
        require_disk_headroom(
            "before_export",
            min_free_bytes=MIN_FREE_BYTES_FOR_EXPORT,
            path=output_dir,
        )
        _write_data_artifacts(
            output_dir,
            args.data_db,
            mutate_data_db_for_upload=args.mutate_data_db_for_upload,
        )
    _write_dataset_image(output_dir)
    _remove_dataset_notebooks(output_dir)
    if args.quality_report is None:
        _prune_private_upload_files(output_dir)

    _write_json(output_dir / "dataset-metadata.json", dataset_metadata())

    if args.quality_report is not None:
        if args.sync_metrics is None or args.status_json is None:
            raise SystemExit(
                "--quality-report requires --sync-metrics and --status-json"
            )
        _write_snapshot_quality_report(
            output_dir=output_dir,
            db_path=output_dir / DB_FILE,
            report_path=args.quality_report,
            sync_metrics=_read_json(args.sync_metrics),
            status=_read_json(args.status_json),
            coverage=_read_json(args.coverage_json) if args.coverage_json else None,
            empty_snapshot_explanation=args.empty_snapshot_explanation,
        )
        if args.prune_private_upload_files:
            _prune_private_upload_files(output_dir)

    if not args.skip_notebooks:
        _write_manager_notebook(args.manager_dir)
        _write_starter_notebook(args.starter_dir)
        _write_example_notebooks(args.examples_dir)

    if args.stage_public_upload_dir is not None:
        _stage_public_upload_dir(output_dir, args.stage_public_upload_dir)
    if args.wait_live_dataset_ready:
        _wait_live_dataset_ready(
            DATASET_ID,
            min_version=args.wait_live_dataset_min_version,
            timeout_seconds=args.wait_live_dataset_timeout_seconds,
            poll_seconds=args.wait_live_dataset_poll_seconds,
        )
    if args.update_live_file_metadata:
        _update_live_file_metadata(
            output_dir / "dataset-metadata.json",
            use_browser_cookies=args.live_file_metadata_browser_cookies,
            use_kaggle_auth=args.live_file_metadata_kaggle_auth,
            sqlite_index_timeout_seconds=args.live_file_metadata_sqlite_timeout_seconds,
            sqlite_index_poll_seconds=args.live_file_metadata_sqlite_poll_seconds,
        )


if __name__ == "__main__":
    main(sys.argv[1:])
