#!/usr/bin/env python3
"""Phase 0: Music File Scanner & Attribute Exporter

Recursively scans a target directory for audio/music files (mp3, m4a, flac, aac, dsf, etc.),
extracts music-specific tags and codec attributes, and exports the structured file list
in user-selected format (JSON default, JSONL, CSV, TXT) with customizable attribute selection.
"""

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import List, Optional, Set
from rich.console import Console
from rich.table import Table

from config import AUDIO_EXTENSIONS, DEFAULT_FILE_LIST_PATH
from metadata import (
    AVAILABLE_EXPORT_ATTRIBUTES,
    DEFAULT_SELECTED_ATTRIBUTES,
    AudioMetadata,
    format_duration,
    format_file_size,
    get_audio_metadata_batch,
)

console = Console()

def scan_directory(
    base_dir: Path,
    output_file: Path,
    extensions: Set[str],
    attributes: Optional[List[str]] = None,
    output_format: str = "json",
    include_hidden: bool = False,
    limit: Optional[int] = None,
) -> int:
    """Recursively scans base_dir for audio files, extracts music attributes, and exports list."""
    base_dir = base_dir.resolve()
    if not base_dir.is_dir():
        console.print(f"[bold red]Error:[/bold red] Base directory does not exist: {base_dir}")
        sys.exit(1)

    selected_attrs = attributes or DEFAULT_SELECTED_ATTRIBUTES

    console.print(f"[cyan]Scanning base directory:[/cyan] {base_dir}")
    console.print(f"[cyan]Target music extensions:[/cyan] {', '.join(sorted(extensions))}")
    console.print(f"[cyan]Exporting attributes ({len(selected_attrs)}):[/cyan] {', '.join(selected_attrs)}")

    collected_paths: List[str] = []
    extension_counts: dict[str, int] = {ext: 0 for ext in extensions}
    total_bytes = 0

    # Walk directory tree
    for root, dirs, files in base_dir.walk():
        if not include_hidden:
            dirs[:] = [d for d in dirs if not d.startswith(".")]

        for file in sorted(files):
            if not include_hidden and file.startswith("."):
                continue

            file_ext = Path(file).suffix.lower()
            if file_ext in extensions:
                full_path = root / file
                rel_path = full_path.relative_to(base_dir).as_posix()
                collected_paths.append(rel_path)

                extension_counts[file_ext] = extension_counts.get(file_ext, 0) + 1
                try:
                    total_bytes += full_path.stat().st_size
                except OSError:
                    pass

                if limit and len(collected_paths) >= limit:
                    break
        if limit and len(collected_paths) >= limit:
            break

    if not collected_paths:
        console.print("[bold yellow]No matching audio files found.[/bold yellow]")
        return 0

    # Extract music tags & codec properties using metadata engine
    console.print(f"[cyan]Extracting audio tags & stream attributes for {len(collected_paths)} files...[/cyan]")
    full_paths = [base_dir / p for p in collected_paths]
    meta_map = get_audio_metadata_batch(full_paths, max_workers=8)

    # Prepare structured records
    records = []
    total_duration_sec = 0.0
    codec_counts: dict[str, int] = {}

    for rel_p in collected_paths:
        full_p_str = str((base_dir / rel_p).resolve())
        meta = meta_map.get(full_p_str)
        if meta:
            rec = meta.to_dict(attributes=selected_attrs, relative_path=rel_p)
            total_duration_sec += meta.duration_seconds
            codec_counts[meta.codec] = codec_counts.get(meta.codec, 0) + 1
        else:
            rec = {"relative_path": rel_p, "filename": Path(rel_p).name}
        records.append(rec)

    # Determine output format from file suffix if not explicitly specified
    out_fmt = output_format.lower()
    if output_file.suffix.lower() in (".json", ".jsonl", ".txt", ".csv"):
        out_fmt = output_file.suffix.lower().lstrip(".")

    output_file.parent.mkdir(parents=True, exist_ok=True)

    # Write output file
    if out_fmt == "json":
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2, ensure_ascii=False)
    elif out_fmt == "jsonl":
        with open(output_file, "w", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    elif out_fmt == "csv":
        with open(output_file, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=selected_attrs, extrasaction="ignore")
            writer.writeheader()
            for rec in records:
                writer.writerow(rec)
    else:  # txt
        with open(output_file, "w", encoding="utf-8") as f:
            for rec in records:
                rel = rec.get("relative_path", "")
                art = rec.get("artist", "")
                tit = rec.get("title", "")
                alb = rec.get("album", "")
                parts = [rel]
                if art or tit:
                    parts.append(f"{art} - {tit}".strip(" -"))
                if alb:
                    parts.append(f"[{alb}]")
                f.write(" | ".join(parts) + "\n")

    # Display summary tables
    table = Table(title="Audio Format Summary", show_header=True, header_style="bold magenta")
    table.add_column("Format / Ext", style="cyan")
    table.add_column("Files", justify="right", style="green")

    for ext, count in sorted(extension_counts.items(), key=lambda x: -x[1]):
        if count > 0:
            table.add_row(ext.upper(), str(count))

    console.print(table)

    if codec_counts:
        c_table = Table(title="Detected Codecs", show_header=True, header_style="bold cyan")
        c_table.add_column("Codec", style="magenta")
        c_table.add_column("Count", justify="right", style="green")
        for c, count in sorted(codec_counts.items(), key=lambda x: -x[1]):
            c_table.add_row(c, str(count))
        console.print(c_table)

    dur_str = format_duration(total_duration_sec)
    size_str = format_file_size(total_bytes)

    console.print(f"[bold green]✓ Total music files scanned:[/bold green] {len(collected_paths)}")
    console.print(f"  • Total Playtime: [bold cyan]{dur_str}[/bold cyan]")
    console.print(f"  • Total Size:     [bold cyan]{size_str}[/bold cyan]")
    console.print(f"[bold green]✓ File list saved to:[/bold green] {output_file.resolve()} ([cyan]{out_fmt.upper()}[/cyan])")

    return len(collected_paths)

def main():
    parser = argparse.ArgumentParser(
        description="Phase 0: Recursively scan directory for music files and export attributes."
    )
    parser.add_argument(
        "base_dir",
        type=Path,
        nargs="?",
        default=Path("."),
        help="Base directory containing music files (default: current directory)",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=DEFAULT_FILE_LIST_PATH,
        help=f"Path to output file list (default: {DEFAULT_FILE_LIST_PATH})",
    )
    parser.add_argument(
        "--format", "-f",
        type=str,
        choices=["json", "jsonl", "csv", "txt"],
        default="json",
        help="Export format (default: json)",
    )
    parser.add_argument(
        "--attributes", "-a",
        type=str,
        default=None,
        help="Comma-separated list of attributes to export (e.g. relative_path,artist,title,album,year,track_number,codec,bitrate_kbps)",
    )
    parser.add_argument(
        "--all-attributes",
        action="store_true",
        help="Export all 24 available music tags and codec attributes",
    )
    parser.add_argument(
        "--extensions", "-e",
        type=str,
        default=None,
        help="Comma-separated audio file extensions to include (default: mp3,m4a,flac,aac,dsf,wav,ogg,opus)",
    )
    parser.add_argument(
        "--include-hidden",
        action="store_true",
        help="Include hidden files and folders",
    )
    parser.add_argument(
        "--limit", "-l",
        type=int,
        default=None,
        help="Limit number of scanned files (useful for quick testing)",
    )

    args = parser.parse_args()

    extensions = (
        {ext.strip().lower() if ext.strip().startswith(".") else f".{ext.strip().lower()}"
         for ext in args.extensions.split(",")}
        if args.extensions
        else AUDIO_EXTENSIONS
    )

    if args.all_attributes:
        attrs = [k for k, _, _ in AVAILABLE_EXPORT_ATTRIBUTES]
    elif args.attributes:
        attrs = [a.strip() for a in args.attributes.split(",") if a.strip()]
    else:
        attrs = DEFAULT_SELECTED_ATTRIBUTES

    scan_directory(
        base_dir=args.base_dir,
        output_file=args.output,
        extensions=extensions,
        attributes=attrs,
        output_format=args.format,
        include_hidden=args.include_hidden,
        limit=args.limit,
    )

if __name__ == "__main__":
    main()
