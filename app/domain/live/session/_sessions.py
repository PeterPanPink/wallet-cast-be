"""Session operations."""

from datetime import datetime, timezone
from typing import Any

from beanie.operators import In
from bson import ObjectId
from loguru import logger
from pymongo import DESCENDING
from pymongo.errors import DuplicateKeyError

from app.app_config import get_app_environ_config
from app.shared.domain.entity_change import dt_to_ms, utc_now
from app.schemas import Channel, Session, SessionState
from app.schemas.session_runtime import SessionRuntime
from app.services.integrations.external_live.external_live_client import ExternalLiveClient
from app.services.integrations.external_live.external_live_schemas import AdminUpdateLiveBody
from app.utils.app_errors import AppError, AppErrorCode, HttpStatusCode

from ...utils.idgen import new_room_id, new_session_id
from ._base import BaseService
from .session_models import (
    SessionCreateParams,
    SessionListResponse,
    SessionResponse,
    SessionUpdateParams,
)


class SessionOperations(BaseService):
    """Session-related operations."""

    async def create_session(
        self,
        params: SessionCreateParams,
    ) -> SessionResponse:
        """
        Create a new session or reuse an existing active session.

        Returns SessionResponse on success, raises ValueError on validation errors.
        """
        # Validate channel exists and belongs to user
        channel = await Channel.find_one(
            Channel.channel_id == params.channel_id,
            Channel.user_id == params.user_id,
        )
        if not channel:
            raise AppError(
                errcode=AppErrorCode.E_CHANNEL_NOT_FOUND,
                errmesg=f"Channel not found: {params.channel_id}",
                status_code=HttpStatusCode.NOT_FOUND,
            )

        # Check for existing active session
        active_statuses = [
            SessionState.IDLE,
            SessionState.READY,
            SessionState.PUBLISHING,
            SessionState.LIVE,
            SessionState.ENDING,
        ]
        existing = await Session.find_one(
            Session.channel_id == params.channel_id,
            In(Session.status, active_statuses),
        )
        if existing:
            if params.end_existing:
                # End the existing session before creating a new one
                from ._end import EndSessionOperations

                end_ops = EndSessionOperations()
                logger.info(
                    f"Ending existing session {existing.session_id} before creating new session"
                )
                await end_ops.end_session(existing.session_id)
            else:
                raise AppError(
                    errcode=AppErrorCode.E_SESSION_EXISTS,
                    errmesg=f"Active session already exists for channel {params.channel_id}: {existing.session_id}",
                    status_code=HttpStatusCode.CONFLICT,
                )

        # Create new session
        now = utc_now()

        # Merge session metadata with channel defaults
        title = params.title or channel.title
        location = params.location or channel.location
        description = params.description or channel.description
        cover = params.cover or channel.cover
        lang = params.lang or channel.lang
        category_ids = params.category_ids or channel.category_ids

        # Get provider config from channel or params
        provider_config = self._resolve_provider_config(params.runtime)

        session_id = new_session_id()
        room_id = new_room_id()

        # Create session
        session = Session(
            session_id=session_id,
            room_id=room_id,
            channel_id=params.channel_id,
            user_id=params.user_id or channel.user_id,
            title=title,
            location=location,
            description=description,
            cover=cover,
            lang=lang,
            category_ids=category_ids,
            status=SessionState.IDLE,
            runtime=provider_config,
            created_at=now,
            updated_at=now,
            started_at=None,
            stopped_at=None,
        )

        logger.debug(f"Creating session: {session.session_id} for channel {params.channel_id}")
        try:
            await session.insert()
        except DuplicateKeyError as e:
            # Race condition: another process created a session for this channel
            logger.warning(
                f"Duplicate key error creating session for channel {params.channel_id}: {e}"
            )
            raise AppError(
                errcode=AppErrorCode.E_SESSION_EXISTS,
                errmesg=f"Active session already exists for channel {params.channel_id}",
                status_code=HttpStatusCode.CONFLICT,
            ) from e

        # Sync session fields back to channel if they were explicitly provided
        sync_fields = {"title", "description", "cover"}
        updates: dict[str, Any] = {}
        changed_sync_fields: set[str] = set()

        for field in sync_fields:
            param_value = getattr(params, field, None)
            channel_value = getattr(channel, field, None)
            if param_value is not None and param_value != channel_value:
                updates[field] = param_value
                changed_sync_fields.add(field)

        if changed_sync_fields:
            await self._sync_channel_fields(session, updates, changed_sync_fields)

        return SessionResponse(**session.model_dump(exclude={"id"}, mode="json"))

    async def get_session(
        self,
        session_id: str,
    ) -> SessionResponse:
        """
        Get a single session by session_id.

        Returns SessionResponse.
        Raises AppError if session not found.
        """
        session = await self._get_session_by_id(session_id)
        if not session:
            raise AppError(
                errcode=AppErrorCode.E_SESSION_NOT_FOUND,
                errmesg=f"Session not found: {session_id}",
                status_code=HttpStatusCode.NOT_FOUND,
            )

        return SessionResponse(**session.model_dump(exclude={"id"}, mode="json"))

    async def get_active_session_by_room_id(
        self,
        room_id: str,
    ) -> SessionResponse:
        """
        Get an active session by room_id.

        Returns SessionResponse.
        Raises AppError if no active session found for room_id.
        """
        session = await self._get_active_session_by_room_id(room_id)
        if not session:
            raise AppError(
                errcode=AppErrorCode.E_SESSION_NOT_FOUND,
                errmesg=f"No active session found for room_id: {room_id}",
                status_code=HttpStatusCode.NOT_FOUND,
            )

        return SessionResponse(**session.model_dump(exclude={"id"}, mode="json"))

    async def get_last_session_by_room_id(
        self,
        room_id: str,
    ) -> SessionResponse:
        """
        Get the most recent session by room_id (regardless of status).

        Returns SessionResponse.
        Raises AppError if no session found for room_id.
        """
        session = await self._get_last_session_by_room_id(room_id)
        if not session:
            raise AppError(
                errcode=AppErrorCode.E_SESSION_NOT_FOUND,
                errmesg=f"No session found for room_id: {room_id}",
                status_code=HttpStatusCode.NOT_FOUND,
            )

        return SessionResponse(**session.model_dump(exclude={"id"}, mode="json"))

    async def get_active_session_by_channel(
        self,
        channel_id: str,
    ) -> SessionResponse:
        """
        Get the active session for a channel.

        Returns SessionResponse.
        Raises AppError if no active session found for channel.
        """
        session = await Session.find_one(
            Session.channel_id == channel_id,
            In(Session.status, SessionState.active_states()),
        )
        if not session:
            raise AppError(
                errcode=AppErrorCode.E_SESSION_NOT_FOUND,
                errmesg=f"No active session found for channel: {channel_id}",
                status_code=HttpStatusCode.NOT_FOUND,
            )

        return SessionResponse(**session.model_dump(exclude={"id"}, mode="json"))

    async def recreate_session_from_stopped(
        self,
        stopped_session: Session,
    ) -> SessionResponse:
        """
        Create a new READY session from a stopped session.

        This is called after a session transitions to STOPPED to allow
        the user to start a new stream using the same room_id.

        Args:
            stopped_session: The session that was just stopped

        Returns:
            SessionResponse for the newly created session
        """
        # Verify the session is actually stopped
        if stopped_session.status != SessionState.STOPPED:
            raise AppError(
                errcode=AppErrorCode.E_INVALID_REQUEST,
                errmesg=f"Can only recreate from STOPPED session, got: {stopped_session.status}",
                status_code=HttpStatusCode.BAD_REQUEST,
            )

        # Get the channel to verify it exists
        channel = await Channel.find_one(
            Channel.channel_id == stopped_session.channel_id,
        )
        if not channel:
            raise AppError(
                errcode=AppErrorCode.E_CHANNEL_NOT_FOUND,
                errmesg=f"Channel not found: {stopped_session.channel_id}",
                status_code=HttpStatusCode.NOT_FOUND,
            )

        # Create new session with READY state
        now = utc_now()
        session_id = new_session_id()

        new_session = Session(
            session_id=session_id,
            room_id=stopped_session.room_id,  # Reuse the same room_id
            channel_id=stopped_session.channel_id,
            user_id=stopped_session.user_id,
            title=stopped_session.title,
            location=stopped_session.location,
            description=stopped_session.description,
            cover=stopped_session.cover,
            lang=stopped_session.lang,
            category_ids=stopped_session.category_ids,
            status=SessionState.READY,
            max_participants=stopped_session.max_participants,
            runtime=SessionRuntime(),
            created_at=now,
            updated_at=now,
            started_at=None,
            stopped_at=None,
        )

        # Create LiveKit room to ensure it exists
        try:
            await self.livekit.create_room(
                room_name=stopped_session.room_id,
                metadata=None,
                empty_timeout=300,
                max_participants=stopped_session.max_participants or 100,
            )
            logger.info(f"Created LiveKit room for {stopped_session.room_id}")
        except Exception as e:
            logger.warning(f"Failed to create LiveKit room {stopped_session.room_id}: {e}")
            # Continue anyway - room might already exist

        # Save the new session
        try:
            await new_session.insert()
            logger.info(
                f"Created new READY session {session_id} for room {stopped_session.room_id} "
                f"based on stopped session {stopped_session.session_id}"
            )
        except DuplicateKeyError:
            # Another process already created a session for this room_id
            logger.info(
                f"Session for room {stopped_session.room_id} already exists, fetching existing session"
            )
            existing = await self._get_active_session_by_room_id(stopped_session.room_id)
            if existing:
                return SessionResponse(**existing.model_dump(exclude={"id"}, mode="json"))
            # If no active session found, re-raise the error
            raise

        return SessionResponse(**new_session.model_dump(exclude={"id"}, mode="json"))

    async def recreate_session_from_terminal(
        self,
        terminal_session: Session,
    ) -> SessionResponse:
        """
        Create a new READY session from a terminal session (STOPPED or CANCELLED).

        This is called after a session transitions to a terminal state to allow
        the user to start a new stream using the same room_id.

        Args:
            terminal_session: The session that reached a terminal state (STOPPED or CANCELLED)

        Returns:
            SessionResponse for the newly created session

        Raises:
            ValueError: If session is not in a terminal state (STOPPED or CANCELLED)
            AppError: If channel is not found or inactive
        """
        # Verify the session is in a terminal state
        terminal_states = {SessionState.STOPPED, SessionState.CANCELLED}
        if terminal_session.status not in terminal_states:
            raise AppError(
                errcode=AppErrorCode.E_INVALID_REQUEST,
                errmesg=f"Can only recreate from terminal session (STOPPED or CANCELLED), got: {terminal_session.status}",
                status_code=HttpStatusCode.BAD_REQUEST,
            )

        # Get the channel to verify it exists
        channel = await Channel.find_one(
            Channel.channel_id == terminal_session.channel_id,
        )
        if not channel:
            raise AppError(
                errcode=AppErrorCode.E_CHANNEL_NOT_FOUND,
                errmesg=f"Channel not found: {terminal_session.channel_id}",
                status_code=HttpStatusCode.NOT_FOUND,
            )

        # Create new session with READY state
        now = utc_now()
        session_id = new_session_id()

        new_session = Session(
            session_id=session_id,
            room_id=terminal_session.room_id,  # Reuse the same room_id
            channel_id=terminal_session.channel_id,
            user_id=terminal_session.user_id,
            title=terminal_session.title,
            location=terminal_session.location,
            description=terminal_session.description,
            cover=terminal_session.cover,
            lang=terminal_session.lang,
            category_ids=terminal_session.category_ids,
            status=SessionState.READY,
            max_participants=terminal_session.max_participants,
            runtime=SessionRuntime(),
            created_at=now,
            updated_at=now,
            started_at=None,
            stopped_at=None,
        )

        # Create LiveKit room to ensure it exists
        try:
            await self.livekit.create_room(
                room_name=terminal_session.room_id,
                metadata=None,
                empty_timeout=300,
                max_participants=terminal_session.max_participants or 100,
            )
            logger.info(f"Created LiveKit room for {terminal_session.room_id}")
        except Exception as e:
            logger.warning(f"Failed to create LiveKit room {terminal_session.room_id}: {e}")
            # Continue anyway - room might already exist

        # Save the new session
        try:
            await new_session.insert()
            logger.info(
                f"Created new READY session {session_id} for room {terminal_session.room_id} "
                f"based on {terminal_session.status.value} session {terminal_session.session_id}"
            )
        except DuplicateKeyError:
            # Another process already created a session for this room_id
            logger.info(
                f"Session for room {terminal_session.room_id} already exists, fetching existing session"
            )
            existing = await self._get_active_session_by_room_id(terminal_session.room_id)
            if existing:
                return SessionResponse(**existing.model_dump(exclude={"id"}, mode="json"))
            # If no active session found, re-raise the error
            raise

        return SessionResponse(**new_session.model_dump(exclude={"id"}, mode="json"))

    async def list_sessions(
        self,
        cursor: str | None = None,
        page_size: int = 20,
        channel_id: str | None = None,
        user_id: str | None = None,
        status: list[SessionState] | SessionState | None = None,
    ) -> SessionListResponse:
        """
        Return paginated sessions with optional filters.

        Returns SessionListResponse with sessions and next_cursor.
        """
        # Validate page_size
        try:
            page_size = int(page_size)
        except Exception:
            page_size = 20

        if page_size < 1 or page_size > 1000:
            logger.warning(f"Invalid page_size: {page_size}")
            page_size = 20

        # Build query using Beanie operators
        conditions: list[Any] = []

        if channel_id:
            conditions.append(Session.channel_id == channel_id)
        if user_id:
            conditions.append(Session.user_id == user_id)

        # Handle status filter
        if status is not None:
            if isinstance(status, list):
                conditions.append(In(Session.status, status))
            else:
                conditions.append(Session.status == status)

        # Handle cursor pagination
        if cursor:
            try:
                c_ms_str, c_oid_str = cursor.split("|", 1)
                c_ms = int(c_ms_str)
                c_dt = datetime.fromtimestamp(c_ms / 1000, tz=timezone.utc)
                c_oid = ObjectId(c_oid_str)
                # Cursor condition: (created_at < c_dt) OR (created_at == c_dt AND _id < c_oid)
                from beanie.operators import LT, And, Or

                cursor_condition = Or(
                    LT(Session.created_at, c_dt),
                    And(Session.created_at == c_dt, LT(Session.id, c_oid)),
                )
                conditions.append(cursor_condition)
            except Exception as e:
                logger.warning(f"Invalid cursor format: {cursor}, error: {e}")

        # Execute query with Beanie's native find
        query = Session.find(*conditions) if conditions else Session.find()
        sessions_list = (
            await query.sort([("created_at", DESCENDING), ("_id", DESCENDING)])  # type: ignore
            .limit(page_size + 1)
            .to_list()
        )

        # Determine next cursor
        next_cursor = None
        if len(sessions_list) > page_size:
            last_doc = sessions_list[page_size - 1]
            next_cursor = f"{dt_to_ms(last_doc.created_at)}|{last_doc.id!s}"
            sessions_list = sessions_list[:page_size]

        # Convert to SessionResponse models
        sessions = [
            SessionResponse(**s.model_dump(exclude={"id"}, mode="json")) for s in sessions_list
        ]

        return SessionListResponse(sessions=sessions, next_cursor=next_cursor)

    async def update_session(
        self,
        session_id: str,
        params: SessionUpdateParams,
    ) -> SessionResponse:
        """
        Update session metadata.

        When title, description, or cover are updated, also updates the associated
        channel and synchronizes with External Live platform if the session is live.

        Returns SessionResponse.
        Raises AppError if session not found.
        Raises ValueError for validation errors.
        """
        # Find the session
        session = await Session.find_one(Session.session_id == session_id)
        if not session:
            logger.warning(f"Session {session_id} not found")
            raise AppError(
                errcode=AppErrorCode.E_SESSION_NOT_FOUND,
                errmesg=f"Session not found: {session_id}",
                status_code=HttpStatusCode.NOT_FOUND,
            )

        # Get updates dict excluding unset and None values
        updates = params.model_dump(exclude_unset=True)

        # Update fields
        changed_keys: list[str] = []

        for field, value in updates.items():
            if getattr(session, field, None) != value:
                setattr(session, field, value)
                changed_keys.append(field)

        # Update timestamp
        session.updated_at = utc_now()

        # Save changes
        if changed_keys:
            logger.debug(f"Updating session {session_id}: {changed_keys}")

            update_fields: dict[Any, Any] = {}
            for field in changed_keys:
                session_field = getattr(Session, field, None)
                if session_field is not None:
                    update_fields[session_field] = getattr(session, field)
            update_fields[Session.updated_at] = session.updated_at

            await session.partial_update_session_with_version_check(
                update_fields,
                max_retry_on_conflicts=2,
            )

            # Check if title, description, or cover changed - sync to channel and External Live
            sync_fields = {"title", "description", "cover"}
            changed_sync_fields = sync_fields.intersection(changed_keys)

            if changed_sync_fields:
                # Update the channel with the same changes
                await self._sync_channel_fields(session, updates, changed_sync_fields)

                # Sync to External Live if the session has a post_id (is live)
                if session.runtime and session.runtime.post_id:
                    await self._sync_external_live(session)

        return SessionResponse(**session.model_dump(exclude={"id"}, mode="json"))

    async def _sync_channel_fields(
        self,
        session: Session,
        updates: dict[str, Any],
        changed_fields: set[str],
    ) -> None:
        """Sync title, description, cover changes to the channel."""
        channel = await Channel.find_one(Channel.channel_id == session.channel_id)
        if not channel:
            logger.warning(
                f"Channel {session.channel_id} not found for session {session.session_id}, "
                "skipping channel sync"
            )
            return

        channel_changed = False
        for field in changed_fields:
            if field in updates:
                setattr(channel, field, updates[field])
                channel_changed = True

        if channel_changed:
            channel.updated_at = utc_now()
            await channel.save()
            logger.info(
                f"Synced session {session.session_id} fields {changed_fields} "
                f"to channel {channel.channel_id}"
            )

    async def _sync_external_live(
        self,
        session: Session,
    ) -> None:
        """Sync title, description, cover to External Live platform.

        Always sends all fields (title, description, cover) from the session,
        not just the changed ones.
        """
        config = get_app_environ_config()
        if not config.EXTERNAL_LIVE_BASE_URL:
            logger.debug("EXTERNAL_LIVE_BASE_URL not configured, skipping External Live sync")
            return

        post_id = session.runtime.post_id if session.runtime else None
        if not post_id:
            logger.debug(f"No post_id for session {session.session_id}, skipping External Live sync")
            return

        try:
            client = ExternalLiveClient(
                base_url=config.EXTERNAL_LIVE_BASE_URL,
                api_key=config.EXTERNAL_LIVE_API_KEY,
            )

            # Log session data before creating body
            logger.debug(
                f"Session data before External Live sync - session_id={session.session_id}, "
                f"title={session.title!r}, description={session.description!r}, "
                f"cover={session.cover!r}"
            )

            # Always pass all data from the session
            body = AdminUpdateLiveBody.model_validate(
                {
                    "post_id": post_id,
                    "title": session.title,
                    "description": session.description,
                    "cover": session.cover,
                }
            )

            # Log the serialized body that will be sent
            serialized_body = body.model_dump(exclude_none=True)
            logger.info(
                f"📤 Calling External Live admin/live/update for session {session.session_id}, "
                f"post_id={post_id}, body={serialized_body}"
            )
            await client.admin_update_live(body)
            logger.info(f"✅ External Live update_live completed for post_id: {post_id}")

        except Exception as e:
            # Log error but don't fail the session update
            logger.error(
                f"Failed to sync session {session.session_id} to External Live: {e}",
                exc_info=True,
            )
