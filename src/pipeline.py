#!/usr/bin/env python3
"""Unified CLI Runner for the Music Renaming and Tagging Pipeline.

Commands:
  scan       Extract audio tags and codec attributes into file_list.json
  plan       Run LLM planner to generate rename_plan.json
  apply      Deterministically validate and preview/execute renames & tags
  rollback   Undo operations from a rollback log file (restores names and tags)
  verify     Run post-rename verification of files and tags on disk
"""

import argparse
import json
import sys
from pathlib import Path

import scan
import plan
import apply
import verify
from config import (
    AUDIO_EXTENSIONS,
    DEFAULT_FILE_LIST_PATH,
    DEFAULT_PLAN_PATH,
    DEFAULT_RULES_PATH,
    DEFAULT_MODEL,
    DEFAULT_OLLAMA_HOST,
    DEFAULT_BATCH_SIZE,
    DEFAULT_NUM_CTX,
    DEFAULT_NUM_THREAD,
)

def main():
    parser = argparse.ArgumentParser(
        description="Music Renaming & Tagging Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Scan subcommand
    scan_p = subparsers.add_parser("scan", help="Phase 0: Scan base directory and export file_list.json")
    scan_p.add_argument("base_dir", type=Path, help="Base directory containing music files")
    scan_p.add_argument("--output", "-o", type=Path, default=DEFAULT_FILE_LIST_PATH, help=f"Output list file (default: {DEFAULT_FILE_LIST_PATH})")
    scan_p.add_argument("--format", "-f", choices=["json", "jsonl", "csv", "txt"], default="json", help="Export format")
    scan_p.add_argument("--attributes", "-a", type=str, default=None, help="Comma-separated attributes to export")
    scan_p.add_argument("--all-attributes", action="store_true", help="Export all music tags and codec attributes")
    scan_p.add_argument("--extensions", "-e", type=str, default=None, help="Comma-separated audio extensions")
    scan_p.add_argument("--limit", "-l", type=int, default=None, help="Limit scanned files")

    # Plan subcommand
    plan_p = subparsers.add_parser("plan", help="Phase 1: Run LLM planner to generate rename_plan.json")
    plan_p.add_argument("--file-list", "-f", type=Path, default=DEFAULT_FILE_LIST_PATH, help="Path to file_list.json")
    plan_p.add_argument("--rules", "-r", type=Path, default=None, help="Path to rules doc")
    plan_p.add_argument("--output", "-o", type=Path, default=DEFAULT_PLAN_PATH, help="Output plan file")
    plan_p.add_argument("--model", "-m", type=str, default=DEFAULT_MODEL, help="Model name")
    plan_p.add_argument("--batch-size", "-b", type=int, default=DEFAULT_BATCH_SIZE, help="Batch size")
    plan_p.add_argument("--limit", "-l", type=int, default=None, help="Limit files to process")
    plan_p.add_argument("--pass2-retry", action="store_true", help="Retry medium/low confidence items")

    # Apply subcommand
    apply_p = subparsers.add_parser("apply", help="Phase 2: Validate plan, preview diff, or execute on disk")
    apply_p.add_argument("base_dir", type=Path, help="Base directory containing the music files")
    apply_p.add_argument("--plan", "-p", type=Path, default=DEFAULT_PLAN_PATH, help="Path to rename_plan.json")
    apply_p.add_argument("--execute", action="store_true", help="Perform actual filesystem renames and tag updates")
    apply_p.add_argument("--apply-medium", action="store_true", help="Also apply medium confidence valid items")
    apply_p.add_argument("--no-tags", action="store_true", help="Skip tag writing")
    apply_p.add_argument("--skip-verify", action="store_true", help="Skip post-rename verification")

    # Rollback subcommand
    rb_p = subparsers.add_parser("rollback", help="Revert operations using a rollback log file")
    rb_p.add_argument("log_file", type=Path, help="Path to rollback_log_*.jsonl")

    # Verify subcommand
    vf_p = subparsers.add_parser("verify", help="Phase 4: Run post-rename verification on disk")
    vf_p.add_argument("base_dir", type=Path, help="Base directory containing the music files")
    vf_p.add_argument("--plan", "-p", type=Path, default=DEFAULT_PLAN_PATH, help="Path to rename_plan.json")
    vf_p.add_argument("--no-tag-verify", action="store_true", help="Skip audio tag read-back check")

    args = parser.parse_args()

    if args.command == "scan":
        extensions = (
            {ext.strip().lower() if ext.strip().startswith(".") else f".{ext.strip().lower()}"
             for ext in args.extensions.split(",")}
            if args.extensions
            else AUDIO_EXTENSIONS
        )
        from metadata import AVAILABLE_EXPORT_ATTRIBUTES, DEFAULT_SELECTED_ATTRIBUTES
        if args.all_attributes:
            attrs = [k for k, _, _ in AVAILABLE_EXPORT_ATTRIBUTES]
        elif args.attributes:
            attrs = [a.strip() for a in args.attributes.split(",") if a.strip()]
        else:
            attrs = DEFAULT_SELECTED_ATTRIBUTES

        scan.scan_directory(
            base_dir=args.base_dir,
            output_file=args.output,
            extensions=extensions,
            attributes=attrs,
            output_format=args.format,
            limit=args.limit,
        )

    elif args.command == "plan":
        plan.run_planner(
            file_list_path=args.file_list,
            rules_path=args.rules,
            output_plan_path=args.output,
            model=args.model,
            batch_size=args.batch_size,
            limit=args.limit,
            ollama_host=DEFAULT_OLLAMA_HOST,
            num_ctx=DEFAULT_NUM_CTX,
            num_thread=DEFAULT_NUM_THREAD,
            pass2_retry=args.pass2_retry,
        )

    elif args.command == "apply":
        plan_path = args.plan
        if not plan_path.is_file():
            alt = Path("rename_plan.json")
            if alt.is_file():
                plan_path = alt
            else:
                print(f"Error: Plan file not found: {args.plan}")
                sys.exit(1)

        with open(plan_path, "r", encoding="utf-8") as f:
            plan_content = json.load(f)
        plan_list = list(plan_content.values()) if isinstance(plan_content, dict) else plan_content
        base_dir = args.base_dir.resolve()

        ready, needs_review, col = apply.validate_plan(
            base_dir=base_dir,
            plan_data=plan_list,
            allow_medium_confidence=args.apply_medium,
        )
        apply.print_diff(ready, needs_review, base_dir)

        if args.execute:
            if ready:
                apply.execute_renames(base_dir, ready, update_tags=not args.no_tags)
                if not args.skip_verify:
                    report = verify.verify_renames(base_dir, ready, verify_tags=not args.no_tags)
                    verify.print_verification_summary(report)
        else:
            print("\nDRY RUN ONLY. Pass --execute to apply changes on disk.")

    elif args.command == "rollback":
        apply.perform_rollback(args.log_file)

    elif args.command == "verify":
        plan_path = args.plan
        if not plan_path.is_file():
            alt = Path("rename_plan.json")
            if alt.is_file():
                plan_path = alt
            else:
                print(f"Error: Plan file not found: {args.plan}")
                sys.exit(1)

        with open(plan_path, "r", encoding="utf-8") as f:
            plan_content = json.load(f)
        plan_list = list(plan_content.values()) if isinstance(plan_content, dict) else plan_content
        base_dir = args.base_dir.resolve()

        report = verify.verify_renames(base_dir, plan_list, verify_tags=not args.no_tag_verify)
        verify.print_verification_summary(report)

if __name__ == "__main__":
    main()
