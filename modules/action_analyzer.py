"""
Гибридный анализ экшна:
- Локальный motion score (OpenCV optical flow) для ВСЕХ кадров
- OpenRouter Vision — только для ключевых (scene_change) кадров
- Если API недоступен — используем чистый motion score
- Параллельные запросы к OpenRouter для ускорения
"""

from __future__ import annotations

import base64
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Tuple

import requests
from tqdm import tqdm

from config import OPENROUTER_API_KEY, VISION_MODEL

logger = logging.getLogger(__name__)


class ActionAnalyzer:
    """
    Анализирует экшн, комбинируя локальный motion score и оценку OpenRouter.
    """

    def __init__(self, api_threshold: int = 7):
        self.api_key = OPENROUTER_API_KEY
        self.model = VISION_MODEL
        self.api_threshold = api_threshold
        self._api_available = True  # optimistic start

    # ------------------------------------------------------------------
    def analyze(
        self,
        frames: List[Tuple[str, float, str]],
        motion_scores: List[Tuple[float, float]],
    ) -> List[Tuple[float, float]]:
        """
        Анализирует экшн для списка кадров.

        Args:
            frames: список (путь, timestamp, тип_кадра) из frame_extractor
            motion_scores: список (timestamp, motion_score 0-1) из MotionAnalyzer

        Returns:
            список (timestamp, action_score 0.0–10.0)
        """
        if not frames:
            return []

        # Строим lookup motion_score по timestamp
        motion_lookup = _build_timestamp_lookup(motion_scores)

        # Определяем, какие кадры отправлять в OpenRouter (только scene_change)
        api_candidates = [
            (path, ts) for path, ts, ftype in frames if ftype == "scene_change"
        ]

        # Если API ключ не настроен — только motion
        if not self.api_key.startswith("sk-or-v1-"):
            logger.warning("OpenRouter API ключ не настроен — используем только motion score")
            self._api_available = False

        # Отправляем scene_change кадры в OpenRouter параллельно
        api_results: List[Tuple[float, float]] = []
        if self._api_available and api_candidates:
            api_results = self._batch_analyze(api_candidates)

        # Строим lookup для API результатов
        api_lookup = _build_timestamp_lookup(api_results)

        # Финальная комбинация: для каждого кадра
        results: List[Tuple[float, float]] = []
        for path, ts, ftype in frames:
            # Базовый motion score
            motion = motion_lookup.get(round(ts, 1), 0.0)

            # OpenRouter score (если есть)
            api_score = api_lookup.get(round(ts, 1))

            if api_score is not None:
                # Комбинируем: motion как нижняя граница, API как уточнение
                score = max(motion * 10.0, api_score)
            else:
                # Для regular-кадров используем motion + интерполяция между API точками
                score = motion * 10.0

            results.append((ts, min(10.0, max(0.0, score))))

        return results

    # ------------------------------------------------------------------
    def _batch_analyze(
        self, candidates: List[Tuple[str, float]], max_workers: int = 3,
    ) -> List[Tuple[float, float]]:
        """Отправляет кадры в OpenRouter параллельно."""
        results: List[Tuple[float, float]] = []
        failed: List[Tuple[str, float]] = []

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {
                executor.submit(self._analyze_single, path, ts): (path, ts)
                for path, ts in candidates
            }

            for future in tqdm(
                as_completed(future_map), total=len(candidates),
                desc="OpenRouter анализ", unit="кадр",
            ):
                path, ts = future_map[future]
                try:
                    score = future.result()
                    if score is not None:
                        results.append((ts, score))
                    else:
                        failed.append((path, ts))
                except Exception as exc:
                    logger.error("Ошибка в OpenRouter для кадра %.1fс: %s", ts, exc)
                    failed.append((path, ts))

        if failed:
            logger.warning(
                "%d из %d кадров не удалось проанализировать через OpenRouter",
                len(failed), len(candidates),
            )
            # Для упавших используем motion score (будет подставлено позже)

        return results

    # ------------------------------------------------------------------
    def _analyze_single(
        self, image_path: str, timestamp: float, retries: int = 2,
    ) -> float | None:
        """Анализирует один кадр через OpenRouter — возвращает 0–10 или None."""
        try:
            with open(image_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("utf-8")
        except FileNotFoundError:
            logger.error("Файл кадра не найден: %s", image_path)
            return None

        # Явно кодируем JSON в UTF-8 (requests иногда ломается на base64)
        import json as _json
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Оцени уровень экшна на этом кадре от 0 до 10.\n"
                                "0 — тихий диалог, спокойный пейзаж, статичная сцена\n"
                                "10 — взрывы, драки, погоня, быстрые движения, крики, спецэффекты\n"
                                "Ответь ТОЛЬКО одним числом от 0 до 10."
                            ),
                        },
                        {
                            "type": "image_url",
                            "image_url": f"data:image/jpeg;base64,{b64}",
                        },
                    ],
                }
            ],
            "temperature": 0.1,
            "max_tokens": 10,
        }
        body = _json.dumps(payload, ensure_ascii=True).encode("utf-8")
        req_headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json; charset=utf-8",
        }

        for attempt in range(retries):
            try:
                resp = requests.post(
                    url="https://openrouter.ai/api/v1/chat/completions",
                    headers=req_headers,
                    data=body,
                    timeout=30,
                )

                if resp.status_code == 200:
                    content = resp.json()["choices"][0]["message"]["content"].strip()
                    numbers = re.findall(r"\d+", content)
                    if numbers:
                        return min(10.0, max(0.0, float(numbers[0])))
                    return 0.0

                logger.warning(
                    "OpenRouter ошибка %d (попытка %d/%.1fс)",
                    resp.status_code, attempt + 1, timestamp,
                )
                time.sleep(1.5 * (attempt + 1))

            except requests.exceptions.Timeout:
                logger.warning("Таймаут OpenRouter (попытка %d/%.1fс)", attempt + 1, timestamp)
                time.sleep(1.0)
            except Exception as exc:
                logger.error("OpenRouter ошибка: %s", exc)
                time.sleep(1.0)

        # Все попытки исчерпаны
        self._api_available = False
        return None


def _build_timestamp_lookup(
    scores: List[Tuple[float, float]],
) -> dict[float, float]:
    """Строит {round(timestamp, 1): score} для быстрого поиска."""
    lookup: dict[float, float] = {}
    for ts, score in scores:
        key = round(ts, 1)
        # Если несколько значений на один timestamp — берём максимум
        if key in lookup:
            lookup[key] = max(lookup[key], score)
        else:
            lookup[key] = score
    return lookup