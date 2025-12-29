from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.domain.livekit_agents.caption_agent.delivery.s3_uploader import CaptionS3Uploader


class _FakeSession:
    def __init__(self, *, session_id: str, started_at: datetime) -> None:
        self.id = session_id  # MongoDB _id field
        self.session_id = session_id
        self.started_at = started_at
        self.caption_last_uploaded_segment: int | None = None
        self.caption_s3_urls: dict[str, str] | None = None
        self.saved = False
        self.version = 1

    async def save(self) -> None:
        self.saved = True

    async def save_session_with_version_check(self) -> bool:
        self.saved = True
        return True

    async def partial_update_session_with_version_check(
        self, updates, max_retry_on_conflicts: int = 0
    ) -> bool:
        self.saved = True
        self.version += 1
        return True

    def model_dump(self, **kwargs):
        return {
            "id": self.id,
            "session_id": self.session_id,
            "started_at": self.started_at,
            "caption_last_uploaded_segment": self.caption_last_uploaded_segment,
            "caption_s3_urls": self.caption_s3_urls,
            "version": self.version,
        }


class _MockTranscript:
    def __init__(
        self,
        *,
        text: str,
        start_time: float,
        end_time: float,
        translations: dict[str, str] | None = None,
    ) -> None:
        self.text = text
        self.start_time = start_time
        self.end_time = end_time
        self.translations = translations or {}


def test_build_m3u8_content_uses_relative_uris() -> None:
    uploader = CaptionS3Uploader(redis_label="test")

    content = uploader._build_m3u8_content(media_sequence=0, latest_segment=2)
    assert content.startswith("#EXTM3U\n")
    assert "#EXT-X-TARGETDURATION:4" in content
    assert "#EXT-X-MEDIA-SEQUENCE:0" in content
    assert "amazonaws.com" not in content
    assert "captions-0.vtt" in content
    assert "captions-1.vtt" in content
    assert "captions-2.vtt" in content

    content_es = uploader._build_m3u8_content(media_sequence=0, latest_segment=1, language="es")
    assert "captions-es-0.vtt" in content_es
    assert "captions-es-1.vtt" in content_es


@pytest.mark.asyncio
async def test_upload_session_captions_splits_cache_controls(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.domain.livekit_agents.caption_agent.delivery.s3_uploader as uploader_mod

    calls: list[tuple[str | None, list[str]]] = []

    async def _fake_upload_caption_files_batch(*, session_id: str, files, cache_control=None):
        calls.append((cache_control, [name for name, _, _ in files]))
        return {name: f"https://cdn.example/{session_id}/{name}" for name, _, _ in files}

    monkeypatch.setattr(
        uploader_mod.s3_service,
        "upload_caption_files_batch",
        _fake_upload_caption_files_batch,
    )

    started_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
    base_ts = started_at.timestamp()
    transcripts = [
        _MockTranscript(
            text="hi",
            start_time=base_ts + 1.0,
            end_time=base_ts + 9.0,
            translations={"es": "hola"},
        )
    ]

    session = _FakeSession(session_id="sess_1", started_at=started_at)
    uploader = CaptionS3Uploader(redis_label="test")

    await uploader._upload_session_captions(session, transcripts)  # type: ignore[arg-type]

    assert session.saved is True
    assert session.caption_last_uploaded_segment == 2
    assert session.caption_s3_urls is not None
    assert "captions.m3u8" in session.caption_s3_urls
    assert "captions-es.m3u8" in session.caption_s3_urls
    assert "captions-0.vtt" in session.caption_s3_urls
    assert "captions-es-2.vtt" in session.caption_s3_urls

    # Two uploads: segments first (long cache), then playlists (short cache).
    assert len(calls) == 2
    assert calls[0][0] == CaptionS3Uploader.SEGMENT_CACHE_CONTROL
    assert all(name.endswith(".vtt") for name in calls[0][1])
    assert calls[1][0] == CaptionS3Uploader.PLAYLIST_CACHE_CONTROL
    assert all(name.endswith(".m3u8") for name in calls[1][1])
