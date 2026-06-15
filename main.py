#!/usr/bin/env python3
"""
🎬 YouTube Shorts Auto-Creator v2.0
Автоматическая нарезка вертикальных видео с цветными субтитрами.

Pipeline:
  1. Извлечение ключевых кадров (scene detection)
  2. Локальный анализ движения (optical flow)
  3. Анализ громкости аудио
  4. Гибридный анализ экшна (motion + OpenRouter Vision)
  5. Поиск хайлайтов (комбинированный video+audio score)
  6. Создание вертикальных клипов 9:16 + цветные субтитры
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
import time
from pathlib import Path
from typing import List, Tuple

from modules.action_analyzer import ActionAnalyzer
from modules.audio_analyzer import AudioAnalyzer
from modules.frame_extractor import extract_keyframes
from modules.highlighter import HighlightFinder
from modules.motion_analyzer import MotionAnalyzer
from modules.subtitler import Subtitler, SubtitleWord
from modules.video_cutter import VideoCutter

# ═══════════════════════════════════════════════════════════════
# Logging setup
# ═══════════════════════════════════════════════════════════════
def _setup_logging():
    # Включаем UTF-8 для Windows (emoji, псевдографика)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    # Handler for stdout (user sees info)
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.INFO)
    fmt = logging.Formatter(
        "[%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    handler.setFormatter(fmt)
    logger.addHandler(handler)

    # Suppress noisy libs
    for lib in ("faster_whisper", "moviepy", "PIL", "matplotlib"):
        logging.getLogger(lib).setLevel(logging.WARNING)

    return logger


logger = _setup_logging()


# ═══════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════
import config as cfg  # noqa: E402


# ═══════════════════════════════════════════════════════════════
# Main orchestrator
# ═══════════════════════════════════════════════════════════════
class ShortsCreator:
    """
    Оркестратор полного пайплайна создания шортсов.
    """

    def __init__(self):
        self.base_dir = Path(__file__).parent
        self.films_dir = self.base_dir / "films"
        self.shorts_dir = self.base_dir / "shorts"
        self.temp_dir = self.base_dir / "temp"

        # Создаём папки (если их удалили)
        for d in (self.films_dir, self.shorts_dir, self.temp_dir):
            d.mkdir(exist_ok=True)

        # Инициализируем модули
        self.action_analyzer = ActionAnalyzer()
        self.motion_analyzer = MotionAnalyzer()
        self.audio_analyzer = AudioAnalyzer()
        self.highlight_finder = HighlightFinder()
        self.video_cutter = VideoCutter()
        self.subtitler = Subtitler()

    # ------------------------------------------------------------------
    def find_videos(self) -> List[Path]:
        """Находит все видео в папке films/."""
        exts = {".mp4", ".avi", ".mov", ".mkv", ".webm", ".m4v"}
        videos = [f for f in self.films_dir.iterdir() if f.suffix.lower() in exts]
        return sorted(videos)

    # ------------------------------------------------------------------
    def process_video(self, video_path: Path):
        """Обрабатывает одно видео через полный пайплайн."""
        video_name = video_path.name
        logger.info("=" * 60)
        logger.info("🎬 Обработка: %s", video_name)
        logger.info("=" * 60)

        video_temp = self.temp_dir / video_path.stem
        frames_dir = video_temp / "frames"
        clips_dir = video_temp / "clips"
        audio_dir = video_temp / "audio"
        for d in (video_temp, frames_dir, clips_dir, audio_dir):
            d.mkdir(parents=True, exist_ok=True)

        try:
            # ── Шаг 1: Извлечение ключевых кадров ──────────────
            logger.info("")
            logger.info("📸 Шаг 1/6: Извлечение ключевых кадров...")
            frames = extract_keyframes(
                str(video_path),
                str(frames_dir),
                interval_sec=cfg.KEYFRAME_INTERVAL,
                scene_threshold=cfg.SCENE_CHANGE_THRESHOLD,
            )
            if not frames:
                logger.error("Не удалось извлечь кадры из видео")
                return

            scene_count = sum(1 for _, _, t in frames if t == "scene_change")
            logger.info(
                "   ✅ Извлечено %d кадров (%d scene_change)",
                len(frames), scene_count,
            )

            # ── Шаг 2: Локальный анализ движения ────────────────
            logger.info("")
            logger.info("🏃 Шаг 2/6: Анализ движения (optical flow)...")
            motion_scores = self.motion_analyzer.analyze_frames(
                [(p, ts) for p, ts, _ in frames],
            )
            avg_motion = sum(s for _, s in motion_scores) / max(len(motion_scores), 1)
            logger.info("   ✅ Средний motion score: %.3f", avg_motion)

            # ── Шаг 3: Анализ аудио ─────────────────────────────
            logger.info("")
            logger.info("🔊 Шаг 3/6: Анализ громкости аудио...")
            audio_scores = self.audio_analyzer.analyze(str(video_path))
            if audio_scores:
                avg_audio = sum(s for _, s in audio_scores) / len(audio_scores)
                logger.info("   ✅ Средняя громкость: %.3f", avg_audio)
            else:
                logger.warning("   ⚠️ Анализ аудио не дал результатов")

            # ── Шаг 4: Гибридный анализ экшна (motion + OpenRouter) ──
            logger.info("")
            logger.info("🤖 Шаг 4/6: Анализ экшна через OpenRouter (ключевые кадры)...")

            # ActionAnalyzer комбинирует:
            #   - motion score для ВСЕХ кадров (быстро, локально)
            #   - OpenRouter Vision для scene_change кадров (точно, но дорого)
            # Если API ключ не задан — использует только motion score
            has_api = cfg.OPENROUTER_API_KEY.startswith("sk-or-v1-")
            if has_api:
                logger.info(
                    "   Отправляем %d scene_change кадров в OpenRouter",
                    sum(1 for _, _, t in frames if t == "scene_change"),
                )
            else:
                logger.info("   OpenRouter не настроен — только motion score")

            video_action = self.action_analyzer.analyze(frames, motion_scores)

            if not video_action:
                logger.warning("   ⚠️ ActionAnalyzer не вернул результатов — fallback на motion")
                video_action = [(ts, s * 10.0) for ts, s in motion_scores]

            avg_action = sum(s for _, s in video_action) / max(len(video_action), 1)
            logger.info("   ✅ Средний action score: %.2f/10", avg_action)

            # ── Шаг 5: Поиск хайлайтов ──────────────────────────
            logger.info("")
            logger.info("✨ Шаг 5/6: Поиск хайлайтов (видео + аудио)...")
            highlights = self.highlight_finder.find_highlights(
                video_action,
                audio_scores if audio_scores else None,
            )

            if not highlights:
                logger.warning(
                    "   ⚠️ Не найдено хайлайтов! "
                    "Попробуйте снизить ACTION_THRESHOLD в config.py",
                )
                return

            logger.info("   ✅ Найдено %d хайлайтов:", len(highlights))
            for idx, (s, e) in enumerate(highlights, 1):
                logger.info("      #%d: %.1fс → %.1fс (длина %.1fс)", idx, s, e, e - s)

            # ── Шаг 6: Создание вертикальных клипов ────────────
            logger.info("")
            logger.info("✂️ Шаг 6/6: Создание вертикальных клипов + субтитры...")

            clip_paths: List[Path] = []
            for idx, (start, end) in enumerate(highlights, 1):
                duration = end - start
                temp_clip = clips_dir / f"clip_{idx}.mp4"
                logger.info("   Обработка хайлайта #%d (%.1f–%.1fс)", idx, start, end)

                try:
                    self.video_cutter.crop_vertical(
                        str(video_path), str(temp_clip), start, duration,
                    )
                    clip_paths.append(temp_clip)
                    logger.info("      ✅ Клип создан: %s", temp_clip.name)
                except RuntimeError as exc:
                    logger.error("      ❌ Ошибка создания клипа #%d: %s", idx, exc)
                    continue

            if not clip_paths:
                logger.error("❌ Не удалось создать ни одного клипа!")
                return

            # ── Шаг 6 (продолжение): Цветные субтитры ──────────
            for idx, clip_path in enumerate(clip_paths, 1):
                logger.info("   Субтитры для хайлайта #%d...", idx)

                try:
                    # Извлекаем аудио для whisper
                    audio_path = audio_dir / f"audio_{idx}.wav"
                    self.video_cutter.extract_audio(str(clip_path), str(audio_path))

                    # Генерируем word-level субтитры
                    logger.info("      📝 Распознавание речи...")
                    words = self.subtitler.generate_word_subtitles(str(audio_path))

                    if not words:
                        logger.warning("      ⚠️ Нет распознанного текста — копируем без субтитров")
                        output_path = self.shorts_dir / f"{video_path.stem}_short_{idx}.mp4"
                        shutil.copy2(clip_path, output_path)
                        continue

                    logger.info("      🎨 Наложение субтитров (%d слов)...", len(words))
                    output_path = self.shorts_dir / f"{video_path.stem}_short_{idx}.mp4"

                    self.subtitler.add_subtitles_to_video(
                        str(clip_path), words, str(output_path),
                    )

                    file_size = os.path.getsize(output_path) / (1024 * 1024)
                    logger.info(
                        "      ✅ Готово: %s (%.1f MB)",
                        output_path.name, file_size,
                    )

                except Exception as exc:
                    logger.error(
                        "      ❌ Ошибка субтитров для #%d: %s",
                        idx, exc,
                    )
                    # Fallback: копируем клип без субтитров
                    fallback_path = self.shorts_dir / f"{video_path.stem}_short_{idx}.mp4"
                    shutil.copy2(clip_path, fallback_path)
                    logger.info("      ⚠️ Сохранён клип без субтитров: %s", fallback_path.name)

            # ── Итог ────────────────────────────────────────────
            logger.info("")
            logger.info("=" * 60)
            logger.info(
                "✅ Обработка завершена! Создано %d шортсов из %d хайлайтов",
                len(list(self.shorts_dir.glob(f"{video_path.stem}_short_*.mp4"))),
                len(highlights),
            )
            logger.info("📁 Результаты сохранены в папку: %s", self.shorts_dir)
            logger.info("=" * 60)

        except Exception as exc:
            logger.error("❌ Критическая ошибка при обработке %s:", video_name)
            logger.exception(exc)

        finally:
            # Опциональная очистка временных файлов
            # shutil.rmtree(video_temp, ignore_errors=True)
            pass

    # ------------------------------------------------------------------
    def run(self):
        """Запускает обработку всех видео в папке films/."""
        logger.info("")
        logger.info("╔════════════════════════════════════════════════════╗")
        logger.info("║   🎬 YouTube Shorts Auto-Creator v2.0             ║")
        logger.info("║   OpenRouter Vision + Motion + Audio + Субтитры   ║")
        logger.info("╚════════════════════════════════════════════════════╝")
        logger.info("")

        # Проверка API ключа
        if not cfg.OPENROUTER_API_KEY.startswith("sk-or-v1-"):
            logger.warning(
                "⚠️ OpenRouter API ключ не настроен! "
                "Будет использован только локальный анализ движения."
            )
            logger.warning("   Получите ключ на https://openrouter.ai/keys")
            logger.warning("   И укажите в config.py или переменной OPENROUTER_API_KEY")
            logger.info("")

        # Поиск видео
        videos = self.find_videos()
        if not videos:
            logger.info("📁 Нет видео в папке: %s", self.films_dir)
            logger.info("   Поместите видеофайлы в папку 'films/' и запустите снова")
            return

        logger.info("📹 Найдено видео: %d", len(videos))
        for v in videos:
            size_mb = os.path.getsize(v) / (1024 * 1024)
            logger.info("   - %s (%.1f MB)", v.name, size_mb)
        logger.info("")

        # Обработка каждого видео
        start_time = time.time()
        for video in videos:
            self.process_video(video)
            logger.info("")

        elapsed = time.time() - start_time
        logger.info("🎉 Все видео обработаны за %.1f минут!", elapsed / 60)


# ═══════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    creator = ShortsCreator()
    creator.run()