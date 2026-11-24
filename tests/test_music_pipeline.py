"""Comprehensive test suite for Music Renaming & Tagging Pipeline."""

import io
import json
import os
import shutil
import struct
import sys
import tempfile
import unittest
import wave
from pathlib import Path

from config import AUDIO_EXTENSIONS, sanitize_relative_path
from metadata import (
    AVAILABLE_EXPORT_ATTRIBUTES,
    AudioMetadata,
    format_duration,
    format_file_size,
    get_audio_metadata,
    write_audio_tags,
)
from scan import scan_directory
from apply import validate_plan, execute_renames, perform_rollback
from verify import verify_renames
from gui.models.model_service import ModelService
from gui.models.plan_model import PlanItem, PlanTableModel
from gui.models.scan_model import ScanItem, ScanTableModel
from gui.models.validation_engine import check_filename_validity, compute_final_destination

class TestMusicPipeline(unittest.TestCase):

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="music_pipeline_test_"))

    def tearDown(self):
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)

    def _create_dummy_wav(self, rel_path: str, duration_sec: float = 0.5) -> Path:
        """Creates a real valid WAV file."""
        target = self.test_dir / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        sample_rate = 44100
        n_frames = int(sample_rate * duration_sec)

        with wave.open(str(target), "wb") as wav_file:
            wav_file.setnchannels(2)      # Stereo
            wav_file.setsampwidth(2)     # 16-bit
            wav_file.setframerate(sample_rate)
            raw_data = b"\x00\x00\x00\x00" * n_frames
            wav_file.writeframes(raw_data)

        return target

    def _create_dummy_dsf(self, rel_path: str) -> Path:
        """Creates a minimal valid Sony DSF header (DSD chunk, fmt chunk, data chunk)."""
        target = self.test_dir / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)

        dsd_chunk = struct.pack("<4sQQQ", b"DSD ", 28, 92, 0)
        fmt_chunk = struct.pack(
            "<4sQIIIIIIQII",
            b"fmt ", 52, 1, 0, 2, 2, 2822400, 1, 2822400, 4096, 0
        )
        data_chunk = struct.pack("<4sQ", b"data", 12)

        with open(target, "wb") as f:
            f.write(dsd_chunk + fmt_chunk + data_chunk)

        return target

    def test_audio_metadata_to_dict_filtering(self):
        meta = AudioMetadata(
            file_path="Pink Floyd/01 - Time.flac",
            filename="01 - Time.flac",
            extension=".flac",
            format="FLAC",
            codec="FLAC",
            title="Time",
            artist="Pink Floyd",
            album="The Dark Side of the Moon",
            year="1973",
            track_number="04",
            duration_seconds=425.2,
            duration_formatted="07:05",
            bitrate_kbps=980,
            sample_rate_hz=96000,
            bits_per_sample=24,
            channels=2,
            channel_layout="Stereo",
        )

        all_dict = meta.to_dict()
        self.assertEqual(all_dict["title"], "Time")
        self.assertEqual(all_dict["artist"], "Pink Floyd")
        self.assertEqual(all_dict["duration_formatted"], "07:05")
        self.assertEqual(all_dict["sample_rate_hz"], 96000)

        filtered = meta.to_dict(attributes=["title", "artist", "year", "codec"])
        self.assertEqual(set(filtered.keys()), {"title", "artist", "year", "codec"})
        self.assertEqual(filtered["title"], "Time")
        self.assertNotIn("duration_seconds", filtered)

    def test_dsf_probing(self):
        dsf_path = self._create_dummy_dsf("DSD/01_test_dsd.dsf")
        meta = get_audio_metadata(dsf_path, use_cache=False)

        self.assertEqual(meta.format, "DSF")
        self.assertEqual(meta.codec, "DSD64")
        self.assertEqual(meta.sample_rate_hz, 2822400)
        self.assertEqual(meta.bits_per_sample, 1)
        self.assertEqual(meta.channels, 2)
        self.assertEqual(meta.channel_layout, "Stereo")

    def test_scan_and_attribute_export(self):
        self._create_dummy_wav("Artist A/Album 1/track01.wav", duration_sec=1.0)
        self._create_dummy_wav("Artist B/Album 2/track02.wav", duration_sec=2.0)
        self._create_dummy_dsf("HighRes/dsd_track.dsf")

        out_json = self.test_dir / "data" / "file_list.json"
        attrs = ["relative_path", "filename", "format", "codec", "sample_rate_hz", "duration_formatted"]

        count = scan_directory(
            base_dir=self.test_dir,
            output_file=out_json,
            extensions=AUDIO_EXTENSIONS,
            attributes=attrs,
            output_format="json",
        )

        self.assertEqual(count, 3)
        self.assertTrue(out_json.exists())

        with open(out_json, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.assertEqual(len(data), 3)
        for item in data:
            self.assertIn("relative_path", item)
            self.assertIn("format", item)
            self.assertIn("codec", item)
            self.assertIn("duration_formatted", item)
            self.assertNotIn("comment", item)

    def test_validation_engine(self):
        ok, _ = check_filename_validity("01 - Valid Artist - Valid Title.mp3")
        self.assertTrue(ok)

        bad, err = check_filename_validity("Invalid:Name?.mp3")
        self.assertFalse(bad)
        self.assertIn("Illegal character", err)

        bad_space, _ = check_filename_validity("Trailing Space .mp3")
        self.assertFalse(bad_space)

        dest = compute_final_destination("Rock/Old Song.flac", "01 - Rock - New Song.flac")
        self.assertEqual(dest, "Rock/01 - Rock - New Song.flac")

    def test_apply_and_rollback(self):
        self._create_dummy_wav("Unsorted/track_01.wav", duration_sec=1.0)
        old_rel = "Unsorted/track_01.wav"
        new_name = "01 - Artist - Track 01.wav"
        new_rel = "Unsorted/01 - Artist - Track 01.wav"

        plan = [
            {
                "old_path": old_rel,
                "new_name": new_name,
                "final_destination": new_rel,
                "confidence": "high",
                "reasoning": "Standardized track prefix",
                "new_tags": {
                    "title": "Track 01",
                    "artist": "Artist",
                    "album": "Album",
                    "track_number": "01",
                    "year": "2024",
                },
            }
        ]

        # 1. Validation
        ready, needs_review, col = validate_plan(self.test_dir, plan)
        self.assertEqual(len(ready), 1)
        self.assertEqual(len(needs_review), 0)

        # 2. Execution (renames and writes tags)
        rb_file = execute_renames(self.test_dir, ready, update_tags=True)
        self.assertTrue(rb_file.exists())
        self.assertFalse((self.test_dir / old_rel).exists())
        self.assertTrue((self.test_dir / new_rel).exists())

        # 3. Post-execution verification with tag check
        report = verify_renames(self.test_dir, ready, verify_tags=True)
        self.assertEqual(report.passed_count, 1)
        self.assertEqual(report.failed_count, 0)

        # 4. Rollback
        perform_rollback(rb_file)
        self.assertTrue((self.test_dir / old_rel).exists())
        self.assertFalse((self.test_dir / new_rel).exists())

    def test_verification_engine_failures(self):
        # Test detection of missing file and tag mismatch
        plan = [
            {
                "old_path": "NonExistent/ghost.mp3",
                "new_name": "ghost.mp3",
                "final_destination": "NonExistent/ghost.mp3",
                "new_tags": {"title": "Ghost Song"},
            }
        ]
        report = verify_renames(self.test_dir, plan, verify_tags=True)
        self.assertEqual(report.total_checked, 1)
        self.assertEqual(report.failed_count, 1)
        self.assertEqual(report.passed_count, 0)
        self.assertIn("does not exist", report.items[0].issues[0])

    def test_model_service_detection(self):
        svc = ModelService()
        self.assertIn(svc.os_type, ["linux", "windows", "macos"])
        info = svc.get_installation_instructions()
        self.assertIn("instructions", info)
        self.assertIn("quick_command", info)
        self.assertFalse(svc.is_enabled)

    def test_pipeline_cli_dispatch(self):
        import subprocess
        # Create a dummy audio file in test_dir
        self._create_dummy_wav("music/test_song.wav")

        cmd = [
            sys.executable,
            "src/pipeline.py",
            "scan",
            str(self.test_dir),
            "-o",
            str(self.test_dir / "data" / "cli_list.json"),
        ]
        env = os.environ.copy()
        env["PYTHONPATH"] = "src"
        res = subprocess.run(cmd, env=env, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"Error: {res.stderr}")
        self.assertTrue((self.test_dir / "data" / "cli_list.json").exists())

if __name__ == "__main__":
    import sys
    unittest.main()
