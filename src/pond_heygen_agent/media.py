"""Bounded, public-network-only media access."""

import asyncio
import hashlib
import io
import ipaddress
import os
import socket
import tempfile
import warnings
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from PIL import Image, UnidentifiedImageError

from . import __version__

MAX_VIDEO_BYTES = 100 * 1024**2
ATTACHMENT_TYPES = {"image/png", "image/jpeg", "application/pdf"}
MAX_IMAGE_PIXELS = 25_000_000


class MediaError(ValueError):
    """A safe, caller-readable media validation or transfer failure."""


async def _public_target(value: str) -> tuple[httpx.URL, str]:
    try:
        url = httpx.URL(value)
        host = url.host.rstrip(".").lower()
        if (
            url.scheme != "https"
            or url.port not in (None, 443)
            or not host
            or url.userinfo
            or url.fragment
            or "#" in value
            or host == "localhost"
            or host.endswith((".localhost", ".local", ".internal"))
            or "%" in host
        ):
            raise MediaError("Files must use a public HTTPS URL on port 443.")
        try:
            addresses = [ipaddress.ip_address(host)]
        except ValueError:
            resolved = await asyncio.wait_for(
                asyncio.to_thread(
                    socket.getaddrinfo,
                    host,
                    443,
                    type=socket.SOCK_STREAM,
                ),
                timeout=10,
            )
            addresses = [ipaddress.ip_address(item[4][0]) for item in resolved]
        if not addresses or any(not address.is_global for address in addresses):
            raise MediaError("File URLs must resolve only to public network addresses.")
        addresses.sort(key=lambda address: address.version != 4)
        return url, str(addresses[0])
    except MediaError:
        raise
    except (ValueError, httpx.InvalidURL, OSError, TimeoutError):
        raise MediaError("The file URL could not be safely resolved.") from None


@asynccontextmanager
async def _stream(
    value: str,
    max_bytes: int,
    client: httpx.AsyncClient | None,
) -> AsyncIterator[httpx.Response]:
    owned = client is None
    if client is None:
        # No ambient proxies or credentials, and no cross-host pooled TLS reuse.
        client = httpx.AsyncClient(
            timeout=httpx.Timeout(30),
            trust_env=False,
            limits=httpx.Limits(max_keepalive_connections=0),
        )
    response = None
    try:
        if max_bytes <= 0:
            raise MediaError("The file exceeds the permitted size.")
        for _ in range(5):
            url, address = await _public_target(value)
            # Connect to the validated literal IP; retain the original HTTP host
            # and TLS certificate/SNI hostname. The transport never resolves again.
            request = httpx.Request(
                "GET",
                url.copy_with(host=address),
                headers={
                    "Host": url.netloc.decode("ascii"),
                    "Accept-Encoding": "identity",
                    "User-Agent": (
                        f"PondHeyGenAgent/{__version__} "
                        "(+https://github.com/Pond-International/pond-heygen-agent)"
                    ),
                },
                extensions={"sni_hostname": url.host},
            )
            response = await client.send(request, stream=True, auth=None, follow_redirects=False)
            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("location")
                await response.aclose()
                if not location:
                    raise MediaError("The file server returned an invalid redirect.")
                value = str(url.join(location))
                continue
            if response.status_code != 200:
                raise MediaError("The file could not be downloaded.")
            if response.headers.get("content-encoding", "identity").lower() != "identity":
                raise MediaError("Compressed HTTP file responses are not supported.")
            try:
                size = int(response.headers.get("content-length", "0"))
            except ValueError:
                raise MediaError("The file server returned an invalid size.") from None
            if size < 0 or size > max_bytes:
                raise MediaError("The file exceeds the permitted size.")
            yield response
            return
        raise MediaError("The file server redirected too many times.")
    except (httpx.HTTPError, httpx.InvalidURL, TimeoutError, OSError):
        raise MediaError("The file transfer failed or timed out.") from None
    finally:
        if response is not None:
            await response.aclose()
        if owned:
            await client.aclose()


def _attachment_type(body: bytes) -> str:
    if body.startswith(b"%PDF-"):
        return "application/pdf"
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(body)) as picture:
                if picture.format not in ("PNG", "JPEG"):
                    raise MediaError("Only PNG, JPEG, and PDF reference files are supported.")
                if picture.width * picture.height > MAX_IMAGE_PIXELS:
                    raise MediaError("The image dimensions exceed the permitted size.")
                mime = "image/png" if picture.format == "PNG" else "image/jpeg"
                picture.verify()
            with Image.open(io.BytesIO(body)) as picture:
                picture.load()
        return mime
    except MediaError:
        raise
    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        SyntaxError,
        Image.DecompressionBombWarning,
        Image.DecompressionBombError,
    ):
        raise MediaError("The file is not a valid PNG, JPEG, or PDF.") from None


async def safe_fetch(
    url: str,
    max_bytes: int,
    allowed_types: set[str] | None = None,
    client: httpx.AsyncClient | None = None,
) -> tuple[bytes, str]:
    """Fetch and inspect a bounded attachment, never forwarding authentication."""
    try:
        async with asyncio.timeout(90):
            async with _stream(url, max_bytes, client) as response:
                body = bytearray()
                async for chunk in response.aiter_bytes(64 * 1024):
                    if len(body) + len(chunk) > max_bytes:
                        raise MediaError("The file exceeds the permitted size.")
                    body.extend(chunk)
            data = bytes(body)
            mime = _attachment_type(data)
            if mime not in (ATTACHMENT_TYPES if allowed_types is None else allowed_types):
                raise MediaError("This file type is not supported for the requested action.")
            return data, mime
    except TimeoutError:
        raise MediaError("The file transfer timed out.") from None


async def download_video(
    url: str,
    destination: Path,
    *,
    client: httpx.AsyncClient | None = None,
) -> dict:
    """Stage a bounded MP4 and atomically publish it after successful verification."""
    stage = None
    try:
        async with asyncio.timeout(180):
            async with _stream(url, MAX_VIDEO_BYTES, client) as response:
                destination.parent.mkdir(parents=True, exist_ok=True)
                digest = hashlib.sha256()
                count = 0
                prefix = bytearray()
                with tempfile.NamedTemporaryFile(
                    dir=destination.parent,
                    prefix=".video-",
                    suffix=".part",
                    delete=False,
                ) as output:
                    stage = Path(output.name)
                    async for chunk in response.aiter_bytes(64 * 1024):
                        count += len(chunk)
                        if count > MAX_VIDEO_BYTES:
                            raise MediaError("The generated video exceeds the 100 MiB limit.")
                        if len(prefix) < 24:
                            prefix.extend(chunk[: 24 - len(prefix)])
                        if len(prefix) >= 12 and prefix[4:8] != b"ftyp":
                            raise MediaError("The generated file is not an MP4 video.")
                        output.write(chunk)
                        digest.update(chunk)
                    if len(prefix) < 16 or prefix[4:8] != b"ftyp":
                        raise MediaError("The generated file is not an MP4 video.")
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(stage, destination)
                stage = None
                return {"byte_count": count, "sha256": digest.hexdigest()}
    except (TimeoutError, OSError):
        raise MediaError("The generated video could not be saved.") from None
    finally:
        if stage is not None:
            stage.unlink(missing_ok=True)
