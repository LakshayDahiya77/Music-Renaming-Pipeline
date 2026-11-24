"""Main Application Controller connecting Models, Views, and Background Worker Threads."""

import csv
import json
from pathlib import Path
from typing import List, Optional
from PyQt6.QtCore import QObject, pyqtSlot
from PyQt6.QtWidgets import QMessageBox

from config import DEFAULT_MODEL, sanitize_relative_path
from gui.common.logger import app_logger
from gui.controllers.worker_threads import (
    ApplyWorker,
    PlanWorker,
    ResourceMonitorWorker,
    ScanWorker,
    VerifyWorker,
)
from gui.models.model_service import ModelService
from gui.models.plan_model import PlanItem, PlanTableModel
from gui.models.scan_model import ScanTableModel, format_size
from gui.views.main_window import MainWindow

class AppController(QObject):
    """Central Controller coordinating the GUI lifecycle, models, and background workers."""

    def __init__(
        self,
        main_window: MainWindow,
        scan_model: ScanTableModel,
        plan_model: PlanTableModel,
        model_service: ModelService,
    ):
        super().__init__()
        self.window = main_window
        self.scan_model = scan_model
        self.plan_model = plan_model
        self.model_service = model_service

        # Active background workers
        self._scan_worker: Optional[ScanWorker] = None
        self._plan_worker: Optional[PlanWorker] = None
        self._apply_worker: Optional[ApplyWorker] = None
        self._verify_worker: Optional[VerifyWorker] = None

        # Start resource monitor thread
        self.res_worker = ResourceMonitorWorker(self.model_service, interval_sec=1.5, parent=self)
        self.res_worker.stats_updated.connect(self._on_resource_stats)
        self.res_worker.start()

        self._connect_signals()
        self._load_initial_data()

    def _connect_signals(self):
        # 1. LLM Setup Tab Signals
        self.window.llm_setup_tab.start_server_requested.connect(self._start_model_server)
        self.window.llm_setup_tab.stop_server_requested.connect(self._stop_model_server)
        self.window.llm_setup_tab.preload_requested.connect(self._load_model)
        self.window.llm_setup_tab.unload_requested.connect(self._unload_model)
        self.window.llm_setup_tab.local_llm_toggled.connect(self._on_local_llm_toggled)

        # 2. Raw Files Tab Signals
        self.window.raw_files_tab.scan_requested.connect(self._start_scan)
        self.window.raw_files_tab.export_requested.connect(self._export_file_list)

        # 3. Plan Tab Signals
        self.window.plan_tab.plan_requested.connect(self._start_planning)
        self.window.plan_tab.stop_requested.connect(self._stop_planning)
        self.window.plan_tab.save_plan_requested.connect(self._save_plan)
        self.window.plan_tab.reload_plan_requested.connect(self._reload_plan)
        self.window.plan_tab.import_plan_requested.connect(self._on_plan_changed)

        # 4. Plan Model change notification
        self.plan_model.plan_changed.connect(self._on_plan_changed)

        # 5. Apply Tab Signals
        self.window.apply_tab.execute_requested.connect(self._execute_apply)
        self.window.apply_tab.rollback_requested.connect(self._execute_rollback)
        self.window.apply_tab.verification_requested.connect(self._run_verification)

        # 6. Tab change synchronization
        self.window.tabs.currentChanged.connect(self._on_tab_changed)

    def _load_initial_data(self):
        """Loads existing rename_plan.json if present."""
        plan_file = Path("data/rename_plan.json")
        if not plan_file.exists():
            plan_file = Path("rename_plan.json")

        if plan_file.exists():
            count = self.plan_model.load_from_file(plan_file)
            app_logger.info(f"Loaded {count} items from existing plan: '{plan_file.name}'", source="PlanModel")
            self.window.status_bar.showMessage(f"Loaded {count} existing items from {plan_file.name}")
            self.window.plan_tab.update_stats_summary()
            self.window.apply_tab.update_summary()

    @pyqtSlot(dict)
    def _on_resource_stats(self, stats: dict):
        self.window.llm_setup_tab.update_resource_stats(stats)

    @pyqtSlot(bool)
    def _on_local_llm_toggled(self, enabled: bool):
        self.window.plan_tab.set_local_llm_enabled(enabled)
        mode_str = "Enabled" if enabled else "Disabled (Default - Cloud LLMs via file_list.json)"
        app_logger.info(f"Local LLM mode: {mode_str}", source="ModelService")
        self.window.status_bar.showMessage(f"Local LLM: {mode_str}")

    # ==========================
    # Model Controls
    # ==========================
    @pyqtSlot()
    def _start_model_server(self):
        self.window.status_bar.showMessage("Starting Ollama background server...")
        app_logger.action("Starting Ollama server daemon...", source="ModelService")
        ok, msg = self.model_service.start_server()
        self.window.status_bar.showMessage(msg)
        self.window.llm_setup_tab.refresh_diagnostics()
        if ok:
            app_logger.success(msg, source="ModelService")
        else:
            app_logger.error(f"Failed to start Ollama server: {msg}", source="ModelService")
            QMessageBox.critical(self.window, "Model Server Error", msg)

    @pyqtSlot()
    def _stop_model_server(self):
        self.window.status_bar.showMessage("Stopping Ollama server and freeing memory...")
        app_logger.action("Stopping Ollama server daemon...", source="ModelService")
        ok, msg = self.model_service.stop_server()
        self.window.status_bar.showMessage(msg)
        self.window.llm_setup_tab.refresh_diagnostics()
        app_logger.info(msg, source="ModelService")

    @pyqtSlot(str)
    def _load_model(self, model_name: str):
        self.window.status_bar.showMessage(f"Pre-loading model '{model_name}' into memory...")
        app_logger.action(f"Pre-loading weights for '{model_name}'...", source="ModelService")
        ok, msg = self.model_service.preload_model(model_name)
        self.window.status_bar.showMessage(msg)
        self.window.llm_setup_tab.refresh_diagnostics()
        if ok:
            app_logger.success(msg, source="ModelService")
        else:
            app_logger.warning(f"Model load warning: {msg}", source="ModelService")
            QMessageBox.warning(self.window, "Model Load Failed", msg)

    @pyqtSlot(str)
    def _unload_model(self, model_name: str):
        self.window.status_bar.showMessage(f"Unloading model '{model_name}' from memory...")
        ok, msg = self.model_service.unload_model(model_name)
        self.window.status_bar.showMessage(msg)
        self.window.llm_setup_tab.refresh_diagnostics()
        app_logger.info(msg, source="ModelService")

    # ==========================
    # Scanner Operations
    # ==========================
    @pyqtSlot(Path, Path, int)
    def _start_scan(self, base_dir: Path, output_file: Path, limit: int):
        self.window.status_bar.showMessage(f"Scanning {base_dir} for music files...")
        app_logger.action(f"Started music scan in '{base_dir}' (limit={limit})", source="Scanner")
        self.window.raw_files_tab.btn_scan.setEnabled(False)

        self.window.apply_tab.set_base_dir(str(base_dir))

        self._scan_worker = ScanWorker(
            base_dir=base_dir,
            output_file=output_file,
            limit=limit if limit > 0 else None,
            parent=self,
        )
        self._scan_worker.progress.connect(lambda count, msg: self.window.status_bar.showMessage(msg))
        self._scan_worker.scan_finished.connect(self._on_scan_finished)
        self._scan_worker.scan_error.connect(self._on_scan_error)
        self._scan_worker.start()

    @pyqtSlot(list, int, "qint64")
    def _on_scan_finished(self, items: list, count: int, total_bytes: int):
        self.scan_model.set_items(items)
        self.window.raw_files_tab.update_summary(count, total_bytes)
        self.window.raw_files_tab.btn_scan.setEnabled(True)
        size_str = format_size(total_bytes)
        self.window.status_bar.showMessage(f"Scan complete: {count} music files discovered.")
        app_logger.success(f"Scan complete: discovered {count} music files ({size_str})", source="Scanner")

    @pyqtSlot(str)
    def _on_scan_error(self, err_msg: str):
        self.window.raw_files_tab.btn_scan.setEnabled(True)
        self.window.status_bar.showMessage(f"Scan error: {err_msg}")
        app_logger.error(f"Scan error: {err_msg}", source="Scanner")
        QMessageBox.critical(self.window, "Scanning Error", err_msg)

    @pyqtSlot(Path, list, str)
    def _export_file_list(self, output_file: Path, attributes: List[str], fmt: str):
        items = self.scan_model.get_items()
        if not items:
            QMessageBox.information(self.window, "No Files", "No scanned files to export.")
            return

        try:
            records = []
            for item in items:
                rec_full = {
                    "relative_path": item.relative_path,
                    "filename": item.filename,
                    "extension": item.extension,
                    "title": item.title,
                    "artist": item.artist,
                    "album": item.album,
                    "year": item.year,
                    "track_number": item.track_number,
                    "genre": item.genre,
                    "format": item.format,
                    "codec": item.codec,
                    "bitrate_kbps": item.bitrate_kbps,
                    "sample_rate_hz": item.sample_rate_hz,
                    "bits_per_sample": item.bits_per_sample,
                    "channels": item.channels,
                    "duration_formatted": item.duration_formatted,
                    "file_size_formatted": item.formatted_size,
                    "codec_details": item.codec_details,
                    "tag_type": item.tag_type,
                }
                rec = {k: rec_full[k] for k in attributes if k in rec_full}
                records.append(rec)

            output_file.parent.mkdir(parents=True, exist_ok=True)

            if fmt == "json":
                with open(output_file, "w", encoding="utf-8") as f:
                    json.dump(records, f, indent=2, ensure_ascii=False)
            elif fmt == "jsonl":
                with open(output_file, "w", encoding="utf-8") as f:
                    for r in records:
                        f.write(json.dumps(r, ensure_ascii=False) + "\n")
            elif fmt == "csv":
                with open(output_file, "w", encoding="utf-8", newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=attributes, extrasaction="ignore")
                    writer.writeheader()
                    for r in records:
                        writer.writerow(r)
            else:  # txt
                with open(output_file, "w", encoding="utf-8") as f:
                    for r in records:
                        f.write(" | ".join(str(r.get(a, "")) for a in attributes) + "\n")

            msg = f"Exported {len(records)} music records with {len(attributes)} attributes to {output_file.name} ({fmt.upper()})"
            self.window.status_bar.showMessage(msg)
            app_logger.action(msg, source="Scanner")
            QMessageBox.information(self.window, "Export Complete", f"{msg}\n\nPath: {output_file.resolve()}")
        except Exception as e:
            app_logger.error(f"Failed to export file list: {e}", source="Scanner")
            QMessageBox.critical(self.window, "Export Error", f"Failed to write file: {e}")

    # ==========================
    # Planning & AI Batch Operations
    # ==========================
    @pyqtSlot(Path, int, int)
    def _start_planning(self, rules_path: Path, batch_size: int, limit: int):
        if not self.model_service.is_server_running():
            reply = QMessageBox.question(
                self.window,
                "Model Server Offline",
                "The local Ollama server is not running. Would you like to start it now?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self._start_model_server()
            else:
                return

        all_paths = self.scan_model.get_relative_paths()
        if not all_paths:
            file_list_p = Path("data/file_list.json")
            if not file_list_p.exists():
                file_list_p = Path("file_list.json")
            if file_list_p.exists():
                try:
                    with open(file_list_p, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        all_paths = [e.get("relative_path") for e in data if isinstance(e, dict) and "relative_path" in e]
                except Exception:
                    pass

        if not all_paths:
            QMessageBox.warning(
                self.window,
                "No Files to Plan",
                "No music files are loaded. Please scan a directory first or export file_list.json.",
            )
            return

        existing_done = {item.old_path for item in self.plan_model.get_items()}
        pending_paths = [p for p in all_paths if p not in existing_done]

        if not pending_paths:
            QMessageBox.information(
                self.window,
                "All Planned",
                "All files in the list are already planned. To re-plan, exclude or reset items first.",
            )
            return

        if limit > 0:
            pending_paths = pending_paths[:limit]

        model_name = self.window.llm_setup_tab.get_selected_model()
        self.window.plan_tab.set_planning_active(True)
        self.window.plan_tab.progress_bar.setRange(0, len(pending_paths))
        self.window.plan_tab.progress_bar.setValue(0)

        base_dir_str = self.window.raw_files_tab.get_target_dir() or self.window.apply_tab.base_dir
        base_dir = Path(base_dir_str) if base_dir_str else None

        app_logger.action(
            f"Starting AI planning: model='{model_name}', batch_size={batch_size}, rules='{rules_path.name}', files={len(pending_paths)}",
            source="Planner",
        )

        self._plan_worker = PlanWorker(
            paths_to_plan=pending_paths,
            rules_path=rules_path,
            base_dir=base_dir,
            model_name=model_name,
            batch_size=batch_size,
            parent=self,
        )
        self._plan_worker.batch_completed.connect(self._on_plan_batch_completed)
        self._plan_worker.progress.connect(self._on_plan_progress)
        self._plan_worker.plan_error.connect(self._on_plan_error)
        self._plan_worker.plan_finished.connect(self._on_plan_finished)
        self._plan_worker.start()

    @pyqtSlot()
    def _stop_planning(self):
        if self._plan_worker and self._plan_worker.isRunning():
            self._plan_worker.cancel()
            app_logger.warning("User requested stop for AI planner", source="Planner")
            self.window.status_bar.showMessage("Stopping planner after current batch completes...")

    @pyqtSlot(list)
    def _on_plan_batch_completed(self, items: List[PlanItem]):
        self.plan_model.add_or_update_items(items)
        plan_p = Path("data/rename_plan.json")
        plan_p.parent.mkdir(parents=True, exist_ok=True)
        self.plan_model.save_to_file(plan_p)
        app_logger.success(f"Batch completed: processed {len(items)} files, checkpoint saved", source="Planner")

    @pyqtSlot(int, int, str)
    def _on_plan_progress(self, completed: int, total: int, msg: str):
        self.window.plan_tab.progress_bar.setValue(completed)
        self.window.status_bar.showMessage(msg)

    @pyqtSlot(str)
    def _on_plan_error(self, err_msg: str):
        self.window.status_bar.showMessage(f"Planner error: {err_msg}")
        app_logger.error(f"Planner error: {err_msg}", source="Planner")
        self.window.apply_tab.log(f"[ERROR] {err_msg}")

    @pyqtSlot()
    def _on_plan_finished(self):
        self.window.plan_tab.set_planning_active(False)
        self.window.status_bar.showMessage("Planning completed. Review proposed names below.")
        app_logger.success("AI planning run completed.", source="Planner")
        self.window.plan_tab.update_stats_summary()
        self.window.apply_tab.update_summary()

    @pyqtSlot()
    def _save_plan(self):
        plan_p = Path("data/rename_plan.json")
        plan_p.parent.mkdir(parents=True, exist_ok=True)
        self.plan_model.save_to_file(plan_p)
        self.window.status_bar.showMessage(f"Saved {self.plan_model.rowCount()} items to {plan_p}")
        app_logger.action(f"Saved {self.plan_model.rowCount()} plan items to '{plan_p}'", source="PlanModel")
        QMessageBox.information(self.window, "Plan Saved", f"Successfully saved plan to {plan_p.resolve()}")

    @pyqtSlot()
    def _reload_plan(self):
        plan_p = Path("data/rename_plan.json")
        if not plan_p.exists():
            plan_p = Path("rename_plan.json")
        count = self.plan_model.load_from_file(plan_p)
        self.window.status_bar.showMessage(f"Reloaded {count} items from {plan_p.name}")
        app_logger.action(f"Reloaded {count} plan items from '{plan_p.name}'", source="PlanModel")

    @pyqtSlot()
    def _on_plan_changed(self):
        self.window.plan_tab.update_stats_summary()
        self.window.apply_tab.update_summary()

    # ==========================
    # Apply, Rollback & Verification
    # ==========================
    @pyqtSlot(bool, bool)
    def _execute_apply(self, dry_run: bool, update_tags: bool):
        base_dir_str = self.window.apply_tab.base_dir or self.window.raw_files_tab.get_target_dir()
        if not base_dir_str:
            QMessageBox.critical(self.window, "Target Directory Required", "Please select a music directory first.")
            return

        base_dir = Path(base_dir_str)
        active_items = [i for i in self.plan_model.get_active_items() if i.status in ("ready", "modified")]

        app_logger.action(
            f"Initiating batch rename (dry_run={dry_run}, update_tags={update_tags}) for {len(active_items)} files in '{base_dir}'",
            source="Executor",
        )
        self.window.apply_tab.log(f"--- Starting rename execution (dry_run={dry_run}, update_tags={update_tags}) for {len(active_items)} files ---")

        self._apply_worker = ApplyWorker(
            base_dir=base_dir,
            items=active_items,
            dry_run=dry_run,
            update_tags=update_tags,
            parent=self,
        )
        self._apply_worker.progress.connect(lambda cur, tot, msg: self.window.apply_tab.log(f"[{cur}/{tot}] {msg}"))
        self._apply_worker.item_log.connect(self.window.apply_tab.log)
        self._apply_worker.apply_finished.connect(self._on_apply_finished)
        self._apply_worker.apply_error.connect(lambda err: self.window.apply_tab.log(f"[FATAL ERROR] {err}"))
        self._apply_worker.start()

    @pyqtSlot(dict)
    def _on_apply_finished(self, summary: dict):
        dry_run = summary.get("dry_run", True)
        renamed = summary.get("renamed_count", 0)
        skipped = summary.get("skipped_count", 0)
        errors = summary.get("errors", [])
        rollback_file = summary.get("rollback_file")

        self.window.apply_tab.log("\n==========================================")
        self.window.apply_tab.log("              APPLY SUMMARY               ")
        self.window.apply_tab.log("==========================================")
        self.window.apply_tab.log(f"✅ Successfully Processed : {renamed}")
        self.window.apply_tab.log(f"⏭️ Skipped / Up-to-date   : {skipped}")
        self.window.apply_tab.log(f"❌ Errors Encountered     : {len(errors)}")

        if errors:
            self.window.apply_tab.log("\n--- DETAILED ERRORS ---")
            for i, err in enumerate(errors, 1):
                self.window.apply_tab.log(f"  {i}. {err}")
                app_logger.error(f"Rename Error #{i}: {err}", source="Executor")

        if rollback_file:
            self.window.apply_tab.log(f"\n📁 Streaming rollback log:\n  {rollback_file}")

        if dry_run:
            app_logger.info(f"Dry-run simulation completed: {renamed} operations simulated cleanly", source="Executor")
            QMessageBox.information(self.window, "Dry Run Finished", f"Simulated {renamed} renames/tags cleanly. No files modified.")
        else:
            app_logger.success(f"Batch rename executed on disk: {renamed} files processed. Launching verification...", source="Executor")
            # Automatically launch verification phase
            self._run_verification()

    @pyqtSlot()
    def _run_verification(self):
        """Runs Phase 4 post-execution verification."""
        base_dir_str = self.window.apply_tab.base_dir or self.window.raw_files_tab.get_target_dir()
        if not base_dir_str:
            QMessageBox.warning(self.window, "Directory Required", "Please select a target directory first.")
            return

        base_dir = Path(base_dir_str)
        items = [i for i in self.plan_model.get_active_items() if i.status in ("ready", "modified")]
        if not items:
            items = self.plan_model.get_items()

        if not items:
            QMessageBox.information(self.window, "No Items", "No items to verify.")
            return

        self.window.apply_tab.log("\n--- Launching Phase 4: Post-Execution Verification ---")
        self.window.status_bar.showMessage("Running verification of files and tags on disk...")

        self._verify_worker = VerifyWorker(
            base_dir=base_dir,
            plan_items=items,
            verify_tags=True,
            parent=self,
        )
        self._verify_worker.verify_finished.connect(self._on_verification_finished)
        self._verify_worker.verify_error.connect(lambda err: self.window.apply_tab.log(f"[VERIFY ERROR] {err}"))
        self._verify_worker.start()

    @pyqtSlot(object)
    def _on_verification_finished(self, report):
        self.window.apply_tab.update_verification_display(
            total=report.total_checked,
            passed=report.passed_count,
            failed=report.failed_count,
            warnings=report.warning_count,
            report_file=report.report_file,
        )

        self.window.apply_tab.log("\n==========================================")
        self.window.apply_tab.log("       PHASE 4 VERIFICATION REPORT        ")
        self.window.apply_tab.log("==========================================")
        self.window.apply_tab.log(f"Total Checked : {report.total_checked}")
        self.window.apply_tab.log(f"Passed        : {report.passed_count}")
        self.window.apply_tab.log(f"Warnings      : {report.warning_count}")
        self.window.apply_tab.log(f"Failed        : {report.failed_count}")
        self.window.apply_tab.log(f"Report File   : {report.report_file}")

        if report.failed_count > 0 or report.warning_count > 0:
            self.window.apply_tab.log("\n--- DISCREPANCIES DETECTED ---")
            for item in report.items:
                if item.status != "PASSED":
                    self.window.apply_tab.log(f"  • [{item.status}] {item.destination}: {', '.join(item.issues)}")

            QMessageBox.warning(
                self.window,
                "Verification Report",
                f"Verification completed with {report.failed_count} failure(s) and {report.warning_count} warning(s).\n\n"
                f"Passed: {report.passed_count}/{report.total_checked}\n"
                f"Full report saved to:\n{report.report_file}",
            )
        else:
            app_logger.success("Verification passed: 100% of files and tags verified on disk.", source="Verifier")
            QMessageBox.information(
                self.window,
                "Verification Passed",
                f"✓ Verification 100% Complete!\n\nAll {report.passed_count} files exist on disk, are valid playable audio streams, and metadata tags match.",
            )

    @pyqtSlot(Path)
    def _execute_rollback(self, log_path: Path):
        base_dir_str = self.window.apply_tab.base_dir or self.window.raw_files_tab.get_target_dir()
        if not base_dir_str:
            QMessageBox.critical(self.window, "Error", "Target directory not set.")
            return

        base_dir = Path(base_dir_str)
        try:
            from apply import perform_rollback
            self.window.apply_tab.log(f"\n--- Initiating Rollback from {log_path.name} ---")
            perform_rollback(log_path)
            self.window.apply_tab.log("✓ Rollback operations completed.")
            QMessageBox.information(self.window, "Rollback Complete", f"Rollback finished using log:\n{log_path.name}")
        except Exception as e:
            app_logger.error(f"Rollback failed: {e}", source="Rollback")
            QMessageBox.critical(self.window, "Rollback Failed", f"Could not process rollback: {e}")

    @pyqtSlot(int)
    def _on_tab_changed(self, index: int):
        target_dir = self.window.raw_files_tab.get_target_dir()
        if target_dir:
            self.window.apply_tab.set_base_dir(target_dir)
        self.window.plan_tab.update_stats_summary()
        self.window.apply_tab.update_summary()

    def shutdown(self):
        """Clean shutdown of background threads."""
        self.res_worker.stop()
        if self._scan_worker and self._scan_worker.isRunning():
            self._scan_worker.cancel()
            self._scan_worker.wait(1000)
        if self._plan_worker and self._plan_worker.isRunning():
            self._plan_worker.cancel()
            self._plan_worker.wait(1000)
