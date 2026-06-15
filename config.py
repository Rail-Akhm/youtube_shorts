"""
Конфигурация YouTube Shorts Auto-Creator v2.0
"""
import os

# ─────────────────────── OpenRouter ───────────────────────
# Получить ключ: https://openrouter.ai/keys
# Укажите ключ в переменной окружения OPENROUTER_API_KEY
# или раскомментируйте строку ниже и вставьте ключ:
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "sk-or-v1-ваш_ключ_здесь")
# Самая дешёвая модель с vision
VISION_MODEL = "google/gemini-2.0-flash-exp"

# ─────────────────────── Пороги экшна ─────────────────────
ACTION_THRESHOLD = 7       # 0–10, порог для OpenRouter-оценки
AUDIO_THRESHOLD = 0.5      # 0–1, нормализованный порог громкости
MIN_CLIP_DURATION = 15     # секунд
MAX_CLIP_DURATION = 59     # секунд (лимит YouTube Shorts)

# ─────────────────────── Извлечение кадров ────────────────
KEYFRAME_INTERVAL = 3.0    # сек — как часто брать кадры при анализе
SCENE_CHANGE_THRESHOLD = 30.0  # порог histogram difference для детекции смены сцены

# ─────────────────────── Локальные модели ─────────────────
DEVICE = "cpu"             # или "cuda" если есть GPU
WHISPER_MODEL = "base"     # tiny | base | small | medium | large-v3

# ─────────────────────── Веса для комбинированной оценки ──
VIDEO_WEIGHT = 0.6         # вес визуального экшна в итоговом score
AUDIO_WEIGHT = 0.4         # вес аудио-громкости

# ─────────────────────── Субтитры ─────────────────────────
SUBTITLE_COLORS = [
    "#FFD700",  # золотой / жёлтый
    "#FF6B35",  # оранжевый
    "#FF3366",  # красный-розовый
    "#00D4FF",  # голубой
]
SUBTITLE_BG_COLOR = "black@0.6"  # цвет фона + прозрачность
SUBTITLE_FONT_SIZE = 72           # px