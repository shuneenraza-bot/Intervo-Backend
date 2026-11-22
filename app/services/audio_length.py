"""Length of an uploaded recording in seconds, read from the file itself before anything is
sent to a speech service. WAV uses the standard library, WebM is read from its Matroska
elements, and MP3 / OGG / M4A use mutagen. Returns None when the length cannot be read."""

import io
import struct
import wave

_MASTERS = {0x18538067, 0x1F43B675, 0x1549A966, 0xA0}  # Segment, Cluster, Info, BlockGroup
_ID_EBML = 0x1A45DFA3
_ID_TIMESCALE, _ID_DURATION, _ID_CLUSTER_TC = 0x2AD7B1, 0x4489, 0xE7
_ID_SIMPLEBLOCK, _ID_BLOCK = 0xA3, 0xA1


def _wav(data: bytes) -> float | None:
    try:
        with wave.open(io.BytesIO(data)) as w:
            return w.getnframes() / float(w.getframerate() or 1)
    except Exception:
        return None


def _vint(data: bytes, pos: int, keep_marker: bool) -> tuple[int, int, bool] | None:
    """(value, length, unknown_size) of the variable-length integer at pos."""
    if pos >= len(data):
        return None
    first = data[pos]
    length = 1
    while length <= 8 and not first & (0x80 >> (length - 1)):
        length += 1
    if length > 8 or pos + length > len(data):
        return None
    value = first if keep_marker else first & (0xFF >> length)
    for b in data[pos + 1:pos + length]:
        value = (value << 8) | b
    unknown = not keep_marker and value == (1 << (7 * length)) - 1
    return value, length, unknown


def _webm(data: bytes) -> float | None:
    """Matroska duration: the Info/Duration element if present (MediaRecorder leaves it out),
    otherwise the timestamp of the last block."""
    scale, declared, cluster_tc, last_ms = 1_000_000, None, 0, None
    pos = 0
    try:
        while pos < len(data):
            el = _vint(data, pos, True)
            if el is None:
                break
            el_id, id_len, _ = el
            sz = _vint(data, pos + id_len, False)
            if sz is None:
                break
            size, size_len, unknown = sz
            body = pos + id_len + size_len
            if el_id in _MASTERS:
                pos = body  # descend: children follow, siblings are read in the same loop
                continue
            if unknown or body + size > len(data):
                break
            payload = data[body:body + size]
            if el_id == _ID_TIMESCALE:
                scale = int.from_bytes(payload, "big")
            elif el_id == _ID_DURATION and size in (4, 8):
                declared = struct.unpack(">f" if size == 4 else ">d", payload)[0]
            elif el_id == _ID_CLUSTER_TC:
                cluster_tc = int.from_bytes(payload, "big")
            elif el_id in (_ID_SIMPLEBLOCK, _ID_BLOCK):
                track = _vint(payload, 0, False)
                if track is not None and len(payload) >= track[1] + 2:
                    rel = struct.unpack(">h", payload[track[1]:track[1] + 2])[0]
                    last_ms = max(last_ms or 0, (cluster_tc + rel) * scale / 1_000_000)
            pos = body + size
    except Exception:
        return None
    if declared:
        return declared * scale / 1_000_000_000
    return last_ms / 1000 if last_ms is not None else None


def _mutagen(data: bytes) -> float | None:
    try:
        import mutagen

        f = mutagen.File(io.BytesIO(data))
        length = getattr(getattr(f, "info", None), "length", None)
        return float(length) if length else None
    except Exception:
        return None


def audio_seconds(ext: str, data: bytes) -> float | None:
    if ext == "wav":
        return _wav(data)
    if ext == "webm":
        return _webm(data)
    return _mutagen(data)
