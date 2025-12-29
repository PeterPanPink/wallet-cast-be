"""LiveKit helper service.

This module provides a thin wrapper around the `livekit-api` package.

Based on the official LiveKit Python SDK:
https://github.com/livekit/python-sdks

Usage:
    from app.services.integrations.livekit_service import livekit_service

    # Generate access token (async - checks room capacity by default)
    token = await livekit_service.create_access_token(
        identity="user-123",
        room="my-room",
        name="John Doe"
    )

    # Update room metadata
    room_info = await livekit_service.update_room_metadata(
        room="my-room",
        metadata='{"layout":"grid"}'
    )
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from livekit import api
from livekit.api.access_token import AccessToken
from livekit.protocol.models import ParticipantInfo
from loguru import logger

from app.app_config import get_app_environ_config
from app.utils.app_errors import AppError, AppErrorCode, HttpStatusCode


class LivekitService:
    """Service wrapper for LiveKit server SDK (livekit-api package).

    This service provides specific methods for LiveKit operations to make
    usage patterns explicit and discoverable.
    """

    def __init__(self) -> None:
        self._cfg = get_app_environ_config()
        self._demo_mode = bool(getattr(self._cfg, "DEMO_MODE", True))
        logger.info("LivekitService initialized")

    @asynccontextmanager
    async def _get_api_client(self) -> AsyncIterator[api.LiveKitAPI]:
        """Internal method to get LiveKit API client.

        This is private to force callers to use specific methods.

        Yields:
            LiveKitAPI instance

        Raises:
            ValueError: If LIVEKIT_URL is not configured
        """
        url = self._cfg.LIVEKIT_URL
        if not url:
            logger.error("LIVEKIT_URL not configured")
            raise AppError(
                errcode=AppErrorCode.E_INVALID_REQUEST,
                errmesg="RTC provider URL must be configured. Set it in env.local or environment variables.",
                status_code=HttpStatusCode.BAD_REQUEST,
            )

        logger.debug(f"Creating LiveKit API client for URL={url}")
        async with api.LiveKitAPI(url) as lkapi:
            yield lkapi

    async def get_room(self, room_name: str) -> api.Room | None:
        """Get room info by name.

        Args:
            room_name: Name of the room to lookup

        Returns:
            Room object if found, None otherwise

        Raises:
            ValueError: If LIVEKIT_URL is not configured
        """
        if self._demo_mode:
            logger.info("LivekitService DEMO_MODE=true: get_room returns None (stub)")
            return None

        logger.debug(f"Getting room info for: {room_name}")
        async with self._get_api_client() as lkapi:
            response = await lkapi.room.list_rooms(api.ListRoomsRequest(names=[room_name]))
            if response.rooms:
                return response.rooms[0]
            return None

    async def get_room_participants(self, room_name: str) -> list[ParticipantInfo]:
        """Get all participants in a room.

        Args:
            room_name: Name of the room

        Returns:
            List of ParticipantInfo objects

        Raises:
            ValueError: If LIVEKIT_URL is not configured
        """
        if self._demo_mode:
            logger.info("LivekitService DEMO_MODE=true: get_room_participants returns [] (stub)")
            return []

        logger.debug(f"Getting participants for room: {room_name}")
        async with self._get_api_client() as lkapi:
            response = await lkapi.room.list_participants(
                api.ListParticipantsRequest(room=room_name)
            )
            return list(response.participants)

    async def create_access_token(
        self,
        identity: str,
        room: str | None = None,
        name: str | None = None,
        metadata: str | None = None,
        room_join: bool = True,
        room_admin: bool = False,
        room_create: bool = False,
        room_list: bool = False,
        room_record: bool = False,
        can_publish: bool = True,
        can_subscribe: bool = True,
        can_publish_data: bool = True,
        kind: AccessToken.ParticipantKind = "standard",
        max_participants: int | None = None,
        check_capacity: bool = True,
    ) -> str:
        """Create and return a LiveKit JWT access token.

        This follows the official LiveKit Python SDK API pattern:
        https://github.com/livekit/python-sdks#generating-an-access-token

        Args:
            identity: Unique identity for the participant
            room: Room name to grant access to (optional)
            name: Display name for the participant (optional)
            metadata: Custom metadata string (optional)
            room_join: Grant permission to join rooms (default: True)
            room_admin: Grant admin privileges in the room (default: False)
            room_create: Grant permission to create rooms (default: False)
            room_list: Grant permission to list rooms (default: False)
            room_record: Grant permission to record rooms (default: False)
            can_publish: Grant permission to publish tracks (default: True)
            can_subscribe: Grant permission to subscribe to tracks (default: True)
            can_publish_data: Grant permission to publish data (default: True)
            kind: Participant kind (default: "standard")
            max_participants: Maximum number of participants allowed in the room (optional)
            check_capacity: Whether to check room capacity before creating token (default: True)

        Returns:
            JWT token string

        Raises:
            ValueError: If LIVEKIT_API_KEY or LIVEKIT_API_SECRET is not configured
            AppError: If the room is at capacity (when check_capacity=True) or
                     if the display name is already in use in the room
        """
        if self._demo_mode:
            # Demo-safe token: deterministic placeholder (NOT a real JWT).
            room_part = room or "any-room"
            return f"DEMO_RTC_TOKEN::{identity}::{room_part}"

        # Validate configuration
        api_key = self._cfg.LIVEKIT_API_KEY
        api_secret = self._cfg.LIVEKIT_API_SECRET

        if not api_key or not api_secret:
            logger.error("LIVEKIT_API_KEY or LIVEKIT_API_SECRET not configured")
            raise AppError(
                errcode=AppErrorCode.E_INVALID_REQUEST,
                errmesg="RTC provider credentials must be configured. Set them in env.local or environment variables.",
                status_code=HttpStatusCode.BAD_REQUEST,
            )

        # Check room capacity and name conflicts (if room is specified)
        # Optimize by fetching room data once and performing both checks
        if room and ((check_capacity and kind == "standard") or name):
            room_obj = await self.get_room(room)
            participants = await self.get_room_participants(room) if room_obj else []

            # Check capacity if needed
            if check_capacity and kind == "standard" and room_obj:
                max_participants = room_obj.max_participants
                if max_participants > 0:
                    standard_count = sum(
                        1
                        for p in participants
                        if p.kind == ParticipantInfo.Kind.STANDARD and p.identity != identity
                    )
                    if standard_count >= max_participants:
                        error_msg = f"Room '{room}' is at capacity ({standard_count}/{max_participants} standard participants)"
                        logger.warning(
                            f"Room capacity exceeded for identity={identity}, room={room}: {error_msg}"
                        )
                        raise AppError(
                            errcode=AppErrorCode.E_ROOM_CAPACITY,
                            errmesg=error_msg,
                            status_code=HttpStatusCode.FORBIDDEN,
                        )

            # Check for name conflicts if name is specified
            if name and room_obj:
                for p in participants:
                    if p.identity != identity and p.name.lower() == name.lower():
                        error_msg = f"Display name '{name}' is already in use in room '{room}'"
                        logger.warning(
                            f"Name conflict for identity={identity}, room={room}, name={name}: {error_msg}"
                        )
                        raise AppError(
                            errcode=AppErrorCode.E_NAME_CONFLICT,
                            errmesg=error_msg,
                            status_code=HttpStatusCode.CONFLICT,
                        )

        logger.info(
            f"Creating LiveKit access token for identity={identity}, room={room}, name={name}"
        )

        # Build token using fluent API
        token = api.AccessToken(api_key, api_secret).with_identity(identity)
        token = token.with_kind(kind)

        if name:
            token = token.with_name(name)

        # Add video grants
        grants = api.VideoGrants(
            room_join=room_join,
            room=room or "",
            room_admin=room_admin,
            room_create=room_create,
            room_list=room_list,
            room_record=room_record,
            can_publish=can_publish,
            can_subscribe=can_subscribe,
            can_publish_data=can_publish_data,
        )
        token = token.with_grants(grants)

        if metadata:
            token = token.with_metadata(metadata)

        # Add room configuration if max_participants is specified
        if max_participants is not None:
            room_config = api.RoomConfiguration(max_participants=max_participants)
            token = token.with_room_config(room_config)

        jwt_token = token.to_jwt()
        logger.debug(f"Successfully created LiveKit access token for identity={identity}")
        return jwt_token

    def create_recorder_token(
        self,
        room: str,
    ) -> str:
        if self._demo_mode:
            return f"DEMO_RECORDER_TOKEN::{room}"
        """Create a LiveKit access token for web egress recorder.

        This creates a special token that allows the egress service to connect to
        a room and subscribe to all tracks without publishing. The token is used
        to construct the URL for the web egress recording page.

        Args:
            room: Room name to grant access to

        Returns:
            JWT token string for the recorder

        Raises:
            ValueError: If LIVEKIT_API_KEY or LIVEKIT_API_SECRET is not configured
        """
        # Validate configuration
        api_key = self._cfg.LIVEKIT_API_KEY
        api_secret = self._cfg.LIVEKIT_API_SECRET

        if not api_key or not api_secret:
            logger.error("LIVEKIT_API_KEY or LIVEKIT_API_SECRET not configured")
            raise AppError(
                errcode=AppErrorCode.E_INVALID_REQUEST,
                errmesg="RTC provider credentials must be configured. Set them in env.local or environment variables.",
                status_code=HttpStatusCode.BAD_REQUEST,
            )

        logger.info(f"Creating recorder token for room={room}")

        # Build recorder token - it should only subscribe, not publish
        identity = f"recorder-{room}"
        token = api.AccessToken(api_key, api_secret).with_identity(identity)
        token = token.with_name("Recorder")

        # Recorder needs to join and subscribe but not publish
        grants = api.VideoGrants(
            room_join=True,
            room=room,
            room_admin=False,
            can_publish=False,
            can_subscribe=True,
            can_publish_data=False,
            hidden=True,  # Hide recorder from participant list
        )
        token = token.with_grants(grants)

        jwt_token = token.to_jwt()
        logger.debug(f"Successfully created recorder token for room={room}")
        return jwt_token

    async def create_room(
        self,
        room_name: str,
        metadata: str | None = None,
        empty_timeout: int = 300,
        max_participants: int = 20,
    ) -> Any:
        """Create a LiveKit room.

        Args:
            room_name: Unique name for the room
            metadata: Optional JSON string containing room metadata
            empty_timeout: Timeout in seconds before room closes when empty (default: 300)
            max_participants: Maximum number of participants allowed (default: 20)

        Returns:
            Room object with .name, .sid, .metadata, .empty_timeout, .max_participants attributes

        Raises:
            ValueError: If LIVEKIT_URL is not configured
            Exception: If the API request fails

        Example:
            room = await livekit_service.create_room(
                room_name="my-livestream",
                metadata='{"layout":"grid"}',
                empty_timeout=600,
            )
            print(f"Created room {room.name} with SID {room.sid}")
        """
        logger.info(
            f"Creating LiveKit room: room_name={room_name}, empty_timeout={empty_timeout}, max_participants={max_participants}"
        )
        async with self._get_api_client() as lkapi:
            room = await lkapi.room.create_room(
                api.CreateRoomRequest(
                    name=room_name,
                    metadata=metadata or "",
                    empty_timeout=empty_timeout,
                    max_participants=max_participants,
                )
            )
            logger.debug(f"Successfully created LiveKit room: name={room.name}, sid={room.sid}")
            return room

    async def delete_room(
        self,
        room_name: str,
    ) -> None:
        """Delete a LiveKit room.

        Args:
            room_name: Room name or SID to delete

        Raises:
            ValueError: If LIVEKIT_URL is not configured
            Exception: If the API request fails

        Example:
            await livekit_service.delete_room(room_name="my-room")
        """
        logger.info(f"Deleting LiveKit room: room_name={room_name}")
        async with self._get_api_client() as lkapi:
            try:
                await lkapi.room.delete_room(api.DeleteRoomRequest(room=room_name))
                logger.debug(f"Successfully deleted LiveKit room: name={room_name}")
            except Exception as e:
                if "not_found" in str(e) or "does not exist" in str(e):
                    logger.info(f"LiveKit room already deleted or not found: name={room_name}")
                else:
                    raise

    async def update_room_metadata(
        self,
        room: str,
        metadata: str,
    ) -> Any:
        """Update metadata for a LiveKit room.

        Args:
            room: Room name or SID
            metadata: JSON string containing room metadata

        Returns:
            Room object with updated metadata (has .name, .sid, .metadata attributes)

        Raises:
            ValueError: If LIVEKIT_URL is not configured
            Exception: If the API request fails

        Example:
            room_info = await livekit_service.update_room_metadata(
                room="my-room",
                metadata='{"layout":"grid","theme":"dark"}'
            )
            print(f"Updated room {room_info.name}")
        """
        logger.info(f"Updating room metadata for room={room}")
        async with self._get_api_client() as lkapi:
            room_info = await lkapi.room.update_room_metadata(
                api.UpdateRoomMetadataRequest(
                    room=room,
                    metadata=metadata,
                )
            )
            logger.debug(
                f"Successfully updated room metadata for room={room_info.name}, sid={room_info.sid}"
            )
            return room_info

    async def start_room_composite_egress(
        self,
        request: api.RoomCompositeEgressRequest,
    ) -> Any:
        """Start a room composite egress.

        Args:
            request: RoomCompositeEgressRequest with room_name, layout, and outputs

        Returns:
            EgressInfo object with .egress_id attribute

        Raises:
            ValueError: If LIVEKIT_URL is not configured
            Exception: If the API request fails

        Example:
            egress_request = api.RoomCompositeEgressRequest(
                room_name="my-room",
                layout="speaker",
                stream_outputs=[api.StreamOutput(
                    protocol=api.StreamProtocol.RTMP,
                    urls=["rtmp://example.com/live/key"]
                )]
            )
            egress_info = await livekit_service.start_room_composite_egress(egress_request)
            print(f"Started egress: {egress_info.egress_id}")
        """
        logger.info(f"Starting room composite egress for room={request.room_name}")
        async with self._get_api_client() as lkapi:
            egress_info = await lkapi.egress.start_room_composite_egress(request)
            logger.debug(
                f"Successfully started egress: egress_id={egress_info.egress_id} for room={request.room_name}"
            )
            return egress_info

    async def start_web_egress(
        self,
        request: api.WebEgressRequest,
    ) -> Any:
        """Start a web egress to record a web page.

        Web egress is used to record a custom web page that displays the room content.
        This allows for custom layouts, branding, and other visual elements.

        Args:
            request: WebEgressRequest with url and output configurations

        Returns:
            EgressInfo object with .egress_id attribute

        Raises:
            ValueError: If LIVEKIT_URL is not configured
            Exception: If the API request fails

        Example:
            egress_request = api.WebEgressRequest(
                url="https://example.com/_recording?token=xxx&livekit_url=wss://...",
                stream_outputs=[api.StreamOutput(
                    protocol=api.StreamProtocol.RTMP,
                    urls=["rtmp://live.mux.com/app/stream-key"]
                )]
            )
            egress_info = await livekit_service.start_web_egress(egress_request)
            print(f"Started web egress: {egress_info.egress_id}")
        """
        logger.info(f"Starting web egress for url={request.url}")
        async with self._get_api_client() as lkapi:
            egress_info = await lkapi.egress.start_web_egress(request)
            logger.debug(f"Successfully started web egress: egress_id={egress_info.egress_id}")
            return egress_info

    async def stop_egress(
        self,
        egress_id: str,
    ) -> Any:
        """Stop an active egress (idempotent).

        This method is idempotent - if the egress is already stopped (COMPLETE, FAILED, or ABORTED),
        it will return the existing egress info instead of raising an error.

        Args:
            egress_id: Egress ID to stop

        Returns:
            EgressInfo object with status

        Raises:
            ValueError: If LIVEKIT_URL is not configured
            Exception: If the API request fails for reasons other than egress already stopped

        Example:
            await livekit_service.stop_egress(egress_id="EG_...")
        """
        logger.info(f"Stopping egress: egress_id={egress_id}")
        async with self._get_api_client() as lkapi:
            try:
                egress_info = await lkapi.egress.stop_egress(
                    api.StopEgressRequest(egress_id=egress_id)
                )
                logger.debug(f"Successfully stopped egress: {egress_id}")
                return egress_info
            except api.TwirpError as e:
                # Check if the error is because egress is already in a terminal state
                if e.code == "failed_precondition":
                    # Get the current egress status to verify it's in a terminal state
                    response = await lkapi.egress.list_egress(
                        api.ListEgressRequest(egress_id=egress_id)
                    )
                    if response.items:
                        egress_info = response.items[0]
                        terminal_statuses = (
                            api.EgressStatus.EGRESS_COMPLETE,
                            api.EgressStatus.EGRESS_FAILED,
                            api.EgressStatus.EGRESS_ABORTED,
                            api.EgressStatus.EGRESS_LIMIT_REACHED,
                        )
                        if egress_info.status in terminal_statuses:
                            logger.info(
                                f"Egress already stopped: egress_id={egress_id}, "
                                f"status={api.EgressStatus.Name(egress_info.status)}"
                            )
                            return egress_info
                # Re-raise if not a terminal state or unknown error
                raise

    async def create_agent_dispatch(
        self,
        agent_name: str,
        room_name: str,
        metadata: str | None = None,
    ) -> Any:
        """Create an explicit agent dispatch to join a room.

        This dispatches an agent to a specific room. The agent must be registered
        with an agent_name in the agent server decorator.

        Args:
            agent_name: Name of the agent to dispatch (must match @server.rtc_session(agent_name=...))
            room_name: Room name to dispatch agent to
            metadata: Optional JSON string containing job metadata for the agent

        Returns:
            AgentDispatch object with dispatch info

        Raises:
            ValueError: If LIVEKIT_URL is not configured
            Exception: If the API request fails

        Example:
            dispatch = await livekit_service.create_agent_dispatch(
                agent_name="caption-agent",
                room_name="my-room",
                metadata='{"mode":"caption","target_language":"Spanish"}'
            )
            print(f"Dispatched agent {dispatch.agent_name} to room {dispatch.room}")

        Reference:
            https://docs.livekit.io/agents/server/agent-dispatch/#explicit
        """
        logger.info(f"Creating agent dispatch: agent_name={agent_name}, room={room_name}")
        async with self._get_api_client() as lkapi:
            dispatch = await lkapi.agent_dispatch.create_dispatch(
                api.CreateAgentDispatchRequest(
                    agent_name=agent_name,
                    room=room_name,
                    metadata=metadata or "",
                )
            )
            logger.debug(
                f"Successfully created agent dispatch: agent={agent_name}, room={room_name}"
            )
            return dispatch

    async def update_participant(
        self,
        room: str,
        identity: str,
        name: str | None = None,
        metadata: str | None = None,
        attributes: dict[str, str] | None = None,
    ) -> Any:
        """Update participant display name, metadata, and/or attributes.

        Args:
            room: Room name where the participant is
            identity: Identity of the participant to update
            name: New display name for the participant (optional)
            metadata: New metadata for the participant (optional)
            attributes: Key-value attributes to update (optional)

        Returns:
            ParticipantInfo object with updated participant details

        Raises:
            ValueError: If LIVEKIT_URL is not configured or no update fields provided
            Exception: If the API request fails

        Example:
            participant = await livekit_service.update_participant(
                room="my-room",
                identity="guest-123",
                name="New Display Name",
                attributes={"stt_language": "zh"}
            )
            print(f"Updated participant {participant.identity}")

        Reference:
            https://docs.livekit.io/home/server/managing-participants/#updateparticipant
        """
        if name is None and metadata is None and attributes is None:
            raise AppError(
                errcode=AppErrorCode.E_INVALID_REQUEST,
                errmesg="At least one of 'name', 'metadata', or 'attributes' must be provided",
                status_code=HttpStatusCode.BAD_REQUEST,
            )

        logger.info(
            f"Updating participant: room={room}, identity={identity}, "
            f"name={name}, attributes={attributes}"
        )

        async with self._get_api_client() as lkapi:
            participant = await lkapi.room.update_participant(
                api.UpdateParticipantRequest(
                    room=room,
                    identity=identity,
                    name=name or "",
                    metadata=metadata or "",
                    attributes=attributes or {},
                )
            )
            logger.debug(
                f"Successfully updated participant: identity={participant.identity}, "
                f"name={participant.name}, attributes={dict(participant.attributes)}"
            )
            return participant


# Module-level singleton
livekit_service = LivekitService()


__all__ = ["LivekitService", "livekit_service"]
