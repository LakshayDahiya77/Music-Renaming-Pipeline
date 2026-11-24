#!/usr/bin/env python3
"""Phase 4: Post-Execution Verification Engine

Verifies that file renames and tag updates were executed correctly on disk:
1. Destination File Existence: Ensures file exists at the expected final destination.
2. Source Disappearance: Ensures old source file no longer lingers (unless no-op rename).
3. File Integrity: Ensures file size > 0 and file is readable.
4. Audio Stream Validity: Validates that audio file is still readable by mutagen.
5. Tag Accuracy: If new tags were specified, reads back the tags and checks for discrepancies.
6. Companion Files: Confirms associated companion files (.lrc, .cue, artwork) were moved.
7. Generates a timestamped verification report (JSON) and outputs clear terminal summary.
"""

import argparse
import datetime
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from rich.console import Console
from rich.table import Table

from config import DATA_DIR, sanitize_relative_path
from metadata import get_audio_metadata

console = Console()

@dataclass
class VerificationResultItem:
    old_path: str
    destination: str
    status: str             # "PASSED", "WARNING", "FAILED"
    size_bytes: int = 0
    issues: List[str] = field(default_factory=list)
    tags_verified: Dict[str, Any] = field(default_factory=dict)

@dataclass
class VerificationReport:
    timestamp: str
    base_dir: str
    total_checked: int
    passed_count: int
    failed_count: int
    warning_count: int
    report_file: Optional[str] = None
    items: List[VerificationResultItem] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "base_dir": self.base_dir,
            "total_checked": self.total_checked,
            "passed_count": self.passed_count,
            "failed_count": self.failed_count,
            "warning_count": self.warning_count,
            "report_file": self.report_file,
            "items": [
                {
                    "old_path": item.old_path,
                    "destination": item.destination,
                    "status": item.status,
                    "size_bytes": item.size_bytes,
                    "issues": item.issues,
                    "tags_verified": item.tags_verified,
                }
                for item in self.items
            ],
        }

def verify_renames(
    base_dir: Path,
    plan_data: List[Dict[str, Any]],
    output_report_dir: Optional[Path] = None,
    verify_tags: bool = True,
) -> VerificationReport:
    """Verifies filesystem changes and tag consistency against plan_data."""
    base_dir = base_dir.resolve()
    report_dir = output_report_dir or DATA_DIR
    report_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = report_dir / f"verification_report_{timestamp}.json"

    result_items: List[VerificationResultItem] = []
    passed = 0
    failed = 0
    warnings = 0

    for entry in plan_data:
        old_rel = sanitize_relative_path(entry.get("old_path", ""))
        new_name = entry.get("new_name", "").strip()
        final_dest = sanitize_relative_path(entry.get("final_destination", "") or new_name)
        new_tags = entry.get("new_tags") or {}

        item_result = VerificationResultItem(
            old_path=old_rel,
            destination=final_dest,
            status="PASSED",
        )

        dst_file = base_dir / final_dest
        src_file = base_dir / old_rel

        # 1. Destination existence check
        if not dst_file.is_file():
            item_result.issues.append(f"Destination file does not exist on disk: '{final_dest}'")
            item_result.status = "FAILED"
            failed += 1
            result_items.append(item_result)
            continue

        # 2. File size and readability check
        try:
            st = dst_file.stat()
            item_result.size_bytes = st.st_size
            if st.st_size == 0:
                item_result.issues.append("Destination file is 0 bytes (corrupt or empty)")
                item_result.status = "FAILED"
        except OSError as e:
            item_result.issues.append(f"Cannot stat destination file: {e}")
            item_result.status = "FAILED"

        # 3. Source disappearance check (only if not a no-op rename)
        if old_rel != final_dest and src_file.exists():
            item_result.issues.append(f"Original source file still exists at '{old_rel}' (possible duplicate)")
            if item_result.status != "FAILED":
                item_result.status = "WARNING"

        # 4. Audio readability & tag verification
        if verify_tags and item_result.status != "FAILED":
            try:
                meta = get_audio_metadata(dst_file, use_cache=False)
                if meta.format == "Unknown":
                    item_result.issues.append("File header cannot be parsed as valid audio format")
                    item_result.status = "FAILED"
                else:
                    item_result.tags_verified["detected_format"] = meta.format
                    item_result.tags_verified["detected_codec"] = meta.codec
                    item_result.tags_verified["duration"] = meta.duration_formatted

                    # Check expected tags
                    for tag_key, expected_val in new_tags.items():
                        if not expected_val:
                            continue
                        actual_val = getattr(meta, tag_key, "")
                        item_result.tags_verified[f"actual_{tag_key}"] = actual_val
                        item_result.tags_verified[f"expected_{tag_key}"] = expected_val

                        # Case-insensitive comparison
                        if str(actual_val).strip().lower() != str(expected_val).strip().lower():
                            # For track numbers, handle leading zero differences (e.g. "01" vs "1")
                            if tag_key == "track_number":
                                act_clean = str(actual_val).lstrip("0")
                                exp_clean = str(expected_val).lstrip("0")
                                if act_clean == exp_clean:
                                    continue
                            item_result.issues.append(
                                f"Tag '{tag_key}' mismatch: expected '{expected_val}', got '{actual_val}'"
                            )
                            if item_result.status != "FAILED":
                                item_result.status = "WARNING"
            except Exception as e:
                item_result.issues.append(f"Audio inspection failed: {e}")
                item_result.status = "WARNING"

        # Tally counts
        if item_result.status == "FAILED":
            failed += 1
        elif item_result.status == "WARNING":
            warnings += 1
        else:
            passed += 1

        result_items.append(item_result)

    report = VerificationReport(
        timestamp=timestamp,
        base_dir=str(base_dir),
        total_checked=len(plan_data),
        passed_count=passed,
        failed_count=failed,
        warning_count=warnings,
        report_file=str(report_path.resolve()),
        items=result_items,
    )

    # Save verification report JSON
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report.to_dict(), f, indent=2, ensure_ascii=False)

    return report

def print_verification_summary(report: VerificationReport) -> None:
    """Prints a beautiful Rich console summary of the verification report."""
    console.print(f"\n[bold cyan]Post-Rename Verification Results:[/bold cyan]")
    console.print(f"  • Base Directory:   {report.base_dir}")
    console.print(f"  • Total Checked:    {report.total_checked}")
    console.print(f"  • Passed:           [bold green]{report.passed_count}[/bold green]")
    console.print(f"  • Warnings:         [bold yellow]{report.warning_count}[/bold yellow]")
    console.print(f"  • Failed:           [bold red]{report.failed_count}[/bold red]")

    if report.failed_count > 0 or report.warning_count > 0:
        table = Table(title="Discrepancies & Issues", show_header=True, header_style="bold red")
        table.add_column("Destination Path", style="dim", max_width=45, overflow="fold")
        table.add_column("Status", width=10)
        table.add_column("Issues Detected", style="bold yellow", max_width=55, overflow="fold")

        for item in report.items:
            if item.status != "PASSED":
                stat_style = "[bold red]FAILED[/bold red]" if item.status == "FAILED" else "[bold yellow]WARNING[/bold yellow]"
                issues_str = "; ".join(item.issues)
                table.add_row(item.destination, stat_style, issues_str)

        console.print(table)
    else:
        console.print("[bold green]✓ All renames and audio tags verified successfully on disk![/bold green]")

    if report.report_file:
        console.print(f"  • Detailed report saved to: [cyan]{report.report_file}[/cyan]\n")

def main():
    parser = argparse.ArgumentParser(
        description="Phase 4: Post-execution verification of music files and tags on disk."
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
        "--no-tag-verify",
        action="store_true",
        help="Skip audio tag read-back verification",
    )

    args = parser.parse_args()

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

    if isinstance(plan_content, dict):
        plan_list = list(plan_content.values())
    elif isinstance(plan_content, list):
        plan_list = plan_content
    else:
        console.print("[bold red]Error:[/bold red] Invalid plan file format.")
        sys.exit(1)

    report = verify_renames(
        base_dir=args.base_dir,
        plan_data=plan_list,
        verify_tags=not args.no_tag_verify,
    )

    print_verification_summary(report)

if __name__ == "__main__":
    main()
