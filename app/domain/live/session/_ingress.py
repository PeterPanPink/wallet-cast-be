"""LiveKit ingress operations for session management."""

from typing import Any

from loguru import logger

from app.app_config import get_app_environ_config
from app.utils.app_errors import AppError, AppErrorCode, HttpStatusCode

from ._base import BaseService


class IngressOperations(BaseService):
    """LiveKit ingress-related operations."""

    async def create_room(
        self,
        room_name: str,
        metadata: str | None = None,
        empty_timeout: int = 300,
        max_participants: int = 100,
    ) -> Any:
        """Create a LiveKit room.

        Args:
            room_name: Unique name for the room (also used as room_id to fetch session)
            metadata: Optional JSON string containing room metadata
            empty_timeout: Timeout in seconds before room closes when empty (default: 300)
            max_participants: Maximum number of participants allowed (default: 100)

        Returns:
            Room object with .name, .sid, .metadata, .empty_timeout, .max_participants attributes

        Raises:
            ValueError: If LIVEKIT_URL is not configured or state transition is invalid
            Exception: If the API request fails

        Example:
            room = await ingress.create_room(
                room_name="my-livestream",
                metadata='{"layout":"grid"}',
                empty_timeout=600,
            )
            print(f"Created room {room.name} with SID {room.sid}")
        """
        logger.info(
            f"Creating LiveKit room: room_name={room_name}, empty_timeout={empty_timeout}, max_participants={max_participants}"
        )

        # Create the room using public API
        room = await self.livekit.create_room(
            room_name=room_name,
            metadata=metadata,
            empty_timeout=empty_timeout,
            max_participants=max_participants,
        )
        logger.debug(f"Successfully created LiveKit room: name={room.name}, sid={room.sid}")

        # Fetch session by room_name (which is the room_id)
        # Note: Session state will be updated to READY when host joins via webhook
        session = await self._get_last_session_by_room_id(room_name)
        if session:
            logger.debug(
                f"Found session {session.room_id} for room {room_name} (state will be updated to READY via webhook)"
            )

        return room

    async def delete_room(
        self,
        room_name: str,
    ) -> None:
        """Delete a LiveKit room.

        This is the counterpart to create_room and should be called when
        the room is no longer needed. Typically called after a session
        has reached a terminal state (STOPPED, CANCELLED, ABORTED).

        Args:
            room_name: Room name (room_id) to delete

        Raises:
            AppError: If the session is not found for the room
            Exception: If the LiveKit API request fails

        Example:
            await ingress.delete_room(room_name="my-livestream")
        """
        logger.info(f"Deleting LiveKit room: room_name={room_name}")

        # Verify session exists for the room
        session = await self._get_last_session_by_room_id(room_name)
        if not session:
            raise AppError(
                errcode=AppErrorCode.E_SESSION_NOT_FOUND,
                errmesg=f"Session not found for room: {room_name}",
                status_code=HttpStatusCode.NOT_FOUND,
            )

        await self.livekit.delete_room(room_name=room_name)
        logger.info(f"Successfully deleted LiveKit room: room_name={room_name}")

    async def get_host_access_token(
        self,
        identity: str,
        room_name: str,
        display_name: str | None = None,
        metadata: str | None = None,
    ) -> str:
        """Generate a LiveKit access token for a host (with full permissions).

        Hosts can:
        - Join the room
        - Publish audio/video tracks
        - Subscribe to other participants' tracks
        - Publish data messages
        - Have admin privileges in the room

        Args:
            identity: Unique identity for the host participant
            room_name: Room name to grant access to
            display_name: Display name for the host (optional, defaults to identity)
            metadata: Custom metadata string (optional)

        Returns:
            JWT token string

        Raises:
            ValueError: If LIVEKIT_API_KEY or LIVEKIT_API_SECRET is not configured, or if room doesn't exist

        Example:
            token = await ingress.get_host_access_token(
                identity="host-user-123",
                room_name="my-livestream",
                display_name="John Host",
                metadata='{"role":"host","level":"premium"}',
            )
        """
        logger.info(
            f"Creating host access token: identity={identity}, room={room_name}, name={display_name or identity}"
        )

        # Check if room exists in database
        session = await self._get_last_session_by_room_id(room_name)
        if not session:
            raise AppError(
                errcode=AppErrorCode.E_SESSION_NOT_FOUND,
                errmesg=f"Room not found: {room_name}",
                status_code=HttpStatusCode.NOT_FOUND,
            )

        # Get max_participants from session or fall back to env config
        cfg = get_app_environ_config()
        max_participants = session.max_participants or cfg.MAX_PARTICIPANTS_LIMIT

        token = await self.livekit.create_access_token(
            identity=identity,
            room=room_name,
            name=display_name or identity,
            metadata=metadata,
            room_join=True,
            room_admin=True,  # Hosts have admin privileges
            room_create=False,  # Hosts can create rooms
            room_list=True,  # Hosts can list rooms
            room_record=True,  # Hosts can record
            can_publish=True,
            can_subscribe=True,
            can_publish_data=True,
            max_participants=max_participants,
        )

        logger.debug(f"Successfully created host access token for identity={identity}")
        return token

    async def get_guest_access_token(
        self,
        identity: str,
        room_name: str,
        display_name: str | None = None,
        metadata: str | None = None,
        can_publish: bool = True,
    ) -> str:
        """Generate a LiveKit access token for a guest/viewer (with restricted permissions).

        Guests can:
        - Join the room
        - Subscribe to host's tracks (watch/listen)
        - Optionally publish tracks (if can_publish=True)
        - Cannot have admin privileges

        Args:
            identity: Unique identity for the guest participant
            room_name: Room name to grant access to
            display_name: Display name for the guest (optional, defaults to identity)
            metadata: Custom metadata string (optional)
            can_publish: Whether guest can publish tracks

        Returns:
            JWT token string

        Raises:
            ValueError: If LIVEKIT_API_KEY or LIVEKIT_API_SECRET is not configured, or if room doesn't exist

        Example:
            # Viewer-only token (cannot publish)
            token = await ingress.get_guest_access_token(
                identity="viewer-456",
                room_name="my-livestream",
                display_name="Jane Viewer",
            )

            # Guest who can publish (e.g., co-host)
            token = await ingress.get_guest_access_token(
                identity="cohost-789",
                room_name="my-livestream",
                display_name="Bob CoHost",
                can_publish=True,
            )
        """
        logger.info(
            f"Creating guest access token: identity={identity}, room={room_name}, name={display_name or identity}, can_publish={can_publish}"
        )

        # Check if room exists in database
        session = await self._get_last_session_by_room_id(room_name)
        if not session:
            raise AppError(
                errcode=AppErrorCode.E_SESSION_NOT_FOUND,
                errmesg=f"Room not found: {room_name}",
                status_code=HttpStatusCode.NOT_FOUND,
            )

        token = await self.livekit.create_access_token(
            identity=identity,
            room=room_name,
            name=display_name or identity,
            metadata=metadata,
            room_join=True,
            room_admin=False,  # Guests never have admin privileges
            room_create=False,  # Guests cannot create rooms
            room_list=False,  # Guests cannot list rooms
            room_record=False,  # Guests cannot record
            can_publish=can_publish,
            can_subscribe=True,  # Guests can always subscribe (watch/listen)
            can_publish_data=can_publish,  # Data publishing tied to can_publish
        )

        logger.debug(f"Successfully created guest access token for identity={identity}")
        return token

    async def get_recorder_access_token(
        self,
        room_name: str,
        identity: str | None = None,
        display_name: str | None = None,
        metadata: str | None = None,
    ) -> str:
        """Generate a LiveKit access token for a recorder to join and record the live.

        Recorders can:
        - Join the room
        - Subscribe to all participants' tracks (receive audio/video)
        - Cannot publish any tracks
        - Cannot have admin privileges

        Args:
            room_name: Room name to grant access to
            identity: Unique identity for the recorder participant (defaults to "recorder-{room_name}")
            display_name: Display name for the recorder (optional, defaults to identity)
            metadata: Custom metadata string (optional)

        Returns:
            JWT token string

        Raises:
            ValueError: If LIVEKIT_API_KEY or LIVEKIT_API_SECRET is not configured, or if room doesn't exist

        Example:
            token = await ingress.get_recorder_access_token(
                room_name="my-livestream",
                identity="recorder-001",
                display_name="Live Recorder",
            )
        """
        recorder_identity = identity or f"recorder-{room_name}"
        logger.info(
            f"Creating recorder access token: identity={recorder_identity}, room={room_name}, name={display_name or recorder_identity}"
        )

        # Check if room exists in database
        session = await self._get_last_session_by_room_id(room_name)
        if not session:
            raise AppError(
                errcode=AppErrorCode.E_SESSION_NOT_FOUND,
                errmesg=f"Room not found: {room_name}",
                status_code=HttpStatusCode.NOT_FOUND,
            )

        token = self.livekit.create_recorder_token(
            room=room_name,
        )

        logger.debug(f"Successfully created recorder access token for identity={recorder_identity}")
        return token

    async def update_room_metadata(
        self,
        room_name: str,
        metadata: str,
    ) -> Any:
        """Update metadata for a LiveKit room.

        Room metadata is shared application-specific state that is visible to all
        participants in the room. This can be used to control shared state like
        layout mode, theme settings, or other configuration.

        The metadata must be a JSON string and is limited to 64 KiB in size.

        All participants in the room will receive a RoomMetadataChanged event
        when the metadata is updated.

        Args:
            room_name: Room name to update (also the room_id)
            metadata: JSON string containing room metadata

        Returns:
            Room object with updated metadata (has .name, .sid, .metadata attributes)

        Raises:
            AppError: If room/session not found
            ValueError: If LIVEKIT_URL is not configured
            Exception: If the API request fails

        Example:
            room_info = await ingress.update_room_metadata(
                room_name="my-livestream",
                metadata='{"layout":"grid","theme":"dark"}'
            )
            print(f"Updated room {room_info.name}")

        Reference:
            https://docs.livekit.io/home/client/state/room-metadata/
        """
        logger.info(f"Updating room metadata for room={room_name}")

        # Verify session exists
        session = await self._get_last_session_by_room_id(room_name)
        if not session:
            raise AppError(
                errcode=AppErrorCode.E_SESSION_NOT_FOUND,
                errmesg=f"Room not found: {room_name}",
                status_code=HttpStatusCode.NOT_FOUND,
            )

        # Update room metadata via LiveKit API
        room_info = await self.livekit.update_room_metadata(
            room=room_name,
            metadata=metadata,
        )

        logger.debug(
            f"Successfully updated room metadata for room={room_info.name}, sid={room_info.sid}"
        )
        return room_info

    async def update_participant(
        self,
        room_name: str,
        identity: str,
        name: str | None = None,
        metadata: str | None = None,
    ) -> Any:
        """Update participant display name and/or metadata.

        This allows updating a participant's display name and metadata while they
        are in the room. All participants in the room will receive events when
        these properties change.

        At least one of name or metadata must be provided.

        Args:
            room_name: Room name where the participant is (also the room_id)
            identity: Identity of the participant to update
            name: New display name for the participant (optional)
            metadata: New metadata for the participant (optional)

        Returns:
            ParticipantInfo object with updated participant details

        Raises:
            ValueError: If neither name nor metadata is provided
            AppError: If room/session not found
            Exception: If the API request fails

        Example:
            participant = await ingress.update_participant(
                room_name="my-livestream",
                identity="guest-123",
                name="New Display Name"
            )
            print(f"Updated participant {participant.identity}")

        Reference:
            https://docs.livekit.io/home/server/managing-participants/#updateparticipant
        """
        logger.info(f"Updating participant: room={room_name}, identity={identity}, name={name}")

        # Verify session exists
        session = await self._get_last_session_by_room_id(room_name)
        if not session:
            raise AppError(
                errcode=AppErrorCode.E_SESSION_NOT_FOUND,
                errmesg=f"Room not found: {room_name}",
                status_code=HttpStatusCode.NOT_FOUND,
            )

        # Update participant via LiveKit API
        participant = await self.livekit.update_participant(
            room=room_name,
            identity=identity,
            name=name,
            metadata=metadata,
        )

        logger.debug(
            f"Successfully updated participant: identity={participant.identity}, name={participant.name} in room={room_name}"
        )
        return participant
