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
- Реализация через ffmpeg drawtext (быстрее moviepy)
- Резерв: ASS субтитры для сложных эффектов

### 3. Анализ аудио + видео
- Извлечение аудио-волны через FFmpeg
- Анализ RMS громкости и обнаружение пиков
- Комбинированная оценка: `score = video_score * 0.6 + audio_score * 0.4`
- Хайлайты = моменты, где и видео, и аудио показывают высокую активность

### 4. Длительность клипов
- MIN_CLIP_DURATION = 15 сек
- MAX_CLIP_DURATION = 59 сек (лимит YouTube Shorts)

### 5. Запуск — только локальный
- Кинул видео в `input/`, запустил `main.py`, получил результат в `output/`

---

## 📄 Требования к улучшению кода

### Общие принципы
- **Type hints** — все функции аннотированы
- **Логгер** — вместо print, с уровнями (INFO, WARNING, ERROR)
- **Обработка ошибок** — везде, включая ffmpeg subprocess
- **Прогресс-бары** — tqdm везде, где есть циклы
- **DRY** — без дублирования кода

### Файлы проекта

#### **config.py**
- OPENROUTER_API_KEY — из переменной окружения
- ACTION_THRESHOLD = 7 (0-10, порог для OpenRouter)
- AUDIO_THRESHOLD = 0.5 (нормализованный, 0-1)
- MIN_CLIP_DURATION = 15
- MAX_CLIP_DURATION = 59
- VISION_MODEL = "google/gemini-2.0-flash-exp"
- DEVICE = "cpu"
- WHISPER_MODEL = "base"
- KEYFRAME_INTERVAL = 3 (сек, как часто брать кадры)
- SCENE_CHANGE_THRESHOLD = 30.0 (для детектора смены сцен)

#### **modules/frame_extractor.py**
- Scene detection через histogram difference
- Извлечение ключевых кадров: каждый N-ый кадр + при смене сцены
- Сохранение метаданных (тип кадра: обычный / смена сцены)

#### **modules/motion_analyzer.py** (НОВЫЙ)
- Локальный анализ движения через optical flow (Farneback)
- Анализ разницы между последовательными кадрами
- Оценка motion score (0.0 - 1.0) для каждого ключевого кадра

#### **modules/audio_analyzer.py** (НОВЫЙ)
- Извлечение аудио-волны через ffmpeg (pcm)
- RMS громкость по окнам
- Нормализация и поиск пиков
- Оценка audio score (0.0 - 1.0) для каждого временного отрезка

#### **modules/action_analyzer.py**
- Улучшен: принимает только ключевые кадры
- Параллельные запросы к OpenRouter (ThreadPoolExecutor)
- Retry с exponential backoff
- Прокси-оценки: если API недоступен — использует motion score

#### **modules/highlighter.py**
- Комбинированный анализ: `total = video_action * 0.6 + audio_loudness * 0.4`
- Динамический порог (не жёсткий 7, а адаптивный под конкретное видео)
- Умное расширение границ хайлайта (не рвать на середине слова/фразы)

#### **modules/video_cutter.py**
- Проверка ошибок ffmpeg (check=True, анализ stderr)
- cropdetect для автоматического определения чёрных полос (pillarbox)
- Улучшенная вертикализация с учётом содержимого

#### **modules/subtitler.py**
- Цветные субтитры (kebab-style) через ffmpeg drawtext
- Несколько цветов: жёлтый `#FFD700`, оранжевый `#FF6B35`, красный `#FF3366`, голубой `#00D4FF`
- Чёрный полупрозрачный фон под текст
- Разбивка длинных строк на 2-3 строки
- Синхронизация с аудио (word-level timestamps из faster-whisper)
- Резерв: moviepy только если ffmpeg drawtext не справляется

---

## 🚀 Быстрый старт

```bash
# 1. Установить зависимости
pip install -r requirements.txt

# 2. Положить большой фильм в папку films/
cp /путь/к/фильму.mp4 films/

# 3. Настроить API ключ OpenRouter (опционально, без него работает локально)
#    Отредактировать config.py или:
$env:OPENROUTER_API_KEY = "sk-or-v1-ваш_ключ"

# 4. Запустить
python main.py

# 5. Готовые шортсы — в папке shorts/
```

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