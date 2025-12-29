"""Room-level multi-participant caption transcriber.

This module provides a single-job implementation that transcribes microphone tracks
for multiple participants in the same room and attaches participant_identity per
transcript segment (persistence + publishing).
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Mapping

from livekit import rtc
from livekit.agents import inference, stt, utils, vad
from livekit.plugins import silero
from loguru import logger

from app.domain.livekit_agents.caption_agent.stt.config import (
    CustomSttConfig,
    SpeakerSttConfig,
    SttConfigType,
    resolve_stt_model,
)
from app.domain.livekit_agents.caption_agent.transcripts.pipeline import TranscriptPipeline
from app.utils.app_errors import AppError, AppErrorCode, HttpStatusCode


class RoomCaptionTranscriber:
    """Transcribes microphone audio for all subscribed participants in a room."""

    STT_LANGUAGE_ATTRIBUTE = "stt_language"

    def __init__(
        self,
        *,
        room: rtc.Room,
        session_id: str,
        room_id: str,
        translation_languages: list[str] | None = None,
        speaker_configs: Mapping[str, SttConfigType] | None = None,
        default_stt: SttConfigType,
        vad_instance: vad.VAD | None = None,
    ) -> None:
        self._room = room
        self._session_id = session_id
        self._room_id = room_id
        self._translation_languages = translation_languages
        self._speaker_configs = dict(speaker_configs) if speaker_configs else {}
        self._default_stt = default_stt

        self._vad: vad.VAD | None = vad_instance
        self._pipeline = TranscriptPipeline.create_default(
            session_id=session_id,
            room_id=room_id,
            room=room,
            translation_languages=translation_languages,
        )

        self._tasks: set[asyncio.Task[None]] = set()
        self._participant_tasks: dict[str, asyncio.Task[None]] = {}
        self._participant_tracks: dict[
            str, tuple[rtc.RemoteAudioTrack, rtc.RemoteTrackPublication]
        ] = {}
        self._closed = False

    def start(self) -> None:
        self._room.on("track_subscribed", self._on_track_subscribed)
        self._room.on("track_unsubscribed", self._on_track_unsubscribed)
        self._room.on("track_unpublished", self._on_track_unpublished)
        self._room.on("participant_disconnected", self._on_participant_disconnected)
        self._room.on("participant_attributes_changed", self._on_participant_attributes_changed)
        logger.info(
            f"RoomCaptionTranscriber started: session={self._session_id} room={self._room_id}"
        )

    def handle_existing_tracks(self) -> None:
        for participant in self._room.remote_participants.values():
            for publication in participant.track_publications.values():
                track = publication.track
                if track is None:
                    continue
                if not isinstance(track, rtc.RemoteAudioTrack):
                    continue
                self._on_track_subscribed(track, publication, participant)

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True

        self._room.off("track_subscribed", self._on_track_subscribed)
        self._room.off("track_unsubscribed", self._on_track_unsubscribed)
        self._room.off("track_unpublished", self._on_track_unpublished)
        self._room.off("participant_disconnected", self._on_participant_disconnected)
        self._room.off("participant_attributes_changed", self._on_participant_attributes_changed)

        await utils.aio.cancel_and_wait(*self._tasks)
        self._tasks.clear()
        self._participant_tasks.clear()
        self._participant_tracks.clear()

    def _get_or_load_vad(self) -> vad.VAD:
        if self._vad is None:
            self._vad = silero.VAD.load()
        return self._vad

    def _on_track_subscribed(
        self,
        track: rtc.Track,
        publication: rtc.RemoteTrackPublication,
        participant: rtc.RemoteParticipant,
    ) -> None:
        if self._closed:
            return
        if not isinstance(track, rtc.RemoteAudioTrack):
            return
        if publication.source != rtc.TrackSource.SOURCE_MICROPHONE:
            return

        identity = participant.identity
        previous_task = self._participant_tasks.get(identity)
        if previous_task and not previous_task.done():
            previous_task.cancel()

        self._participant_tracks[identity] = (track, publication)
        task = asyncio.create_task(
            self._transcribe_track(
                participant_identity=identity, track=track, publication=publication
            )
        )
        self._participant_tasks[identity] = task
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _on_track_unsubscribed(
        self,
        track: rtc.Track,
        publication: rtc.RemoteTrackPublication,
        participant: rtc.RemoteParticipant,
    ) -> None:
        if not isinstance(track, rtc.RemoteAudioTrack):
            return
        self._stop_participant(participant.identity)

    def _on_track_unpublished(
        self,
        publication: rtc.RemoteTrackPublication,
        participant: rtc.RemoteParticipant,
    ) -> None:
        self._stop_participant(participant.identity)

    def _on_participant_disconnected(self, participant: rtc.RemoteParticipant) -> None:
        self._stop_participant(participant.identity)

    def _on_participant_attributes_changed(
        self, changed_attributes: dict[str, str], participant: rtc.Participant
    ) -> None:
        if self.STT_LANGUAGE_ATTRIBUTE not in changed_attributes:
            return
        identity = participant.identity
        self._restart_participant(identity)

    def _stop_participant(self, identity: str) -> None:
        task = self._participant_tasks.pop(identity, None)
        if task and not task.done():
            task.cancel()
        self._participant_tracks.pop(identity, None)

    def _restart_participant(self, identity: str) -> None:
        if identity not in self._participant_tracks:
            return
        track, publication = self._participant_tracks[identity]
        participant = self._room.remote_participants.get(identity)
        if participant is None:
            return
        self._on_track_subscribed(track, publication, participant)

    def _resolve_stt_config(self, participant_identity: str) -> SttConfigType:
        participant = self._room.remote_participants.get(participant_identity)
        if participant and self.STT_LANGUAGE_ATTRIBUTE in participant.attributes:
            return SpeakerSttConfig(language=participant.attributes[self.STT_LANGUAGE_ATTRIBUTE])
        return self._speaker_configs.get(participant_identity, self._default_stt)

    def _build_stt_instance(self, stt_config: SttConfigType) -> tuple[stt.STT, bool]:
        stt_model, custom_config = resolve_stt_model(stt_config)
        use_vad = False

        if isinstance(custom_config, CustomSttConfig):
            use_vad = custom_config.use_vad
            stt_instance = custom_config.stt
        elif isinstance(stt_model, stt.STT):
            stt_instance = stt_model
        elif isinstance(stt_model, str):
            stt_instance = inference.STT.from_model_string(stt_model)
        else:
            raise AppError(
                AppErrorCode.E_UNSUPPORTED_STT_CONFIG,
                f"Unsupported STT config: {type(stt_config)}",
                HttpStatusCode.BAD_REQUEST,
            )

        if use_vad or not stt_instance.capabilities.streaming:
            stt_instance = stt.StreamAdapter(stt=stt_instance, vad=self._get_or_load_vad())

        return stt_instance, use_vad

    async def _transcribe_track(
        self,
        *,
        participant_identity: str,
        track: rtc.RemoteAudioTrack,
        publication: rtc.RemoteTrackPublication,
    ) -> None:
        extra = {"participant": participant_identity, "track_sid": publication.sid}
        logger.info("Starting transcription", extra=extra)

        stt_config = self._resolve_stt_config(participant_identity)
        stt_instance, _ = self._build_stt_instance(stt_config)

        audio_stream = rtc.AudioStream.from_track(
            track=track,
            sample_rate=24000,
            num_channels=1,
            frame_size_ms=50,
            noise_cancellation=None,
        )

        async def _forward_audio(stream: stt.RecognizeStream) -> None:
            try:
                async for ev in audio_stream:
                    stream.push_frame(ev.frame)
            finally:
                with contextlib.suppress(RuntimeError):
                    stream.end_input()

        try:
            async with stt_instance.stream() as stream:
                forward_task = asyncio.create_task(_forward_audio(stream))
                try:
                    async for ev in stream:
                        if (
                            ev.type == stt.SpeechEventType.FINAL_TRANSCRIPT
                            and ev.alternatives
                            and ev.alternatives[0].text.strip()
                        ):
                            await self._pipeline.handle_final_speech(
                                participant_identity=participant_identity,
                                speech=ev.alternatives[0],
                            )
                finally:
                    await utils.aio.cancel_and_wait(forward_task)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception(f"Transcription task failed: {exc}", extra=extra)
        finally:
            await audio_stream.aclose()
            try:
                wrapped = getattr(stt_instance, "wrapped_stt", None)
                await stt_instance.aclose()
                if wrapped is not None and hasattr(wrapped, "aclose"):
                    await wrapped.aclose()
            except Exception:
                pass
            logger.info("Stopped transcription", extra=extra)
