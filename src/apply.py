#!/usr/bin/env python3
"""Phase 2: Deterministic Music Validator & Applier with Tag Writing & Verification

Validates music rename proposals and tag updates before execution:
- Verifies source audio file exists.
- Rejects illegal filesystem characters, empty names, or altered audio extensions.
- Detects target filename collisions.
- Writes / updates audio tags (ID3, Vorbis comments, MP4 atoms) when specified.
- Moves companion files (.lrc, .cue, artwork) alongside audio files.
- Records timestamped streaming rollback logs capturing original paths and original tags.
- Provides rollback mode to cleanly undo filenames AND tags.
- Automatically launches Phase 4 Verification upon completion.
"""

import argparse
import datetime
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from rich.console import Console
from rich.table import Table

from config import ILLEGAL_FILENAME_CHARS, sanitize_relative_path
from companions import (
    find_companion_files,
    build_companion_index,
    compute_companion_destination,
)
from metadata import get_audio_metadata, write_audio_tags
from verify import verify_renames, print_verification_summary

console = Console()

def is_valid_filename(name: str) -> Tuple[bool, str]:
    """Validates filename against illegal characters, control codes, and trailing dots/spaces."""
    if not name or not name.strip():
        return False, "Empty or whitespace-only filename"

    for char in name:
        if ord(char) < 32 or char in ILLEGAL_FILENAME_CHARS:
            return False, f"Illegal character '{char}' in filename"

    p = Path(name)
    if name.endswith(" ") or name.endswith("."):
        return False, "Filename ends with trailing dot or space"
    if p.stem.endswith(" ") or p.stem.endswith("."):
        return False, f"Filename stem '{p.stem}' ends with trailing dot or space"

    return True, "Valid"

def validate_plan(
    base_dir: Path,
    plan_data: List[Dict[str, Any]],
    allow_medium_confidence: bool = False,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[str]]:
    """Deterministically validates all entries in the music renaming plan.
    
    Returns:
        (ready_to_apply, needs_review, collision_warnings)
    """
    ready_to_apply: List[Dict[str, Any]] = []
    needs_review: List[Dict[str, Any]] = []
    collision_warnings: List[str] = []

    target_dest_map: Dict[str, List[str]] = {}

    for item in plan_data:
        old_path_str = sanitize_relative_path(item.get("old_path", ""))
        new_name = item.get("new_name", "").strip()
        old_p = Path(old_path_str)
        old_ext = old_p.suffix

        # Auto-repair missing extension
        if old_ext and not new_name.lower().endswith(old_ext.lower()):
            new_name = new_name.rstrip(". ") + old_ext

        final_dest = item.get("final_destination")
        if not final_dest:
            new_p = Path(new_name)
            if len(new_p.parts) > 1:
                final_dest = sanitize_relative_path(new_name)
            elif str(old_p.parent) != ".":
                final_dest = sanitize_relative_path(str(old_p.parent / new_name))
            else:
                final_dest = sanitize_relative_path(new_name)
        else:
            final_dest = sanitize_relative_path(final_dest)
            if old_ext and not final_dest.lower().endswith(old_ext.lower()):
                final_dest = final_dest.rstrip(". ") + old_ext

        confidence = item.get("confidence", "low").lower()
        reasoning = item.get("reasoning", "")
        new_tags = item.get("new_tags") or {}

        item_copy = {
            "old_path": old_path_str,
            "new_name": new_name,
            "final_destination": final_dest,
            "confidence": confidence,
            "reasoning": reasoning,
            "new_tags": new_tags,
            "issues": [],
        }

        # 1. Source existence check
        source_file = base_dir / old_path_str
        if not source_file.is_file():
            item_copy["issues"].append(f"Source file not found on disk: {old_path_str}")

        # 2. Filename validity check
        target_filename = Path(final_dest).name
        valid_name, name_issue = is_valid_filename(target_filename)
        if not valid_name:
            item_copy["issues"].append(f"Invalid target filename: {name_issue}")

        # 3. Audio extension preservation check
        old_ext_lower = old_p.suffix.lower()
        new_ext_lower = Path(target_filename).suffix.lower()
        if old_ext_lower != new_ext_lower:
            item_copy["issues"].append(f"Audio extension altered: '{old_ext_lower}' -> '{new_ext_lower}'")

        # 4. Confidence thresholds
        if confidence == "low":
            item_copy["issues"].append("Low confidence requires manual review")
        elif confidence == "medium" and not allow_medium_confidence:
            item_copy["issues"].append("Medium confidence (use --apply-medium to include)")

        target_dest_map.setdefault(final_dest, []).append(old_path_str)

        if item_copy["issues"]:
            needs_review.append(item_copy)
        else:
            ready_to_apply.append(item_copy)

    # 5. Collision checks
    final_ready: List[Dict[str, Any]] = []
    for item in ready_to_apply:
        dest = item["final_destination"]
        sources = target_dest_map[dest]

        if len(sources) > 1:
            warn = f"Target collision: Multiple audio files map to '{dest}' ({', '.join(sources)})"
            collision_warnings.append(warn)
            item["issues"].append(warn)
            needs_review.append(item)
            continue

        target_file = base_dir / dest
        source_file = base_dir / item["old_path"]
        if target_file.is_file() and target_file.resolve() != source_file.resolve():
            warn = f"Target already exists on disk and is a different file: '{dest}'"
            collision_warnings.append(warn)
            item["issues"].append(warn)
            needs_review.append(item)
            continue

        final_ready.append(item)

    return final_ready, needs_review, collision_warnings

def print_diff(ready: List[Dict[str, Any]], needs_review: List[Dict[str, Any]], base_dir: Path) -> None:
    """Prints a colorized diff table of proposed filenames and tag updates."""
    console.print(f"\n[bold cyan]Music Base Directory:[/bold cyan] {base_dir.resolve()}\n")

    if ready:
        table = Table(title="✓ Ready To Apply (Passed Validation)", show_header=True, header_style="bold green")
        table.add_column("Original Path", style="dim", max_width=40, overflow="fold")
        table.add_column("Proposed New Path", style="bold green", max_width=45, overflow="fold")
        table.add_column("Tag Updates", style="cyan", max_width=35, overflow="fold")
        table.add_column("Conf.", style="magenta", width=7)

        for item in ready:
            is_noop = item["old_path"] == item["final_destination"]
            dest_display = f"{item['final_destination']} [dim](unchanged)[/dim]" if is_noop else item["final_destination"]
            tag_summary = []
            for k, v in item.get("new_tags", {}).items():
                if v:
                    tag_summary.append(f"{k}: {v}")
            tag_str = ", ".join(tag_summary[:3]) if tag_summary else "[dim]None[/dim]"
            table.add_row(item["old_path"], dest_display, tag_str, item["confidence"])

        console.print(table)
    else:
        console.print("[yellow]No music files currently eligible for automatic execution.[/yellow]")

    if needs_review:
        table_review = Table(title="⚠ Flagged For Review (Excluded From Execution)", show_header=True, header_style="bold yellow")
        table_review.add_column("Original Path", style="dim", max_width=40, overflow="fold")
        table_review.add_column("Proposed Destination", style="yellow", max_width=40, overflow="fold")
        table_review.add_column("Conf.", style="cyan", width=7)
        table_review.add_column("Issues / Flags", style="bold red", max_width=40, overflow="fold")

        for item in needs_review:
            issues_str = "; ".join(item.get("issues", []))
            table_review.add_row(item["old_path"], item["final_destination"], item["confidence"], issues_str)

        console.print(table_review)

def execute_renames(
    base_dir: Path,
    ready_items: List[Dict[str, Any]],
    update_tags: bool = True,
) -> Path:
    """Executes file renames and tag updates on disk, streaming an append-only rollback log."""
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    rollback_file = base_dir / f"rollback_log_{timestamp}.jsonl"

    executed_count = 0
    tag_updated_count = 0
    skipped_noop_count = 0

    console.print("\n[bold green]Pre-indexing companion files across target directories (O(N))...[/bold green]")
    audio_src_paths = [base_dir / item["old_path"] for item in ready_items]
    companion_index = build_companion_index(audio_src_paths)

    console.print(f"[bold green]Executing music renames & tags (streaming to {rollback_file.name})...[/bold green]")

    with open(rollback_file, "a", encoding="utf-8") as rb_f:
        for item in ready_items:
            old_rel = item["old_path"]
            new_rel = item["final_destination"]
            new_tags = item.get("new_tags") or {}

            src = base_dir / old_rel
            dst = base_dir / new_rel

            # Read current tags before modifying for rollback logging
            orig_meta = get_audio_metadata(src, use_cache=False)
            orig_tags = {
                "title": orig_meta.title,
                "artist": orig_meta.artist,
                "album": orig_meta.album,
                "year": orig_meta.year,
                "track_number": orig_meta.track_number,
                "genre": orig_meta.genre,
            }

            companions = companion_index.get(src.resolve(), [])

            # Step 1: Write/update audio tags if requested and available
            tags_were_updated = False
            if update_tags and new_tags:
                ok, tag_msg = write_audio_tags(src, new_tags)
                if ok:
                    tags_were_updated = True
                    tag_updated_count += 1
                else:
                    console.print(f"  [yellow]Tag update warning for {src.name}:[/yellow] {tag_msg}")

            # Step 2: Rename / Move file on disk
            dst.parent.mkdir(parents=True, exist_ok=True)
            renamed_on_disk = False

            if src.resolve() != dst.resolve():
                try:
                    src.rename(dst)
                    renamed_on_disk = True
                    executed_count += 1
                except Exception as e:
                    console.print(f"[bold red]Failed to rename:[/bold red] {old_rel} -> {new_rel}: {e}")
                    continue
            else:
                skipped_noop_count += 1

            # Log operation to rollback file
            op_record = {
                "original_path": old_rel,
                "new_path": new_rel,
                "old_absolute": str(src.resolve()),
                "new_absolute": str(dst.resolve()),
                "original_tags": orig_tags,
                "new_tags": new_tags if tags_were_updated else {},
                "tags_updated": tags_were_updated,
                "renamed": renamed_on_disk,
                "timestamp": datetime.datetime.now().isoformat(),
                "type": "audio",
            }
            rb_f.write(json.dumps(op_record, ensure_ascii=False) + "\n")

            # Move companion files
            target_audio_for_comp = dst if renamed_on_disk else src
            for comp in companions:
                comp_dst = compute_companion_destination(comp, src, dst)
                comp_dst.parent.mkdir(parents=True, exist_ok=True)
                try:
                    comp.rename(comp_dst)
                    op_comp = {
                        "original_path": str(comp.relative_to(base_dir).as_posix()),
                        "new_path": str(comp_dst.relative_to(base_dir).as_posix()),
                        "old_absolute": str(comp.resolve()),
                        "new_absolute": str(comp_dst.resolve()),
                        "timestamp": datetime.datetime.now().isoformat(),
                        "type": "companion",
                    }
                    rb_f.write(json.dumps(op_comp, ensure_ascii=False) + "\n")
                    console.print(f"  [cyan]↳ Moved companion:[/cyan] {comp.name} -> {comp_dst.name}")
                except Exception as e:
                    console.print(f"  [yellow]Failed to move companion {comp.name}:[/yellow] {e}")

            rb_f.flush()
            time.sleep(0.005)

    console.print(f"\n[bold green]✓ Execution completed:[/bold green]")
    console.print(f"  • {executed_count} audio files renamed on disk.")
    if tag_updated_count > 0:
        console.print(f"  • {tag_updated_count} files had metadata tags updated.")
    if skipped_noop_count > 0:
        console.print(f"  • {skipped_noop_count} files were already named correctly (tags updated if needed).")
    console.print(f"  • Streaming rollback log saved to: [bold cyan]{rollback_file.resolve()}[/bold cyan]")

    return rollback_file

def perform_rollback(rollback_file: Path) -> None:
    """Reverses operations recorded in a rollback log, restoring original filenames AND tags."""
    if not rollback_file.is_file():
        console.print(f"[bold red]Error:[/bold red] Rollback log not found: {rollback_file}")
        sys.exit(1)

    operations: List[Dict[str, Any]] = []
    with open(rollback_file, "r", encoding="utf-8") as f:
        content = f.read().strip()
        if not content:
            console.print(f"[yellow]Rollback log is empty:[/yellow] {rollback_file}")
            return

        # Attempt to load line by line (jsonl) first
        for line in content.splitlines():
            line_str = line.strip()
            if not line_str:
                continue
            try:
                item = json.loads(line_str)
                if isinstance(item, dict):
                    if "operations" in item and isinstance(item["operations"], list):
                        operations.extend(item["operations"])
                    else:
                        operations.append(item)
                elif isinstance(item, list):
                    operations.extend(item)
            except json.JSONDecodeError:
                pass

        # If line-by-line found nothing, attempt full document parse
        if not operations:
            try:
                data = json.loads(content)
                if isinstance(data, list):
                    operations = data
                elif isinstance(data, dict):
                    operations = data.get("operations", [data])
            except json.JSONDecodeError:
                pass

    console.print(f"[bold cyan]Rolling back {len(operations)} operations from:[/bold cyan] {rollback_file}")

    reverted_files = 0
    reverted_tags = 0
    errors = 0

    for op in reversed(operations):
        new_abs = Path(op["new_absolute"])
        old_abs = Path(op["old_absolute"])
        orig_tags = op.get("original_tags") or {}

        # 1. Revert audio tags first if they were updated
        target_file_for_tags = new_abs if new_abs.exists() else old_abs
        if op.get("tags_updated") and orig_tags and target_file_for_tags.exists():
            ok, _ = write_audio_tags(target_file_for_tags, orig_tags)
            if ok:
                reverted_tags += 1

        # 2. Revert filename
        if op.get("renamed", True):
            if not new_abs.exists():
                console.print(f"[bold red]Cannot rollback file:[/bold red] Not found at {new_abs}")
                errors += 1
                continue

            old_abs.parent.mkdir(parents=True, exist_ok=True)
            try:
                new_abs.rename(old_abs)
                reverted_files += 1
            except Exception as e:
                try:
                    shutil.move(new_abs, old_abs)
                    reverted_files += 1
                except Exception as e2:
                    console.print(f"[bold red]Error reverting:[/bold red] {new_abs} -> {old_abs}: {e2}")
                    errors += 1

    console.print(f"\n[bold green]Rollback completed:[/bold green]")
    console.print(f"  • Reverted {reverted_files} files back to original paths.")
    if reverted_tags > 0:
        console.print(f"  • Restored original audio tags for {reverted_tags} files.")
    if errors > 0:
        console.print(f"  • [bold red]Errors encountered:[/bold red] {errors}")

def main():
    parser = argparse.ArgumentParser(
        description="Phase 2: Deterministic Music Validator & Applier with Tag Writing & Verification."
    )
    parser.add_argument(
        "base_dir",
        type=Path,
        nargs="?",
        default=Path("."),
        help="Base directory containing the music files (default: current directory)",
    )
    parser.add_argument(
        "--plan", "-p",
        type=Path,
        default=Path("data/rename_plan.json"),
        help="Path to rename_plan.json (default: data/rename_plan.json)",
    )
    parser.add_argument(
        "--needs-review", "-r",
        type=Path,
        default=Path("data/needs_review.json"),
        help="Path to export flagged items (default: data/needs_review.json)",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Execute disk rename and tag operations. If omitted, performs safe dry-run preview.",
    )
    parser.add_argument(
        "--apply-medium",
        action="store_true",
        help="Include medium-confidence valid items in execution",
    )
    parser.add_argument(
        "--no-tags",
        action="store_true",
        help="Rename files on disk without writing/updating audio tags",
    )
    parser.add_argument(
        "--rollback",
        type=Path,
        default=None,
        help="Revert operations using a specified rollback_log_*.jsonl file",
    )
    parser.add_argument(
        "--skip-verify",
        action="store_true",
        help="Skip post-rename verification phase after execution",
    )

    args = parser.parse_args()

    if args.rollback:
        perform_rollback(args.rollback)
        return

    plan_path = args.plan
    if not plan_path.is_file():
        alt = Path("rename_plan.json")
        if alt.is_file():
            plan_path = alt
        else:
            console.print(f"[bold red]Error:[/bold red] Plan file not found: {args.plan}")
            sys.exit(1)

    with open(plan_path, "r", encoding="utf-8") as f:
        plan_content = json.load(f)

    plan_list = list(plan_content.values()) if isinstance(plan_content, dict) else plan_content
    base_dir = args.base_dir.resolve()

    ready, needs_review, collision_warnings = validate_plan(
        base_dir=base_dir,
        plan_data=plan_list,
        allow_medium_confidence=args.apply_medium,
    )

    if needs_review:
        args.needs_review.parent.mkdir(parents=True, exist_ok=True)
        with open(args.needs_review, "w", encoding="utf-8") as f:
            json.dump(needs_review, f, indent=2, ensure_ascii=False)

    print_diff(ready, needs_review, base_dir)

    console.print("\n[bold magenta]Validation Statistics:[/bold magenta]")
    console.print(f"  • Total planned music files: {len(plan_list)}")
    console.print(f"  • Ready for execution:       [bold green]{len(ready)}[/bold green]")
    console.print(f"  • Flagged for review:        [bold yellow]{len(needs_review)}[/bold yellow] (saved to {args.needs_review})")
    if collision_warnings:
        console.print(f"  • [bold red]Collisions detected:[/bold red]    {len(collision_warnings)}")

    if not args.execute:
        console.print("\n[bold yellow]DRY RUN COMPLETE.[/bold yellow] No files or tags were modified on disk.")
        if ready:
            console.print("[bold green]To apply these changes, run again with the --execute flag:[/bold green]")
            console.print(f"  python apply.py \"{base_dir}\" --execute\n")
    else:
        if not ready:
            console.print("\n[yellow]No valid files to execute.[/yellow]")
            return

        execute_renames(base_dir, ready, update_tags=not args.no_tags)

        # Launch Verification Phase
        if not args.skip_verify:
            console.print("\n[bold cyan]Phase 4: Launching post-rename verification...[/bold cyan]")
            report = verify_renames(base_dir, ready, verify_tags=not args.no_tags)
            print_verification_summary(report)

if __name__ == "__main__":
    main()
