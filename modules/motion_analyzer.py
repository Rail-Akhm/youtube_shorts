"""
Локальный анализ движения через OpenCV.
Использует optical flow (Farneback) и разницу между последовательными кадрами.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Tuple

import cv2
import numpy as np
from tqdm import tqdm

logger = logging.getLogger(__name__)


class MotionAnalyzer:
    """
    Анализирует движение в видео, возвращая score (0.0–1.0) для каждого кадра.
    """

    def __init__(self, motion_threshold: float = 0.15):
        """
        Args:
            motion_threshold: минимальное движение, чтобы считать кадр «активным»
        """
        self.motion_threshold = motion_threshold

    # ------------------------------------------------------------------
    def analyze_video(
        self, video_path: str, step_frames: int = 30
    ) -> List[Tuple[float, float]]:
        """
        Анализирует движение во всём видео.

        Args:
            video_path: путь к видеофайлу
            step_frames: каждые N кадров делать замер (30 ≈ 1 fps при 30 fps)

        Returns:
            список (timestamp_сек, motion_score_0_1)
        """
        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        results: List[Tuple[float, float]] = []
        prev_gray: np.ndarray | None = None
        frame_idx = 0

        total_steps = total_frames // step_frames
        with tqdm(total=total_steps, desc="Анализ движения", unit="шаг") as pbar:
            while True:
                ret, frame = cap.read()
                if not ret:
                    break

                if frame_idx % step_frames == 0:
                    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    gray = cv2.GaussianBlur(gray, (5, 5), 0)

                    timestamp = frame_idx / fps
                    score = self._compute_motion_score(prev_gray, gray)
                    results.append((timestamp, score))
                    prev_gray = gray
                    pbar.update(1)

                frame_idx += 1

        cap.release()
        return results

    # ------------------------------------------------------------------
    def analyze_frames(
        self, frames: List[Tuple[str, float]], video_path: str | None = None
    ) -> List[Tuple[float, float]]:
        """
        Анализирует движение в предоставленных кадрах (уже извлечённых).

        Args:
            frames: список (путь_к_кадру, timestamp)
            video_path: если передан, используется как fallback для optical flow
                       между кадрами, которые могут быть непоследовательными

        Returns:
            список (timestamp, motion_score_0_1)
        """
        results: List[Tuple[float, float]] = []
        prev_gray: np.ndarray | None = None

        for frame_path, timestamp in tqdm(frames, desc="Анализ движения по кадрам"):
            img = cv2.imread(frame_path)
            if img is None:
                results.append((timestamp, 0.0))
                continue

            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            gray = cv2.GaussianBlur(gray, (5, 5), 0)

            score = self._compute_motion_score(prev_gray, gray)
            results.append((timestamp, score))
            prev_gray = gray

        return results

    # ------------------------------------------------------------------
    def _compute_motion_score(
        self, prev_gray: np.ndarray | None, gray: np.ndarray
    ) -> float:
        """Считает optical flow между двумя кадрами и возвращает 0.0–1.0."""
        if prev_gray is None:
            return 0.0

        # Optical flow (Farneback)
        flow = cv2.calcOpticalFlowFarneback(
            prev_gray, gray, None,
            pyr_scale=0.5, levels=3, winsize=15,
            iterations=3, poly_n=5, poly_sigma=1.2, flags=0,
        )

        magnitude, _ = cv2.cartToPolar(flow[..., 0], flow[..., 1])
        mean_motion = float(np.mean(magnitude))

        # Нормализация: 0–10 пикселей → 0.0–1.0
        score = min(1.0, mean_motion / 10.0)
        return score