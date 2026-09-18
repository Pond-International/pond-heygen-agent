"""Bounded local-media duration fallback; ffprobe never receives a remote URL."""

import asyncio
import json
import tempfile
from pathlib import Path

from .media import MediaError
from .media_files import MAX_FILE_BYTES, fetch_media
from .video_usage import UsageError, duration_seconds

VIDEO_TYPES = {"video/mp4", "video/webm", "video/quicktime"}


async def probe_file(path):
    path = Path(path).resolve(strict=True)
    if not path.is_file() or not 0 < path.stat().st_size <= MAX_FILE_BYTES:
        raise UsageError("Video duration measurement exceeded the media size limit.")
    try:
        process = await asyncio.create_subprocess_exec(
            "ffprobe",
            "-v",
            "quiet",
            "-protocol_whitelist",
            "file",
            "-format_whitelist",
            "mov,matroska,webm",
            "-max_alloc",
            "16777216",
            "-probesize",
            "5000000",
            "-analyzeduration",
            "5000000",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_type,duration:format=duration",
            "-of",
            "json",
            str(path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except OSError:
        raise UsageError("Video duration measurement is unavailable.") from None
    try:
        async with asyncio.timeout(10):
            stdout, _ = await process.communicate()
    except BaseException as error:
        if process.returncode is None:
            process.kill()
        await process.wait()
        if isinstance(error, TimeoutError):
            raise UsageError("Video duration measurement timed out.") from None
        raise
    try:
        if process.returncode:
            raise ValueError
        data = json.loads(stdout)
        stream = data["streams"][0]
        if stream.get("codec_type") != "video":
            raise ValueError
        try:
            return duration_seconds(stream.get("duration"))
        except UsageError:
            return duration_seconds(data.get("format", {}).get("duration"))
    except (ValueError, TypeError, KeyError, IndexError, AttributeError):
        raise UsageError("The completed video's actual duration could not be measured.") from None


async def measure_video_url(url, client):
    try:
        # Reuse pinned public-IP transport, redirect, signature and size checks.
        content, _ = await fetch_media(url, MAX_FILE_BYTES, VIDEO_TYPES, client)
        with tempfile.TemporaryDirectory(prefix="heygen-duration-") as directory:
            path = Path(directory) / "video.media"
            await asyncio.to_thread(path.write_bytes, content)
            return await probe_file(path)
    except (MediaError, OSError):
        raise UsageError(
            "The completed video could not be read for duration measurement."
        ) from None
