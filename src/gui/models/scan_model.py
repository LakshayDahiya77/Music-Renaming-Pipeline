"""Data structures and virtual table model for raw scanned music/audio files."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt

from metadata import AudioMetadata, format_file_size

# Alias for backward compatibility
format_size = format_file_size

@dataclass
class ScanItem:
    index: int
    relative_path: str
    filename: str
    folder: str
    extension: str
    size_bytes: int
    formatted_size: str
    title: str = ""
    artist: str = ""
    album: str = ""
    year: str = ""
    track_number: str = ""
    genre: str = ""
    format: str = "Unknown"
    codec: str = "Unknown"
    bitrate_kbps: int = 0
    duration_formatted: str = "00:00"
    sample_rate_hz: int = 0
    bits_per_sample: int = 0
    channels: int = 2
    codec_details: str = ""
    tag_type: str = ""

    @property
    def display_tag_summary(self) -> str:
        parts = []
        if self.artist:
            parts.append(self.artist)
        if self.title:
            parts.append(f'"{self.title}"')
        if self.album:
            parts.append(f"[{self.album}]")
        return " - ".join(parts) if parts else self.filename

class ScanTableModel(QAbstractTableModel):
    """Virtualized QAbstractTableModel displaying music files with rich audio metadata."""

    COLUMNS = [
        "#",
        "Filename",
        "Artist",
        "Title",
        "Album",
        "Year",
        "Track",
        "Codec",
        "Bitrate",
        "Duration",
        "Size",
        "Folder",
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: List[ScanItem] = []

    def set_items(self, items: List[ScanItem]):
        self.beginResetModel()
        self._items = items
        self.endResetModel()

    def update_metadata(self, meta_map: Dict[str, AudioMetadata]):
        """Updates music tags and audio properties in-place."""
        changed = False
        for item in self._items:
            meta = meta_map.get(item.relative_path)
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
                changed = True
        if changed:
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(len(self._items) - 1, len(self.COLUMNS) - 1),
                [Qt.ItemDataRole.DisplayRole],
            )

    def clear(self):
        self.beginResetModel()
        self._items.clear()
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._items)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(self.COLUMNS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            if 0 <= section < len(self.COLUMNS):
                return self.COLUMNS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or not (0 <= index.row() < len(self._items)):
            return None

        item = self._items[index.row()]
        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                return str(item.index)
            elif col == 1:
                return item.filename
            elif col == 2:
                return item.artist or "—"
            elif col == 3:
                return item.title or "—"
            elif col == 4:
                return item.album or "—"
            elif col == 5:
                return item.year or "—"
            elif col == 6:
                return item.track_number or "—"
            elif col == 7:
                return item.codec
            elif col == 8:
                return f"{item.bitrate_kbps} kbps" if item.bitrate_kbps > 0 else "—"
            elif col == 9:
                return item.duration_formatted
            elif col == 10:
                return item.formatted_size
            elif col == 11:
                return item.folder or "/"

        elif role == Qt.ItemDataRole.ToolTipRole:
            if col == 1:
                return f"Relative Path: {item.relative_path}\nExtension: {item.extension.upper()}"
            elif col in (2, 3, 4):
                return f"{item.artist} - {item.title}\nAlbum: {item.album} ({item.year})\nGenre: {item.genre}"
            elif col in (7, 8, 9):
                return (
                    f"Codec: {item.codec} ({item.format})\n"
                    f"Details: {item.codec_details}\n"
                    f"Sample Rate: {item.sample_rate_hz} Hz | Bit Depth: {item.bits_per_sample}-bit\n"
                    f"Channels: {item.channels} | Tag Type: {item.tag_type}"
                )
            elif col == 11:
                return f"Parent Folder: {item.folder or 'Root'}"

        elif role == Qt.ItemDataRole.TextAlignmentRole:
            if col in (0, 5, 6, 7, 8, 9):
                return Qt.AlignmentFlag.AlignCenter
            elif col == 10:
                return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter

        elif role == Qt.ItemDataRole.UserRole:
            if col == 0:
                return item.index
            elif col == 1:
                return item.filename.lower()
            elif col == 2:
                return item.artist.lower()
            elif col == 3:
                return item.title.lower()
            elif col == 4:
                return item.album.lower()
            elif col == 5:
                return item.year
            elif col == 6:
                try:
                    return int(item.track_number.split("/")[0])
                except (ValueError, IndexError):
                    return 0
            elif col == 7:
                return item.codec.lower()
            elif col == 8:
                return item.bitrate_kbps
            elif col == 9:
                return item.duration_formatted
            elif col == 10:
                return item.size_bytes
            elif col == 11:
                return (item.folder or "").lower()

        return None

    def get_items(self) -> List[ScanItem]:
        return self._items

    def get_relative_paths(self) -> List[str]:
        return [item.relative_path for item in self._items]

    def total_size_bytes(self) -> int:
        return sum(item.size_bytes for item in self._items)
