import os
import webvtt
import subprocess
import json
import datetime
from colorama import Fore, Style
from ffmpeg_streaming import Formats, Representation, Size, Bitrate, input
import re
from datetime import timedelta
import platform

def print_colored(text, color=Fore.WHITE):
    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"{color}{current_time} - {text}{Style.RESET_ALL}")

def remove_file(file_path):
    try:
        os.remove(file_path)
        return True
    except Exception:
        return False

def correct_hls_version(m3u8_path, target_version):
    try:
        if not os.path.exists(m3u8_path):
            return False
            
        with open(m3u8_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        if '#EXT-X-VERSION:' in content:
            new_content = re.sub(r'#EXT-X-VERSION:\d+', f'#EXT-X-VERSION:{target_version}', content, count=1)
        else:
            new_content = content.replace('#EXTM3U', f'#EXTM3U\n#EXT-X-VERSION:{target_version}', 1)
            
        with open(m3u8_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        return True
    except Exception as e:
        return False

def segment_webvtt(vtt_input_path, output_folder, lang, segment_duration=2):
    os.makedirs(output_folder, exist_ok=True)
    vtt = webvtt.read(vtt_input_path)

    segments = []
    segment_index = 0
    current_segment = []
    current_start = 0.0

    def time_to_seconds(t):
        h, m, s = t.split(':')
        s, ms = s.split('.')
        return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000

    def shift_time(t, offset=0):
        h, m, s = t.split(':')
        s, ms = s.split('.')
        total = int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000 + offset
        total = max(total, 0)
        new_h = int(total // 3600)
        new_m = int((total % 3600) // 60)
        new_s = int(total % 60)
        new_ms = int(round((total - int(total)) * 1000))
        return f"{new_h:02}:{new_m:02}:{new_s:02}.{new_ms:03}"

    from webvtt.structures import Caption

    for caption in vtt:
        shifted_start = shift_time(caption.start, 0)
        shifted_end = shift_time(caption.end, 0)
        start_sec = time_to_seconds(shifted_start)

        new_caption = Caption(
            start=shifted_start,
            end=shifted_end,
            text=caption.text
        )

        if start_sec >= current_start + segment_duration:
            segment_filename = f"{segment_index:04}.vtt"
            with open(os.path.join(output_folder, segment_filename), 'w', encoding='utf-8') as seg_file:
                seg_file.write("WEBVTT\n\n")
                for cap in current_segment:
                    seg_file.write(f"{cap.start} --> {cap.end}\n{cap.text}\n\n")

            segments.append(segment_filename)
            segment_index += 1
            current_start += segment_duration
            current_segment = []

        current_segment.append(new_caption)

    if current_segment:
        segment_filename = f"{segment_index:04}.vtt"
        with open(os.path.join(output_folder, segment_filename), 'w', encoding='utf-8') as seg_file:
            seg_file.write("WEBVTT\n\n")
            for cap in current_segment:
                seg_file.write(f"{cap.start} --> {cap.end}\n{cap.text}\n\n")
        segments.append(segment_filename)

    m3u8_path = os.path.join(output_folder, f"subtitles_{lang}.m3u8")
    with open(m3u8_path, 'w', encoding='utf-8') as m3u:
        m3u.write("#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:2\n#EXT-X-MEDIA-SEQUENCE:0\n")
        for seg in segments:
            m3u.write("#EXTINF:2.0,\n")
            m3u.write(f"{seg}\n")
        m3u.write("#EXT-X-ENDLIST\n")
        
    if os.path.exists(vtt_input_path):
        os.remove(vtt_input_path)

current_dir = "./"
mkv_files = [file for file in os.listdir(current_dir) if file.endswith(".mkv")]

for mkv_file in mkv_files:
    base_name = os.path.splitext(mkv_file)[0]
    print_colored(f"Processing file: {mkv_file}...", Fore.YELLOW)

    if not os.path.exists(base_name):
        os.mkdir(base_name)

    os.chdir(base_name)

    ffprobe_output = subprocess.check_output(
        f"ffprobe -v quiet -print_format json -show_streams ../{mkv_file}", shell=True
    )
    streams_info = json.loads(ffprobe_output)

    src_w, src_h = None, None
    for _s in streams_info.get("streams", []):
        if _s.get("codec_type") == "video":
            src_w = int(_s.get("width", 0) or 0)
            src_h = int(_s.get("height", 0) or 0)
            break

    if src_w and src_h:
        ratio = src_w / src_h
    else:
        ratio = 1.77

    if ratio > 2.1:
        resolutions = {
            "1080p": ("1920:804", 4100000),
            "720p":  ("1280:536", 2250000),
            "480p":  ("854:358", 1100000),
            "360p":  ("640:268", 600000)
        }
    elif ratio > 1.8:
        resolutions = {
            "1080p": ("1920:1038", 5300000),
            "720p":  ("1280:692", 2900000),
            "480p":  ("854:462", 1450000),
            "360p":  ("640:346", 750000)
        }
    else:
        resolutions = {
            "1080p": ("1920:1080", 5500000),
            "720p": ("1280:720", 3000000),
            "480p": ("854:480", 1500000),
            "360p": ("640:360", 800000)
        }

    for res_label, (scale, bitrate) in resolutions.items():
        w_target, h_target = map(int, scale.split(":"))
        if src_w and src_h and (w_target > src_w or h_target > src_h):
            print_colored(f"Skipping {res_label}: resolution higher than source.", Fore.BLUE)
            continue

        os.makedirs(res_label, exist_ok=True)
        output_path = f"{res_label}/{res_label}.m3u8"
        
        is_mac = platform.system() == "Darwin"

        if is_mac:
            ffmpeg_cmd_hardware = (
                f"ffmpeg -hide_banner -loglevel error -y -i ../{mkv_file} "
                f"-c:v h264_videotoolbox "
                f"-profile:v main "
                f"-b:v {bitrate} -maxrate {int(bitrate * 1.1)} -bufsize {int(bitrate * 2)} "
                f"-vf scale={scale} "
                f"-g 48 -force_key_frames \"expr:gte(t,n_forced*2)\" "
                f"-an -sn "
                f"-hls_time 2 -hls_playlist_type vod -hls_flags independent_segments "
                f"-hls_segment_type fmp4 "
                f"-hls_segment_filename {res_label}/%04d.m4s "
                f"{res_label}/{res_label}.m3u8"
            )
            success_log_msg = f"VideoToolbox encoding successful ({res_label})."
        else:
            ffmpeg_cmd_hardware = (
                f"ffmpeg -hide_banner -loglevel error -y -i ../{mkv_file} "
                f"-c:v h264_nvenc -gpu 0 "
                f"-profile:v main -level 4.1 "
                f"-b:v {bitrate} -maxrate {int(bitrate * 1.1)} -bufsize {int(bitrate * 2)} "
                f"-vf scale={scale} "
                f"-g 48 -force_key_frames \"expr:gte(t,n_forced*2)\" "
                f"-an -sn "
                f"-hls_time 2 -hls_playlist_type vod -hls_flags independent_segments "
                f"-hls_segment_type fmp4 "
                f"-hls_segment_filename {res_label}/%04d.m4s "
                f"{res_label}/{res_label}.m3u8"
            )
            success_log_msg = f"CUDA encoding successful ({res_label})."

        ffmpeg_cmd_cpu = (            
            f"ffmpeg -hide_banner -loglevel error -y -i ../{mkv_file} "
            f"-c:v libx264 -preset slow -profile:v main -level 4.1 "
            f"-b:v {bitrate} -maxrate {int(bitrate * 1.1)} -bufsize {int(bitrate * 2)} "
            f"-vf scale={scale} "
            f"-g 48 -keyint_min 48 -sc_threshold 0 -force_key_frames \"expr:gte(t,n_forced*2)\" "
            f"-an -sn "
            f"-hls_time 2 -hls_playlist_type vod -hls_flags independent_segments "
            f"-hls_segment_type fmp4 "
            f"-hls_segment_filename {res_label}/%04d.m4s "
            f"{res_label}/{res_label}.m3u8"
        )

        result = subprocess.run(ffmpeg_cmd_hardware, shell=True, stderr=subprocess.DEVNULL)
        if result.returncode != 0:
            subprocess.run(ffmpeg_cmd_cpu, shell=True)
            print_colored(f"CPU encoding successful ({res_label}).", Fore.CYAN)
        else:
            print_colored(success_log_msg, Fore.CYAN)

        correct_hls_version(output_path, 6)

    lang_aliases = {
        "rus": "ru", "ukr": "uk", "eng": "en", 
        "fra": "fr", "kaz": "kk", "zho": "zh", "chi": "zh", "und": "und"
    }

    lang_names_capitalized = {
        "uk": "Ukrainian", "ru": "Russian", "en": "English", 
        "fr": "French", "kk": "Kazakh", "zh": "Chinese", "und": "Undetermined"
    }

    audio_streams = []
    subtitle_streams = []

    for stream in streams_info.get("streams", []):
        if stream.get("codec_type") == "audio":
            audio_streams.append(stream)
        elif stream.get("codec_type") == "subtitle":
            subtitle_streams.append(stream)

    def get_audio_rank(st):
        title = st.get("tags", {}).get("title", "").lower()
        if "original" in title or "оригинал" in title: return 1
        if "official dub" in title or "официальный дубляж" in title or "дубляж" in title or "dub" in title: return 2
        if "unofficial dub" in title or "неофициальный дубляж" in title: return 3
        if "multi" in title or "многоголосый" in title: return 4
        if "dual" in title or "двухголосый" in title: return 5
        if "single" in title or "одноголосый" in title or "voiceover" in title: return 6
        return 10

    def get_subtitle_rank(st):
        title = st.get("tags", {}).get("title", "").lower()
        if "sdh" in title: return 1
        if "full" in title or "полн" in title or "повн" in title: return 2
        if "forced" in title or "форсир" in title or "форс" in title: return 3
        return 10

    LANG_ORDER = ['uk', 'ru', 'en', 'fr', 'kk', 'zh']
    def get_lang_priority(st):
        l = st.get("tags", {}).get("language", "und")
        l = lang_aliases.get(l, l)
        return LANG_ORDER.index(l) if l in LANG_ORDER else 999

    audio_streams.sort(key=lambda s: (get_lang_priority(s), get_audio_rank(s)))
    subtitle_streams.sort(key=lambda s: (get_lang_priority(s), get_subtitle_rank(s)))

    audio_tracks_processed = []
    subtitle_tracks_processed = []

    for internal_idx, stream in enumerate(audio_streams, start=1):
        lang = stream.get("tags", {}).get("language", "und")
        lang = lang_aliases.get(lang, lang)
        
        mkv_title = stream.get("tags", {}).get("title", "").strip()
        lang_prefix = lang_names_capitalized.get(lang, lang.capitalize())
        
        if mkv_title:
            final_name = f"{lang_prefix} {mkv_title}"
        else:
            final_name = f"{lang_prefix} Track {internal_idx}"
        
        folder = f"audio_{lang}_{internal_idx}"
        playlist_name = f"audio_{lang}_{internal_idx}.m3u8"
        playlist_path = os.path.join(folder, playlist_name)
        
        os.makedirs(folder, exist_ok=True)
        audio_cmd = (
            f"ffmpeg -hide_banner -loglevel error -y -i ../{mkv_file} "
            f"-map 0:{stream['index']} -map -0:v:m:attached_pic "
            f"-c:a aac -b:a 192k -ac 2 "
            f"-avoid_negative_ts make_zero -flush_packets 1 -fflags +genpts "
            f"-hls_time 2 -hls_playlist_type vod "
            f"-hls_flags independent_segments+split_by_time "
            f"-hls_segment_type fmp4 "
            f"-hls_fmp4_init_filename init.mp4 "
            f"-hls_segment_filename {folder}/%04d.m4s "
            f"{playlist_path}"
        )

        subprocess.run(audio_cmd, shell=True, stderr=subprocess.DEVNULL)
        correct_hls_version(playlist_path, 6)
        
        audio_tracks_processed.append({
            "lang": lang,
            "name": final_name,
            "playlist_uri": f"{folder}/{playlist_name}"
        })
        print_colored(f"Audio track '{final_name}' processed (Folder: {folder}).", Fore.GREEN)


    for internal_idx, stream in enumerate(subtitle_streams, start=1):
        lang = stream.get("tags", {}).get("language", "und")
        lang = lang_aliases.get(lang, lang)
        
        mkv_title = stream.get("tags", {}).get("title", "").strip()
        lang_prefix = lang_names_capitalized.get(lang, lang.capitalize())
        
        if mkv_title:
            final_name = f"{lang_prefix} {mkv_title}"
        else:
            final_name = f"{lang_prefix} Track {internal_idx}"
        
        folder = f"subtitles_{lang}_{internal_idx}"
        os.makedirs(folder, exist_ok=True)
        
        vtt_filename = f"subtitles_{lang}_{internal_idx}.vtt"
        vtt_path = os.path.join(folder, vtt_filename)
        playlist_name = f"subtitles_{lang}_{internal_idx}.m3u8"
        playlist_path = os.path.join(folder, playlist_name)

        def parse_timestamp(ts):
            parts = ts.split(':')
            if len(parts) == 2:
                m, rest = parts
                s, ms = rest.split('.')
                return timedelta(minutes=int(m), seconds=int(s), milliseconds=int(ms))
            elif len(parts) == 3:
                h, m, rest = parts
                s, ms = rest.split('.')
                return timedelta(hours=int(h), minutes=int(m), seconds=int(s), milliseconds=int(ms))
            else:
                raise ValueError(f"Invalid time format: {ts}")

        def format_timestamp(td):
            total_seconds = td.total_seconds()
            hours = int(total_seconds // 3600)
            minutes = int((total_seconds % 3600) // 60)
            seconds = int(total_seconds % 60)
            ms = int(td.microseconds / 1000)
            return f"{hours:02}:{minutes:02}:{seconds:02}.{ms:03}"

        def shift_subtitles(input_file, output_file, shift=timedelta(seconds=0)):
            with open(input_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            pattern = re.compile(
                r"(\d{2}:\d{2}:\d{2}\.\d{3}|\d{2}:\d{2}\.\d{3}) --> (\d{2}:\d{2}:\d{2}\.\d{3}|\d{2}:\d{2}\.\d{3})"
            )

            with open(output_file, 'w', encoding='utf-8') as f_out:
                for line in lines:
                    match = pattern.match(line)
                    if match:
                        start = parse_timestamp(match.group(1)) + shift
                        end = parse_timestamp(match.group(2)) + shift
                        if start.total_seconds() < 0: start = timedelta(seconds=0)
                        if end.total_seconds() < 0: end = timedelta(seconds=0)
                        f_out.write(f"{format_timestamp(start)} --> {format_timestamp(end)}\n")
                    else:
                        f_out.write(line)

        temp_vtt_path = os.path.join(folder, f"temp_{lang}_{internal_idx}.vtt")
        
        subtitle_cmd = (
            f"ffmpeg -hide_banner -loglevel error -y -i ../{mkv_file} "
            f"-map 0:{stream['index']} -map -0:v:m:attached_pic "
            f"-f webvtt {temp_vtt_path}"
        )
        subprocess.run(subtitle_cmd, shell=True)

        if os.path.exists(temp_vtt_path):
            shift_subtitles(temp_vtt_path, vtt_path)
            os.remove(temp_vtt_path)

            with open(playlist_path, "w", encoding="utf-8") as m3u:
                m3u.write("#EXTM3U\n")
                m3u.write("#EXT-X-VERSION:3\n")
                m3u.write("#EXT-X-TARGETDURATION:10000\n")
                m3u.write("#EXT-X-MEDIA-SEQUENCE:0\n")
                m3u.write(f"#EXTINF:10000.0,\n")
                m3u.write(f"{vtt_filename}\n")
                m3u.write("#EXT-X-ENDLIST\n")

            subtitle_tracks_processed.append({
                "lang": lang,
                "name": final_name,
                "playlist_uri": f"{folder}/{playlist_name}"
            })
            print_colored(f"Subtitles '{final_name}' processed (Folder: {folder}).", Fore.BLUE)
        else:
            print_colored(f"Skipping subtitle stream {stream['index']} (unsupported/empty format).", Fore.RED)

    available_renditions = []
    for res_label, (scale, bitrate) in resolutions.items():
        w, h = map(int, scale.split(":"))
        if src_w and src_h and (w > src_w or h > src_h):
            continue
        if os.path.isfile(os.path.join(res_label, f"{res_label}.m3u8")):
            available_renditions.append((res_label, w, h, bitrate))

    with open("master.m3u8", "w", encoding="utf-8") as master:
        master.write("#EXTM3U\n#EXT-X-VERSION:6\n#EXT-X-INDEPENDENT-SEGMENTS\n\n")
        master.write("# Video streams\n")

        for res_label, w, h, bitrate in available_renditions:
            master.write(
                f"#EXT-X-STREAM-INF:BANDWIDTH={bitrate},AVERAGE-BANDWIDTH={int(bitrate*0.9)},"
                f"RESOLUTION={w}x{h},FRAME-RATE=23.976,AUDIO=\"audio\""
                f"{',SUBTITLES=\"subs\"' if subtitle_tracks_processed else ',CLOSED-CAPTIONS=NONE'}\n"
                f"{res_label}/{res_label}.m3u8\n"
            )

        master.write("\n# Audio streams\n")
        for i, track in enumerate(audio_tracks_processed):
            master.write(
                f"#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID=\"audio\",NAME=\"{track['name']}\",LANGUAGE=\"{track['lang']}\","
                f"AUTOSELECT={'YES' if i == 0 else 'NO'},DEFAULT={'YES' if i == 0 else 'NO'},"
                f"URI=\"{track['playlist_uri']}\"\n"
            )

        if subtitle_tracks_processed:
            master.write("\n# Subtitle streams\n")
            for track in subtitle_tracks_processed:
                master.write(
                    f"#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID=\"subs\",NAME=\"{track['name']}\",LANGUAGE=\"{track['lang']}\","
                    f"DEFAULT=NO,AUTOSELECT=NO,FORCED=NO,"
                    f"URI=\"{track['playlist_uri']}\"\n"
                )

    print_colored("File master.m3u8 successfully created.", Fore.CYAN)

    os.chdir("..")
    os.remove(mkv_file)
    print_colored(f"Source file {mkv_file} deleted.", Fore.RED)

print_colored("All MKV files processed.", Fore.YELLOW)
