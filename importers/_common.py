"""Shared helpers for the importer parsers. Internal module."""

import struct
import zipfile
from contextlib import contextmanager

ZIP_MAGICS = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
READ_CHUNK_SIZE = 64 * 1024
MAX_ZIP_MEMBERS = 20_000
MAX_COMPRESSION_RATIO = 500
EOCD_SIGNATURE = b"PK\x05\x06"
EOCD_MIN_SIZE = 22
MAX_ZIP_COMMENT = 65_535


@contextmanager
def open_binary(file_or_path):
    """Yield a seekable binary file object for a path or file-like input.

    Closes the file only if this function opened it.
    """
    if hasattr(file_or_path, "read"):
        yield file_or_path
    else:
        f = open(file_or_path, "rb")
        try:
            yield f
        finally:
            f.close()


def is_zip(stream):
    """True if the (seekable) binary stream starts with the zip magic bytes."""
    pos = stream.tell()
    head = stream.read(4)
    stream.seek(pos)
    return head in ZIP_MAGICS


def require_stream_size(stream, max_bytes, label):
    """Reject a seekable stream larger than max_bytes without consuming it."""
    try:
        pos = stream.tell()
        stream.seek(0, 2)
        size = stream.tell()
        stream.seek(pos)
    except (AttributeError, OSError) as exc:
        raise ValueError(f"{label} must be a seekable binary stream") from exc
    if size > max_bytes:
        raise ValueError(f"{label} exceeds the {max_bytes}-byte size limit")
    return size


def read_limited(stream, max_bytes, label):
    """Read at most max_bytes from a binary stream and reject trailing data."""
    chunks = []
    total = 0
    while True:
        chunk = stream.read(min(READ_CHUNK_SIZE, max_bytes - total + 1))
        if not chunk:
            break
        if not isinstance(chunk, bytes):
            raise ValueError(f"{label} must contain binary data")
        total += len(chunk)
        if total > max_bytes:
            raise ValueError(f"{label} exceeds the {max_bytes}-byte size limit")
        chunks.append(chunk)
    return b"".join(chunks)


def open_zip(stream):
    """Open a ZipFile over a stream, mapping corruption to ValueError."""
    try:
        _check_eocd_member_count(stream)
        return zipfile.ZipFile(stream)
    except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError) as exc:
        raise ValueError(f"not a valid zip archive: {exc}") from exc


def _check_eocd_member_count(stream):
    """Reject excessive member counts before ZipFile allocates its info list."""
    pos = stream.tell()
    stream.seek(0, 2)
    size = stream.tell()
    tail_size = min(size, EOCD_MIN_SIZE + MAX_ZIP_COMMENT)
    stream.seek(size - tail_size)
    tail = stream.read(tail_size)
    stream.seek(pos)

    search_end = len(tail)
    while True:
        offset = tail.rfind(EOCD_SIGNATURE, 0, search_end)
        if offset < 0:
            return
        if offset + EOCD_MIN_SIZE <= len(tail):
            comment_length = struct.unpack_from("<H", tail, offset + 20)[0]
            if offset + EOCD_MIN_SIZE + comment_length == len(tail):
                count = struct.unpack_from("<H", tail, offset + 10)[0]
                if count > MAX_ZIP_MEMBERS:
                    raise ValueError(
                        f"zip archive contains more than {MAX_ZIP_MEMBERS} members"
                    )
                return
        search_end = offset


def zip_infos(zf):
    """Return bounded archive metadata, rejecting oversized central directories."""
    infos = zf.infolist()
    if len(infos) > MAX_ZIP_MEMBERS:
        raise ValueError(
            f"zip archive contains more than {MAX_ZIP_MEMBERS} members"
        )
    return infos


def validate_zip_member(info, max_bytes, label):
    """Reject encrypted, oversized, or implausibly compressed archive members."""
    if info.flag_bits & 0x1:
        raise ValueError(f"{label} is encrypted")
    if info.file_size > max_bytes:
        raise ValueError(f"{label} exceeds the {max_bytes}-byte size limit")
    if info.file_size and not info.compress_size:
        raise ValueError(f"{label} has an invalid compressed size")
    if (
        info.compress_size
        and info.file_size / info.compress_size > MAX_COMPRESSION_RATIO
    ):
        raise ValueError(
            f"{label} exceeds the {MAX_COMPRESSION_RATIO}:1 compression-ratio limit"
        )


def fmt_minutes(minutes):
    """65 -> '1h5m', 60 -> '1h', 45 -> '45m', 0 -> '0m'."""
    hours, rem = divmod(int(minutes), 60)
    if hours and rem:
        return f"{hours}h{rem}m"
    if hours:
        return f"{hours}h"
    return f"{rem}m"


def merge_intervals(intervals):
    """Merge overlapping/touching (start, end) tuples; return merged list.

    Used to de-duplicate the same sleep span reported by multiple devices.
    """
    merged = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            if end > merged[-1][1]:
                merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))
    return merged
