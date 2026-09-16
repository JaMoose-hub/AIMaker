from app.capture import sources
from app.capture.sources import MjpegFrameParser


def test_every_chunk_boundary_preserves_native_jpeg_and_tail():
    frames = [b'\xff\xd8' + bytes([i])*105 + b'\xff\x00\x03\xff\xd9' for i in range(3)]
    payload = b'noise' + b''.join(frames) + b'\xff\xd8partial'
    for size in (1, 2, 3, 7, 64, 4096):
        parser = MjpegFrameParser()
        actual = []
        for offset in range(0, len(payload), size):
            actual += parser.feed(payload[offset:offset+size])
        assert actual == frames
        assert parser.buffer == b'\xff\xd8partial'


def test_parser_does_not_rescan_prior_jpeg_payload():
    class CountScans(bytearray):
        scanned = 0
        def find(self, value, start=0):
            self.scanned += max(0, len(self) - start)
            return super().find(value, start)
    buffer = CountScans()
    parser = MjpegFrameParser(buffer)
    payload = b'\xff\xd8' + b'x' * 50000 + b'\xff\xd9'
    result = []
    for offset in range(0, len(payload), 64):
        result += parser.feed(payload[offset:offset+64])
    assert result == [payload]
    assert buffer.scanned < len(payload) * 2


def test_corrupt_oversized_frame_is_bounded_and_recovers(monkeypatch):
    monkeypatch.setattr(sources, '_MAX_MJPEG_BUFFER_BYTES', 64)
    parser = MjpegFrameParser()
    assert parser.feed(b'\xff\xd8' + b'x'*80) == []
    assert not parser.buffer
    assert parser.feed(b'\xff\xd8good\xff\xd9') == [b'\xff\xd8good\xff\xd9']
    assert parser.feed(b'\xff\xd8' + b'x'*80 + b'\xff\xd8new') == []
    assert parser.buffer == b'\xff\xd8new'
    assert parser.feed(b'\xff\xd9') == [b'\xff\xd8new\xff\xd9']
