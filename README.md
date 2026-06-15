<div align="center">

# 🎬 YouTube Shorts Auto-Creator

**Автоматическая нарезка вертикальных видео с цветными субтитрами**

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://python.org)
[![OpenRouter](https://img.shields.io/badge/OpenRouter-Vision-FF6B35?logo=openai&logoColor=white)](https://openrouter.ai)
[![FFmpeg](https://img.shields.io/badge/FFmpeg-required-007808?logo=ffmpeg&logoColor=white)](https://ffmpeg.org)
[![Licence](https://img.shields.io/badge/Licence-MIT-green)](LICENSE)

**Пайплайн:** OpenRouter Vision · Motion Flow · Audio Analysis · Scene Detection · Kebab-субтитры

</div>

---

## 📋 Содержание

- [Возможности](#-возможности)
- [Как это работает](#-как-это-работает)
- [Установка](#-установка)
- [Использование](#-использование)
- [Пример работы](#-пример-работы)
- [Структура проекта](#-структура-проекта)
- [Конфигурация](#-конфигурация)
- [Планы развития](#-планы-развития)

---

## ✨ Возможности

| Возможность | Описание |
|-------------|----------|
| 🎯 **Умный анализ экшна** | Комбинация локального optical flow + OpenRouter Vision |
| 🔊 **Анализ аудио** | Поиск пиков громкости (крики, взрывы, музыка) |
| 🎨 **Цветные субтитры** | Kebab-style: каждое слово своего цвета на тёмном фоне |
| 🎬 **Scene detection** | Автоматическое определение смены сцен через гистограммы |
| ✂️ **Вертикализация 9:16** | Умная обрезка с авто-удалением чёрных полос |
| ⚡ **Экономия API** | В OpenRouter отправляются только ключевые кадры (~20% от всех) |
| 🔄 **Fallback** | Без API ключа — полноценная работа на локальном анализе |

---

## 🧠 Как это работает

```
🎬 Фильм (любой: mp4, avi, mkv, mov)
   │
   ├─📸 Шаг 1: Извлечение ключевых кадров
   │   • Кадр каждые 3 секунды
   │   • Scene detection (histogram diff)
   │   • Пометка: regular / scene_change
   │
   ├─🏃 Шаг 2: Локальный анализ движения
   │   • Optical Flow (Farneback)
   │   • Motion score 0.0–1.0 для каждого кадра
   │   • Бесплатно, без API
   │
   ├─🔊 Шаг 3: Анализ громкости аудио
   │   • PCM-волна через FFmpeg
   │   • RMS громкость по окнам
   │   • Пики → audio score 0.0–1.0
   │
   ├─🤖 Шаг 4: OpenRouter Vision (только для scene_change)
   │   • ❌ Есть API ключ → точная оценка экшна 0–10
   │   • ✅ Нет ключа → fallback на motion score
   │   • Экономия ~5x vs отправка всех кадров
   │
   ├─✨ Шаг 5: Поиск хайлайтов
   │   • Комбинация: video × 0.6 + audio × 0.4
   │   • Динамический порог (под каждое video)
   │   • Длина: 15–59 секунд
   │
   └─✂️ Шаг 6: Создание шортсов
       • cropdetect → удаление чёрных полос
       • Обрезка 9:16 с центрированием
       • Цветные kebab-субтитры
       • 4 цвета в цикле + чёрный фон
```

---

## 📦 Установка

### 1️⃣ Системные требования

| Компонент | Версия |
|-----------|--------|
| Python | 3.10+ |
| FFmpeg | любая (должен быть в PATH) |
| pip | последняя |

### 2️⃣ Установка FFmpeg

<details>
<summary>🐧 Linux</summary>

```bash
sudo apt install ffmpeg
# или
sudo pacman -S ffmpeg
```
</details>

<details>
<summary>🍎 macOS</summary>

```bash
brew install ffmpeg
```
</details>

<details>
<summary>🪟 Windows</summary>

```bash
# Через winget:
winget install FFmpeg

# Или вручную:
# 1. Скачать: https://ffmpeg.org/download.html
# 2. Распаковать в C:\ffmpeg
# 3. Добавить C:\ffmpeg\bin в PATH
```
</details>

Проверьте установку:
```bash
ffmpeg -version
ffprobe -version
```

### 3️⃣ Установка проекта

```bash
# Клонировать
git clone https://github.com/Rail-Akhm/youtube_shorts.git
cd youtube_shorts

# Установить зависимости
pip install -r requirements.txt
```

### 4️⃣ Настройка API ключа (опционально)

```bash
# Через .env файл:
cp .env.example .env
# Отредактируйте .env — вставьте ключ

# Или через переменную окружения:
export OPENROUTER_API_KEY="sk-or-v1-ваш_ключ"
```

Ключ получить: https://openrouter.ai/keys

> **Без ключа** проект работает в локальном режиме (только motion + audio анализ).

---

## 🚀 Использование

```bash
# 1. Положить фильм в папку films/
cp /путь/к/фильму.mp4 films/

# 2. Запустить
python main.py

# 3. Забрать шортсы из папки shorts/
```

Всё! 🎉

---

## 🎬 Пример работы

**Вход:** `films/rick_and_morty_s1_e1.mp4` (22 мин, 375 MB)

**Результат:**
- 451 кадров извлечено (119 scene_change)
- Средний motion score: 0.674
- Найдено хайлайтов: N штук длиной 15–59 сек
- Выход: `shorts/rick_and_morty_s1_e1_short_1.mp4`, `_short_2.mp4` ...

---

## 📁 Структура проекта

```
youtube_shorts/
│
├── films/                  # 📥 Сюда кладёте фильмы
├── shorts/                 # 📤 Готовые шортсы
├── temp/                   # 🗑️ Временные файлы (автоочистка)
│
├── main.py                 # 🚀 Запуск пайплайна
├── config.py               # ⚙️ Настройки (пороги, веса, цвета)
├── requirements.txt        # 📦 Зависимости
├── .env.example            # 🔑 Шаблон для API ключа
│
├── modules/
│   ├── frame_extractor.py  # Scene detection + ключевые кадры
│   ├── motion_analyzer.py  # Optical Flow (Farneback)
│   ├── audio_analyzer.py   # RMS громкость аудио
│   ├── action_analyzer.py  # OpenRouter Vision (только keyframes)
│   ├── highlighter.py      # Комбинированный поиск хайлайтов
│   ├── video_cutter.py     # Вертикализация 9:16 + cropdetect
│   └── subtitler.py        # Цветные kebab-субтитры
│
├── CLAUDE.md               # Техническая документация
└── README.md               # Вы здесь 👋
```

---

## ⚙️ Конфигурация

Все настройки в `config.py`:

| Параметр | Значение | Описание |
|----------|----------|----------|
| `ACTION_THRESHOLD` | `7` | Порог экшна (0–10) |
| `AUDIO_THRESHOLD` | `0.5` | Порог громкости (0–1) |
| `MIN_CLIP_DURATION` | `15` | Мин. длина шортса (сек) |
| `MAX_CLIP_DURATION` | `59` | Макс. длина (лимит YouTube) |
| `KEYFRAME_INTERVAL` | `3.0` | Интервал между кадрами (сек) |
| `VIDEO_WEIGHT` | `0.6` | Вес видео в итоговом score |
| `AUDIO_WEIGHT` | `0.4` | Вес аудио |
| `WHISPER_MODEL` | `base` | Модель распознавания речи |
| `SUBTITLE_COLORS` | `4 цвета` | Палитра субтитров |

---

## 🗺️ Планы развития

- [ ] **Word-level субтитры из faster-whisper** — посекундная синхронизация
- [ ] **ASS-субтитры** — для сложных анимированных эффектов
- [ ] **Telegram-бот** — отправляешь фильм, получаешь шортсы
- [ ] **CUDA** — GPU-ускорение whisper
- [ ] **Веб-интерфейс (Streamlit)** — для удобного просмотра результатов

---

<div align="center">

**Made with ❤️ by [Rail-Akhm](https://github.com/Rail-Akhm)**

</div>