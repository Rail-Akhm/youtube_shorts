# 🎬 YouTube Shorts Auto-Creator v2.0
## Автоматическая нарезка вертикальных видео (OpenRouter + OpenCV + FFmpeg)

---

## 📁 Структура проекта

```
shorts_creator/
├── main.py                    # Главный скрипт запуска
├── config.py                  # Конфигурация (API ключи, thresholds)
├── requirements.txt           # Зависимости
│
├── films/                     # 📥 СЮДА кладёте большой фильм
├── shorts/                    # 📤 ГОТОВЫЕ шортсы сохраняются сюда
├── temp/                      # 🗑️ Временные файлы (создаётся автоматически)
│
├── modules/
│   ├── __init__.py
│   ├── frame_extractor.py     # Извлечение ключевых кадров (scene detect)
│   ├── motion_analyzer.py     # Локальный анализ движения (OpenCV optical flow)
│   ├── audio_analyzer.py      # Анализ громкости аудио (FFmpeg)
│   ├── action_analyzer.py     # Анализ экшна через OpenRouter (только ключевые кадры)
│   ├── highlighter.py         # Поиск интересных моментов (видео + аудио)
│   ├── video_cutter.py        # Нарезка и вертикализация
│   └── subtitler.py           # Современные цветные субтитры (ffmpeg drawtext/ass)
│
├── CLAUDE.md
└── README.md
```

---

## 🧠 Архитектурные решения (v2.0)

### 1. Анализ экшна — гибридный подход
- **Локально**: OpenCV (оптический поток + детектор движения) для быстрого прореживания
- **Scene detection**: histogram-based для выделения ключевых кадров
- **OpenRouter**: только ключевые кадры (1 кадр в 3-5 сек + сцены), а не все 1 fps
- **Результат**: ~в 3-5 раз меньше запросов к API, экономия времени и денег

### 2. Субтитры — современные цветные (кебы)
- Цветные блоки с текстом (kebab-style): разные цвета для акцентов
- Жёлтый, оранжевый, красный, голубой — смена цвета между словами
- Чёрный полупрозрачный фон под текст
- Крупный шрифт на весь экран
- Анимация появления (опционально)
- Реализация через moviepy (кросс-платформенно)
- Резерв: ffmpeg drawtext для простых случаев

### 3. Анализ аудио + видео
- Извлечение аудио-волны через FFmpeg (PCM s16le)
- Анализ RMS громкости и обнаружение пиков
- Комбинированная оценка: `score = video_score * 0.6 + audio_score * 0.4`
- Хайлайты = моменты, где и видео, и аудио показывают высокую активность

### 4. Длительность клипов
- MIN_CLIP_DURATION = 15 сек
- MAX_CLIP_DURATION = 59 сек (лимит YouTube Shorts)

### 5. Запуск — только локальный
- Кинул видео в `films/`, запустил `main.py`, получил результат в `shorts/`

---

## 📄 Файлы проекта

### **config.py**
- OPENROUTER_API_KEY — из переменной окружения (или .env)
- ACTION_THRESHOLD = 7 (0-10, порог для OpenRouter)
- AUDIO_THRESHOLD = 0.5 (нормализованный, 0-1)
- MIN_CLIP_DURATION = 15
- MAX_CLIP_DURATION = 59
- VISION_MODEL = "google/gemini-2.0-flash-exp"
- DEVICE = "cpu"
- WHISPER_MODEL = "base"
- KEYFRAME_INTERVAL = 3 (сек, как часто брать кадры)
- SCENE_CHANGE_THRESHOLD = 30.0 (для детектора смены сцен)
- VIDEO_WEIGHT = 0.6 / AUDIO_WEIGHT = 0.4 (веса комбинированной оценки)

### **modules/frame_extractor.py**
- Scene detection через histogram difference (HSV hue)
- Извлечение ключевых кадров: каждый N-ый кадр + при смене сцены
- Сохранение метаданных (тип кадра: regular / scene_change)

### **modules/motion_analyzer.py**
- Локальный анализ движения через optical flow (Farneback)
- Анализ разницы между последовательными кадрами
- Оценка motion score (0.0 - 1.0) для каждого ключевого кадра

### **modules/audio_analyzer.py**
- Извлечение аудио-волны через ffmpeg (PCM s16le, 16kHz, моно)
- RMS громкость по окнам (дефолт 1 сек)
- Нормализация и поиск пиков
- Оценка audio score (0.0 - 1.0) для каждого временного отрезка

### **modules/action_analyzer.py**
- Гибрид: motion score для ВСЕХ кадров + OpenRouter для scene_change
- Параллельные запросы к OpenRouter (ThreadPoolExecutor, до 3 воркеров)
- Retry с exponential backoff (2 попытки)
- Прокси-оценки: если API недоступен — использует motion score
- **Фикс кодировки**: JSON payload кодируется в UTF-8 вручную (чинит latin-1 ошибку)

### **modules/highlighter.py**
- Комбинированный анализ: `total = video_action * 0.6 + audio_loudness * 0.4`
- Динамический порог (75-й перцентиль + ACTION_THRESHOLD как минимум)
- Умное расширение границ хайлайта (не рвать на середине слова/фразы)

### **modules/video_cutter.py**
- Проверка ошибок ffmpeg (check=True, анализ stderr)
- cropdetect для автоматического определения чёрных полос (pillarbox)
- Улучшенная вертикализация с учётом содержимого

### **modules/subtitler.py**
- Цветные субтитры (kebab-style) через moviepy (кросс-платформенно)
- Несколько цветов: жёлтый `#FFD700`, оранжевый `#FF6B35`, красный `#FF3366`, голубой `#00D4FF`
- Чёрный полупрозрачный фон под текст (bg_color="black")
- Разбивка длинных строк на 2-4 слова
- Синхронизация с аудио (word-level timestamps из faster-whisper)
- Резерв: ffmpeg drawtext для коротких видео (<200 слов)

### **main.py**
- 6-шаговый pipeline: кадры → motion → аудио → OpenRouter → хайлайты → субтитры
- Логгер с уровнями (вместо print)
- Прогресс-бары (tqdm)
- Обработка ошибок на каждом шаге
- Авто-создание папок films/, shorts/, temp/

---

## 🚀 Быстрый старт

```bash
# 1. Установить зависимости
pip install -r requirements.txt

# 2. Убедиться что FFmpeg установлен
ffmpeg -version

# 3. Положить большой фильм в папку films/
cp /путь/к/фильму.mp4 films/

# 4. Настроить API ключ OpenRouter (опционально, без него работает локально)
$env:OPENROUTER_API_KEY = "sk-or-v1-ваш_ключ"
# Или навсегда:
[Environment]::SetEnvironmentVariable("OPENROUTER_API_KEY", "sk-or-v1-ваш_ключ", "User")

# 5. Запустить
python main.py

# 6. Готовые шортсы — в папке shorts/
```

---

## 🧪 Известные проблемы

| Проблема | Причина | Решение |
|----------|---------|---------|
| `[WinError 2]` на шаге 3 | FFmpeg не в PATH | Установить FFmpeg: `winget install FFmpeg` |
| `latin-1 codec` в OpenRouter | Requests кодирует JSON как latin-1 | Исправлено: явный UTF-8 payload |
| tqdm кракозябры в логе | Кодировка cp1251 в Windows | Только в сохранённом выводе, в терминале OK |

---

## 📦 Зависимости

```txt
opencv-python>=4.9.0.80
ffmpeg-python>=0.2.0
openai>=1.12.0
requests>=2.31.0
faster-whisper>=1.0.0
moviepy>=1.0.3
numpy>=1.24.3
pillow>=10.1.0
tqdm>=4.66.1
```

Дополнительно:
- **FFmpeg + ffprobe** — должны быть в системе (или в PATH)
- **CUDA** (опционально) — для GPU-ускорения whisper