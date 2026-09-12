# MKV to HLS Converter **"Segmint"**  

[🇺🇦 Українська](#українська) | [🇷🇺 Русский](#русский) | [🇬🇧 English](#english)  

---

## Українська  

**Segmint** — це Python-скрипт, який автоматизує  
конвертацію відеофайлів `.mkv` у формат **HLS (HTTP Live Streaming)** із сегментами fMP4 (`.m4s`)  
із підтримкою кількох роздільностей, аудіодоріжок та субтитрів.

### Основні можливості:

- 🎥 Створення до чотирьох варіантів якості **1080p, 720p, 480p, 360p** зі збереженням пропорцій, округленням розмірів до парних чисел і без збільшення роздільності джерела. Базові бітрейти у `STANDARD_RESOLUTIONS` — **3,5 / 1,75 / 0,7 / 0,35 Мбіт/с**; цільовий бітрейт перераховується пропорційно кількості пікселів кожного варіанта.  
- 🔊 Перекодування всіх наявних **аудіодоріжок** у **AAC, 192 кбіт/с, стерео** із сортуванням за мовою та типом доріжки; перелік мов не обмежений.  
- 💬 Конвертація наявних текстових **субтитрів у WebVTT** із перевіркою часових міток і форматом `HH:MM:SS.mmm`. Графічні субтитри не підтримуються, OCR не виконується; стилі ASS/SSA можуть втрачатися.  
- 🧩 Генерація **`master.m3u8`** із кількома мовами та варіантами якості лише після успішної обробки й валідації: перевіряються файли, тривалість, часові мітки та вибіркове декодування сегментів.  
- ⚙️ Послідовна обробка відеоваріантів, потім аудіодоріжок і субтитрів. Відео H.264 через **NVIDIA NVENC**, **Apple VideoToolbox** або **CPU/libx264 slow**; HLS версії **6** для відео, аудіо та master, версії **3** для субтитрів. Цільова тривалість відео- й аудіосегментів — **2 с**.  
- 🧹 Автоматичне видалення вихідних `.mkv`-файлів лише після успішної обробки та створення master; у разі помилки джерело зберігається.

### Використання:

1. Поклади повністю скопійовані `.mkv`-файли у папку зі скриптом і відкрий термінал у цій папці: обробляється поточна робоча папка без підпапок.  
2. Встанови залежності, зазначені нижче, і запусти скрипт:
   ```bash
   py main.py
   ```
   Без аргументів використовується `auto`: VideoToolbox на macOS, NVENC на інших системах, із переходом на CPU за недоступності або помилки апаратного кодування. Для явного вибору додай `libx264`, `h264_nvenc` або `h264_videotoolbox`, наприклад `py main.py libx264`; автоматичний перехід на інший кодер тоді вимкнений. Якщо команда `py` недоступна, використовуй `python3`.
3. Отримай готову структуру HLS для вебплеєра в папці з назвою вихідного файлу без `.mkv`.

---

## Русский  

**Segmint** — это Python-скрипт, который автоматизирует  
конвертацию видеофайлов `.mkv` в формат **HLS (HTTP Live Streaming)** с сегментами fMP4 (`.m4s`)  
с поддержкой нескольких разрешений, аудиодорожек и субтитров.

### Основные возможности:

- 🎥 Создание до четырёх вариантов качества **1080p, 720p, 480p, 360p** с сохранением пропорций, округлением размеров до чётных чисел и без увеличения разрешения источника. Базовые битрейты в `STANDARD_RESOLUTIONS` — **3,5 / 1,75 / 0,7 / 0,35 Мбит/с**; целевой битрейт пересчитывается пропорционально количеству пикселей каждого варианта.  
- 🔊 Перекодирование всех имеющихся **аудиодорожек** в **AAC, 192 кбит/с, стерео** с сортировкой по языку и типу дорожки; список языков не ограничен.  
- 💬 Конвертация имеющихся текстовых **субтитров в WebVTT** с проверкой временных меток и форматом `HH:MM:SS.mmm`. Графические субтитры не поддерживаются, OCR не выполняется; стили ASS/SSA могут теряться.  
- 🧩 Генерация **`master.m3u8`** с несколькими языками и вариантами качества только после успешной обработки и валидации: проверяются файлы, длительность, временные метки и выборочное декодирование сегментов.  
- ⚙️ Последовательная обработка видеовариантов, затем аудиодорожек и субтитров. Видео H.264 через **NVIDIA NVENC**, **Apple VideoToolbox** или **CPU/libx264 slow**; HLS версии **6** для видео, аудио и master, версии **3** для субтитров. Целевая длительность видео- и аудиосегментов — **2 с**.  
- 🧹 Автоматическое удаление исходных `.mkv`-файлов только после успешной обработки и создания master; при ошибке источник сохраняется.

### Использование:

1. Помести полностью скопированные `.mkv`-файлы в папку со скриптом и открой терминал в этой папке: обрабатывается текущая рабочая папка без подпапок.  
2. Установи зависимости, указанные ниже, и запусти скрипт:
   ```bash
   py main.py
   ```
   Без аргументов используется `auto`: VideoToolbox на macOS, NVENC на остальных системах, с переходом на CPU при недоступности или ошибке аппаратного кодирования. Для явного выбора добавь `libx264`, `h264_nvenc` или `h264_videotoolbox`, например `py main.py libx264`; автоматический переход на другой кодировщик тогда отключён. Если команда `py` недоступна, используй `python3`.
3. Получи готовую HLS-структуру для веб-плеера в папке с именем исходного файла без `.mkv`.

---

## English  

**Segmint** is a Python script that automates  
the conversion of `.mkv` video files into **HLS (HTTP Live Streaming)** format with fMP4 (`.m4s`) segments,  
supporting multiple resolutions, audio tracks, and subtitles.

### Key features:

- 🎥 Generates up to four quality variants: **1080p, 720p, 480p, 360p**, preserving aspect ratio with even-dimension rounding and no upscaling. Base bitrates in `STANDARD_RESOLUTIONS` are **3.5 / 1.75 / 0.7 / 0.35 Mbps**; each variant's target bitrate is adjusted proportionally to its pixel count.  
- 🔊 Transcodes all available **audio tracks** to **AAC, 192 kbps, stereo**, sorted by language and track type; languages are not restricted to a fixed list.  
- 💬 Converts existing text **subtitles to WebVTT**, validating timestamps and normalizing them to `HH:MM:SS.mmm`. Bitmap subtitles are unsupported, no OCR is performed, and ASS/SSA styling may be lost.  
- 🧩 Creates **`master.m3u8`** with multiple languages and quality levels only after successful processing and validation of output files, durations, timestamps, and sampled segment decoding.  
- ⚙️ Processes video variants sequentially, followed by audio tracks and subtitles. H.264 video encoding via **NVIDIA NVENC**, **Apple VideoToolbox**, or **CPU/libx264 slow**; HLS version **6** for video, audio, and master playlists, version **3** for subtitles. Video and audio segments have a target duration of **2 seconds**.  
- 🧹 Removes source `.mkv` files only after successful processing and master creation; sources are retained on failure.

### Usage:

1. Place fully copied `.mkv` files in the script directory and open a terminal there: the script processes the current working directory without scanning subdirectories.  
2. Install the dependencies listed below and run the script:
   ```bash
   py main.py
   ```
   The default is `auto`: VideoToolbox on macOS or NVENC on other systems, with CPU fallback when hardware encoding is unavailable or fails. To select an encoder explicitly, append `libx264`, `h264_nvenc`, or `h264_videotoolbox`, for example `py main.py libx264`; automatic encoder fallback is then disabled. Use `python3` if `py` is unavailable.
3. The output folder, named after the source file without `.mkv`, will contain the HLS structure for web playback.

---

⚡ **Project version:** v1.1.0  
📦 **Dependencies:** Python, `colorama` (`python3 -m pip install -r requirements.txt`); separately installed `ffmpeg` and `ffprobe` available in `PATH`. Hardware encoding requires compatible hardware, drivers, and an FFmpeg build with the selected encoder.
