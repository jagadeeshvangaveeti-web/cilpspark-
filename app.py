import os, re, uuid, shutil, subprocess
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_from_directory, abort

BASE = Path(__file__).resolve().parent
UPLOADS, OUTPUTS = BASE / "uploads", BASE / "outputs"
UPLOADS.mkdir(exist_ok=True)
OUTPUTS.mkdir(exist_ok=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024 * 1024
JOBS = {}

def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode:
        detail = (p.stderr or p.stdout or "Unknown processing error").strip()
        raise RuntimeError(detail[-1800:])
    return p

def video_duration(path):
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
               "-of", "default=noprint_wrappers=1:nokey=1", str(path)]).stdout.strip()
    return float(out)

def download_video(url, destination):
    # Use only videos you own or have permission to process.
    cmd = [
        "yt-dlp", "--no-playlist", "--no-warnings",
        "--js-runtimes", "node",
        "-f", "bv*[height<=1080]+ba/b[height<=1080]",
        "--merge-output-format", "mp4",
        "-o", str(destination), url
    ]
    run(cmd)
    if not destination.exists():
        candidates = list(destination.parent.glob(destination.stem + ".*"))
        if candidates:
            candidates[0].replace(destination)
    if not destination.exists():
        raise RuntimeError("The video download did not create an output file. Try uploading the video instead.")

def highlight_windows(video, count):
    total = video_duration(video)
    if total < 3:
        raise RuntimeError("This video is too short to create clips.")
    if total < 9:
        return [(0.0, total)]

    clip_len = min(30.0, max(8.0, total / count * 0.72))
    clip_len = min(clip_len, total)
    step = max(1.5, min(3.0, total / 250))
    scores = []
    t = 0.0
    while t < total:
        span = min(step, total - t)
        try:
            p = run(["ffmpeg", "-ss", str(t), "-t", str(span), "-i", str(video),
                     "-vn", "-af", "volumedetect", "-f", "null", "-"])
            match_mean = re.search(r"mean_volume:\s*(-?[\d.]+)\s*dB", p.stderr)
            match_peak = re.search(r"max_volume:\s*(-?[\d.]+)\s*dB", p.stderr)
            mean = float(match_mean.group(1)) if match_mean else -60
            peak = float(match_peak.group(1)) if match_peak else -60
            score = (mean + 60) * 0.6 + (peak + 60) * 0.4
        except Exception:
            score = 0
        scores.append((t + span / 2, score))
        t += step

    candidates = sorted(scores, key=lambda item: item[1], reverse=True)
    starts = []
    min_gap = clip_len * 0.62
    for center, _ in candidates:
        start = max(0.0, min(total - clip_len, center - clip_len / 2))
        if all(abs(start - old) >= min_gap for old in starts):
            starts.append(start)
        if len(starts) == count:
            break

    # Fill any remaining slots evenly so the requested count is honored.
    if len(starts) < count:
        for i in range(count * 3):
            start = (max(0.0, total - clip_len) * i) / max(1, count * 3 - 1)
            if all(abs(start - old) >= max(1.0, clip_len * 0.35) for old in starts):
                starts.append(start)
            if len(starts) == count:
                break

    starts = sorted(starts[:count])
    return [(s, min(clip_len, total - s)) for s in starts]

def make_subtitles(video, start, length, output_srt):
    try:
        from faster_whisper import WhisperModel
        model = WhisperModel(os.getenv("WHISPER_MODEL", "tiny"), device="cpu", compute_type="int8")
        segments, _ = model.transcribe(str(video), vad_filter=True)
        rows, index = [], 1
        for seg in segments:
            a, b = max(seg.start, start), min(seg.end, start + length)
            if b <= a:
                continue
            ms_a, ms_b = int((a-start)*1000), int((b-start)*1000)
            def stamp(ms):
                h, ms = divmod(ms, 3600000)
                m, ms = divmod(ms, 60000)
                s, ms = divmod(ms, 1000)
                return f"{h:02}:{m:02}:{s:02},{ms:03}"
            rows.append(f"{index}\n{stamp(ms_a)} --> {stamp(ms_b)}\n{seg.text.strip()}\n")
            index += 1
        output_srt.write_text("\n".join(rows), encoding="utf-8")
        return bool(rows)
    except Exception:
        output_srt.write_text("", encoding="utf-8")
        return False

@app.get("/")
def home():
    return render_template("index.html")

@app.post("/api/create")
def create():
    url = request.form.get("source", "").strip()
    uploaded = request.files.get("video")
    try:
        count = int(request.form.get("clip_count", "30"))
    except ValueError:
        count = 30
    count = max(5, min(30, count))
    if not url and not (uploaded and uploaded.filename):
        return jsonify(error="Paste a YouTube link or choose a video file."), 400

    job = uuid.uuid4().hex[:10]
    job_dir = OUTPUTS / job
    job_dir.mkdir(parents=True, exist_ok=True)
    input_path = UPLOADS / f"{job}.mp4"
    try:
        if uploaded and uploaded.filename:
            if not uploaded.filename.lower().endswith((".mp4", ".mov", ".mkv", ".webm", ".m4v")):
                raise ValueError("Choose an MP4, MOV, MKV or WebM video.")
            uploaded.save(input_path)
        else:
            if not re.match(r"^https?://", url):
                raise ValueError("Enter a valid video URL beginning with http:// or https://.")
            download_video(url, input_path)

        windows = highlight_windows(input_path, count)
        clips = []
        for index, (start, length) in enumerate(windows, 1):
            filename = f"clip_{index}.mp4"
            srt = job_dir / f"clip_{index}.srt"
            has_captions = make_subtitles(input_path, start, length, srt)
            output = job_dir / filename
            vf = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920"
            if has_captions:
                safe_srt = str(srt).replace("\\", "/").replace(":", r"\:")
                vf += f",subtitles='{safe_srt}':force_style='FontName=Arial,FontSize=18,Outline=2,Shadow=1,Alignment=2,MarginV=120'"
            run(["ffmpeg", "-y", "-ss", str(start), "-i", str(input_path), "-t", str(length),
                 "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                 "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(output)])
            clips.append({
                "id": index, "file": f"/media/{job}/{filename}",
                "start": round(start, 1), "duration": round(length, 1),
                "captions": has_captions
            })
        JOBS[job] = True
        return jsonify(job=job, clips=clips,
                       note=f"Created {len(clips)} clips. Highlight selection uses audio peaks, so review the clips before publishing.")
    except Exception as exc:
        shutil.rmtree(job_dir, ignore_errors=True)
        input_path.unlink(missing_ok=True)
        return jsonify(error=str(exc)), 500

@app.get("/media/<job>/<filename>")
def media(job, filename):
    if job not in JOBS:
        abort(404)
    return send_from_directory(OUTPUTS / job, filename, as_attachment=False)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=False)
