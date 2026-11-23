# ClipForge AI V2

A mobile-friendly Flask + FFmpeg video clipper.

## What's new
- Actual clip-count setting: 5, 10, 15, 20, 25, or 30 (default 30).
- The selected count is sent to the backend and controls how many clips are generated.
- YouTube URL input or local video upload.
- Vertical 1080 × 1920 MP4 exports.
- Improved yt-dlp invocation and clearer processing errors.

## Deploy on Render
1. Upload the contents of this ZIP into your `clipforge-ai-v2` GitHub repository (keep the `static` and `templates` folders).
2. In Render, create a new **Web Service** and connect that repository.
3. Select **Docker** runtime if it is not detected automatically.
4. Deploy. The `render.yaml` is included as a reference.

## Important
- Highlight detection is an audio-energy heuristic, not semantic AI. It may choose loud music or effects; review clips before publishing.
- YouTube downloads can fail due to YouTube access controls, regional restrictions, rate limits, or extractor changes. Uploading a video file is the fallback.
- Use only videos you own or have permission to process.
- Video processing needs CPU, memory, and disk space. Free hosting may time out or run out of resources on long videos.
- Files on ephemeral hosting may be deleted when the service restarts. Use persistent storage for ongoing use.
- Optional speech captions can be enabled by adding `faster-whisper` to `requirements.txt`; this increases build size and CPU/RAM requirements.
