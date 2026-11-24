#!/usr/bin/env python3
"""Companion file handling for audio / music files.

Audio files often have associated companions:
1. Lyrics files (.lrc)
2. Cue sheets (.cue)
3. Ripping / EAC log files (.log)
4. Matching track cover art (.jpg, .png, .webp)
5. Metadata / info text files (.nfo, .txt)

When an audio file is renamed or moved, its direct companions (e.g. Song.mp3 -> Song.lrc)
are automatically kept in sync and moved alongside.
"""

from pathlib import Path
from typing import Dict, List, Set

# Supported audio companion file extensions
LYRICS_EXTENSIONS: Set[str] = {".lrc"}
CUE_EXTENSIONS: Set[str] = {".cue"}
LOG_EXTENSIONS: Set[str] = {".log"}
IMAGE_EXTENSIONS: Set[str] = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
METADATA_EXTENSIONS: Set[str] = {".nfo", ".txt"}

AUDIO_COMPANION_EXTENSIONS: Set[str] = (
    LYRICS_EXTENSIONS | CUE_EXTENSIONS | LOG_EXTENSIONS | IMAGE_EXTENSIONS | METADATA_EXTENSIONS
)

# For backward compatibility
COMPANION_EXTENSIONS = AUDIO_COMPANION_EXTENSIONS

def is_companion_filename(file_stem: str, audio_stem: str) -> bool:
    """Determines if a companion file corresponds to the target audio file.
    
    Examples matching 'Track01':
      - 'Track01.lrc' (exact match)
      - 'Track01_thumb.jpg', 'Track01-cover.png', 'Track01 (1).jpg'
    """
    s_file = file_stem.strip()
    s_audio = audio_stem.strip()

    if s_file.lower() == s_audio.lower():
        return True

    if s_file.lower().startswith(s_audio.lower()):
        separator = s_file[len(s_audio):len(s_audio) + 1]
        if separator in ("_", "-", " ", ".", "("):
            return True

    return False

def find_companion_files(audio_path: Path) -> List[Path]:
    """Finds all companion files on disk associated with audio_path."""
    if not audio_path.parent.exists() or not audio_path.parent.is_dir():
        return []

    audio_stem = audio_path.stem
    companions: List[Path] = []

    try:
        for entry in audio_path.parent.iterdir():
            if not entry.is_file():
                continue
            if entry.resolve() == audio_path.resolve():
                continue
            if entry.suffix.lower() not in AUDIO_COMPANION_EXTENSIONS:
                continue

            if is_companion_filename(entry.stem, audio_stem):
                companions.append(entry)
    except OSError:
        pass

    return sorted(companions, key=lambda p: p.name)

def build_companion_index(audio_paths: List[Path]) -> Dict[Path, List[Path]]:
    """Pre-indexes companion files in O(N) across unique parent directories.
    
    Avoids O(N^2) repetitive readdir/stat calls over external mounts and NTFS.
    """
    index: Dict[Path, List[Path]] = {}
    dirs_to_audios: Dict[Path, List[Path]] = {}

    for ap in audio_paths:
        try:
            ap_res = ap.resolve()
            parent = ap_res.parent
            if parent.exists() and parent.is_dir():
                dirs_to_audios.setdefault(parent, []).append(ap_res)
                index[ap_res] = []
        except OSError:
            continue

    for parent_dir, a_list in dirs_to_audios.items():
        try:
            for entry in parent_dir.iterdir():
                if not entry.is_file():
                    continue
                if entry.suffix.lower() not in AUDIO_COMPANION_EXTENSIONS:
                    continue
                entry_res = entry.resolve()
                entry_stem = entry.stem

                for a in a_list:
                    if entry_res == a:
                        continue
                    if is_companion_filename(entry_stem, a.stem):
                        index[a].append(entry)
                        break
        except OSError:
            continue

    return index

def compute_companion_destination(
    companion_src: Path,
    audio_src: Path,
    audio_dst: Path,
) -> Path:
    """Calculates target destination for a companion file when its audio is renamed/moved."""
    dst_parent = audio_dst.parent
    dst_audio_stem = audio_dst.stem
    comp_ext = companion_src.suffix

    src_audio_stem = audio_src.stem
    comp_stem = companion_src.stem

    if comp_stem.lower() == src_audio_stem.lower():
        new_comp_name = f"{dst_audio_stem}{comp_ext}"
    elif comp_stem.lower().startswith(src_audio_stem.lower()):
        suffix_diff = comp_stem[len(src_audio_stem):]
        new_comp_name = f"{dst_audio_stem}{suffix_diff}{comp_ext}"
    else:
        new_comp_name = f"{dst_audio_stem}_{companion_src.name}"

    return dst_parent / new_comp_name
