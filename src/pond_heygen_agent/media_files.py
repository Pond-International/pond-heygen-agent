"""Bounded media transfers with signature checks, not trust in file extensions.

Audio/video checks identify containers; they do not certify complete codec decodability.
Images are fully decoded by the existing attachment validator.
"""

import asyncio
import io
import json
import re
import zipfile
from pathlib import PurePosixPath
from types import MappingProxyType

from .media import MediaError, _attachment_type, _stream

SUPPORTED_MEDIA = MappingProxyType(
    {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "application/pdf": ".pdf",
        "video/mp4": ".mp4",
        "video/webm": ".webm",
        "video/quicktime": ".mov",
        "audio/wav": ".wav",
        "audio/mpeg": ".mp3",
        "audio/mp4": ".m4a",
        "audio/ogg": ".ogg",
        "application/json": ".json",
        "application/x-subrip": ".srt",
        "text/vtt": ".vtt",
        "application/zip": ".zip",
    }
)
MAX_FILE_BYTES = 100 * 1024**2
MAX_BUNDLE_BYTES = 200 * 1024**2
MAX_OUTPUT_FILES = 32


def _subtitle(content, vtt):
    lines = content.replace("\r\n", "\n").strip().split("\n")
    if vtt:
        if not re.fullmatch(r"WEBVTT(?:[ \t][^\n]*)?", lines[0]):
            return False
        lines = lines[1:]
    stamp = r"(?:\d{2,}:)?[0-5]\d:[0-5]\d\.\d{3}" if vtt else r"\d{2,}:[0-5]\d:[0-5]\d,\d{3}"
    timing = re.compile(rf"^{stamp} --> {stamp}(?:[ \t].*)?$")
    found = False
    for block in re.split(r"\n\s*\n", "\n".join(lines).strip()):
        if not block:
            continue
        if vtt and block.startswith(("NOTE", "STYLE", "REGION")):
            continue
        parts = block.split("\n")
        index = 0 if timing.fullmatch(parts[0]) else 1
        if len(parts) <= index + 1 or not timing.fullmatch(parts[index]):
            return False
        if not vtt and (index != 1 or not parts[0].isdigit()):
            return False
        if any(re.search(r"<\s*(?:script|iframe|object)\b", line, re.I) for line in parts):
            return False
        found = True
    return found or (vtt and not "\n".join(lines).strip())


def inspect_media(data: bytes, allowed_types: set[str]) -> str:
    mime = None
    if data.startswith((b"\x89PNG\r\n", b"\xff\xd8", b"%PDF-")):
        mime = _attachment_type(data)
    elif len(data) >= 16 and data[4:8] == b"ftyp":
        if data[8:12] in {b"M4A ", b"M4B "}:
            mime = "audio/mp4"
        elif data[8:12] == b"qt  ":
            mime = "video/quicktime"
        elif data[8:12] in {
            b"isom",
            b"iso2",
            b"iso4",
            b"iso5",
            b"iso6",
            b"mp41",
            b"mp42",
            b"avc1",
            b"dash",
        }:
            mime = "video/mp4"
    elif len(data) >= 16 and data.startswith(b"\x1aE\xdf\xa3") and b"webm" in data[:4096]:
        mime = "video/webm"
    elif len(data) >= 36 and data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        mime = "audio/wav"
    elif len(data) >= 16 and (
        data.startswith(b"ID3")
        or (
            data[0] == 255
            and data[1] & 0xE0 == 0xE0
            and data[1] & 0x06 != 0
            and data[1] & 0x18 != 0x08
            and data[2] >> 4 not in {0, 15}
            and data[2] & 0x0C != 0x0C
        )
    ):
        mime = "audio/mpeg"
    elif len(data) >= 27 and data.startswith(b"OggS"):
        mime = "audio/ogg"
    elif data.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                entries = archive.infolist()
                if len(entries) > 2000 or sum(e.file_size for e in entries) > MAX_BUNDLE_BYTES:
                    raise MediaError("The ZIP project exceeds the uncompressed limit.")
                for entry in entries:
                    path = PurePosixPath(entry.filename)
                    if (
                        path.is_absolute()
                        or ".." in path.parts
                        or "\\" in entry.filename
                        or entry.flag_bits & 1
                    ):
                        raise MediaError("ZIP projects must use safe relative unencrypted entries.")
                mime = "application/zip"
        except zipfile.BadZipFile:
            raise MediaError("Invalid ZIP project.") from None
    else:
        try:
            content = data.decode("utf-8-sig")
            if content.startswith("WEBVTT") and _subtitle(content, True):
                mime = "text/vtt"
            elif _subtitle(content, False):
                mime = "application/x-subrip"
            else:
                json.loads(content, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                mime = "application/json"
        except (UnicodeDecodeError, ValueError):
            pass
    if mime not in allowed_types or mime not in SUPPORTED_MEDIA:
        raise MediaError("The file content does not match a supported media type for this action.")
    return mime


async def fetch_media(url, max_bytes, allowed_types, client=None) -> tuple[bytes, str]:
    """Fetch public HTTPS without auth; enforce bounded bytes and actual file type."""
    try:
        async with asyncio.timeout(120):
            async with _stream(url, min(max_bytes, MAX_FILE_BYTES), client) as response:
                data = bytearray()
                async for chunk in response.aiter_bytes(64 * 1024):
                    if len(data) + len(chunk) > min(max_bytes, MAX_FILE_BYTES):
                        raise MediaError("The file exceeds the permitted size.")
                    data.extend(chunk)
            result = bytes(data)
            return result, inspect_media(result, allowed_types)
    except TimeoutError:
        raise MediaError("The file transfer timed out.") from None
