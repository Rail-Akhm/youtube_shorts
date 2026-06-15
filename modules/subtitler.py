"""
Современные цветные субтитры (kebab-style).

Генерация:
1. faster-whisper → word-level таймстемпы
2. Группировка слов во фразы (по паузам и длине)
3. Каждая фраза — цветной текст на чёрном фоне
4. Цвета циклически меняются между словами

Реализация: moviepy v2 (кросс-платформенно)
"""

from __future__ import annotations

import logging
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
    """Генератор цветных субтитров (moviepy v2)."""

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
        max_line_width = 50

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

                if line_len + len(word_text) > max_line_width:
                    line_len = 0

                color = COLOR_CYCLE[color_idx % len(COLOR_CYCLE)]
                words.append(SubtitleWord(
                    text=word_text,
                    start=w.start,
                    end=w.end,
                    color=color,
                ))

                line_len += len(word_text) + 1

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
        Накладывает цветные субтитры на видео (moviepy v2).

        Args:
            video_path: исходное видео (уже вертикальное 9:16)
            words: список слов с таймингом
            output_path: куда сохранить

        Returns:
            output_path
        """
        return self._render_with_moviepy(video_path, words, output_path)

    # ------------------------------------------------------------------
    def _render_with_moviepy(
        self,
        video_path: str,
        words: List[SubtitleWord],
        output_path: str,
    ) -> str:
        """Рендерит субтитры через moviepy v2."""
        logger.info("Рендеринг субтитров через moviepy (%d слов)", len(words))
        video = VideoFileClip(video_path)

        lines = self._group_words_into_lines(words)

        text_clips = []
        font_size = SUBTITLE_FONT_SIZE
        line_height = font_size + 20
        margin_bottom = 80
        margin_horizontal = 40

        for line_idx, (_line_start, _line_end, line_words) in enumerate(lines):
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
                )
                # moviepy v2: with_* вместо set_*
                txt = txt.with_start(word.start)
                txt = txt.with_duration(max(0.05, word.end - word.start))
                txt = txt.with_position((x_offset, y_pos))

                text_clips.append(txt)

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
        pause_threshold = 0.5

        for word in words:
            if not current_line:
                current_line.append(word)
            else:
                pause = word.start - current_line[-1].end
                last_word = current_line[-1]

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