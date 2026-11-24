"""Configuration, schemas, and shared utilities for the Music Renaming and Tagging Pipeline."""

from pathlib import Path
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

# Recognized audio / music file extensions for scanning
AUDIO_EXTENSIONS = {
    ".mp3", ".m4a", ".flac", ".aac", ".dsf",
    ".wav", ".ogg", ".opus", ".aiff", ".aif", ".alac", ".wma", ".ape"
}

# Backward compatibility alias
VIDEO_EXTENSIONS = AUDIO_EXTENSIONS

# Common music file presets
COMMON_MUSIC_FORMATS = [".mp3", ".m4a", ".flac", ".aac", ".dsf"]

# Model & Inference defaults (Local LLM is OPTIONAL and not default)
DEFAULT_MODEL = "qwen2.5:14b"
FALLBACK_MODELS = [
    "qwen2.5:14b",
    "qwen2.5:7b",
    "llama3.2:latest",
    "llama3.1:8b",
    "mistral:latest",
    "movie-renamer",
    "richardyoung/qwen3-14b-abliterated",
]
DEFAULT_OLLAMA_HOST = "http://localhost:11434"
DEFAULT_BATCH_SIZE = 10
DEFAULT_NUM_CTX = 8192
DEFAULT_NUM_THREAD = 8
DEFAULT_TEMPERATURE = 0.2
DEFAULT_TOP_P = 0.95
RETRY_TEMPERATURE = 0.5

# Characters not permitted in file names across Linux and Windows
ILLEGAL_FILENAME_CHARS = set('<>:"/\\|?*\0')

# Standard project directory layout paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_RULES_PATH = PROJECT_ROOT / "Renaming Rules.txt"
DEFAULT_PLAN_PATH = DATA_DIR / "rename_plan.json"
DEFAULT_FILE_LIST_PATH = DATA_DIR / "file_list.json"
DEFAULT_NEEDS_REVIEW_PATH = DATA_DIR / "needs_review.json"
DEFAULT_VERIFICATION_PATH = DATA_DIR / "verification_report.json"
FORMAT_DOC_PATH = PROJECT_ROOT / "input_output_format.txt"

class MusicTags(BaseModel):
    """Structured audio tags schema."""
    title: Optional[str] = Field(None, description="Song / track title")
    artist: Optional[str] = Field(None, description="Track artist")
    album: Optional[str] = Field(None, description="Album name")
    album_artist: Optional[str] = Field(None, description="Album artist")
    year: Optional[str] = Field(None, description="Year or date of release (YYYY or YYYY-MM-DD)")
    track_number: Optional[str] = Field(None, description="Track number / position (e.g. '01' or '1/12')")
    disc_number: Optional[str] = Field(None, description="Disc number (e.g. '1' or '1/2')")
    genre: Optional[str] = Field(None, description="Musical genre")
    composer: Optional[str] = Field(None, description="Composer")
    comment: Optional[str] = Field(None, description="User or release comment")

class RenameItem(BaseModel):
    """Pydantic schema enforcing chain-of-thought before generation for music files."""
    old_path: str = Field(..., description="Original relative path to the music file")
    reasoning: str = Field(..., description="Rule breakdown, tag parsing logic, and format analysis")
    new_name: str = Field(..., description="Target standardized file name with extension preserved")
    confidence: Literal["high", "medium", "low"] = Field(..., description="Confidence score")
    new_tags: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional proposed new tags (title, artist, album, year, track_number, genre) to write into the audio file"
    )

class BatchRenameResponse(BaseModel):
    """Schema for batch inference output."""
    items: List[RenameItem]

class PlanEntry(BaseModel):
    """Represents an entry stored in rename_plan.json."""
    old_path: str
    reasoning: str
    new_name: str
    final_destination: str
    confidence: Literal["high", "medium", "low"]
    new_tags: Optional[Dict[str, Any]] = None
    current_tags: Optional[Dict[str, Any]] = None
    format: Optional[str] = None
    codec: Optional[str] = None
    duration: Optional[str] = None
    bitrate_kbps: Optional[int] = None
    sample_rate_hz: Optional[int] = None

def sanitize_relative_path(path_str: str) -> str:
    """Normalizes path string to POSIX relative format."""
    p = Path(path_str)
    parts = p.parts
    clean_parts = [part for part in parts if part not in ("", "/", "\\", ".")]
    return "/".join(clean_parts)
