"""Plan data structures, QAbstractTableModel with inline editing and atomic checkpointing for music files."""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt, pyqtSignal

from config import sanitize_relative_path
from gui.models.validation_engine import (
    compute_final_destination,
    validate_all_items,
    ValidationStatus,
)

@dataclass
class PlanItem:
    index: int
    old_path: str
    original_name: str
    folder: str
    proposed_name: str
    final_destination: str
    reasoning: str
    confidence: str  # "high", "medium", "low"
    artist: str = ""
    title: str = ""
    album: str = ""
    year: str = ""
    track_number: str = ""
    genre: str = ""
    codec: str = ""
    duration: str = ""
    new_tags: Dict[str, Any] = field(default_factory=dict)
    status: ValidationStatus = "ready"
    is_modified: bool = False
    is_excluded: bool = False
    validation_error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "old_path": self.old_path,
            "reasoning": self.reasoning,
            "new_name": self.proposed_name,
            "final_destination": self.final_destination,
            "confidence": self.confidence,
            "new_tags": self.new_tags,
            "artist": self.artist,
            "title": self.title,
            "album": self.album,
            "year": self.year,
            "track_number": self.track_number,
            "genre": self.genre,
            "codec": self.codec,
            "is_modified": self.is_modified,
            "is_excluded": self.is_excluded,
        }

def get_display_folder(final_destination: str, old_path: str = "") -> str:
    """Returns compact folder info for display."""
    dest = final_destination or old_path
    if not dest:
        return "/"
    dest_parent = Path(dest).parent
    dest_str = "" if str(dest_parent) in (".", "") else dest_parent.as_posix()
    return f"{dest_str}/" if dest_str else "/"

class PlanTableModel(QAbstractTableModel):
    """High-performance QAbstractTableModel supporting inline editing of proposed music filenames,
    tags display, and automatic re-validation."""

    COLUMNS = [
        "#",
        "Original Name",
        "Proposed Name",
        "Artist",
        "Title",
        "Track",
        "Confidence",
        "Status",
        "Reasoning",
        "Folder",
    ]

    plan_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: List[PlanItem] = []

    def set_items(self, items: List[PlanItem]):
        self.beginResetModel()
        self._items = items
        validate_all_items(self._items)
        self.endResetModel()
        self.plan_changed.emit()

    def add_or_update_items(self, new_items: List[PlanItem]):
        """Merges new items from AI planning or manual import and re-validates."""
        existing_map = {item.old_path: i for i, item in enumerate(self._items)}
        self.beginResetModel()
        for item in new_items:
            if item.old_path in existing_map:
                idx = existing_map[item.old_path]
                self._items[idx] = item
            else:
                item.index = len(self._items) + 1
                self._items.append(item)
        validate_all_items(self._items)
        self.endResetModel()
        self.plan_changed.emit()

    def clear(self):
        self.beginResetModel()
        self._items.clear()
        self.endResetModel()
        self.plan_changed.emit()

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._items)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(self.COLUMNS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            if 0 <= section < len(self.COLUMNS):
                return self.COLUMNS[section]
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags

        base_flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

        # Column 2: Proposed Name is editable
        if index.column() == 2:
            item = self._items[index.row()]
            if not item.is_excluded:
                return base_flags | Qt.ItemFlag.ItemIsEditable

        return base_flags

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or not (0 <= index.row() < len(self._items)):
            return None

        item = self._items[index.row()]
        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole or role == Qt.ItemDataRole.EditRole:
            if col == 0:
                return str(item.index)
            elif col == 1:
                return item.original_name
            elif col == 2:
                return item.proposed_name
            elif col == 3:
                return item.artist or "—"
            elif col == 4:
                return item.title or "—"
            elif col == 5:
                return item.track_number or "—"
            elif col == 6:
                return item.confidence.capitalize()
            elif col == 7:
                return item.status.capitalize()
            elif col == 8:
                return item.reasoning
            elif col == 9:
                return get_display_folder(item.final_destination, item.old_path)

        elif role == Qt.ItemDataRole.ToolTipRole:
            if col == 1:
                return f"Original path: {item.old_path}"
            elif col == 2:
                return f"Double-click to edit proposed name.\nOriginal: {item.original_name}"
            elif col in (3, 4):
                tag_preview = []
                if item.new_tags:
                    for k, v in item.new_tags.items():
                        if v:
                            tag_preview.append(f"{k}: {v}")
                tag_str = "\n".join(tag_preview) if tag_preview else "No new tags planned"
                return f"Tags to write:\n{tag_str}"
            elif col == 6:
                return f"Confidence: {item.confidence.upper()}"
            elif col == 7:
                return item.validation_error or f"Status: {item.status.capitalize()}"
            elif col == 8:
                return item.reasoning
            elif col == 9:
                return f"Destination path: {item.final_destination}"

        elif role == Qt.ItemDataRole.TextAlignmentRole:
            if col in (0, 5, 6, 7):
                return Qt.AlignmentFlag.AlignCenter
            return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter

        elif role == Qt.ItemDataRole.UserRole:
            if col == 0:
                return item.index
            elif col == 1:
                return item.original_name.lower()
            elif col == 2:
                return item.proposed_name.lower()
            elif col == 3:
                return item.artist.lower()
            elif col == 4:
                return item.title.lower()
            elif col == 5:
                try:
                    return int(item.track_number.split("/")[0])
                except (ValueError, IndexError):
                    return 0
            elif col == 6:
                conf_ranks = {"high": 3, "medium": 2, "low": 1}
                return conf_ranks.get(item.confidence.lower(), 0)
            elif col == 7:
                status_ranks = {"ready": 5, "modified": 4, "review": 3, "collision": 2, "illegal": 1, "excluded": 0}
                return status_ranks.get(item.status.lower(), 0)
            elif col == 8:
                return item.reasoning.lower()
            elif col == 9:
                return get_display_folder(item.final_destination, item.old_path).lower()

        return None

    def setData(self, index: QModelIndex, value: Any, role: int = Qt.ItemDataRole.EditRole) -> bool:
        if not index.isValid() or role != Qt.ItemDataRole.EditRole:
            return False

        if index.column() == 2:
            new_val = str(value).strip()
            if not new_val:
                return False

            item = self._items[index.row()]
            if item.proposed_name != new_val:
                item.proposed_name = new_val
                item.is_modified = True
                validate_all_items(self._items)
                top_left = self.index(index.row(), 0)
                bottom_right = self.index(index.row(), len(self.COLUMNS) - 1)
                self.dataChanged.emit(top_left, bottom_right, [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole])
                self.plan_changed.emit()
                return True

        return False

    def toggle_exclude(self, row_indices: List[int]):
        for r in row_indices:
            if 0 <= r < len(self._items):
                item = self._items[r]
                item.is_excluded = not item.is_excluded

        validate_all_items(self._items)
        if row_indices:
            self.dataChanged.emit(
                self.index(min(row_indices), 0),
                self.index(max(row_indices), len(self.COLUMNS) - 1),
                [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole],
            )
            self.plan_changed.emit()

    def reset_to_original(self, row_indices: List[int]):
        for r in row_indices:
            if 0 <= r < len(self._items):
                item = self._items[r]
                item.proposed_name = item.original_name
                item.is_modified = False
                item.is_excluded = False

        validate_all_items(self._items)
        if row_indices:
            self.dataChanged.emit(
                self.index(min(row_indices), 0),
                self.index(max(row_indices), len(self.COLUMNS) - 1),
                [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole],
            )
            self.plan_changed.emit()

    def get_items(self) -> List[PlanItem]:
        return self._items

    def get_active_items(self) -> List[PlanItem]:
        return [item for item in self._items if not item.is_excluded]

    def save_to_file(self, file_path: Path):
        data = [item.to_dict() for item in self._items]
        temp_path = file_path.with_suffix(".tmp")
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        temp_path.replace(file_path)

    def load_from_file(self, file_path: Path) -> int:
        if not file_path.exists():
            return 0

        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, dict):
            data = list(data.values())
        elif not isinstance(data, list):
            return 0

        loaded_items: List[PlanItem] = []
        for i, entry in enumerate(data):
            old_path = sanitize_relative_path(entry.get("old_path", ""))
            p = Path(old_path)
            folder = str(p.parent) if str(p.parent) != "." else ""
            proposed_name = entry.get("new_name", p.name)

            old_ext = p.suffix
            if old_ext and not proposed_name.lower().endswith(old_ext.lower()):
                proposed_name = proposed_name.rstrip(". ") + old_ext

            final_dest = entry.get("final_destination") or compute_final_destination(old_path, proposed_name)
            if old_ext and not final_dest.lower().endswith(old_ext.lower()):
                final_dest = final_dest.rstrip(". ") + old_ext

            new_tags = entry.get("new_tags") or {}

            item = PlanItem(
                index=i + 1,
                old_path=old_path,
                original_name=p.name,
                folder=folder,
                proposed_name=proposed_name,
                final_destination=final_dest,
                reasoning=entry.get("reasoning", ""),
                confidence=entry.get("confidence", "medium"),
                artist=entry.get("artist") or new_tags.get("artist", ""),
                title=entry.get("title") or new_tags.get("title", ""),
                album=entry.get("album") or new_tags.get("album", ""),
                year=entry.get("year") or new_tags.get("year", ""),
                track_number=entry.get("track_number") or new_tags.get("track_number", ""),
                genre=entry.get("genre") or new_tags.get("genre", ""),
                codec=entry.get("codec", ""),
                new_tags=new_tags,
                is_modified=entry.get("is_modified", False),
                is_excluded=entry.get("is_excluded", False),
            )
            loaded_items.append(item)

        self.set_items(loaded_items)
        return len(loaded_items)
