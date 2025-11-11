# MKV to HLS Converter **"Segmint"**  

[🇺🇦 Українська](#українська) | [🇷🇺 Русский](#русский) | [🇬🇧 English](#english)  

---

## Українська  

**Segmint** — це Python-скрипт, який автоматизує  
конвертацію відеофайлів `.mkv` у формат **HLS (HTTP Live Streaming)** у контейнерах `.m4s`  
із підтримкою кількох роздільностей, аудіодоріжок та субтитрів.

### Основні можливості:

- 🎥 Автоматичне створення HLS-потоків для роздільностей **1080p, 720p, 480p, 360p**.  
- 🔊 Витягування **аудіодоріжок** українською, російською, англійською, казахською та китайською мовами (можна змінювати за потреби).  
- 💬 Автоматичне створення **субтитрів (WebVTT)** українською, російською, англійською, казахською та китайською мовами (можна змінювати за потреби).  
- 🧩 Генерація **`master.m3u8`** із підтримкою кількох мов і варіантів якості.  
- ⚙️ Оптимізація HLS до версії 6 та підтримка кодування через **CUDA (GPU)** або **CPU**.  
- 🧹 Автоматичне видалення вихідних `.mkv`-файлів після успішної обробки.

### Використання:

1. Поклади `.mkv`-файли у папку зі скриптом.  
2. Запусти скрипт:
   ```bash
   py main.py
   ```
3. Отримай готову структуру HLS для вебплеєра.

---

## Русский  

**Segmint** — это Python-скрипт, который автоматизирует  
конвертацию видеофайлов `.mkv` в формат **HLS (HTTP Live Streaming)** в контейнерах `.m4s`  
с поддержкой нескольких разрешений, аудиодорожек и субтитров.

### Основные возможности:

- 🎥 Автоматическое создание HLS-потоков для разрешений **1080p, 720p, 480p, 360p**.  
- 🔊 Извлечение **аудиодорожек** на украинском, русском, английском, казахском и китайском языках (можно изменить при необходимости).  
- 💬 Автоматическое создание **субтитров (WebVTT)** на украинском, русском, английском, казахском и китайском языках (можно изменить при необходимости).  
- 🧩 Генерация **`master.m3u8`** с поддержкой нескольких языков и вариантов качества.  
- ⚙️ Оптимизация HLS до версии 6 и поддержка кодирования через **CUDA (GPU)** или **CPU**.  
- 🧹 Автоматическое удаление исходных `.mkv`-файлов после успешной обработки.

### Использование:

1. Помести `.mkv`-файлы в папку со скриптом.  
2. Запусти скрипт:
   ```bash
   py main.py
   ```
3. Получи готовую HLS-структуру для веб-плеера.

---

## English  

**Segmint** is a Python script that automates  
the conversion of `.mkv` video files into **HLS (HTTP Live Streaming)** format in `.m4s` containers,  
supporting multiple resolutions, audio tracks, and subtitles.

### Key features:

- 🎥 Automatically generates HLS streams for **1080p, 720p, 480p, 360p** resolutions.  
- 🔊 Extracts **audio tracks** in Ukrainian, Russian, English, Kazakh, and Chinese (customizable).  
- 💬 Automatically generates **subtitles (WebVTT)** in Ukrainian, Russian, English, Kazakh, and Chinese (customizable).  
- 🧩 Creates a **`master.m3u8`** playlist supporting multiple languages and quality levels.  
- ⚙️ Optimized for HLS version 6 with **CUDA (GPU)** or **CPU** encoding support.  
- 🧹 Automatically removes source `.mkv` files after successful processing.

### Usage:

1. Place your `.mkv` files in the same directory as the script.  
2. Run the script:
   ```bash
   py main.py
   ```
3. The output folder will contain a complete HLS structure ready for web playback.

---

⚡ **Project version:** v1.0.0  
📦 **Dependencies:** `ffmpeg`, `python-ffmpeg-video-streaming`, `colorama`, `webvtt-py`
