"""
Анализ громкости аудио-дорожки через FFmpeg.
Извлекает аудио-волну (PCM) и вычисляет RMS громкость по окнам.
"""

from __future__ import annotations

import json
import logging
import math
import os
import subprocess
import tempfile
from pathlib import Path
from typing import List, Tuple

import numpy as np
from tqdm import tqdm

logger = logging.getLogger(__name__)


class AudioAnalyzer:
    """
    Извлекает аудио-волну из видео и возвращает уровни громкости (0.0–1.0)
    для каждого временного отрезка.
    """

    def __init__(self, window_sec: float = 1.0):
        """
        Args:
            window_sec: размер окна в секундах для усреднения громкости
        """
        self.window_sec = window_sec

    # ------------------------------------------------------------------
    def analyze(self, video_path: str) -> List[Tuple[float, float]]:
        """
        Анализирует громкость аудио-дорожки по окнам.

        Args:
            video_path: путь к видеофайлу

        Returns:
            список (timestamp_сек, loudness_0_1) — усреднённая громкость
            на окнах длиной window_sec.
        """
        # Сначала получаем длительность видео
        duration = self._get_duration(video_path)
        if duration is None or duration <= 0:
            logger.warning("Не удалось определить длительность видео")
            return []

        # Пробуем извлечь аудио-волну через ffmpeg в формате сырых сэмплов
        samples, sample_rate = self._extract_raw_audio(video_path)
        if samples is None or len(samples) == 0:
            logger.warning("Не удалось извлечь аудио — возвращаем пустой результат")
            return []

        window_size = int(sample_rate * self.window_sec)
        num_windows = max(1, len(samples) // window_size)

        results: List[Tuple[float, float]] = []
        for i in tqdm(range(num_windows), desc="Анализ аудио", unit="окно"):
            start = i * window_size
            end = min(start + window_size, len(samples))
            chunk = samples[start:end]

            if len(chunk) == 0:
                continue

            # RMS громкость
            rms = float(np.sqrt(np.mean(chunk.astype(np.float64) ** 2)))

            # Нормализация: 0–0.5 RMS (типичный макс для 16-bit PCM) → 0.0–1.0
            # Для 16-bit PCM макс значение 32768, RMS редко превышает 0.3 от макс
            # Если samples уже float в [-1, 1], RMS макс ~1.0
            normalized = min(1.0, rms * 3.0)

            timestamp = i * self.window_sec
            results.append((timestamp, normalized))

        return results

    # ------------------------------------------------------------------
    def _get_duration(self, video_path: str) -> float | None:
        """Возвращает длительность видео в секундах через ffprobe."""
        try:
            cmd = [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "json",
                video_path,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            data = json.loads(result.stdout)
            return float(data["format"]["duration"])
        except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError, ValueError) as exc:
            logger.error("Ошибка получения длительности: %s", exc)
            return None

    # ------------------------------------------------------------------
    def _extract_raw_audio(
        self, video_path: str, sample_rate: int = 16000
    ) -> Tuple[np.ndarray | None, int]:
        """
        Извлекает аудио-дорожку как массив сэмплов через ffmpeg.

        Returns:
            (numpy_array_samples, sample_rate) или (None, 0) при ошибке
        """
        try:
            cmd = [
                "ffmpeg", "-i", video_path,
                "-acodec", "pcm_s16le",   # 16-bit signed little-endian PCM
                "-ar", str(sample_rate),   # частота дискретизации
                "-ac", "1",                # моно
                "-f", "s16le",             # raw PCM
                "-y",
                "pipe:1",                  # вывод в stdout
            ]
            result = subprocess.run(
                cmd, capture_output=True, timeout=300, check=True,
            )
            raw_bytes = result.stdout
            if not raw_bytes:
                return None, 0

            # Конвертируем байты в int16, затем во float32 [-1.0, 1.0]
            samples = np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float32)
            samples /= 32768.0  # нормализация

            return samples, sample_rate

        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr[:500] if exc.stderr else ""
            logger.error("FFmpeg ошибка извлечения аудио: %s", stderr)
            return None, 0
        except subprocess.TimeoutExpired:
            logger.error("Таймаут при извлечении аудио (видео слишком длинное?)")
            return None, 0