"""YouTube Shorts Auto-Creator — модули для обработки видео."""

from .frame_extractor import extract_keyframes
from .motion_analyzer import MotionAnalyzer
from .audio_analyzer import AudioAnalyzer
from .action_analyzer import ActionAnalyzer
from .highlighter import HighlightFinder
from .video_cutter import VideoCutter
from .subtitler import Subtitler

__all__ = [
    "extract_keyframes",
    "MotionAnalyzer",
    "AudioAnalyzer",
    "ActionAnalyzer",
    "HighlightFinder",
    "VideoCutter",
    "Subtitler",
]