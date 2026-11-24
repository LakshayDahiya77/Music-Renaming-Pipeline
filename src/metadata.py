"""High-performance, modular audio metadata extraction and tagging engine.

Supports reading and writing metadata for common music formats:
- MP3 (ID3v1, ID3v2.3, ID3v2.4)
- M4A / AAC (MP4 iTunes atoms, ALAC, AAC-LC)
- FLAC (Vorbis comments, native FLAC streaminfo)
- AAC (Raw ADTS stream with ID3)
- DSF (Sony DSD Stream File: DSD64, DSD128, DSD256 with ID3v2)
- WAV, OGG (Vorbis), OPUS, AIFF, WMA

Extracts both high-level music tags (artist, album, title, year, track, disc, genre, composer)
and codec-specific technical attributes (bitrate, sample rate, bit depth, channels, DSD clock, duration).
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
import os
import threading
from typing import Any, Dict, List, Optional, Set, Tuple

import mutagen
from mutagen.flac import FLAC
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4, MP4Tags
from mutagen.dsf import DSF
from mutagen.id3 import ID3, TIT2, TPE1, TALB, TPE2, TDRC, TRCK, TPOS, TCON, TCOM, COMM, ID3NoHeaderError

# Audio extensions handled by this engine
AUDIO_EXTENSIONS: Set[str] = {
    ".mp3", ".m4a", ".flac", ".aac", ".dsf",
    ".wav", ".ogg", ".opus", ".aiff", ".aif", ".alac", ".wma", ".ape"
}

# Standard user-selectable export attributes
AVAILABLE_EXPORT_ATTRIBUTES = [
    ("relative_path", "Relative Path", "Original relative path from base directory"),
    ("filename", "Filename", "Base name of the audio file"),
    ("title", "Title", "Song / Track title tag"),
    ("artist", "Artist", "Performing artist(s)"),
    ("album", "Album", "Album / Release title"),
    ("album_artist", "Album Artist", "Album artist (e.g. Various Artists)"),
    ("year", "Year / Date", "Release year or full date (YYYY or YYYY-MM-DD)"),
    ("track_number", "Track Number", "Track index / number"),
    ("disc_number", "Disc Number", "Disc / volume number"),
    ("genre", "Genre", "Musical genre(s)"),
    ("composer", "Composer", "Song composer / songwriter"),
    ("comment", "Comment", "Embedded user comments"),
    ("format", "Format", "Container / format name (MP3, FLAC, M4A, DSF...)"),
    ("codec", "Codec", "Underlying audio stream codec"),
    ("duration_formatted", "Duration", "Duration in mm:ss or hh:mm:ss format"),
    ("duration_seconds", "Duration (Sec)", "Duration in raw decimal seconds"),
    ("bitrate_kbps", "Bitrate (kbps)", "Audio stream bitrate in kilobits per second"),
    ("sample_rate_hz", "Sample Rate", "Sample frequency (e.g. 44100, 96000, 2822400)"),
    ("bits_per_sample", "Bit Depth", "Bits per audio sample (e.g. 16, 24, 1-bit DSD)"),
    ("channels", "Channels", "Number of audio channels (1, 2, 6)"),
    ("channel_layout", "Channel Layout", "Mono, Stereo, 5.1 Surround, etc."),
    ("codec_details", "Codec Details", "High-res specs (e.g. DSD64 2.8MHz, 24-bit/96kHz)"),
    ("file_size_formatted", "File Size", "Human-readable file size (MB / GB)"),
    ("tag_type", "Tag Type", "Tagging container specification (ID3v2, Vorbis, etc.)"),
]

DEFAULT_SELECTED_ATTRIBUTES = [
    "relative_path",
    "filename",
    "title",
    "artist",
    "album",
    "year",
    "track_number",
    "genre",
    "duration_formatted",
    "codec",
    "bitrate_kbps",
    "sample_rate_hz",
    "bits_per_sample",
]

def format_duration(seconds: float) -> str:
    """Formats raw seconds into mm:ss or hh:mm:ss."""
    if not seconds or seconds <= 0:
        return "00:00"
    total_sec = int(round(seconds))
    hrs = total_sec // 3600
    mins = (total_sec % 3600) // 60
    secs = total_sec % 60
    if hrs > 0:
        return f"{hrs:02d}:{mins:02d}:{secs:02d}"
    return f"{mins:02d}:{secs:02d}"

def format_file_size(size_bytes: int | float) -> str:
    """Formats bytes into human readable format."""
    num = float(size_bytes or 0)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if num < 1024.0:
            if unit == "B":
                return f"{int(num)} B"
            return f"{num:.2f} {unit}"
        num /= 1024.0
    return f"{num:.2f} PB"

@dataclass
class AudioMetadata:
    """Immutable metadata record for an audio / music file."""
    file_path: str
    filename: str
    extension: str
    format: str                     # e.g., "MP3", "FLAC", "M4A", "AAC", "DSF", "WAV"
    codec: str                      # e.g., "MP3", "FLAC", "AAC", "ALAC", "DSD64", "PCM"
    title: str = ""
    artist: str = ""
    album: str = ""
    album_artist: str = ""
    year: str = ""
    track_number: str = ""
    disc_number: str = ""
    genre: str = ""
    composer: str = ""
    comment: str = ""
    duration_seconds: float = 0.0
    duration_formatted: str = "00:00"
    bitrate_kbps: int = 0
    sample_rate_hz: int = 0
    bits_per_sample: int = 0        # 1 for DSD, 16/24/32 for PCM
    channels: int = 2
    channel_layout: str = "Stereo"
    codec_details: str = ""
    file_size_bytes: int = 0
    file_size_formatted: str = "0 B"
    tag_type: str = "Unknown"
    raw_tags: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self, attributes: Optional[List[str]] = None, relative_path: str = "") -> Dict[str, Any]:
        """Converts metadata to dict filtered to requested attributes."""
        full_dict = {
            "relative_path": relative_path or self.file_path,
            "filename": self.filename,
            "extension": self.extension,
            "title": self.title,
            "artist": self.artist,
            "album": self.album,
            "album_artist": self.album_artist,
            "year": self.year,
            "track_number": self.track_number,
            "disc_number": self.disc_number,
            "genre": self.genre,
            "composer": self.composer,
            "comment": self.comment,
            "format": self.format,
            "codec": self.codec,
            "duration_formatted": self.duration_formatted,
            "duration_seconds": round(self.duration_seconds, 2),
            "bitrate_kbps": self.bitrate_kbps,
            "sample_rate_hz": self.sample_rate_hz,
            "bits_per_sample": self.bits_per_sample,
            "channels": self.channels,
            "channel_layout": self.channel_layout,
            "codec_details": self.codec_details,
            "file_size_bytes": self.file_size_bytes,
            "file_size_formatted": self.file_size_formatted,
            "tag_type": self.tag_type,
        }

        if not attributes:
            return full_dict

        return {k: full_dict[k] for k in attributes if k in full_dict}

    @property
    def display_tag_summary(self) -> str:
        """Returns concise Artist - Title (Album) summary string."""
        parts = []
        if self.artist:
            parts.append(self.artist)
        if self.title:
            parts.append(f'"{self.title}"')
        if self.album:
            parts.append(f"[{self.album}]")
        return " - ".join(parts) if parts else self.filename

class MetadataCache:
    """Thread-safe in-memory cache keyed by file path, size, and modification timestamp."""

    def __init__(self):
        self._cache: Dict[Tuple[str, int, int], AudioMetadata] = {}
        self._lock = threading.Lock()

    def _get_key(self, path_obj: Path) -> Tuple[str, int, int]:
        p_str = str(path_obj.resolve()) if path_obj.exists() else str(path_obj)
        try:
            st = path_obj.stat()
            return (p_str, st.st_size, st.st_mtime_ns)
        except OSError:
            return (p_str, 0, 0)

    def get(self, path_obj: Path) -> Optional[AudioMetadata]:
        key = self._get_key(path_obj)
        with self._lock:
            return self._cache.get(key)

    def set(self, path_obj: Path, meta: AudioMetadata):
        key = self._get_key(path_obj)
        with self._lock:
            self._cache[key] = meta

    def clear(self):
        with self._lock:
            self._cache.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._cache)

_GLOBAL_CACHE = MetadataCache()

def _first_str(val: Any) -> str:
    """Helper to extract first clean string from list or tag object."""
    if val is None:
        return ""
    if isinstance(val, (list, tuple)):
        return str(val[0]).strip() if val else ""
    return str(val).strip()

def _parse_track_disc(val: Any) -> Tuple[str, str]:
    """Parses track/disc tuple or string into (number, total)."""
    if not val:
        return "", ""
    if isinstance(val, (list, tuple)):
        if len(val) >= 2:
            num = str(val[0]) if val[0] else ""
            tot = str(val[1]) if val[1] else ""
            return num, tot
        elif len(val) == 1:
            return _parse_track_disc(val[0])
    s = str(val).strip()
    if "/" in s:
        parts = s.split("/", 1)
        return parts[0].strip(), parts[1].strip()
    return s, ""

def _probe_dsf(file_path: Path) -> Optional[AudioMetadata]:
    """Extracts Sony DSD Stream File (.dsf) tags and audio stream properties."""
    try:
        dsf = DSF(str(file_path))
        info = dsf.info
        tags = dsf.tags or {}

        # DSD Sample rate: e.g. 2822400 (DSD64), 5644800 (DSD128), 11289600 (DSD256)
        srate = int(getattr(info, "sample_rate", 0) or 0)
        channels = int(getattr(info, "channels", 2) or 2)
        bitrate = int(getattr(info, "bitrate", 0) or 0) // 1000
        duration = float(getattr(info, "length", 0.0) or 0.0)

        # Classify DSD rate
        if srate >= 22579200:
            dsd_rate = "DSD512"
        elif srate >= 11289600:
            dsd_rate = "DSD256"
        elif srate >= 5644800:
            dsd_rate = "DSD128"
        elif srate >= 2822400:
            dsd_rate = "DSD64"
        else:
            dsd_rate = f"DSD ({srate}Hz)"

        codec_details = f"{dsd_rate} (1-bit / {srate / 1000000:.4f} MHz)"
        ch_layout = "Stereo" if channels == 2 else ("Mono" if channels == 1 else f"{channels}.0 Ch")

        # Tags in DSF are ID3v2.3/ID3v2.4
        title = _first_str(tags.get("TIT2"))
        artist = _first_str(tags.get("TPE1"))
        album = _first_str(tags.get("TALB"))
        album_artist = _first_str(tags.get("TPE2"))
        year = _first_str(tags.get("TDRC") or tags.get("TYER"))
        genre = _first_str(tags.get("TCON"))
        composer = _first_str(tags.get("TCOM"))
        track, _ = _parse_track_disc(_first_str(tags.get("TRCK")))
        disc, _ = _parse_track_disc(_first_str(tags.get("TPOS")))

        comment_obj = tags.get("COMM") or tags.get("COMM::eng") or tags.get("COMM::XXX")
        comment = str(comment_obj) if comment_obj else ""

        size_bytes = file_path.stat().st_size if file_path.exists() else 0

        return AudioMetadata(
            file_path=str(file_path),
            filename=file_path.name,
            extension=file_path.suffix.lower(),
            format="DSF",
            codec=dsd_rate,
            title=title,
            artist=artist,
            album=album,
            album_artist=album_artist,
            year=year,
            track_number=track,
            disc_number=disc,
            genre=genre,
            composer=composer,
            comment=comment,
            duration_seconds=duration,
            duration_formatted=format_duration(duration),
            bitrate_kbps=bitrate,
            sample_rate_hz=srate,
            bits_per_sample=1,
            channels=channels,
            channel_layout=ch_layout,
            codec_details=codec_details,
            file_size_bytes=size_bytes,
            file_size_formatted=format_file_size(size_bytes),
            tag_type="ID3v2 (DSF)",
            raw_tags={k: str(v) for k, v in tags.items()},
        )
    except Exception:
        return None

def _probe_flac(file_path: Path) -> Optional[AudioMetadata]:
    """Extracts FLAC Vorbis comments and native FLAC stream info."""
    try:
        audio = FLAC(str(file_path))
        info = audio.info

        srate = int(getattr(info, "sample_rate", 0) or 0)
        bits = int(getattr(info, "bits_per_sample", 16) or 16)
        channels = int(getattr(info, "channels", 2) or 2)
        duration = float(getattr(info, "length", 0.0) or 0.0)
        size_bytes = file_path.stat().st_size if file_path.exists() else 0

        # Bitrate in FLAC: info.bitrate or calculate from size/duration
        bitrate = int(getattr(info, "bitrate", 0) or 0) // 1000
        if bitrate <= 0 and duration > 0 and size_bytes > 0:
            bitrate = int((size_bytes * 8) / (duration * 1000))

        ch_layout = "Stereo" if channels == 2 else ("Mono" if channels == 1 else f"{channels}-Ch")
        srate_khz = srate / 1000.0
        codec_details = f"FLAC {bits}-bit / {srate_khz:.1f} kHz Lossless"

        # Vorbis comments are case-insensitive lists
        tags = audio.tags or {}
        def get_tag(key: str) -> str:
            # Check lowercase, uppercase, titlecase
            for candidate in (key.lower(), key.upper(), key.capitalize()):
                if candidate in tags:
                    return _first_str(tags[candidate])
            return ""

        title = get_tag("title")
        artist = get_tag("artist")
        album = get_tag("album")
        album_artist = get_tag("albumartist") or get_tag("album artist")
        year = get_tag("date") or get_tag("year")
        genre = get_tag("genre")
        composer = get_tag("composer")
        comment = get_tag("comment") or get_tag("description")
        track, _ = _parse_track_disc(get_tag("tracknumber") or get_tag("track"))
        disc, _ = _parse_track_disc(get_tag("discnumber") or get_tag("disc"))

        return AudioMetadata(
            file_path=str(file_path),
            filename=file_path.name,
            extension=file_path.suffix.lower(),
            format="FLAC",
            codec="FLAC",
            title=title,
            artist=artist,
            album=album,
            album_artist=album_artist,
            year=year,
            track_number=track,
            disc_number=disc,
            genre=genre,
            composer=composer,
            comment=comment,
            duration_seconds=duration,
            duration_formatted=format_duration(duration),
            bitrate_kbps=bitrate,
            sample_rate_hz=srate,
            bits_per_sample=bits,
            channels=channels,
            channel_layout=ch_layout,
            codec_details=codec_details,
            file_size_bytes=size_bytes,
            file_size_formatted=format_file_size(size_bytes),
            tag_type="Vorbis Comment",
            raw_tags={k: str(v) for k, v in tags.items()},
        )
    except Exception:
        return None

def _probe_mp4(file_path: Path) -> Optional[AudioMetadata]:
    """Extracts M4A / MP4 (AAC / ALAC) iTunes metadata atoms and audio stream properties."""
    try:
        mp4 = MP4(str(file_path))
        info = mp4.info
        tags = mp4.tags or {}

        srate = int(getattr(info, "sample_rate", 0) or 0)
        channels = int(getattr(info, "channels", 2) or 2)
        bitrate = int(getattr(info, "bitrate", 0) or 0) // 1000
        bits = int(getattr(info, "bits_per_sample", 16) or 16)
        duration = float(getattr(info, "length", 0.0) or 0.0)
        codec_name = str(getattr(info, "codec", "") or "AAC").upper()

        if "ALAC" in codec_name or getattr(info, "alac", False):
            codec = "ALAC"
            codec_details = f"Apple Lossless ({bits}-bit / {srate / 1000:.1f} kHz)"
        else:
            codec = "AAC"
            codec_details = f"AAC-LC {bitrate} kbps / {srate / 1000:.1f} kHz"

        title = _first_str(tags.get("\xa9nam"))
        artist = _first_str(tags.get("\xa9ART"))
        album = _first_str(tags.get("\xa9alb"))
        album_artist = _first_str(tags.get("aART"))
        year = _first_str(tags.get("\xa9day"))
        genre = _first_str(tags.get("\xa9gen"))
        composer = _first_str(tags.get("\xa9wrt"))
        comment = _first_str(tags.get("\xa9cmt"))

        track_data = tags.get("trkn")
        track = ""
        if track_data and isinstance(track_data, list) and track_data[0]:
            t_pair = track_data[0]
            if isinstance(t_pair, (list, tuple)) and t_pair[0]:
                track = str(t_pair[0])

        disc_data = tags.get("disk")
        disc = ""
        if disc_data and isinstance(disc_data, list) and disc_data[0]:
            d_pair = disc_data[0]
            if isinstance(d_pair, (list, tuple)) and d_pair[0]:
                disc = str(d_pair[0])

        ch_layout = "Stereo" if channels == 2 else ("Mono" if channels == 1 else f"{channels}-Ch")
        size_bytes = file_path.stat().st_size if file_path.exists() else 0

        return AudioMetadata(
            file_path=str(file_path),
            filename=file_path.name,
            extension=file_path.suffix.lower(),
            format="M4A",
            codec=codec,
            title=title,
            artist=artist,
            album=album,
            album_artist=album_artist,
            year=year,
            track_number=track,
            disc_number=disc,
            genre=genre,
            composer=composer,
            comment=comment,
            duration_seconds=duration,
            duration_formatted=format_duration(duration),
            bitrate_kbps=bitrate,
            sample_rate_hz=srate,
            bits_per_sample=bits,
            channels=channels,
            channel_layout=ch_layout,
            codec_details=codec_details,
            file_size_bytes=size_bytes,
            file_size_formatted=format_file_size(size_bytes),
            tag_type="iTunes MP4 Tag",
            raw_tags={str(k): str(v) for k, v in tags.items()},
        )
    except Exception:
        return None

def _probe_mp3(file_path: Path) -> Optional[AudioMetadata]:
    """Extracts MP3 ID3 tags and MPEG audio stream properties."""
    try:
        mp3 = MP3(str(file_path))
        info = mp3.info
        tags = mp3.tags or {}

        srate = int(getattr(info, "sample_rate", 44100) or 44100)
        channels = int(getattr(info, "channels", 2) or 2)
        bitrate = int(getattr(info, "bitrate", 0) or 0) // 1000
        duration = float(getattr(info, "length", 0.0) or 0.0)

        # ID3 version
        id3_ver = "ID3v2"
        if hasattr(mp3, "tags") and mp3.tags and hasattr(mp3.tags, "version"):
            v = mp3.tags.version
            id3_ver = f"ID3v2.{v[1]}" if len(v) >= 2 else "ID3v2"

        title = _first_str(tags.get("TIT2"))
        artist = _first_str(tags.get("TPE1"))
        album = _first_str(tags.get("TALB"))
        album_artist = _first_str(tags.get("TPE2"))
        year = _first_str(tags.get("TDRC") or tags.get("TYER"))
        genre = _first_str(tags.get("TCON"))
        composer = _first_str(tags.get("TCOM"))
        track, _ = _parse_track_disc(_first_str(tags.get("TRCK")))
        disc, _ = _parse_track_disc(_first_str(tags.get("TPOS")))

        comm_obj = tags.get("COMM") or tags.get("COMM::eng") or tags.get("COMM::XXX")
        comment = str(comm_obj) if comm_obj else ""

        mode = getattr(info, "mode", 0)
        mode_names = {0: "Stereo", 1: "Joint Stereo", 2: "Dual Channel", 3: "Mono"}
        ch_layout = mode_names.get(mode, "Stereo" if channels == 2 else "Mono")

        vbr_mode = "VBR" if getattr(info, "bitrate_mode", None) else f"{bitrate} kbps"
        codec_details = f"MPEG Layer 3 ({vbr_mode} / {srate / 1000:.1f} kHz)"
        size_bytes = file_path.stat().st_size if file_path.exists() else 0

        return AudioMetadata(
            file_path=str(file_path),
            filename=file_path.name,
            extension=file_path.suffix.lower(),
            format="MP3",
            codec="MP3",
            title=title,
            artist=artist,
            album=album,
            album_artist=album_artist,
            year=year,
            track_number=track,
            disc_number=disc,
            genre=genre,
            composer=composer,
            comment=comment,
            duration_seconds=duration,
            duration_formatted=format_duration(duration),
            bitrate_kbps=bitrate,
            sample_rate_hz=srate,
            bits_per_sample=16,
            channels=channels,
            channel_layout=ch_layout,
            codec_details=codec_details,
            file_size_bytes=size_bytes,
            file_size_formatted=format_file_size(size_bytes),
            tag_type=id3_ver,
            raw_tags={str(k): str(v) for k, v in tags.items()},
        )
    except Exception:
        return None

def _probe_generic_mutagen(file_path: Path) -> Optional[AudioMetadata]:
    """Fallback probe using mutagen.File for other audio formats (.ogg, .opus, .wav, .aac, .aiff, .wma)."""
    try:
        audio = mutagen.File(str(file_path))
        if not audio:
            return None

        info = getattr(audio, "info", None)
        tags = getattr(audio, "tags", None) or {}

        srate = int(getattr(info, "sample_rate", 0) or 0)
        channels = int(getattr(info, "channels", 2) or 2)
        bitrate = int(getattr(info, "bitrate", 0) or 0) // 1000
        bits = int(getattr(info, "bits_per_sample", 16) or 16)
        duration = float(getattr(info, "length", 0.0) or 0.0)

        ext = file_path.suffix.lower()
        fmt_name = ext.lstrip(".").upper()

        title = _first_str(tags.get("title") or tags.get("TITLE") or tags.get("TIT2") or tags.get("\xa9nam"))
        artist = _first_str(tags.get("artist") or tags.get("ARTIST") or tags.get("TPE1") or tags.get("\xa9ART"))
        album = _first_str(tags.get("album") or tags.get("ALBUM") or tags.get("TALB") or tags.get("\xa9alb"))
        album_artist = _first_str(tags.get("albumartist") or tags.get("TPE2") or tags.get("aART"))
        year = _first_str(tags.get("date") or tags.get("year") or tags.get("TDRC") or tags.get("\xa9day"))
        genre = _first_str(tags.get("genre") or tags.get("TCON") or tags.get("\xa9gen"))
        composer = _first_str(tags.get("composer") or tags.get("TCOM") or tags.get("\xa9wrt"))
        track, _ = _parse_track_disc(_first_str(tags.get("tracknumber") or tags.get("TRCK") or tags.get("trkn")))
        disc, _ = _parse_track_disc(_first_str(tags.get("discnumber") or tags.get("TPOS") or tags.get("disk")))
        comment = _first_str(tags.get("comment") or tags.get("COMM") or tags.get("\xa9cmt"))

        ch_layout = "Stereo" if channels == 2 else ("Mono" if channels == 1 else f"{channels}-Ch")
        size_bytes = file_path.stat().st_size if file_path.exists() else 0
        codec_details = f"{fmt_name} {bitrate} kbps / {srate / 1000:.1f} kHz" if srate else fmt_name

        return AudioMetadata(
            file_path=str(file_path),
            filename=file_path.name,
            extension=ext,
            format=fmt_name,
            codec=fmt_name,
            title=title,
            artist=artist,
            album=album,
            album_artist=album_artist,
            year=year,
            track_number=track,
            disc_number=disc,
            genre=genre,
            composer=composer,
            comment=comment,
            duration_seconds=duration,
            duration_formatted=format_duration(duration),
            bitrate_kbps=bitrate,
            sample_rate_hz=srate,
            bits_per_sample=bits,
            channels=channels,
            channel_layout=ch_layout,
            codec_details=codec_details,
            file_size_bytes=size_bytes,
            file_size_formatted=format_file_size(size_bytes),
            tag_type=type(tags).__name__,
            raw_tags={str(k): str(v) for k, v in tags.items()},
        )
    except Exception:
        return None

def get_audio_metadata(file_path: Path | str, use_cache: bool = True) -> AudioMetadata:
    """Reads audio metadata and codec attributes for an audio file.
    
    Checks in-memory stat cache first.
    Uses format-specific parsers for DSF, FLAC, M4A, MP3, and fallback generic mutagen.
    """
    path_obj = Path(file_path)
    if use_cache and path_obj.exists():
        cached = _GLOBAL_CACHE.get(path_obj)
        if cached:
            return cached

    if not path_obj.is_file():
        empty_meta = AudioMetadata(
            file_path=str(path_obj),
            filename=path_obj.name,
            extension=path_obj.suffix.lower(),
            format="Unknown",
            codec="Unknown",
        )
        return empty_meta

    ext = path_obj.suffix.lower()
    meta: Optional[AudioMetadata] = None

    if ext == ".dsf":
        meta = _probe_dsf(path_obj)
    elif ext == ".flac":
        meta = _probe_flac(path_obj)
    elif ext in (".m4a", ".mp4", ".alac"):
        meta = _probe_mp4(path_obj)
    elif ext == ".mp3":
        meta = _probe_mp3(path_obj)

    # General fallback
    if not meta:
        meta = _probe_generic_mutagen(path_obj)

    # If still completely unknown, fallback to basic file info
    if not meta:
        size_bytes = path_obj.stat().st_size if path_obj.exists() else 0
        meta = AudioMetadata(
            file_path=str(path_obj),
            filename=path_obj.name,
            extension=ext,
            format=ext.lstrip(".").upper() or "Unknown",
            codec=ext.lstrip(".").upper() or "Unknown",
            file_size_bytes=size_bytes,
            file_size_formatted=format_file_size(size_bytes),
        )

    if use_cache and path_obj.exists():
        _GLOBAL_CACHE.set(path_obj, meta)

    return meta

def get_audio_metadata_batch(
    file_paths: List[Path | str],
    max_workers: int = 8,
) -> Dict[str, AudioMetadata]:
    """Extracts audio metadata in parallel across multiple threads with caching."""
    results: Dict[str, AudioMetadata] = {}
    to_probe: List[Path] = []

    for p in file_paths:
        path_obj = Path(p)
        p_str = str(path_obj.resolve()) if path_obj.exists() else str(path_obj)
        cached = _GLOBAL_CACHE.get(path_obj) if path_obj.exists() else None
        if cached:
            results[p_str] = cached
        else:
            to_probe.append(path_obj)

    if not to_probe:
        return results

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {
            executor.submit(get_audio_metadata, path, True): str(path.resolve())
            for path in to_probe
        }
        for future in as_completed(future_map):
            p_str = future_map[future]
            try:
                results[p_str] = future.result()
            except Exception:
                p_obj = Path(p_str)
                results[p_str] = AudioMetadata(
                    file_path=p_str,
                    filename=p_obj.name,
                    extension=p_obj.suffix.lower(),
                    format="Unknown",
                    codec="Unknown",
                )

    return results

def write_audio_tags(file_path: Path | str, new_tags: Dict[str, Any]) -> Tuple[bool, str]:
    """Writes / updates metadata tags in an audio file across all supported formats.
    
    Supported target keys:
      - title
      - artist
      - album
      - album_artist
      - year / date
      - track_number (e.g. "1" or "01" or "1/12")
      - disc_number (e.g. "1" or "1/2")
      - genre
      - composer
      - comment
    """
    path_obj = Path(file_path)
    if not path_obj.is_file():
        return False, f"File not found: {path_obj}"

    ext = path_obj.suffix.lower()

    try:
        # 1. FLAC / OGG / OPUS (Vorbis Comments)
        if ext in (".flac", ".ogg", ".opus"):
            audio = FLAC(str(path_obj)) if ext == ".flac" else mutagen.File(str(path_obj))
            if audio is None:
                return False, f"Failed to parse {ext} file for tag writing"

            if "title" in new_tags and new_tags["title"]:
                audio["TITLE"] = [str(new_tags["title"]).strip()]
            if "artist" in new_tags and new_tags["artist"]:
                audio["ARTIST"] = [str(new_tags["artist"]).strip()]
            if "album" in new_tags and new_tags["album"]:
                audio["ALBUM"] = [str(new_tags["album"]).strip()]
            if "album_artist" in new_tags and new_tags["album_artist"]:
                audio["ALBUMARTIST"] = [str(new_tags["album_artist"]).strip()]
            if "year" in new_tags and new_tags["year"]:
                audio["DATE"] = [str(new_tags["year"]).strip()]
            if "genre" in new_tags and new_tags["genre"]:
                audio["GENRE"] = [str(new_tags["genre"]).strip()]
            if "composer" in new_tags and new_tags["composer"]:
                audio["COMPOSER"] = [str(new_tags["composer"]).strip()]
            if "comment" in new_tags and new_tags["comment"]:
                audio["COMMENT"] = [str(new_tags["comment"]).strip()]
            if "track_number" in new_tags and new_tags["track_number"]:
                num, tot = _parse_track_disc(new_tags["track_number"])
                audio["TRACKNUMBER"] = [num]
                if tot:
                    audio["TRACKTOTAL"] = [tot]
            if "disc_number" in new_tags and new_tags["disc_number"]:
                num, tot = _parse_track_disc(new_tags["disc_number"])
                audio["DISCNUMBER"] = [num]
                if tot:
                    audio["DISCTOTAL"] = [tot]

            audio.save()
            return True, "Tags updated successfully (Vorbis Comment)"

        # 2. MP4 / M4A / ALAC (iTunes atoms)
        elif ext in (".m4a", ".mp4", ".alac"):
            mp4 = MP4(str(path_obj))
            if mp4.tags is None:
                mp4.add_tags()

            tags = mp4.tags
            if "title" in new_tags and new_tags["title"]:
                tags["\xa9nam"] = [str(new_tags["title"]).strip()]
            if "artist" in new_tags and new_tags["artist"]:
                tags["\xa9ART"] = [str(new_tags["artist"]).strip()]
            if "album" in new_tags and new_tags["album"]:
                tags["\xa9alb"] = [str(new_tags["album"]).strip()]
            if "album_artist" in new_tags and new_tags["album_artist"]:
                tags["aART"] = [str(new_tags["album_artist"]).strip()]
            if "year" in new_tags and new_tags["year"]:
                tags["\xa9day"] = [str(new_tags["year"]).strip()]
            if "genre" in new_tags and new_tags["genre"]:
                tags["\xa9gen"] = [str(new_tags["genre"]).strip()]
            if "composer" in new_tags and new_tags["composer"]:
                tags["\xa9wrt"] = [str(new_tags["composer"]).strip()]
            if "comment" in new_tags and new_tags["comment"]:
                tags["\xa9cmt"] = [str(new_tags["comment"]).strip()]

            if "track_number" in new_tags and new_tags["track_number"]:
                num, tot = _parse_track_disc(new_tags["track_number"])
                try:
                    tags["trkn"] = [(int(num or 0), int(tot or 0))]
                except ValueError:
                    pass

            if "disc_number" in new_tags and new_tags["disc_number"]:
                num, tot = _parse_track_disc(new_tags["disc_number"])
                try:
                    tags["disk"] = [(int(num or 0), int(tot or 0))]
                except ValueError:
                    pass

            mp4.save()
            return True, "Tags updated successfully (MP4 iTunes atoms)"

        # 3. MP3, DSF, AAC, or WAV (ID3v2 tags)
        elif ext in (".mp3", ".dsf", ".aac", ".wav"):
            wav_obj = None
            if ext == ".dsf":
                dsf = DSF(str(path_obj))
                tags = dsf.tags
                if tags is None:
                    tags = ID3()
            elif ext == ".wav":
                from mutagen.wave import WAVE
                wav_obj = WAVE(str(path_obj))
                if wav_obj.tags is None:
                    wav_obj.add_tags()
                tags = wav_obj.tags
            else:
                try:
                    tags = ID3(str(path_obj))
                except ID3NoHeaderError:
                    tags = ID3()

            if "title" in new_tags and new_tags["title"]:
                tags["TIT2"] = TIT2(encoding=3, text=[str(new_tags["title"]).strip()])
            if "artist" in new_tags and new_tags["artist"]:
                tags["TPE1"] = TPE1(encoding=3, text=[str(new_tags["artist"]).strip()])
            if "album" in new_tags and new_tags["album"]:
                tags["TALB"] = TALB(encoding=3, text=[str(new_tags["album"]).strip()])
            if "album_artist" in new_tags and new_tags["album_artist"]:
                tags["TPE2"] = TPE2(encoding=3, text=[str(new_tags["album_artist"]).strip()])
            if "year" in new_tags and new_tags["year"]:
                tags["TDRC"] = TDRC(encoding=3, text=[str(new_tags["year"]).strip()])
            if "genre" in new_tags and new_tags["genre"]:
                tags["TCON"] = TCON(encoding=3, text=[str(new_tags["genre"]).strip()])
            if "composer" in new_tags and new_tags["composer"]:
                tags["TCOM"] = TCOM(encoding=3, text=[str(new_tags["composer"]).strip()])
            if "comment" in new_tags and new_tags["comment"]:
                tags["COMM"] = COMM(encoding=3, lang="eng", desc="", text=[str(new_tags["comment"]).strip()])
            if "track_number" in new_tags and new_tags["track_number"]:
                tags["TRCK"] = TRCK(encoding=3, text=[str(new_tags["track_number"]).strip()])
            if "disc_number" in new_tags and new_tags["disc_number"]:
                tags["TPOS"] = TPOS(encoding=3, text=[str(new_tags["disc_number"]).strip()])

            if ext == ".dsf":
                dsf.tags = tags
                dsf.save()
            elif ext == ".wav" and wav_obj is not None:
                wav_obj.save()
            else:
                tags.save(str(path_obj))
            return True, f"Tags updated successfully (ID3v2 on {ext.upper()})"

        else:
            # Generic attempt with mutagen.File
            audio = mutagen.File(str(path_obj), easy=False)
            if audio is not None:
                for k, v in new_tags.items():
                    if v:
                        audio[k] = [str(v).strip()]
                audio.save()
                return True, "Tags updated successfully (Generic)"

            return False, f"Unsupported audio format for tag writing: {ext}"

    except Exception as e:
        return False, f"Failed to write tags to {path_obj.name}: {e}"
