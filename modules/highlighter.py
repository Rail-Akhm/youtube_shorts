"""
Поиск интересных моментов (хайлайтов) на основе:
- Визуального action_score
- Аудио-громкости (loudness)

Итоговый score = VIDEO_WEIGHT * action + AUDIO_WEIGHT * audio
Используется динамический порог (адаптивный под каждое видео).
"""

from __future__ import annotations

import logging
from typing import List, Tuple

import numpy as np

from config import (
    MIN_CLIP_DURATION,
    MAX_CLIP_DURATION,
    VIDEO_WEIGHT,
    AUDIO_WEIGHT,
    ACTION_THRESHOLD,
    AUDIO_THRESHOLD,
)

logger = logging.getLogger(__name__)


class HighlightFinder:
    """
    Находит отрезки с высоким combined-score и возвращает их границы.
    """

    def __init__(self):
        self.min_duration = MIN_CLIP_DURATION
        self.max_duration = MAX_CLIP_DURATION
        self.video_weight = VIDEO_WEIGHT
        self.audio_weight = AUDIO_WEIGHT

    # ------------------------------------------------------------------
    def find_highlights(
        self,
        action_scores: List[Tuple[float, float]],
        audio_scores: List[Tuple[float, float]] | None = None,
    ) -> List[Tuple[float, float]]:
        """
        Находит хайлайты по комбинированному score.

        Args:
            action_scores: список (timestamp, action_score 0-10) из ActionAnalyzer
            audio_scores: список (timestamp, loudness 0-1) из AudioAnalyzer (опционально)

        Returns:
            список (start_time, end_time) в секундах
        """
        if not action_scores:
            return []

        # Строим combined score
        combined = self._combine_scores(action_scores, audio_scores)

        # Динамический порог на основе распределения scores
        scores_only = [s for _, s in combined]
        if not scores_only:
            return []

        threshold = self._dynamic_threshold(scores_only)
        logger.info("Динамический порог хайлайта: %.1f (из max=%.1f)", threshold, max(scores_only))

        # Находим отрезки выше порога
        raw_segments = self._find_above_threshold(combined, threshold)

        # Фильтруем по длительности
        highlights = self._filter_by_duration(raw_segments)

        # Объединяем пересекающиеся
        highlights = self._merge_overlapping(highlights)

        # Финальная проверка длительности
        highlights = [
            (s, e) for s, e in highlights
            if self.min_duration <= (e - s) <= self.max_duration + 5
        ]

        # Ограничиваем каждый хайлайт по max_duration
        highlights = [
            (s, min(e, s + self.max_duration)) for s, e in highlights
        ]

        logger.info("Найдено %d хайлайтов", len(highlights))
        for s, e in highlights:
            logger.info("  хайлайт: %.1fс → %.1fс (длина %.1fс)", s, e, e - s)

        return highlights

    # ------------------------------------------------------------------
    def _combine_scores(
        self,
        action_scores: List[Tuple[float, float]],
        audio_scores: List[Tuple[float, float]] | None,
    ) -> List[Tuple[float, float]]:
        """Комбинирует видео и аудио скоры."""
        if not audio_scores:
            return action_scores  # только видео

        # Интерполируем audio_scores к временной шкале action_scores
        audio_lookup = _build_linear_lookup(audio_scores)

        combined: List[Tuple[float, float]] = []
        for ts, vscore in action_scores:
            # Нормализуем video score (0-10) → (0-1)
            v_norm = vscore / 10.0

            # Аудио громкость в той же точке
            a_norm = audio_lookup(ts) if audio_scores else 0.0

            # Взвешенная сумма
            total = self.video_weight * v_norm + self.audio_weight * a_norm

            # Обратно в шкалу 0-10
            combined.append((ts, total * 10.0))

        return combined

    # ------------------------------------------------------------------
    def _dynamic_threshold(self, scores: List[float], percentile: float = 75.0) -> float:
        """
        Вычисляет динамический порог на основе распределения.

        Берёт максимум из:
        - ACTION_THRESHOLD (глобальный минимум)
        - заданного перцентиля scores
        """
        if not scores:
            return float(ACTION_THRESHOLD)

        arr = np.array(scores)
        # Отбрасываем нулевые значения (тихие сцены)
        non_zero = arr[arr > 0.5]
        if len(non_zero) == 0:
            return float(ACTION_THRESHOLD)

        perc_val = float(np.percentile(non_zero, percentile))
        return max(float(ACTION_THRESHOLD), perc_val)

    # ------------------------------------------------------------------
    def _find_above_threshold(
        self,
        combined: List[Tuple[float, float]],
        threshold: float,
    ) -> List[Tuple[float, float]]:
        """Находит непрерывные отрезки, где score >= threshold."""
        segments: List[Tuple[float, float]] = []
        i = 0
        n = len(combined)

        while i < n:
            ts, score = combined[i]

            if score >= threshold:
                start_time = ts

                # Идём вперёд, пока score >= порога (с запасом 70% от порога)
                j = i + 1
                while j < n and combined[j][1] >= threshold * 0.7:
                    j += 1

                end_time = combined[min(j, n - 1)][0]
                segments.append((start_time, end_time))
                i = j
            else:
                i += 1

        return segments

    # ------------------------------------------------------------------
    def _filter_by_duration(
        self, segments: List[Tuple[float, float]]
    ) -> List[Tuple[float, float]]:
        """Оставляет только сегменты длиннее min_duration."""
        filtered = []
        for s, e in segments:
            dur = e - s
            if dur < self.min_duration:
                # Пытаемся расширить
                needed = self.min_duration - dur
                e2 = min(e + needed, e + needed)  # будет расширено позже
                filtered.append((s, max(e, s + self.min_duration)))
            else:
                filtered.append((s, e))
        return filtered

    # ------------------------------------------------------------------
    def _merge_overlapping(
        self, highlights: List[Tuple[float, float]]
    ) -> List[Tuple[float, float]]:
        """Объединяет пересекающиеся отрезки."""
        if not highlights:
            return []

        sorted_hl = sorted(highlights)
        merged: List[Tuple[float, float]] = [sorted_hl[0]]

        for start, end in sorted_hl[1:]:
            prev_s, prev_e = merged[-1]
            if start <= prev_e:
                # Пересекаются — объединяем
                merged[-1] = (prev_s, max(prev_e, end))
            else:
                merged.append((start, end))

        return merged


def _build_linear_lookup(
    scores: List[Tuple[float, float]],
) -> callable:
    """
    Строит функцию линейной интерполяции для lookup по timestamp.
    """
    if not scores:
        return lambda ts: 0.0

    timestamps = np.array([s[0] for s in scores])
    values = np.array([s[1] for s in scores])

    if len(timestamps) == 1:
        return lambda ts: float(values[0])

    def lookup(ts: float) -> float:
        return float(np.interp(ts, timestamps, values))

    return lookup