"""
Извлечение ключевых кадров из видео.

Использует:
- Histogram difference для детекции смены сцены
- Равномерный интервал (KEYFRAME_INTERVAL) для гарантированного покрытия
- Сохранение метаданных: тип кадра (regular / scene_change)
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import List, Tuple

import cv2
import numpy as np
from tqdm import tqdm

logger = logging.getLogger(__name__)


def extract_keyframes(
    video_path: str,
    output_dir: str,
    interval_sec: float = 3.0,
    scene_threshold: float = 30.0,
    max_frames: int = 600,
) -> List[Tuple[str, float, str]]:
    """
    Извлекает ключевые кадры из видео.

    Стратегия:
      1. Берём кадр каждые `interval_sec` секунд (гарантированное покрытие).
      2. Если histogram difference между соседними кадрами превышает
         `scene_threshold`, помечаем кадр как scene_change.
      3. Если подряд идёт несколько scene_change — сохраняем только первый.

    Args:
        video_path: путь к видеофайлу
        output_dir: папка для сохранения JPG-кадров
        interval_sec: интервал между кадрами (сек)
        scene_threshold: порог histogram difference для детекции смены сцены
        max_frames: максимум кадров (защита от бесконечных циклов)

    Returns:
        список (путь_к_файлу, timestamp_сек, тип_кадра)
        где тип_кадра — "regular" или "scene_change"
    """
    os.makedirs(output_dir, exist_ok=True)

    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / fps if total_frames > 0 else 0

    interval_frames = max(1, int(fps * interval_sec))
    frames: List[Tuple[str, float, str]] = []
    prev_hist: np.ndarray | None = None
    frame_idx = 0
    saved_count = 0
    last_was_scene_change = False

    total_expected = min(total_frames // interval_frames, max_frames) if total_frames > 0 else max_frames

    with tqdm(total=total_expected, desc="Извлечение ключевых кадров") as pbar:
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            # Берём кадр только по интервалу
            if frame_idx % interval_frames != 0:
                frame_idx += 1
                continue

            if saved_count >= max_frames:
                logger.warning("Достигнут лимит кадров (%d), останавливаем извлечение", max_frames)
                break

            timestamp = frame_idx / fps
            hist = _calc_histogram(frame)

            # Определяем тип кадра
            frame_type = "regular"
            if prev_hist is not None:
                diff = cv2.compareHist(prev_hist, hist, cv2.HISTCMP_BHATTACHARYYA)
                if diff > scene_threshold / 100.0 and not last_was_scene_change:
                    frame_type = "scene_change"
                    last_was_scene_change = True
                else:
                    last_was_scene_change = False
            else:
                # Первый кадр всегда scene_change (начало видео)
                frame_type = "scene_change"

            # Сохраняем кадр
            frame_path = os.path.join(
                output_dir,
                f"frame_{saved_count:06d}_{timestamp:06.2f}_{frame_type}.jpg",
            )
            cv2.imwrite(frame_path, frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            frames.append((frame_path, timestamp, frame_type))
            saved_count += 1
            pbar.update(1)

            prev_hist = hist
            frame_idx += 1

    cap.release()

    stats = sum(1 for _, _, t in frames if t == "scene_change")
    logger.info(
        "Извлечено %d кадров (из них %d scene_change) из видео %.1fс",
        len(frames), stats, duration,
    )
    return frames


def _calc_histogram(frame: np.ndarray) -> np.ndarray:
    """Вычисляет нормализованную гистограмму для BGR-кадра (использует Hue)."""
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0], None, [50], [0, 180])
    cv2.normalize(hist, hist, 0, 1, cv2.NORM_MINMAX)
    return hist