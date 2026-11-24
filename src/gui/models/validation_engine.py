"""Deterministic validation engine for live checking of music rename proposals."""

from pathlib import Path
from typing import Any, Literal
from config import AUDIO_EXTENSIONS, ILLEGAL_FILENAME_CHARS, sanitize_relative_path

ValidationStatus = Literal["ready", "review", "collision", "illegal", "modified", "excluded"]

def check_filename_validity(name: str) -> tuple[bool, str]:
    """Validates filename against illegal characters, control codes, trailing dots/spaces."""
    if not name or not name.strip():
        return False, "Empty or whitespace-only filename"

    p = Path(name)
    parts = p.parts if len(p.parts) > 1 else [name]

    for part in parts:
        if not part.strip():
            return False, "Empty path component"
        for char in part:
            if ord(char) < 32 or char in (ILLEGAL_FILENAME_CHARS - {'/', '\\'}):
                return False, f"Illegal character '{char}' in filename"

        if part.endswith(" ") or part.endswith("."):
            return False, f"Component '{part}' ends with trailing dot or space"

    # Also reject trailing dot or space in stem (e.g. 'Song .mp3')
    if p.stem.endswith(" ") or p.stem.endswith("."):
        return False, f"Filename stem '{p.stem}' ends with trailing dot or space"

    return True, "Valid"

def compute_final_destination(old_path_str: str, new_name: str, existing_dest: str = "") -> str:
    """Computes destination path preserving directory structure or existing destination folder."""
    new_p = Path(new_name)

    if len(new_p.parts) > 1:
        return sanitize_relative_path(str(new_p))

    if existing_dest:
        dest_p = Path(existing_dest)
        if len(dest_p.parts) > 1:
            return sanitize_relative_path(str(dest_p.parent / new_p.name))

    old_p = Path(old_path_str)
    parent = old_p.parent
    if str(parent) in (".", ""):
        return sanitize_relative_path(new_name)
    return sanitize_relative_path(str(parent / new_name))

def validate_all_items(items: list[Any]) -> None:
    """In-place updates status and validation_error for a list of PlanItem objects."""
    dest_map: dict[str, list[Any]] = {}

    for item in items:
        if getattr(item, "is_excluded", False):
            item.status = "excluded"
            item.validation_error = "Excluded by user"
            continue

        # Auto-heal missing audio extension
        old_ext = Path(item.old_path).suffix
        if old_ext and not item.proposed_name.lower().endswith(old_ext.lower()):
            item.proposed_name = item.proposed_name.rstrip(". ") + old_ext

        existing_dest = getattr(item, "final_destination", "")
        dest = compute_final_destination(item.old_path, item.proposed_name, existing_dest)
        item.final_destination = dest
        dest_map.setdefault(dest, []).append(item)

    for item in items:
        if getattr(item, "is_excluded", False):
            continue

        # 1. Illegal characters check
        is_valid, err_msg = check_filename_validity(item.proposed_name)
        if not is_valid:
            item.status = "illegal"
            item.validation_error = err_msg
            continue

        # 2. Extension match check
        old_ext = Path(item.old_path).suffix.lower()
        new_ext = Path(item.proposed_name).suffix.lower()
        if old_ext != new_ext:
            item.status = "illegal"
            item.validation_error = f"Audio extension changed from '{old_ext}' to '{new_ext}'"
            continue

        # 3. Collision check
        colliders = dest_map.get(item.final_destination, [])
        if len(colliders) > 1:
            item.status = "collision"
            other_paths = [c.old_path for c in colliders if c.old_path != item.old_path]
            item.validation_error = f"Target collision with {len(other_paths)} other file(s): {', '.join(other_paths[:2])}"
            continue

        # 4. Modified vs Confidence review
        if getattr(item, "is_modified", False):
            item.status = "modified"
            item.validation_error = "Manually edited by user"
        elif item.confidence in ("medium", "low"):
            item.status = "review"
            item.validation_error = f"Flagged for review ({item.confidence} confidence)"
        else:
            item.status = "ready"
            item.validation_error = "Ready to rename"
