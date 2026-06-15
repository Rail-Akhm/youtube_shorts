"""
Нарезка и вертикализация видео через FFmpeg.
- cropdetect для авто-определения чёрных полос
- Проверка ошибок ffmpeg
- Вертикализация 9:16
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
from pathlib import Path
from typing import Tuple

logger = logging.getLogger(__name__)


class VideoCutter:
    """Обрезает видео, вертикализирует, извлекает аудио."""

    # ------------------------------------------------------------------
    def crop_vertical(
        self,
        input_path: str,
        output_path: str,
        start_time: float,
        duration: float,
        auto_crop: bool = True,
    ) -> str:
        """
        Обрезает видео и делает вертикальным (9:16).

        1. Определяет чёрные полосы через cropdetect (если auto_crop=True)
        2. Обрезает полосы
        3. Делает вертикальную нарезку 9:16 (центрирование)

        Args:
            input_path: исходное видео
            output_path: куда сохранить
            start_time: начало отрезка (сек)
            duration: длительность (сек)
            auto_crop: автоматически обрезать чёрные полосы

        Returns:
            output_path
        """
        # Шаг 1: получаем размеры исходного видео
        width, height = self._get_video_size(input_path)
        logger.info("Исходное видео: %dx%d", width, height)

        # Шаг 2: cropdetect для чёрных полос
        crop_filter = ""
        if auto_crop:
            detected = self._detect_crop(input_path, start_time, duration)
            if detected:
                crop_filter = f"crop={detected[0]}:{detected[1]}:{detected[2]}:{detected[3]}"
                logger.info("Cropdetect: %s", crop_filter)
                # Обновляем размеры для следующего шага
                width, height = detected[0], detected[1]

        # Шаг 3: вычисляем параметры вертикальной обрезки
        vertical_filter = self._build_vertical_filter(width, height)

        # Комбинируем фильтры
        if crop_filter and vertical_filter:
            vf = f"{crop_filter},{vertical_filter}"
        elif vertical_filter:
            vf = vertical_filter
        elif crop_filter:
            vf = crop_filter
        else:
            vf = vertical_filter or ""

        # Шаг 4: ffmpeg команда
        cmd = [
            "ffmpeg", "-i", input_path,
            "-ss", str(start_time),
            "-t", str(duration),
        ]
        if vf:
            cmd += ["-vf", vf]
        cmd += [
            "-c:v", "libx264", "-preset", "fast", "-crf", "22",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            "-y",
            output_path,
        ]

        logger.info("Вертикализация: %s", " ".join(cmd))
        self._run_ffmpeg(cmd)
        logger.info("Вертикальный клип создан: %s", output_path)
        return output_path

    # ------------------------------------------------------------------
    def extract_audio(self, video_path: str, audio_path: str) -> str:
        """
        Извлекает аудиодорожку (16kHz моно WAV для whisper).

        Args:
            video_path: входное видео
            audio_path: выходной WAV-файл

        Returns:
            audio_path
        """
        cmd = [
            "ffmpeg", "-i", video_path,
            "-vn",
            "-acodec", "pcm_s16le",
            "-ar", "16000",
            "-ac", "1",
            "-y", audio_path,
        ]
        logger.info("Извлечение аудио: %s → %s", Path(video_path).name, audio_path)
        self._run_ffmpeg(cmd)
        return audio_path

    # ------------------------------------------------------------------
    def get_duration(self, video_path: str) -> float:
        """Возвращает длительность видео в секундах."""
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "json",
            video_path,
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            data = json.loads(result.stdout)
            return float(data["format"]["duration"])
        except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError, ValueError) as exc:
            logger.error("Не удалось получить длительность видео: %s", exc)
            return 0.0

    # ------------------------------------------------------------------
    def _get_video_size(self, video_path: str) -> Tuple[int, int]:
        """Получает ширину и высоту видео через ffprobe."""
        cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "json",
            video_path,
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            data = json.loads(result.stdout)
            stream = data["streams"][0]
            return int(stream["width"]), int(stream["height"])
        except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError, IndexError) as exc:
            raise RuntimeError(f"Не удалось получить размер видео: {exc}")

    # ------------------------------------------------------------------
    def _detect_crop(
        self, input_path: str, start_time: float, duration: float,
    ) -> Tuple[int, int, int, int] | None:
        """
        Определяет область обрезки чёрных полос через cropdetect.

        Returns:
            (width, height, x, y) для crop фильтра, или None если полос нет
        """
        cmd = [
            "ffmpeg", "-ss", str(start_time), "-i", input_path,
            "-t", str(min(duration, 3.0)),  # анализируем первые 3 сек
            "-vf", "cropdetect=limit=24:round=2:reset=0",
            "-f", "null", "-",
        ]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30,
            )
            # Ищем последнюю crop-строку в stderr
            matches = re.findall(
                r"crop=(\d+):(\d+):(\d+):(\d+)", result.stderr,
            )
            if matches:
                w, h, x, y = map(int, matches[-1])
                return (w, h, x, y)
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as exc:
            logger.warning("cropdetect не сработал: %s", exc)

        return None

    # ------------------------------------------------------------------
    def _build_vertical_filter(self, width: int, height: int) -> str | None:
        """
        Строит фильтр для обрезки в вертикальный формат 9:16.
        Возвращает None, если видео уже вертикальное.
        """
        if height > width:
            # Видео уже портретное — возможно субтитры? Оставляем как есть
            ratio = height / width
            if abs(ratio - 16 / 9) < 0.05:
                return None  # уже 9:16
            # Не 9:16 — центрируем
            target_w = width
            target_h = int(width * 16 / 9)
            if target_h > height:
                target_h = height
                target_w = int(height * 9 / 16)
                x = (width - target_w) // 2
                y = 0
            else:
                x = 0
                y = (height - target_h) // 2
            return f"crop={target_w}:{target_h}:{x}:{y}"

        target_h = height
        target_w = int(height * 9 / 16)

        if target_w > width:
            # Слишком узкое — обрезаем по высоте
            target_w = width
            target_h = int(width * 16 / 9)
            crop_filter = f"crop={target_w}:{target_h}:0:{(height - target_h) // 2}"
        else:
            # Стандартный случай: центрируем по горизонтали
            crop_filter = f"crop={target_w}:{target_h}:{(width - target_w) // 2}:0"

        return crop_filter

    # ------------------------------------------------------------------
    @staticmethod
    def _run_ffmpeg(cmd: list) -> None:
        """Запускает ffmpeg и проверяет ошибки."""
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=600, check=True,
            )
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr[:2000] if exc.stderr else ""
            stdout = exc.stdout[:500] if exc.stdout else ""
            raise RuntimeError(
                f"FFmpeg ошибка (код {exc.returncode}): {stderr}\n{stdout}"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"FFmpeg таймаут: команда выполнялась >600 секунд"
            ) from exc