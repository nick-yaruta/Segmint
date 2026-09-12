import os
import subprocess
import json
import datetime
from colorama import Fore, Style
import re
import platform
import argparse
import runpy
import tempfile
import stat
from contextlib import contextmanager
from types import MappingProxyType
from statistics import median
from bisect import bisect_left
from array import array
import unicodedata
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING
from urllib.parse import quote, unquote


# utilities

class ProcessingError(RuntimeError):
    pass


def print_colored(text, color=Fore.LIGHTWHITE_EX):
    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"{Style.NORMAL}{color}{current_time} - {text}{Style.RESET_ALL}")


@contextmanager
def atomic_text_writer(path):
    path = os.path.abspath(path)
    try:
        mode = stat.S_IMODE(os.stat(path).st_mode)
    except FileNotFoundError:
        mode = None
    with tempfile.TemporaryDirectory(prefix=".segmint-", dir=os.path.dirname(path)) as temp_dir:
        temporary_path = os.path.join(temp_dir, "playlist.m3u8")
        with open(temporary_path, "w", encoding="utf-8") as output:
            yield output
        if mode is not None:
            os.chmod(temporary_path, mode)
        os.replace(temporary_path, path)


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
            
        with atomic_text_writer(m3u8_path) as f:
            f.write(new_content)
        return True
    except Exception:
        return False


def run_command(args, timeout=None):
    try:
        result = subprocess.run(args, shell=False, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True,
                                encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        stderr = exc.stderr or ""
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        result = subprocess.CompletedProcess(args, 124, "", f"{stderr}\nHardware probe timed out.")
    except OSError as exc:
        raise ProcessingError(f"Cannot run {args[0]}: {exc}") from exc
    if result.stderr.strip():
        print_colored(result.stderr.rstrip(), Fore.LIGHTRED_EX if result.returncode else Fore.LIGHTYELLOW_EX)
    return result


def compact_fields(line):
    return dict(part.split("=", 1) for part in line.split("|") if "=" in part)


def language_path_tag(language):
    if len(language) <= 128 and re.fullmatch(
            r"(?:[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*|[ixIX](?:-[A-Za-z0-9]{1,8})+)", language):
        return language
    return "und"


# validator

VTT_TIMING = re.compile(
    r"(?P<prefix>[ \t]*)(?P<start>(?:\d{2,}:)?\d{2}:\d{2}\.\d{3})"
    r"[ \t]+-->[ \t]+(?P<end>(?:\d{2,}:)?\d{2}:\d{2}\.\d{3})"
    r"(?P<settings>(?:[ \t]+[^\r\n]*)?)(?P<ending>\r?\n)?$")


def probe_source(path):
    result = run_command(["ffprobe", "-v", "error", "-print_format", "json",
                          "-show_streams", "-show_format", path])
    if result.returncode or result.stderr.strip():
        raise ProcessingError("Source probing failed.")
    return json.loads(result.stdout)


def summarize_packets(samples, time_base):
    samples.sort(key=lambda sample: sample[0])
    starts = [sample[0] for sample in samples]
    steps = [right - left for left, right in zip(starts, starts[1:]) if right > left]
    durations = [sample[1] for sample in samples if sample[1] > 0]
    cadence = median(durations or steps) if durations or steps else time_base
    intervals = []
    for index, (pts, duration, flags) in enumerate(samples):
        if duration <= 0:
            duration = starts[index + 1] - pts if index + 1 < len(starts) else cadence
        intervals.append((pts, pts + duration))
    start = intervals[0][0]
    end = start
    covered = Decimal(0)
    gaps = []
    for left, right in intervals:
        if left > end:
            gaps.append((end - start, left - start))
        covered += max(Decimal(0), right - max(left, end))
        end = max(end, right)
    return {"start": start, "end": end, "count": len(samples),
            "covered": covered, "gaps": gaps, "cadence": cadence,
            "min_step": min(steps) if steps else cadence,
            "max_duration": max(durations) if durations else cadence,
            "time_base": time_base, "duplicates": len(starts) != len(set(starts)),
            "last_pts": starts[-1], "keyframes": [pts for pts, _, flags in samples if "K" in flags]}


def probe_timeline(path, selector=None, wanted_indexes=None):
    args = ["ffprobe", "-v", "error"]
    if selector:
        args += ["-select_streams", selector]
    args += ["-show_packets", "-show_streams", "-show_entries",
             "packet=stream_index,pts,pts_time,dts,dts_time,duration,duration_time,flags:"
             "stream=index,time_base:stream_tags=:stream_disposition=",
             "-of", "compact=p=0", path]
    packets = {}
    time_bases = {}
    with tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as diagnostics:
        try:
            proc = subprocess.Popen(args, shell=False, stdout=subprocess.PIPE,
                                    stderr=diagnostics, text=True, encoding="utf-8",
                                    errors="replace")
        except OSError as exc:
            raise ProcessingError(f"Cannot run ffprobe: {exc}") from exc
        try:
            for line in proc.stdout:
                fields = compact_fields(line.strip())
                if "time_base" in fields and "index" in fields:
                    numerator, denominator = fields["time_base"].split("/")
                    time_base = Decimal(numerator) / Decimal(denominator)
                    if not time_base.is_finite() or time_base <= 0:
                        raise ProcessingError(f"Invalid time base in {path}.")
                    time_bases[int(fields["index"])] = time_base
                if "stream_index" not in fields:
                    continue
                index = int(fields["stream_index"])
                if wanted_indexes is not None and index not in wanted_indexes:
                    continue
                if fields.get("pts", "N/A") == "N/A":
                    raise ProcessingError(f"Missing packet timestamps in {path}.")
                pts = int(fields["pts"])
                duration = fields.get("duration", "0")
                duration = int(duration) if duration != "N/A" else 0
                dts = fields.get("dts", "N/A")
                dts = int(dts) if dts != "N/A" else None
                if duration < 0 or "C" in fields.get("flags", ""):
                    raise ProcessingError(f"Invalid/corrupt packet in {path}.")
                if index not in packets:
                    packets[index] = {"pts": array("q"), "durations": array("q"), "keys": bytearray(),
                                      "last_dts": None, "dts_reversed": False}
                info = packets[index]
                if dts is not None and info["last_dts"] is not None and dts <= info["last_dts"]:
                    info["dts_reversed"] = True
                if dts is not None:
                    info["last_dts"] = dts
                info["pts"].append(pts)
                info["durations"].append(duration)
                info["keys"].append("K" in fields.get("flags", ""))
            returncode = proc.wait()
        finally:
            proc.stdout.close()
            if proc.poll() is None:
                proc.kill()
                proc.wait()
        diagnostics.seek(0)
        errors = diagnostics.read().strip()
    if errors:
        print_colored(errors, Fore.LIGHTRED_EX)
    if returncode or errors:
        raise ProcessingError(f"Packet analysis failed: {path}")
    timelines = {}
    for index, info in packets.items():
        if index not in time_bases:
            raise ProcessingError(f"Missing time base for stream {index}: {path}")
        time_base = time_bases[index]
        samples = [(pts * time_base, duration * time_base, "K" if key else "")
                   for pts, duration, key in zip(info["pts"], info["durations"], info["keys"])]
        timelines[index] = summarize_packets(samples, time_base)
        timelines[index]["dts_reversed"] = info["dts_reversed"]
    return timelines


def file_signature(path):
    stat = os.stat(path)
    return (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_ino)


def output_snapshot(folder):
    return {os.path.abspath(entry.path): file_signature(entry.path)
            for entry in os.scandir(folder) if entry.is_file()}


def require_current_file(path, before):
    signature = file_signature(path)
    if signature[0] == 0 or before.get(os.path.abspath(path)) == signature:
        raise ProcessingError(f"Missing, empty or stale output: {path}")


def validate_packet_coverage(actual, expected, source_origin):
    if not actual or not expected:
        raise ProcessingError("No media packets available for coverage validation.")
    tolerance = 2 * (max(actual["cadence"], expected["cadence"])
                     + actual["time_base"] + expected["time_base"])
    actual_duration = actual["end"] - actual["start"]
    expected_duration = expected["end"] - expected["start"]
    if abs(actual_duration - expected_duration) > tolerance:
        raise ProcessingError(f"Duration mismatch: expected {expected_duration}s, got {actual_duration}s "
                              f"(frame/time-base tolerance {tolerance}s).")
    if expected["covered"] - actual["covered"] > tolerance:
        raise ProcessingError("Substantial packet coverage loss inside the presentation.")
    if actual["duplicates"] or actual["dts_reversed"]:
        raise ProcessingError("Duplicate PTS or non-increasing DTS in the output.")
    for left, right in actual["gaps"]:
        if right - left > tolerance and not any(
                left >= old_left - tolerance and right <= old_right + tolerance
                for old_left, old_right in expected["gaps"]):
            raise ProcessingError(f"New packet timeline gap: {left}s to {right}s.")
    offset = actual["start"] - (expected["start"] - source_origin)
    return offset, tolerance


def validate_rendition_alignment(current, reference):
    if reference is not None:
        tolerance = max(current["tolerance"], reference["tolerance"])
        if abs(current["offset"] - reference["offset"]) > tolerance:
            raise ProcessingError("Video renditions have inconsistent presentation offsets.")


def validate_decode_samples(path, media_type, durations, timeline, segments):
    selector = "v:0" if media_type == "video" else "a:0"
    starts = []
    position = timeline["start"]
    for duration in durations:
        starts.append(position)
        position += duration
    tail_start = (timeline["keyframes"][-1] if media_type == "video" and timeline["keyframes"]
                  else max(timeline["start"], timeline["last_pts"] - 8 * timeline["cadence"]))
    decoded = []
    with tempfile.TemporaryDirectory(prefix="segmint-validation-") as temp_dir:
        manifest = os.path.join(temp_dir, "fragments.txt")
        for offset in range(0, len(segments), 128):
            batch = segments[offset:offset + 128]
            init_path = batch[0][0]
            if any(init != init_path for init, _ in batch):
                raise ProcessingError(f"Changing initialization sections are not supported by this validator: {path}")
            with open(manifest, "w", encoding="utf-8") as listing:
                for resource in [init_path] + [segment for _, segment in batch]:
                    resource = "file:" + os.path.abspath(resource)
                    if "\n" in resource or "\r" in resource:
                        raise ProcessingError("A validation resource path contains a line break.")
                    listing.write("'" + resource.replace("'", "'\\''") + "'\n")
            intervals = [f"{start:f}%+#8" for start in starts[offset:offset + len(batch)]]
            if offset + len(batch) == len(segments):
                intervals.append(f"{tail_start:f}%{timeline['end'] + timeline['time_base']:f}")
            result = run_command(["ffprobe", "-v", "error", "-protocol_whitelist", "file,concatf",
                                  "-select_streams", selector, "-read_intervals", ",".join(intervals),
                                  "-show_frames", "-show_entries",
                                  "frame=best_effort_timestamp_time:frame_side_data=",
                                  "-of", "compact=p=0", "concatf:" + manifest])
            if result.returncode or result.stderr.strip():
                raise ProcessingError(f"Sample decoding failed: {path}")
            for line in result.stdout.splitlines():
                fields = compact_fields(line)
                value = fields.get("best_effort_timestamp_time")
                if value and value != "N/A":
                    pts = Decimal(value)
                    if not pts.is_finite():
                        raise ProcessingError(f"Invalid decoded sample timestamp: {path}")
                    decoded.append(pts)
    decoded.sort()
    rounding = timeline["time_base"] + Decimal("0.000001")
    if not decoded or not any(abs(pts - timeline["start"]) <= rounding for pts in decoded):
        raise ProcessingError(f"The beginning of the presentation could not be decoded: {path}")
    if not any(abs(pts - timeline["last_pts"]) <= rounding for pts in decoded):
        raise ProcessingError(f"The end of the presentation could not be decoded: {path}")
    for start, duration in zip(starts, durations):
        sample_index = bisect_left(decoded, start - rounding)
        if sample_index == len(decoded) or decoded[sample_index] >= start + duration + rounding:
            raise ProcessingError(f"No decoded sample for the segment at {start}s: {path}")


def validate_coverage(actual, expected, source_origin, tolerance):
    if not actual or not expected:
        raise ProcessingError("No media samples available for coverage validation.")
    for edge in ("start", "end"):
        wanted = expected[edge] - source_origin
        if abs(actual[edge] - wanted) > tolerance:
            raise ProcessingError(
                f"Time coverage mismatch ({edge}): expected {wanted}s, got {actual[edge]}s "
                f"(tolerance {tolerance}s). Timestamps have not been changed.")


def validate_hls_files(path, before):
    require_current_file(path, before)
    with open(path, encoding="utf-8") as playlist:
        lines = [line.strip() for line in playlist if line.strip()]
    if not lines or lines[0] != "#EXTM3U" or lines[-1] != "#EXT-X-ENDLIST":
        raise ProcessingError(f"Incomplete .hls playlist: {path}")
    durations = []
    pending = None
    target = None
    init_seen = False
    init_path = None
    segments = []
    folder = os.path.dirname(path)
    for line in lines[1:]:
        if line.startswith("#EXT-X-MAP:"):
            match = re.search(r'(?:^|,)URI="([^"]+)"', line.split(":", 1)[1])
            if not match:
                raise ProcessingError(f"Invalid init reference: {path}")
            init_path = os.path.join(folder, unquote(match.group(1)))
            require_current_file(init_path, before)
            init_seen = True
        elif line.startswith("#EXT-X-TARGETDURATION:"):
            target = Decimal(line.split(":", 1)[1])
        elif line.startswith("#EXTINF:"):
            if pending is not None:
                raise ProcessingError(f"Missing segment URI: {path}")
            pending = Decimal(line.split(":", 1)[1].split(",", 1)[0])
            if not pending.is_finite() or pending <= 0:
                raise ProcessingError(f"Invalid segment duration: {path}")
        elif not line.startswith("#"):
            if pending is None or not init_seen:
                raise ProcessingError(f"Missing duration/init: {path}")
            segment_path = os.path.join(folder, unquote(line))
            require_current_file(segment_path, before)
            segments.append((init_path, segment_path))
            durations.append(pending)
            pending = None
    if not durations or pending is not None or target is None or not target.is_finite() or target <= 0:
        raise ProcessingError(f"Invalid .hls playlist: {path}")
    if any(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP) > target for d in durations):
        raise ProcessingError(f"Segment exceeds target duration: {path}")
    return durations, segments


def validate_hls(path, before, expected, source_origin, media_type):
    durations, segments = validate_hls_files(path, before)
    timelines = probe_timeline(path, "v:0" if media_type == "video" else "a:0")
    if len(timelines) != 1:
        raise ProcessingError(f"Expected exactly one {media_type} stream: {path}")
    actual = next(iter(timelines.values()))
    offset, tolerance = validate_packet_coverage(actual, expected, source_origin)
    duration = sum(durations, Decimal(0))
    if abs(duration - (actual["end"] - actual["start"])) > tolerance:
        raise ProcessingError(f"Playlist duration does not match packet timeline: {path}")
    validate_decode_samples(path, media_type, durations, actual, segments)
    validation_name = os.path.basename(os.path.dirname(path))
    print_colored(f"Validated {validation_name}: offset {offset:+.3f}s, duration {duration:.3f}s.", Fore.LIGHTMAGENTA_EX)
    step = actual["min_step"]
    frame_rate = f"{Decimal(1) / step:.3f}" if step and media_type == "video" else None
    return {"duration": duration, "frame_rate": frame_rate, "offset": offset, "tolerance": tolerance}


def vtt_seconds(timestamp):
    parts = timestamp.split(":")
    hours, minutes, seconds = parts if len(parts) == 3 else ("0", *parts)
    if int(minutes) >= 60 or Decimal(seconds) >= 60:
        raise ProcessingError(f"Invalid WebVTT timestamp: {timestamp}")
    return Decimal(hours) * 3600 + Decimal(minutes) * 60 + Decimal(seconds)


def validate_vtt(path, expected, source_origin, presentation_duration):
    with open(path, encoding="utf-8-sig") as source:
        content = source.read()
    blocks = re.split(r"\n[ \t]*\n", content.strip())
    if not blocks[0] or not re.fullmatch(r"WEBVTT(?:[ \t].*)?", blocks[0].splitlines()[0]):
        raise ProcessingError(f"Invalid WebVTT header: {path}")
    cues = []
    for block in blocks[1:]:
        lines = block.splitlines()
        if re.match(r"NOTE(?:[ \t]|$)", lines[0]) or lines[0] in ("STYLE", "REGION"):
            continue
        timing_index = 0 if VTT_TIMING.fullmatch(lines[0]) else 1
        match = VTT_TIMING.fullmatch(lines[timing_index]) if len(lines) > timing_index else None
        if not match or len(lines) <= timing_index + 1:
            raise ProcessingError(f"Malformed WebVTT cue: {path}")
        start, end = vtt_seconds(match["start"]), vtt_seconds(match["end"])
        if end <= start or (cues and start < cues[-1][0]):
            raise ProcessingError(f"Invalid WebVTT cue interval: {path}")
        if end > presentation_duration + Decimal("0.010"):
            raise ProcessingError(f"WebVTT cue exceeds presentation duration: {path}")
        cues.append((start, end))
    if expected:
        actual = {"start": cues[0][0], "end": max(end for _, end in cues)} if cues else None
        validate_coverage(actual, expected, source_origin, Decimal("0.010"))
    elif cues:
        raise ProcessingError(f"Unexpected WebVTT cues: {path}")
    return len(cues)


# hardware

class HardwareBackend:
    def __init__(self, requested_encoder="auto"):
        self.requested_encoder = requested_encoder
        self.forced = requested_encoder != "auto"

        if requested_encoder == "auto":
            self.encoder = (
                "h264_videotoolbox"
                if platform.system() == "Darwin"
                else "h264_nvenc"
            )
        else:
            self.encoder = requested_encoder

        self.disabled_reason = None

        result = run_command(["ffmpeg", "-hide_banner", "-encoders"])
        if result.returncode:
            raise ProcessingError("Cannot query FFmpeg encoders.")

        if not re.search(r"\b" + re.escape(self.encoder) + r"\b", result.stdout):
            self.disabled_reason = (
                f"Encoder {self.encoder} is absent from this FFmpeg build."
            )

    def record_failure(self, result):
        permanent_errors = (
            "cannot load libcuda",
            "cannot load nvcuda",
            "cannot load libnvidia-encode",
            "cannot load nvencodeapi",
            "no nvenc capable devices found",
            "no cuda capable device is detected",
            "cuda_error_no_device",
            "driver does not support the required nvenc api",
            "videotoolbox",
            "hardware acceleration",
        )

        if any(message in result.stderr.lower() for message in permanent_errors):
            self.disabled_reason = result.stderr.strip()

    def probe(self, command):
        if self.disabled_reason:
            print_colored(
                f"Hardware unavailable: {self.disabled_reason}",
                Fore.LIGHTYELLOW_EX
            )
            return False

        probe = (
            command[:command.index("-hls_time")]
            + ["-frames:v", "1", "-f", "null", "-"]
        )

        result = run_command(probe, timeout=30)

        if result.returncode or result.stderr.strip():
            self.record_failure(result)

        return result.returncode == 0 and not result.stderr.strip()


# converter

LANG_ALIASES = MappingProxyType({
    "ukr": "uk", "bel": "be", "rus": "ru", "eng": "en",
    "ger": "de", "deu": "de", "fra": "fr", "spa": "es",
    "kaz": "kk", "zho": "zh", "chi": "zh", "und": "und"
})


LANG_NAMES_CAPITALIZED = MappingProxyType({
    "uk": "Ukrainian", "be": "Belarusian", "ru": "Russian",
    "en": "English", "de": "German", "fr": "French",
    "es": "Spanish", "kk": "Kazakh", "zh": "Chinese", "und": "Undetermined"
})


LANG_ORDER = ('uk', 'be', 'ru', 'de', 'en', 'fr', 'es', 'kk', 'zh')


TEXT_CODECS = frozenset({"subrip", "srt", "ass", "ssa", "webvtt", "mov_text", "text",
                         "microdvd", "mpl2", "jacosub", "pjs", "realtext", "sami",
                         "stl", "subviewer", "subviewer1", "vplayer", "ttml", "eia_608"})


BITMAP_CODECS = frozenset({"hdmv_pgs_subtitle", "dvd_subtitle", "dvb_subtitle", "xsub"})


STANDARD_RESOLUTIONS = (
    ('1080p', '1920:1080', 3500000),
    ('720p', '1280:720', 1750000),
    ('480p', '854:480', 700000),
    ('360p', '640:360', 350000),
)


def get_audio_rank(st):
    title = st.get("tags", {}).get("title", "").lower()
    if "original" in title or "оригинал" in title: return 1
    if "unofficial dub" in title or "неофициальный дубляж" in title: return 3
    if "official dub" in title or "официальный дубляж" in title or "дубляж" in title or "dub" in title: return 2
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


def get_lang_priority(st):
    l = st.get("tags", {}).get("language", "und")
    l = LANG_ALIASES.get(l, l)
    return LANG_ORDER.index(l) if l in LANG_ORDER else 999


def get_track_identity(stream, internal_idx):
    tags = stream.get("tags", {})
    lang = tags.get("language", "und")
    lang = LANG_ALIASES.get(lang, lang)
    title = tags.get("title", "").strip()
    prefix = LANG_NAMES_CAPITALIZED.get(lang, lang.capitalize())
    return lang, f"{prefix} {title}" if title else f"{prefix} Track {internal_idx}"


def normalize_webvtt(input_path, output_path):
    def timestamp(value):
        parts = value.split(":")
        hours, minutes, seconds = parts if len(parts) == 3 else ("0", *parts)
        seconds, milliseconds = seconds.split(".")
        return f"{int(hours):02}:{int(minutes):02}:{int(seconds):02}.{int(milliseconds):03}"

    with open(input_path, encoding="utf-8") as source:
        lines = source.readlines()
    with open(output_path, "w", encoding="utf-8") as output:
        for line in lines:
            match = VTT_TIMING.match(line)
            if match:
                output.write(f"{match['prefix']}{timestamp(match['start'])} --> {timestamp(match['end'])}"
                             f"{match['settings']}{match['ending'] or ''}")
            else:
                output.write(line)

def build_video_command(
    encoder,
    input_path,
    video_index,
    bitrate,
    scale,
    rendition_dir,
    output_path
):
    output_options = [
        "-b:v", str(bitrate),
        "-maxrate", str(int(bitrate * 1.1)),
        "-bufsize", str(int(bitrate * 2)),
        "-g", "48",
        "-force_key_frames", "expr:gte(t,n_forced*2)",
        "-an", "-sn",
        "-hls_time", "2",
        "-hls_playlist_type", "vod",
        "-hls_flags", "independent_segments",
        "-hls_segment_type", "fmp4",
        "-hls_segment_filename",
        os.path.join(rendition_dir, "%04d.m4s"),
        output_path,
    ]

    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    if encoder == "h264_videotoolbox":
        command += ["-hwaccel", "videotoolbox", "-hwaccel_output_format", "nv12"]
        encoder_options = [
            "-profile:v", "high",
            "-vf", f"sidedata=mode=delete,scale={scale}",
        ]
    elif encoder == "h264_nvenc":
        encoder_options = [
            "-gpu", "0",
            "-profile:v", "main",
            "-level", "4.1",
            "-vf", f"scale={scale}",
        ]
    elif encoder == "libx264":
        encoder_options = [
            "-preset", "slow",
            "-profile:v", "main",
            "-level", "4.1",
            "-vf", f"scale={scale}",
            "-keyint_min", "48",
            "-sc_threshold", "0",
        ]
    else:
        raise ProcessingError(f"Unsupported video encoder: {encoder}")

    return (command + ["-i", input_path, "-map", f"0:{video_index}", "-c:v", encoder]
            + encoder_options + output_options)

def process_file(mkv_file, hardware):
    input_path = os.path.abspath(mkv_file)
    output_dir = os.path.splitext(input_path)[0]
    print_colored(f"Source file usage: {mkv_file}...", Fore.LIGHTYELLOW_EX)

    if not os.path.exists(output_dir):
        os.mkdir(output_dir)
    streams_info = probe_source(input_path)
    video_stream = next((stream for stream in streams_info.get("streams", [])
                         if stream.get("codec_type") == "video"
                         and not stream.get("disposition", {}).get("attached_pic")), None)
    if video_stream is None:
        raise ProcessingError("No main video stream found.")
    video_index = video_stream["index"]
    src_w = int(video_stream.get("width", 0) or 0)
    src_h = int(video_stream.get("height", 0) or 0)
    wanted_indexes = {stream["index"] for stream in streams_info.get("streams", [])
                      if stream.get("codec_type") in ("audio", "subtitle")}
    wanted_indexes.add(video_index)
    source_times = probe_timeline(input_path, wanted_indexes=wanted_indexes)
    if video_index not in source_times:
        raise ProcessingError("The selected video stream has no timed packets.")
    origin = streams_info.get("format", {}).get("start_time")
    source_origin = Decimal(origin) if origin not in (None, "N/A") else min(
        info["start"] for info in source_times.values())
    if not source_origin.is_finite():
        raise ProcessingError("Invalid source start time.")
    file_ok = True
    available_renditions = []
    presentation_duration = Decimal(0)
    reference_rendition = None

    if src_w > 0 and src_h > 0:
        resolutions = []
        for res_label, base_scale, base_bitrate in STANDARD_RESOLUTIONS:
            base_w, base_h = map(int, base_scale.split(":"))
            if src_w * base_h >= src_h * base_w:
                target_w = base_w
                target_h = max(2, 2 * ((base_w * src_h + src_w) // (2 * src_w)))
            else:
                target_h = base_h
                target_w = max(2, 2 * ((base_h * src_w + src_h) // (2 * src_h)))
            base_pixels = base_w * base_h
            bitrate = (base_bitrate * target_w * target_h + base_pixels // 2) // base_pixels
            resolutions.append((res_label, f"{target_w}:{target_h}", bitrate))
    else:
        resolutions = STANDARD_RESOLUTIONS

    for res_label, scale, bitrate in resolutions:
        w_target, h_target = map(int, scale.split(":"))
        if src_w and src_h and (w_target > src_w or h_target > src_h):
            print_colored(f"Skipping {res_label}: resolution higher than source.", Fore.LIGHTYELLOW_EX)
            continue

        rendition_dir = os.path.join(output_dir, res_label)
        os.makedirs(rendition_dir, exist_ok=True)
        output_path = os.path.join(rendition_dir, f"{res_label}.m3u8")
        
        encoder = hardware.encoder

        using_hardware = encoder in {
            "h264_nvenc",
            "h264_videotoolbox"
        }

        ffmpeg_command = build_video_command(
            encoder,
            input_path,
            video_index,
            bitrate,
            scale,
            rendition_dir,
            output_path
        )

        before = output_snapshot(rendition_dir)

        if using_hardware:
            if not hardware.probe(ffmpeg_command):
                if hardware.forced:
                    raise ProcessingError(
                        f"Requested encoder {encoder} is unavailable."
                    )

                print_colored(
                    f"{encoder} unavailable. Falling back to libx264...",
                    Fore.LIGHTYELLOW_EX
                )
                encoder = "libx264"
                ffmpeg_command = build_video_command(
                    encoder,
                    input_path,
                    video_index,
                    bitrate,
                    scale,
                    rendition_dir,
                    output_path
                )
                before = output_snapshot(rendition_dir)

        result = run_command(ffmpeg_command)

        if result.returncode or result.stderr.strip():
            if using_hardware and not hardware.forced:
                print_colored(
                    f"{hardware.encoder} failed. Falling back to libx264...",
                    Fore.LIGHTYELLOW_EX
                )

                encoder = "libx264"
                ffmpeg_command = build_video_command(
                    encoder,
                    input_path,
                    video_index,
                    bitrate,
                    scale,
                    rendition_dir,
                    output_path
                )
                before = output_snapshot(rendition_dir)
                result = run_command(ffmpeg_command)

        if result.returncode or result.stderr.strip():
            file_ok = False
            print_colored(
                f"Video encoding failed ({res_label}); source will be retained.",
                Fore.LIGHTRED_EX
            )
            continue

        success_log_msg = (
            f"Video: {encoder} encoding successfully ({res_label})."
        )
        try:
            validated = validate_hls(output_path, before, source_times[video_index], source_origin, "video")
            validate_rendition_alignment(validated, reference_rendition)
            if not correct_hls_version(output_path, 6):
                raise ProcessingError(f"Cannot set the existing .hls version: {output_path}")
        except (ProcessingError, OSError, ValueError, ArithmeticError) as exc:
            file_ok = False
            print_colored(f"Video validation failed ({res_label}): {exc}", Fore.LIGHTRED_EX)
            continue
        if reference_rendition is None:
            reference_rendition = validated
        available_renditions.append((res_label, w_target, h_target, bitrate, validated["frame_rate"]))
        presentation_duration = max(presentation_duration, validated["duration"])
        print_colored(success_log_msg, Fore.LIGHTBLUE_EX)

    audio_streams = []
    subtitle_streams = []

    for stream in streams_info.get("streams", []):
        if stream.get("codec_type") == "audio":
            audio_streams.append(stream)
        elif stream.get("codec_type") == "subtitle":
            subtitle_streams.append(stream)

    audio_streams.sort(key=lambda s: (get_lang_priority(s), get_audio_rank(s)))
    subtitle_streams.sort(key=lambda s: (get_lang_priority(s), get_subtitle_rank(s)))

    audio_tracks_processed = []
    subtitle_tracks_processed = []

    for internal_idx, stream in enumerate(audio_streams, start=1):
        lang, final_name = get_track_identity(stream, internal_idx)
        
        path_lang = language_path_tag(lang)
        folder_name = f"audio_{path_lang}_{internal_idx}"
        folder = os.path.join(output_dir, folder_name)
        playlist_name = f"audio_{path_lang}_{internal_idx}.m3u8"
        playlist_path = os.path.join(folder, playlist_name)
        
        os.makedirs(folder, exist_ok=True)
        audio_cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", input_path,
            "-map", f"0:{stream['index']}", "-map", "-0:v:m:attached_pic",
            "-c:a", "aac", "-b:a", "192k", "-ac", "2",
            "-avoid_negative_ts", "make_zero", "-flush_packets", "1", "-fflags", "+genpts",
            "-hls_time", "2", "-hls_playlist_type", "vod", "-hls_flags", "split_by_time",
            "-hls_segment_type", "fmp4", "-hls_fmp4_init_filename", "init.mp4",
            "-hls_segment_filename", os.path.join(folder, "%04d.m4s"), playlist_path,
        ]
        before = output_snapshot(folder)
        result = run_command(audio_cmd)
        try:
            if result.returncode or result.stderr.strip():
                raise ProcessingError("Audio encoder failed.")
            expected = source_times.get(stream["index"])
            if not expected:
                raise ProcessingError("The source audio stream has no timed packets.")
            validated = validate_hls(playlist_path, before, expected, source_origin, "audio")
            if not correct_hls_version(playlist_path, 6):
                raise ProcessingError(f"Cannot set the existing .hls version: {playlist_path}")
        except (ProcessingError, OSError, ValueError, ArithmeticError) as exc:
            file_ok = False
            print_colored(f"Audio validation failed ({final_name}): {exc}", Fore.LIGHTRED_EX)
            continue
        presentation_duration = max(presentation_duration, validated["duration"])

        audio_tracks_processed.append({
            "lang": lang,
            "name": final_name,
            "playlist_uri": f"{folder_name}/{playlist_name}"
        })
        print_colored(f"Audio: {final_name} processed successfully.", Fore.LIGHTGREEN_EX)

    for internal_idx, stream in enumerate(subtitle_streams, start=1):
        subtitle_codec = stream.get("codec_name", "unknown")
        if subtitle_codec in BITMAP_CODECS:
            file_ok = False
            print_colored(f"Unsupported subtitle codec {subtitle_codec} (stream {stream['index']}); "
                          "source will be retained. No OCR is performed.", Fore.LIGHTRED_EX)
            continue
        if subtitle_codec not in TEXT_CODECS:
            print_colored(f"Subtitle codec {subtitle_codec} is not classified; the existing "
                          "WebVTT conversion will be attempted and validated.", Fore.LIGHTYELLOW_EX)
        if subtitle_codec in {"ass", "ssa", "mov_text", "ttml"}:
            print_colored(f"Subtitle stream {stream['index']}: conversion to WebVTT may lose "
                          "format-specific styling/effects.", Fore.LIGHTYELLOW_EX)
        lang, final_name = get_track_identity(stream, internal_idx)
        
        path_lang = language_path_tag(lang)
        folder_name = f"subtitles_{path_lang}_{internal_idx}"
        folder = os.path.join(output_dir, folder_name)
        os.makedirs(folder, exist_ok=True)
        
        vtt_filename = f"subtitles_{path_lang}_{internal_idx}.vtt"
        vtt_path = os.path.join(folder, vtt_filename)
        playlist_name = f"subtitles_{path_lang}_{internal_idx}.m3u8"
        playlist_path = os.path.join(folder, playlist_name)

        temp_vtt_path = os.path.join(folder, f"temp_{path_lang}_{internal_idx}.vtt")
        
        subtitle_cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", input_path,
            "-map", f"0:{stream['index']}", "-map", "-0:v:m:attached_pic",
            "-f", "webvtt", temp_vtt_path,
        ]
        before = output_snapshot(folder)
        result = run_command(subtitle_cmd)
        try:
            if result.returncode or result.stderr.strip():
                raise ProcessingError("Subtitle conversion failed.")
            require_current_file(temp_vtt_path, before)
            if presentation_duration <= 0:
                raise ProcessingError("No validated presentation duration is available.")
            expected = source_times.get(stream["index"])
            validate_vtt(temp_vtt_path, expected, source_origin, presentation_duration)
            normalize_webvtt(temp_vtt_path, vtt_path)
            validate_vtt(vtt_path, expected, source_origin, presentation_duration)
            os.remove(temp_vtt_path)

            with open(playlist_path, "w", encoding="utf-8") as m3u:
                m3u.write("#EXTM3U\n")
                m3u.write("#EXT-X-VERSION:3\n")
                m3u.write(f"#EXT-X-TARGETDURATION:{presentation_duration.to_integral_value(rounding=ROUND_CEILING)}\n")
                m3u.write("#EXT-X-MEDIA-SEQUENCE:0\n")
                m3u.write(f"#EXTINF:{presentation_duration:f},\n")
                m3u.write(f"{vtt_filename}\n")
                m3u.write("#EXT-X-ENDLIST\n")

            subtitle_tracks_processed.append({
                "lang": lang,
                "name": final_name,
                "playlist_uri": f"{folder_name}/{playlist_name}"
            })
            print_colored(f"Subtitles: {final_name} processed successfully.", Fore.LIGHTYELLOW_EX)
        except (ProcessingError, OSError, ValueError, ArithmeticError) as exc:
            file_ok = False
            print_colored(f"Subtitle validation failed (stream {stream['index']}): {exc}", Fore.LIGHTRED_EX)

    if not file_ok or not available_renditions:
        print_colored("Conversion incomplete; master.m3u8 was not updated and the source is retained.", Fore.LIGHTRED_EX)
        return False
    write_master_playlist(output_dir, available_renditions,
                          audio_tracks_processed, subtitle_tracks_processed)

    print_colored("Master: created successfully.", Fore.LIGHTGREEN_EX)

    return True


# master playlist

def hls_attribute(value):
    value = unicodedata.normalize("NFC", str(value))
    return "".join(" " if ord(char) < 32 or 127 <= ord(char) <= 159 else
                   "’" if char == '"' else char for char in value)


def prepare_hls_tracks(tracks):
    names = set()
    for track in tracks:
        base = hls_attribute(track["name"])
        name = base
        suffix = 2
        while name in names:
            name = f"{base} ({suffix})"
            suffix += 1
        names.add(name)
        track["hls_name"] = name
        track["hls_lang"] = hls_attribute(track["lang"])
        track["hls_uri"] = quote(track["playlist_uri"], safe="/-._~")


def write_master_playlist(output_dir, available_renditions,
                          audio_tracks_processed, subtitle_tracks_processed):
    prepare_hls_tracks(audio_tracks_processed)
    prepare_hls_tracks(subtitle_tracks_processed)

    with atomic_text_writer(os.path.join(output_dir, "master.m3u8")) as master:
        master.write("#EXTM3U\n#EXT-X-VERSION:6\n#EXT-X-INDEPENDENT-SEGMENTS\n\n")
        master.write("# Video streams\n")

        for res_label, w, h, bitrate, frame_rate in available_renditions:
            master.write(
                f"#EXT-X-STREAM-INF:BANDWIDTH={bitrate},AVERAGE-BANDWIDTH={int(bitrate*0.9)},"
                f"RESOLUTION={w}x{h}"
                f"{',FRAME-RATE=' + frame_rate if frame_rate else ''}"
                f"{',AUDIO=\"audio\"' if audio_tracks_processed else ''}"
                f"{',SUBTITLES=\"subs\"' if subtitle_tracks_processed else ',CLOSED-CAPTIONS=NONE'}\n"
                f"{res_label}/{res_label}.m3u8\n"
            )

        master.write("\n# Audio streams\n")
        for i, track in enumerate(audio_tracks_processed):
            master.write(
                f"#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID=\"audio\",NAME=\"{track['hls_name']}\",LANGUAGE=\"{track['hls_lang']}\","
                f"AUTOSELECT={'YES' if i == 0 else 'NO'},DEFAULT={'YES' if i == 0 else 'NO'},"
                f"URI=\"{track['hls_uri']}\"\n"
            )

        if subtitle_tracks_processed:
            master.write("\n# Subtitle streams\n")
            for track in subtitle_tracks_processed:
                master.write(
                    f"#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID=\"subs\",NAME=\"{track['hls_name']}\",LANGUAGE=\"{track['hls_lang']}\","
                    f"DEFAULT=NO,AUTOSELECT=NO,FORCED=NO,"
                    f"URI=\"{track['hls_uri']}\"\n"
                )


# main

def main():
    parser = argparse.ArgumentParser(
        description="Convert MKV files to HLS."
    )

    parser.add_argument(
        "encoder",
        nargs="?",
        default="auto",
        choices=[
            "auto",
            "libx264",
            "h264_nvenc",
            "h264_videotoolbox",
        ],
        help="Video encoder to use. Default: auto."
    )

    args = parser.parse_args()

    current_dir = os.path.abspath(".")

    autorenamer_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "autorenamer.py")
    if os.path.isfile(autorenamer_path):
        try:
            runpy.run_path(autorenamer_path)["rename_files_in_folder"](current_dir)
        except (Exception, KeyboardInterrupt) as exc:
            print_colored(
                f"Autorenamer failed: {exc or 'cancelled'}. Processing stopped.",
                Fore.LIGHTRED_EX
            )
            return 1

    with os.scandir(current_dir) as entries:
        mkv_files = [
            entry.path
            for entry in entries
            if entry.name.lower().endswith(".mkv")
            and entry.is_file(follow_symlinks=False)
        ]

    if not mkv_files:
        print_colored(
            "All .mkv files processed.",
            Fore.LIGHTGREEN_EX
        )
        return 0

    try:
        hardware = HardwareBackend(args.encoder)
    except (ProcessingError, OSError, ValueError) as exc:
        print_colored(str(exc), Fore.LIGHTRED_EX)
        return 1

    print_colored(
        f"Selected encoder: {hardware.encoder}",
        Fore.LIGHTMAGENTA_EX
    )

    all_ok = True

    for mkv_file in mkv_files:
        success = False

        try:
            success = process_file(mkv_file, hardware)
        except (
            ProcessingError,
            OSError,
            ValueError,
            ArithmeticError
        ) as exc:
            print_colored(
                f"Failed: {os.path.basename(mkv_file)} — {exc}. "
                "Source file retained.",
                Fore.LIGHTRED_EX
            )

        if success:
            try:
                os.remove(mkv_file)
                print_colored(
                    f"Source file deleted: {mkv_file}...",
                    Fore.LIGHTRED_EX
                )
            except OSError as exc:
                success = False
                print_colored(
                    f"Cannot delete source file "
                    f"{os.path.basename(mkv_file)}: {exc}",
                    Fore.LIGHTRED_EX
                )

        all_ok = all_ok and success

    print_colored(
        "All .mkv files processed."
        if all_ok
        else "Processing finished with errors; failed sources retained.",
        Fore.LIGHTGREEN_EX if all_ok else Fore.LIGHTRED_EX
    )

    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
