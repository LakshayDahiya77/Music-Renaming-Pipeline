#!/usr/bin/env python3
"""Phase 1: Resumable Music Renaming & Tagging Planner

Reads file_list.json (or file_list.txt), passes music paths and extracted metadata
in batches to an LLM with naming and tagging rules injected, and checkpoints structured
rename proposals and tag updates to rename_plan.json.
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
import httpx
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeRemainingColumn
from rich.table import Table

import ollama
from config import (
    DEFAULT_MODEL,
    DEFAULT_OLLAMA_HOST,
    DEFAULT_BATCH_SIZE,
    DEFAULT_NUM_CTX,
    DEFAULT_NUM_THREAD,
    DEFAULT_TEMPERATURE,
    DEFAULT_TOP_P,
    DEFAULT_FILE_LIST_PATH,
    DEFAULT_PLAN_PATH,
    RETRY_TEMPERATURE,
    BatchRenameResponse,
    RenameItem,
    sanitize_relative_path,
)
from metadata import get_audio_metadata_batch

console = Console()

DEFAULT_MUSIC_FEW_SHOTS = """
### Few-Shot Examples for Music Renaming & Tagging:
Input:
Path: "Queen/A Night at the Opera/04 Youre My Best Friend (Remastered 2011).flac"
Metadata: { "artist": "Queen", "title": "You're My Best Friend", "album": "A Night at the Opera", "year": "1975", "track_number": "4" }
Output:
{
  "old_path": "Queen/A Night at the Opera/04 Youre My Best Friend (Remastered 2011).flac",
  "reasoning": "Formatted track with 2-digit pad (04). Standardized clean Title without redundant remaster clutter. Kept original FLAC format.",
  "new_name": "04 - Queen - You're My Best Friend.flac",
  "confidence": "high",
  "new_tags": {
    "artist": "Queen",
    "title": "You're My Best Friend",
    "album": "A Night at the Opera",
    "track_number": "04",
    "year": "1975"
  }
}

Input:
Path: "Downloads/01-pink_floyd_-_speak_to_me-dsd64.dsf"
Metadata: { "artist": "Pink Floyd", "title": "Speak to Me", "album": "The Dark Side of the Moon", "year": "1973", "track_number": "1", "codec": "DSD64" }
Output:
{
  "old_path": "Downloads/01-pink_floyd_-_speak_to_me-dsd64.dsf",
  "reasoning": "Removed underscores and release tags. Padded track number to 01. Preserved Sony DSD (.dsf) extension.",
  "new_name": "01 - Pink Floyd - Speak to Me.dsf",
  "confidence": "high",
  "new_tags": {
    "artist": "Pink Floyd",
    "title": "Speak to Me",
    "album": "The Dark Side of the Moon",
    "track_number": "01",
    "year": "1973"
  }
}

Input:
Path: "Various Artists/Top Hits/track_07_unknown.mp3"
Metadata: { "artist": "", "title": "Track 07", "album": "Top Hits", "year": "2020", "track_number": "7" }
Output:
{
  "old_path": "Various Artists/Top Hits/track_07_unknown.mp3",
  "reasoning": "Artist metadata missing from tags and filename. Formatted conservatively and flagged low confidence for review.",
  "new_name": "07 - Track 07.mp3",
  "confidence": "low",
  "new_tags": {
    "title": "Track 07",
    "album": "Top Hits",
    "track_number": "07",
    "year": "2020"
  }
}
"""

def build_system_prompt(rules_text: str, custom_few_shots: Optional[str] = None) -> str:
    few_shots = custom_few_shots if custom_few_shots is not None else DEFAULT_MUSIC_FEW_SHOTS
    return f"""You are an expert music tagging and audio file renaming assistant.
Your job is to inspect audio file paths and embedded music metadata (artist, title, album, year, track number, format),
and determine the standardized filename and cleaned metadata tags according to the rules below.

### MUSIC NAMING & TAGGING DOCUMENTATION:
{rules_text.strip()}

{few_shots.strip()}

### CRITICAL OPERATIONAL INSTRUCTIONS:
1. You will receive a batch of music files with their relative paths and extracted tags.
2. For every input music file, you MUST provide:
   - "old_path": the exact relative path given to you.
   - "reasoning": brief breakdown of the rules applied and parsing logic used.
   - "new_name": the final standardized filename including the original file extension. Unless instructed to restructure folders, return only the filename.
   - "confidence": "high", "medium", or "low" based on certainty of parsed artist/title/track metadata.
   - "new_tags": optional dictionary with cleaned tags: "artist", "title", "album", "year", "track_number", "genre".
3. PRESERVE THE ORIGINAL FILE EXTENSION EXACTLY (e.g. .mp3, .flac, .m4a, .aac, .dsf, .wav).
4. If metadata is missing or ambiguous, do your best common-sense formatting and set confidence to "medium" or "low".
5. Output valid JSON strictly conforming to the requested schema.
"""

def load_rules(rules_path: Optional[Path]) -> str:
    """Loads naming rules from the specified or auto-detected path."""
    search_paths = [
        rules_path,
        Path("Renaming Rules.txt"),
        Path("renaming_rules.txt"),
        Path("rules.md"),
        Path("RULES.md"),
    ]
    for p in search_paths:
        if p and p.is_file():
            console.print(f"[cyan]Loaded naming rules from:[/cyan] {p.resolve()}")
            return p.read_text(encoding="utf-8")

    console.print("[bold yellow]Notice:[/bold yellow] No specific naming rules file found. Using default music standards.")
    return (
        "Standardize music filenames into: '{Track} - {Artist} - {Title}.{ext}'. "
        "Pad track numbers to 2 digits (e.g. 01, 02). Remove web URLs, release group tags, and messy symbols."
    )

def load_file_list(file_list_path: Path, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """Reads file list from .json, .jsonl, or .txt."""
    if not file_list_path.is_file():
        console.print(f"[bold red]Error:[/bold red] File list not found: {file_list_path}")
        console.print("[yellow]Hint:[/yellow] Run `scan.py <base_dir>` first to generate the file list.")
        sys.exit(1)

    items: List[Dict[str, Any]] = []

    if file_list_path.suffix.lower() == ".json":
        try:
            with open(file_list_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    for entry in data:
                        if isinstance(entry, dict) and "relative_path" in entry:
                            items.append(entry)
                        elif isinstance(entry, str):
                            items.append({"relative_path": sanitize_relative_path(entry)})
        except Exception as e:
            console.print(f"[bold red]Failed to parse JSON file list:[/bold red] {e}")
            sys.exit(1)

    elif file_list_path.suffix.lower() == ".jsonl":
        with open(file_list_path, "r", encoding="utf-8") as f:
            for line in f:
                line_str = line.strip()
                if line_str:
                    try:
                        entry = json.loads(line_str)
                        items.append(entry)
                    except json.JSONDecodeError:
                        items.append({"relative_path": sanitize_relative_path(line_str)})

    else:  # .txt fallback
        with open(file_list_path, "r", encoding="utf-8") as f:
            for line in f:
                cleaned = line.strip()
                if cleaned and not cleaned.startswith("#"):
                    rel = sanitize_relative_path(cleaned.split("|")[0].strip())
                    items.append({"relative_path": rel})

    if limit:
        items = items[:limit]

    return items

def load_checkpoint(plan_path: Path) -> Dict[str, Dict[str, Any]]:
    """Loads existing rename_plan.json into a dict keyed by old_path."""
    if not plan_path.is_file():
        return {}

    try:
        with open(plan_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return {sanitize_relative_path(item.get("old_path", "")): item for item in data if "old_path" in item}
            elif isinstance(data, dict):
                return {sanitize_relative_path(k): v for k, v in data.items()}
    except Exception as e:
        console.print(f"[bold yellow]Warning:[/bold yellow] Could not read existing checkpoint {plan_path}: {e}")
    return {}

def save_checkpoint(plan_path: Path, plan_dict: Dict[str, Dict[str, Any]]) -> None:
    """Atomically saves checkpoint to rename_plan.json using a temp file."""
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = plan_path.with_suffix(".tmp")
    items_list = list(plan_dict.values())
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(items_list, f, indent=2, ensure_ascii=False)
    os.replace(temp_path, plan_path)

def compute_final_destination(old_path: str, new_name: str) -> str:
    """Calculates relative destination path under base directory."""
    old_p = Path(old_path)
    new_p = Path(new_name)

    if len(new_p.parts) > 1:
        return sanitize_relative_path(new_name)
    else:
        parent = old_p.parent
        if str(parent) in (".", ""):
            return sanitize_relative_path(new_name)
        return sanitize_relative_path(f"{parent.as_posix()}/{new_name}")

def resolve_model(client: ollama.Client, requested_model: str) -> str:
    """Resolves requested or fallback local Ollama model."""
    from config import FALLBACK_MODELS
    try:
        response = client.list()
        installed_names = [m.model for m in response.models]
    except Exception:
        installed_names = []

    for name in installed_names:
        if name == requested_model or name.startswith(f"{requested_model}:"):
            return name

    for candidate in FALLBACK_MODELS:
        for name in installed_names:
            if name == candidate or name.startswith(f"{candidate}:"):
                console.print(f"[cyan]Auto-detected installed model:[/cyan] [bold green]{name}[/bold green]")
                return name

    return requested_model

def call_ollama_batch(
    client: ollama.Client,
    model: str,
    system_prompt: str,
    batch_entries: List[Dict[str, Any]],
    temperature: float,
    num_ctx: int,
    num_thread: int = DEFAULT_NUM_THREAD,
) -> List[RenameItem]:
    """Sends a batch of music entries with tags to Ollama and returns parsed RenameItem objects."""
    num_items = len(batch_entries)
    user_prompt = (
        f"Process the following {num_items} music files according to the naming and tagging rules.\n"
        f"Return a JSON object containing an 'items' array with EXACTLY {num_items} elements in the same order:\n\n"
    )

    for idx, entry in enumerate(batch_entries, 1):
        rel_path = entry.get("relative_path", "")
        # Include available tag hints
        tag_hints = []
        for tag_k in ("artist", "title", "album", "year", "track_number", "genre", "codec", "format"):
            val = entry.get(tag_k)
            if val:
                tag_hints.append(f"{tag_k}: '{val}'")
        hint_str = f" [Tags: {', '.join(tag_hints)}]" if tag_hints else ""
        user_prompt += f"{idx}. Path: \"{rel_path}\"{hint_str}\n"

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    options = {
        "temperature": temperature,
        "top_p": DEFAULT_TOP_P,
        "num_ctx": num_ctx,
        "num_thread": num_thread,
        "num_predict": max(600, num_items * 180),
    }

    try:
        response = client.chat(
            model=model,
            messages=messages,
            format=BatchRenameResponse.model_json_schema(),
            options=options,
        )
    except Exception as e:
        console.print(f"[yellow]Notice: Strict schema failed ({e}), retrying with json mode...[/yellow]")
        response = client.chat(
            model=model,
            messages=messages,
            format="json",
            options=options,
        )

    content = response.message.content

    try:
        parsed_batch = BatchRenameResponse.model_validate_json(content)
        return parsed_batch.items
    except Exception:
        raw = json.loads(content)
        if isinstance(raw, list):
            return [RenameItem.model_validate(item) for item in raw]
        elif isinstance(raw, dict):
            if "items" in raw and isinstance(raw["items"], list):
                return [RenameItem.model_validate(item) for item in raw["items"]]
            if "old_path" in raw and "new_name" in raw:
                return [RenameItem.model_validate(raw)]
        raise ValueError(f"Could not parse valid RenameItem batch from response: {content[:200]}")

def run_planner(
    file_list_path: Path,
    rules_path: Optional[Path],
    output_plan_path: Path,
    model: str,
    batch_size: int,
    limit: Optional[int],
    ollama_host: str,
    num_ctx: int,
    num_thread: int = DEFAULT_NUM_THREAD,
    pass2_retry: bool = False,
) -> None:
    client = ollama.Client(host=ollama_host)

    try:
        client.list()
    except Exception as e:
        console.print(f"[bold red]Error connecting to Ollama at {ollama_host}:[/bold red] {e}")
        console.print("[yellow]Ensure Ollama is running (`ollama serve`), or configure external cloud LLM.[/yellow]")
        sys.exit(1)

    model = resolve_model(client, model)
    console.print(f"[cyan]Using local model:[/cyan] [bold green]{model}[/bold green]")

    rules_text = load_rules(rules_path)
    system_prompt = build_system_prompt(rules_text)

    all_entries = load_file_list(file_list_path, limit=limit)
    plan_dict = load_checkpoint(output_plan_path)

    if pass2_retry:
        console.print("[bold cyan]Mode: Pass 2 Retry for Medium/Low confidence items[/bold cyan]")
        to_process = [
            e for e in all_entries
            if e.get("relative_path") in plan_dict
            and plan_dict[e["relative_path"]].get("confidence") in ("medium", "low")
        ]
        temperature = RETRY_TEMPERATURE
    else:
        to_process = [
            e for e in all_entries
            if e.get("relative_path") not in plan_dict
        ]
        temperature = DEFAULT_TEMPERATURE

    total_files = len(all_entries)
    already_done = total_files - len(to_process)

    console.print(f"[cyan]Total music files in list:[/cyan] {total_files}")
    console.print(f"[cyan]Already planned (skipped):[/cyan] {already_done}")
    console.print(f"[bold green]Pending processing:[/bold green] {len(to_process)}")

    if not to_process:
        console.print("[bold green]✓ All files in list are already planned![/bold green]")
        return

    batches = [to_process[i:i + batch_size] for i in range(0, len(to_process), batch_size)]

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TextColumn("({task.completed}/{task.total} batches)"),
        TimeRemainingColumn(),
        console=console,
    ) as progress:
        task_id = progress.add_task("Planning music renames & tags...", total=len(batches))

        for batch in batches:
            try:
                results = call_ollama_batch(
                    client=client,
                    model=model,
                    system_prompt=system_prompt,
                    batch_entries=batch,
                    temperature=temperature,
                    num_ctx=num_ctx,
                    num_thread=num_thread,
                )

                results_by_path = {sanitize_relative_path(r.old_path): r for r in results}

                for entry in batch:
                    orig_path = sanitize_relative_path(entry.get("relative_path", ""))
                    item = results_by_path.get(orig_path)
                    if item:
                        destination = compute_final_destination(item.old_path, item.new_name)
                        plan_dict[orig_path] = {
                            "old_path": item.old_path,
                            "reasoning": item.reasoning,
                            "new_name": item.new_name,
                            "final_destination": destination,
                            "confidence": item.confidence,
                            "new_tags": item.new_tags or {},
                            "current_tags": {
                                "artist": entry.get("artist", ""),
                                "title": entry.get("title", ""),
                                "album": entry.get("album", ""),
                                "year": entry.get("year", ""),
                                "track_number": entry.get("track_number", ""),
                            },
                            "format": entry.get("format", ""),
                            "codec": entry.get("codec", ""),
                        }
                    else:
                        plan_dict[orig_path] = {
                            "old_path": orig_path,
                            "reasoning": "Missing from model response batch. Marked for manual review.",
                            "new_name": Path(orig_path).name,
                            "final_destination": orig_path,
                            "confidence": "low",
                            "new_tags": {},
                        }

                save_checkpoint(output_plan_path, plan_dict)

            except Exception as e:
                console.print(f"\n[bold red]Error in batch processing:[/bold red] {e}")
                save_checkpoint(output_plan_path, plan_dict)
                console.print(f"[yellow]Checkpoint saved to {output_plan_path}.[/yellow]")
                raise

            progress.advance(task_id)

    # Print summary
    conf_counts = {"high": 0, "medium": 0, "low": 0}
    for item in plan_dict.values():
        c = item.get("confidence", "low")
        conf_counts[c] = conf_counts.get(c, 0) + 1

    table = Table(title="Planning Summary", show_header=True, header_style="bold magenta")
    table.add_column("Confidence Level", style="cyan")
    table.add_column("Count", justify="right", style="green")
    table.add_row("High Confidence (Auto-Appliable)", str(conf_counts.get("high", 0)))
    table.add_row("Medium Confidence (Review)", str(conf_counts.get("medium", 0)))
    table.add_row("Low Confidence (Manual Action)", str(conf_counts.get("low", 0)))
    console.print(table)
    console.print(f"[bold green]✓ Rename plan saved to:[/bold green] {output_plan_path.resolve()}")

def main():
    parser = argparse.ArgumentParser(
        description="Phase 1: Resumable Music Renaming & Tagging Planner."
    )
    parser.add_argument(
        "--file-list", "-f",
        type=Path,
        default=DEFAULT_FILE_LIST_PATH,
        help=f"Input file list (default: {DEFAULT_FILE_LIST_PATH})",
    )
    parser.add_argument(
        "--rules", "-r",
        type=Path,
        default=None,
        help="Path to naming rules document",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=DEFAULT_PLAN_PATH,
        help=f"Checkpoint plan output file (default: {DEFAULT_PLAN_PATH})",
    )
    parser.add_argument(
        "--model", "-m",
        type=str,
        default=DEFAULT_MODEL,
        help=f"Local Ollama model name (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--batch-size", "-b",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Batch size of files per LLM call (default: {DEFAULT_BATCH_SIZE})",
    )
    parser.add_argument(
        "--limit", "-l",
        type=int,
        default=None,
        help="Limit number of files to process",
    )
    parser.add_argument(
        "--ollama-host",
        type=str,
        default=os.environ.get("OLLAMA_HOST", DEFAULT_OLLAMA_HOST),
        help=f"Ollama server host (default: {DEFAULT_OLLAMA_HOST})",
    )
    parser.add_argument(
        "--num-ctx",
        type=int,
        default=DEFAULT_NUM_CTX,
        help=f"Context window size (default: {DEFAULT_NUM_CTX})",
    )
    parser.add_argument(
        "--num-threads", "-t",
        type=int,
        default=DEFAULT_NUM_THREAD,
        help=f"Number of CPU threads for inference (default: {DEFAULT_NUM_THREAD})",
    )
    parser.add_argument(
        "--pass2-retry",
        action="store_true",
        help="Pass 2 Retry: Re-process medium/low confidence items",
    )

    args = parser.parse_args()

    run_planner(
        file_list_path=args.file_list,
        rules_path=args.rules,
        output_plan_path=args.output,
        model=args.model,
        batch_size=args.batch_size,
        limit=args.limit,
        ollama_host=args.ollama_host,
        num_ctx=args.num_ctx,
        num_thread=args.num_threads,
        pass2_retry=args.pass2_retry,
    )

if __name__ == "__main__":
    main()
