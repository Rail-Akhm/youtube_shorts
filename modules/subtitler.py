"""
Современные цветные субтитры (kebab-style).

Генерация:
1. faster-whisper → word-level таймстемпы
2. Группировка слов во фразы (по паузам и длине)
3. Каждая фраза — цветной текст на чёрном полупрозрачном фоне
4. Цвета циклически меняются между словами для визуального разнообразия

Реализация:
- ffmpeg drawtext — основной рендер (быстрый)
- moviepy — fallback (если фильтр слишком сложный)
"""

from __future__ import annotations

import enum
import logging
import math
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import List, Tuple

from faster_whisper import WhisperModel
from moviepy import VideoFileClip, TextClip, CompositeVideoClip

from config import DEVICE, WHISPER_MODEL, SUBTITLE_COLORS, SUBTITLE_FONT_SIZE

logger = logging.getLogger(__name__)

COLOR_CYCLE = SUBTITLE_COLORS or ["#FFD700", "#FF6B35", "#FF3366", "#00D4FF"]


class SubtitleWord:
    """Одно слово с таймингом."""
    __slots__ = ("text", "start", "end", "color")

    def __init__(self, text: str, start: float, end: float, color: str | None = None):
        self.text = text
        self.start = start
        self.end = end
        self.color = color or COLOR_CYCLE[0]


class Subtitler:
    """
    Генератор цветных субтитров.
    """

    def __init__(self):
        self.model = WhisperModel(WHISPER_MODEL, device=DEVICE, compute_type="int8")

    # ------------------------------------------------------------------
    def generate_word_subtitles(self, audio_path: str) -> List[SubtitleWord]:
        """
        Генерирует субтитры с word-level таймстемпами.

        Args:
            audio_path: путь к WAV-файлу

        Returns:
            список SubtitleWord
        """
        max_line_width = 50  # макс символов в строке

        segments, info = self.model.transcribe(
            audio_path,
            language="ru",
            beam_size=5,
            word_timestamps=True,
            vad_filter=True,
        )

        words: List[SubtitleWord] = []
        color_idx = 0
        line_len = 0

        for segment in segments:
            if not segment.words:
                # Нет word-level — создаём из текста сегмента
                words.append(SubtitleWord(
                    text=segment.text.strip(),
                    start=segment.start,
                    end=segment.end,
                    color=COLOR_CYCLE[color_idx % len(COLOR_CYCLE)],
                ))
                color_idx += 1
                continue

            for w in segment.words:
                word_text = w.word.strip()
                if not word_text:
                    continue

                # Определяем цвет для слова (меняем при знаках препинания или
                # каждые 2-3 слова для разнообразия)
                needs_newline = False
                if line_len + len(word_text) > max_line_width:
                    needs_newline = True
                    line_len = 0

                # Добавляем цвет к слову
                color = COLOR_CYCLE[color_idx % len(COLOR_CYCLE)]
                words.append(SubtitleWord(
                    text=word_text,
                    start=w.start,
                    end=w.end,
                    color=color,
                ))

                line_len += len(word_text) + 1

                # Меняем цвет каждые 2-3 слова
                if len(words) % 3 == 0:
                    color_idx += 1

        if not words:
            logger.warning("Whisper не вернул слов — пустой результат")
            return []

        logger.info(
            "Сгенерировано %d слов, язык: %s (вероятность %.1f%%)",
            len(words), info.language, info.language_probability * 100,
        )
        return words

    # ------------------------------------------------------------------
    def add_subtitles_to_video(
        self,
        video_path: str,
        words: List[SubtitleWord],
        output_path: str,
    ) -> str:
        """
        Накладывает цветные субтитры на видео.

        Пытается использовать ffmpeg drawtext. Если фильтр слишком сложный
        (много слов), падает на moviepy.

        Args:
            video_path: исходное видео (уже вертикальное 9:16)
            words: список слов с таймингом
            output_path: куда сохранить

        Returns:
            output_path
        """
        # Если слов мало — пробуем ffmpeg
        if len(words) < 200:
            try:
                return self._render_with_ffmpeg(video_path, words, output_path)
            except Exception as exc:
                logger.warning("FFmpeg субтитры не удались (%s), падаем на moviepy", exc)

        # Fallback на moviepy
        return self._render_with_moviepy(video_path, words, output_path)

    # ------------------------------------------------------------------
    def _render_with_ffmpeg(
        self,
        video_path: str,
        words: List[SubtitleWord],
        output_path: str,
    ) -> str:
        """
        Рендерит субтитры через ffmpeg drawtext.
        Каждое слово — отдельный drawtext фильтр с цветным текстом
        и чёрным фоном.
        """
        # Группируем слова в строки для отображения
        lines = self._group_words_into_lines(words)

        # Строим drawtext фильтры
        drawtext_filters = []
        video = VideoFileClip(video_path)
        video_w, video_h = video.w, video.h
        video.close()

        font_size = SUBTITLE_FONT_SIZE
        line_height = font_size + 20
        margin_bottom = 80  # отступ от низа
        margin_horizontal = 40

        for line_idx, (line_start, line_end, line_words) in enumerate(lines):
            # Позиция строки (снизу вверх)
            y_pos = video_h - margin_bottom - line_idx * line_height

            # Строим текст для строки — каждая часть со своим цветом
            # Используем \fs для размера и \c для цвета в ASS-стиле
            # На самом деле drawtext не поддерживает inline цвета в одном фильтре.
            # Поэтому каждое слово — отдельный drawtext фильтр.

            x_offset = margin_horizontal
            for word in line_words:
                # Измеряем ширину текста (приблизительно)
                text_width = len(word.text) * font_size * 0.6
                bg_padding = 10

                # drawtext фильтр для этого слова
                # Цвет текста + чёрный фон
                color = word.color.lstrip("#")
                filter_str = (
                    f"drawtext=text='{self._escape_ffmpeg_text(word.text)}':"
                    f"fontsize={font_size}:"
                    f"fontcolor={color}:"
                    f"box=1:boxcolor=black@0.6:"
                    f"boxborderw={bg_padding}:"
                    f"x={x_offset}:"
                    f"y={y_pos}:"
                    f"enable='between(t,{word.start:.2f},{word.end:.2f})'"
                )
                drawtext_filters.append(filter_str)
                x_offset += text_width + bg_padding * 2 + 8

        if not drawtext_filters:
            # Нет слов — копируем без изменений
            logger.warning("Нет слов для субтитров")
            cmd = [
                "ffmpeg", "-i", video_path,
                "-c", "copy",
                "-y", output_path,
            ]
            subprocess.run(cmd, check=True, capture_output=True)
            return output_path

        # Комбинируем все фильтры через запятую
        filter_complex = ",".join(drawtext_filters)

        cmd = [
            "ffmpeg", "-i", video_path,
            "-vf", filter_complex,
            "-c:v", "libx264", "-preset", "fast", "-crf", "22",
            "-c:a", "aac", "-b:a", "128k",
            "-y", output_path,
        ]

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=600,
            )
            if result.returncode != 0:
                stderr = result.stderr[:1000] if result.stderr else ""
                raise RuntimeError(f"FFmpeg error: {stderr}")

            logger.info("Субтитры наложены через ffmpeg (%d фильтров)", len(drawtext_filters))
            return output_path

        except subprocess.TimeoutExpired:
            raise RuntimeError("FFmpeg таймаут при наложении субтитров")

    # ------------------------------------------------------------------
    def _render_with_moviepy(
        self,
        video_path: str,
        words: List[SubtitleWord],
        output_path: str,
    ) -> str:
        """
        Рендерит субтитры через moviepy (более гибкий, но медленнее).
        """
        logger.info("Рендеринг субтитров через moviepy (%d слов)", len(words))
        video = VideoFileClip(video_path)

        lines = self._group_words_into_lines(words)

        text_clips = []
        font_size = SUBTITLE_FONT_SIZE
        line_height = font_size + 20
        margin_bottom = 80
        margin_horizontal = 40

        for line_idx, (line_start, line_end, line_words) in enumerate(lines):
            # Каждое слово отдельным TextClip, выложенным в строку
            x_offset = margin_horizontal
            y_pos = video.h - margin_bottom - line_idx * line_height

            for word in line_words:
                txt = TextClip(
                    "arial",
                    text=word.text,
                    font_size=font_size,
                    color=word.color,
                    bg_color="black",
                    stroke_color="black",
                    stroke_width=2,
                    method="label",
                ).set_start(word.start).set_duration(
                    max(0.05, word.end - word.start)
                ).set_position((x_offset, y_pos))

                text_clips.append(txt)

                # Обновляем x_offset (приблизительная ширина)
                text_width = len(word.text) * font_size * 0.6
                x_offset += text_width + 20

        final = CompositeVideoClip(
            [video] + text_clips,
            size=video.size,
        )

        final.write_videofile(
            output_path,
            codec="libx264",
            audio_codec="aac",
            fps=video.fps,
            preset="fast",
            threads=4,
            logger=None,
        )

        video.close()
        final.close()
        return output_path

    # ------------------------------------------------------------------
    def _group_words_into_lines(
        self,
        words: List[SubtitleWord],
    ) -> List[Tuple[float, float, List[SubtitleWord]]]:
        """
        Группирует слова в строки (2-4 слова на строку).

        Returns:
            список (start_time, end_time, [SubtitleWord, ...])
        """
        if not words:
            return []

        lines: List[Tuple[float, float, List[SubtitleWord]]] = []
        current_line: List[SubtitleWord] = []
        max_words_per_line = 4
        pause_threshold = 0.5  # сек — пауза длиннее → новая строка

        for word in words:
            if not current_line:
                current_line.append(word)
            else:
                pause = word.start - current_line[-1].end
                last_word = current_line[-1]

                # Начинаем новую строку если:
                if (
                    len(current_line) >= max_words_per_line
                    or pause > pause_threshold
                    or len(" ".join(w.text for w in current_line + [word])) > 50
                ):
                    line_start = current_line[0].start
                    line_end = last_word.end
                    lines.append((line_start, line_end, current_line))
                    current_line = [word]
                else:
                    current_line.append(word)

        if current_line:
            line_start = current_line[0].start
            line_end = current_line[-1].end
            lines.append((line_start, line_end, current_line))

        return lines

    # ------------------------------------------------------------------
    @staticmethod
    def _escape_ffmpeg_text(text: str) -> str:
        """Экранирует спецсимволы для drawtext."""
        replacements = {
            "'": "’",
            ":": "\\:",
            "\\": "\\\\",
            "[": "\\[",
            "]": "\\]",
            "{": "\\{",
            "}": "\\}",
            "%": "\\%",
        }
        for old, new in replacements.items():
            text = text.replace(old, new)
        return text

    # ------------------------------------------------------------------
    def generate_subtitles(self, audio_path: str) -> list:
        """
        Совместимость со старым API: возвращает список (start, end, text)
        для сегментов (без цветов).
        """
        segments, _ = self.model.transcribe(audio_path, language="ru", beam_size=5)
        return [(seg.start, seg.end, seg.text) for seg in segments]

    # ------------------------------------------------------------------
    def add_subtitles_to_video(self, video_path: str, subtitles: list, output_path: str):
        """
        Совместимость со старым API (без цветов, обычные субтитры).
        """
        video = VideoFileClip(video_path)
        text_clips = []

        for start, end, text in subtitles:
            if not text.strip():
                continue

            if len(text) > 50:
                words = text.split()
                lines = []
                current_line = []
                for word in words:
                    current_line.append(word)
                    if len(" ".join(current_line)) > 40:
                        lines.append(" ".join(current_line))
                        current_line = []
                if current_line:
                    lines.append(" ".join(current_line))
                display_text = "\n".join(lines)
            else:
                display_text = text

            txt_clip = (
                TextClip(
                    "arial",
                    text=display_text,
                    font_size=SUBTITLE_FONT_SIZE,
                    color="white",
                    bg_color="black",
                    stroke_color="black",
                    stroke_width=3,
                    method="caption",
                    size=(video.w - 100, None),
                )
                .set_position(("center", "bottom"))
                .set_start(start)
                .set_duration(end - start)
            )
            text_clips.append(txt_clip)

        final_video = CompositeVideoClip([video] + text_clips)
        final_video.write_videofile(
            output_path,
            codec="libx264",
            audio_codec="aac",
            fps=video.fps,
            preset="fast",
            threads=4,
            logger=None,
        )
        video.close()
        final_video.close()
        return output_path