"""Background worker threads to ensure the Qt GUI never blocks or stutters."""

import datetime
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from PyQt6.QtCore import QThread, pyqtSignal

import ollama
from config import (
    AUDIO_EXTENSIONS,
    DEFAULT_MODEL,
    DEFAULT_NUM_CTX,
    DEFAULT_NUM_THREAD,
    DEFAULT_TEMPERATURE,
    DEFAULT_TOP_P,
    sanitize_relative_path,
)
from gui.common.logger import app_logger
from gui.models.model_service import ModelService
from gui.models.plan_model import PlanItem
from gui.models.scan_model import ScanItem, format_size
from gui.models.validation_engine import compute_final_destination
from companions import build_companion_index, compute_companion_destination
from metadata import get_audio_metadata, get_audio_metadata_batch, write_audio_tags
from plan import build_system_prompt, call_ollama_batch, load_rules
from verify import verify_renames, VerificationReport

class ResourceMonitorWorker(QThread):
    """Periodically inspects CPU % and RAM usage of Ollama inference and system."""

    stats_updated = pyqtSignal(dict)

    def __init__(self, model_service: ModelService, interval_sec: float = 1.5, parent=None):
        super().__init__(parent)
        self.model_service = model_service
        self.interval_sec = interval_sec
        self._running = True

    def run(self):
        while not self.isInterruptionRequested() and self._running:
            try:
                stats = self.model_service.get_resource_stats()
                self.stats_updated.emit(stats)
            except Exception:
                pass
            for _ in range(int(self.interval_sec * 10)):
                if self.isInterruptionRequested() or not self._running:
                    return
                time.sleep(0.1)

    def stop(self):
        self._running = False
        self.requestInterruption()
        self.wait(2000)

class ScanWorker(QThread):
    """Background directory scanner for music files with audio metadata extraction."""

    progress = pyqtSignal(int, str)
    scan_finished = pyqtSignal(list, int, "qint64")
    scan_error = pyqtSignal(str)

    def __init__(
        self,
        base_dir: Path,
        output_file: Optional[Path] = None,
        extensions: Optional[set[str]] = None,
        include_hidden: bool = False,
        limit: Optional[int] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.base_dir = base_dir
        self.output_file = output_file
        self.extensions = extensions or AUDIO_EXTENSIONS
        self.include_hidden = include_hidden
        self.limit = limit
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        try:
            if not self.base_dir.is_dir():
                self.scan_error.emit(f"Base directory does not exist: {self.base_dir}")
                return

            collected_items: List[ScanItem] = []
            total_bytes = 0
            index = 1

            for root, dirs, files in self.base_dir.walk():
                if self._is_cancelled:
                    break

                if not self.include_hidden:
                    dirs[:] = [d for d in dirs if not d.startswith(".")]

                for file in sorted(files):
                    if self._is_cancelled:
                        break

                    if not self.include_hidden and file.startswith("."):
                        continue

                    file_ext = Path(file).suffix.lower()
                    if file_ext in self.extensions:
                        full_path = root / file
                        rel_path = full_path.relative_to(self.base_dir).as_posix()
                        parent_folder = str(full_path.parent.relative_to(self.base_dir).as_posix())
                        if parent_folder == ".":
                            parent_folder = ""

                        try:
                            size = full_path.stat().st_size
                        except OSError:
                            size = 0

                        total_bytes += size
                        collected_items.append(
                            ScanItem(
                                index=index,
                                relative_path=rel_path,
                                filename=file,
                                folder=parent_folder,
                                extension=file_ext,
                                size_bytes=size,
                                formatted_size=format_size(size),
                            )
                        )
                        index += 1

                        if len(collected_items) % 25 == 0:
                            self.progress.emit(len(collected_items), f"Scanned {len(collected_items)} music files...")

                        if self.limit and len(collected_items) >= self.limit:
                            break

                if self.limit and len(collected_items) >= self.limit:
                    break

            # Parallel audio metadata probe
            if collected_items and not self._is_cancelled:
                self.progress.emit(len(collected_items), "Extracting music tags & codec details...")
                full_paths = [self.base_dir / item.relative_path for item in collected_items]
                meta_map = get_audio_metadata_batch(full_paths, max_workers=8)

                for item in collected_items:
                    p_str = str((self.base_dir / item.relative_path).resolve())
                    meta = meta_map.get(p_str)
                    if meta:
                        item.title = meta.title
                        item.artist = meta.artist
                        item.album = meta.album
                        item.year = meta.year
                        item.track_number = meta.track_number
                        item.genre = meta.genre
                        item.format = meta.format
                        item.codec = meta.codec
                        item.bitrate_kbps = meta.bitrate_kbps
                        item.duration_formatted = meta.duration_formatted
                        item.sample_rate_hz = meta.sample_rate_hz
                        item.bits_per_sample = meta.bits_per_sample
                        item.channels = meta.channels
                        item.codec_details = meta.codec_details
                        item.tag_type = meta.tag_type

            # Save initial raw file list if requested
            if self.output_file and collected_items:
                try:
                    self.output_file.parent.mkdir(parents=True, exist_ok=True)
                    records = [
                        {
                            "relative_path": item.relative_path,
                            "filename": item.filename,
                            "artist": item.artist,
                            "title": item.title,
                            "album": item.album,
                            "year": item.year,
                            "track_number": item.track_number,
                            "genre": item.genre,
                            "format": item.format,
                            "codec": item.codec,
                            "bitrate_kbps": item.bitrate_kbps,
                            "duration_formatted": item.duration_formatted,
                        }
                        for item in collected_items
                    ]
                    with open(self.output_file, "w", encoding="utf-8") as f:
                        json.dump(records, f, indent=2, ensure_ascii=False)
                except Exception as e:
                    self.scan_error.emit(f"Failed to write output file: {e}")

            self.scan_finished.emit(collected_items, len(collected_items), total_bytes)

        except Exception as e:
            self.scan_error.emit(f"Scanning failed: {e}")

class PlanWorker(QThread):
    """Background AI planner executing LLM batch inference with music metadata awareness."""

    batch_started = pyqtSignal(int, int)
    batch_completed = pyqtSignal(list)
    progress = pyqtSignal(int, int, str)
    plan_error = pyqtSignal(str)
    plan_finished = pyqtSignal()

    def __init__(
        self,
        paths_to_plan: List[str],
        rules_path: Path,
        base_dir: Optional[Path] = None,
        model_name: str = DEFAULT_MODEL,
        batch_size: int = 10,
        num_ctx: int = DEFAULT_NUM_CTX,
        temperature: float = DEFAULT_TEMPERATURE,
        parent=None,
    ):
        super().__init__(parent)
        self.paths_to_plan = paths_to_plan
        self.rules_path = rules_path
        self.base_dir = base_dir
        self.model_name = model_name
        self.batch_size = batch_size
        self.num_ctx = num_ctx
        self.temperature = temperature
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        try:
            if not self.rules_path.is_file():
                self.plan_error.emit(f"Rules document not found: {self.rules_path}")
                return

            rules_text = load_rules(self.rules_path)
            system_prompt = build_system_prompt(rules_text)
            client = ollama.Client(host="http://localhost:11434")

            batches = [
                self.paths_to_plan[i : i + self.batch_size]
                for i in range(0, len(self.paths_to_plan), self.batch_size)
            ]
            total_batches = len(batches)
            completed_items_count = 0

            for b_idx, batch in enumerate(batches, 1):
                if self._is_cancelled:
                    break

                self.batch_started.emit(b_idx, total_batches)
                self.progress.emit(
                    completed_items_count,
                    len(self.paths_to_plan),
                    f"Processing batch {b_idx}/{total_batches} ({len(batch)} files)...",
                )

                # Pre-fetch metadata for the batch
                meta_dict: Dict[str, Any] = {}
                if self.base_dir:
                    batch_full_paths = [self.base_dir / p for p in batch if (self.base_dir / p).exists()]
                    meta_dict = get_audio_metadata_batch(batch_full_paths)

                # Format entries for prompt
                batch_entries = []
                for p in batch:
                    full_p_str = str((self.base_dir / p).resolve()) if self.base_dir else ""
                    m = meta_dict.get(full_p_str)
                    entry_dict = {"relative_path": p}
                    if m:
                        entry_dict.update({
                            "artist": m.artist,
                            "title": m.title,
                            "album": m.album,
                            "year": m.year,
                            "track_number": m.track_number,
                            "genre": m.genre,
                            "codec": m.codec,
                            "format": m.format,
                        })
                    batch_entries.append(entry_dict)

                try:
                    results = call_ollama_batch(
                        client=client,
                        model=self.model_name,
                        system_prompt=system_prompt,
                        batch_entries=batch_entries,
                        temperature=self.temperature,
                        num_ctx=self.num_ctx,
                        num_thread=DEFAULT_NUM_THREAD,
                    )
                except Exception as e:
                    self.plan_error.emit(f"Error in batch {b_idx}: {e}")
                    results = []

                results_by_path = {sanitize_relative_path(r.old_path): r for r in results}
                produced_items: List[PlanItem] = []

                for entry in batch_entries:
                    path_str = entry["relative_path"]
                    p = Path(path_str)
                    folder = str(p.parent) if str(p.parent) != "." else ""
                    item_res = results_by_path.get(path_str)

                    if item_res:
                        dest = compute_final_destination(path_str, item_res.new_name)
                        new_tags = item_res.new_tags or {}
                        plan_item = PlanItem(
                            index=completed_items_count + len(produced_items) + 1,
                            old_path=path_str,
                            original_name=p.name,
                            folder=folder,
                            proposed_name=item_res.new_name,
                            final_destination=dest,
                            reasoning=item_res.reasoning,
                            confidence=item_res.confidence,
                            artist=new_tags.get("artist") or entry.get("artist", ""),
                            title=new_tags.get("title") or entry.get("title", ""),
                            album=new_tags.get("album") or entry.get("album", ""),
                            year=new_tags.get("year") or entry.get("year", ""),
                            track_number=new_tags.get("track_number") or entry.get("track_number", ""),
                            genre=new_tags.get("genre") or entry.get("genre", ""),
                            codec=entry.get("codec", ""),
                            new_tags=new_tags,
                        )
                    else:
                        plan_item = PlanItem(
                            index=completed_items_count + len(produced_items) + 1,
                            old_path=path_str,
                            original_name=p.name,
                            folder=folder,
                            proposed_name=p.name,
                            final_destination=path_str,
                            reasoning="Missing from model batch output. Marked for review.",
                            confidence="low",
                            artist=entry.get("artist", ""),
                            title=entry.get("title", ""),
                            album=entry.get("album", ""),
                            year=entry.get("year", ""),
                            track_number=entry.get("track_number", ""),
                            genre=entry.get("genre", ""),
                            codec=entry.get("codec", ""),
                        )

                    produced_items.append(plan_item)

                completed_items_count += len(batch)
                self.batch_completed.emit(produced_items)
                self.progress.emit(
                    completed_items_count,
                    len(self.paths_to_plan),
                    f"Completed batch {b_idx}/{total_batches} ({completed_items_count}/{len(self.paths_to_plan)} files)",
                )

            self.plan_finished.emit()

        except Exception as e:
            self.plan_error.emit(f"Planner fatal error: {e}")

class ApplyWorker(QThread):
    """Background worker for applying renames and writing tags with streaming rollback log."""

    progress = pyqtSignal(int, int, str)
    item_log = pyqtSignal(str)
    apply_finished = pyqtSignal(dict)
    apply_error = pyqtSignal(str)

    def __init__(
        self,
        base_dir: Path,
        items: List[PlanItem],
        dry_run: bool = True,
        update_tags: bool = True,
        parent=None,
    ):
        super().__init__(parent)
        self.base_dir = base_dir
        self.items = items
        self.dry_run = dry_run
        self.update_tags = update_tags

    def run(self):
        try:
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            executed_entries = []
            skipped_entries = []
            errors = []
            log_buffer = []

            total = len(self.items)

            self.progress.emit(0, total, "Pre-indexing companion files across target directories (O(N))...")
            src_paths = [self.base_dir / item.old_path for item in self.items if (self.base_dir / item.old_path).exists()]
            companion_index = build_companion_index(src_paths)

            rollback_file = self.base_dir / f"rollback_log_{timestamp}.jsonl"
            rb_f = open(rollback_file, "a", encoding="utf-8") if not self.dry_run else None

            try:
                for idx, item in enumerate(self.items, 1):
                    src_path = self.base_dir / item.old_path
                    dst_path = self.base_dir / item.final_destination

                    if not src_path.exists():
                        msg = f"Source file not found: {item.old_path}"
                        errors.append(msg)
                        skipped_entries.append(item.old_path)
                        app_logger.error(msg, source="ApplyWorker")
                        log_buffer.append(f"❌ [ERROR] {msg}")
                        continue

                    # Read original tags for rollback
                    orig_meta = get_audio_metadata(src_path, use_cache=False)
                    orig_tags = {
                        "title": orig_meta.title,
                        "artist": orig_meta.artist,
                        "album": orig_meta.album,
                        "year": orig_meta.year,
                        "track_number": orig_meta.track_number,
                        "genre": orig_meta.genre,
                    }

                    companions = companion_index.get(src_path.resolve(), [])
                    tags_updated = False

                    if not self.dry_run:
                        # 1. Update tags if present
                        if self.update_tags and item.new_tags:
                            ok, tag_msg = write_audio_tags(src_path, item.new_tags)
                            if ok:
                                tags_updated = True
                                log_buffer.append(f"  🏷️ [TAGS] Updated tags for '{src_path.name}'")

                        # 2. Rename on disk
                        renamed = False
                        if src_path != dst_path:
                            try:
                                dst_path.parent.mkdir(parents=True, exist_ok=True)
                                src_path.rename(dst_path)
                                renamed = True
                                log_buffer.append(f"  ✓ [RENAME] '{item.old_path}' -> '{item.final_destination}'")
                            except Exception as e:
                                err_str = f"Failed to rename {item.old_path}: {e}"
                                errors.append(err_str)
                                app_logger.error(err_str, source="ApplyWorker")
                                log_buffer.append(f"❌ [ERROR] {err_str}")
                                continue
                        else:
                            skipped_entries.append(item.old_path)

                        op_record = {
                            "original_path": item.old_path,
                            "new_path": item.final_destination,
                            "old_absolute": str(src_path.resolve()),
                            "new_absolute": str(dst_path.resolve()),
                            "original_tags": orig_tags,
                            "new_tags": item.new_tags if tags_updated else {},
                            "tags_updated": tags_updated,
                            "renamed": renamed,
                            "timestamp": datetime.datetime.now().isoformat(),
                            "type": "audio",
                        }
                        if rb_f:
                            rb_f.write(json.dumps(op_record, ensure_ascii=False) + "\n")
                        executed_entries.append(op_record)

                        # Move companions
                        target_audio = dst_path if renamed else src_path
                        for comp in companions:
                            comp_dst = compute_companion_destination(comp, src_path, dst_path)
                            comp_dst.parent.mkdir(parents=True, exist_ok=True)
                            try:
                                comp.rename(comp_dst)
                                op_comp = {
                                    "original_path": str(comp.relative_to(self.base_dir).as_posix()),
                                    "new_path": str(comp_dst.relative_to(self.base_dir).as_posix()),
                                    "old_absolute": str(comp.resolve()),
                                    "new_absolute": str(comp_dst.resolve()),
                                    "timestamp": datetime.datetime.now().isoformat(),
                                    "type": "companion",
                                }
                                if rb_f:
                                    rb_f.write(json.dumps(op_comp, ensure_ascii=False) + "\n")
                                log_buffer.append(f"  ↳ [COMPANION] '{comp.name}' -> '{comp_dst.name}'")
                            except Exception:
                                pass

                        if rb_f:
                            rb_f.flush()
                        time.sleep(0.005)

                    else:
                        executed_entries.append({
                            "original_path": item.old_path,
                            "new_path": item.final_destination,
                            "dry_run": True,
                        })
                        log_buffer.append(f"  [SIMULATED] '{item.old_path}' -> '{item.final_destination}'")
                        if self.update_tags and item.new_tags:
                            log_buffer.append(f"    (Would update tags: {item.new_tags})")

                    if idx % 15 == 0 or idx == total or len(log_buffer) >= 15:
                        if log_buffer:
                            self.item_log.emit("\n".join(log_buffer))
                            log_buffer.clear()
                        action_word = "Simulated" if self.dry_run else "Processed"
                        self.progress.emit(idx, total, f"{action_word} {idx}/{total} files...")

            finally:
                if rb_f:
                    rb_f.flush()
                    rb_f.close()

            if log_buffer:
                self.item_log.emit("\n".join(log_buffer))
                log_buffer.clear()

            self.apply_finished.emit({
                "dry_run": self.dry_run,
                "total_considered": total,
                "renamed_count": len(executed_entries),
                "skipped_count": len(skipped_entries),
                "errors": errors,
                "rollback_file": str(rollback_file) if not self.dry_run and executed_entries else None,
            })

        except Exception as e:
            self.apply_error.emit(f"Execution failed: {e}")

class VerifyWorker(QThread):
    """Background worker for Phase 4 verification."""

    verify_finished = pyqtSignal(object)
    verify_error = pyqtSignal(str)

    def __init__(self, base_dir: Path, plan_items: List[PlanItem], verify_tags: bool = True, parent=None):
        super().__init__(parent)
        self.base_dir = base_dir
        self.plan_items = plan_items
        self.verify_tags = verify_tags

    def run(self):
        try:
            plan_dicts = [item.to_dict() for item in self.plan_items]
            report = verify_renames(
                base_dir=self.base_dir,
                plan_data=plan_dicts,
                verify_tags=self.verify_tags,
            )
            self.verify_finished.emit(report)
        except Exception as e:
            self.verify_error.emit(f"Verification failed: {e}")
