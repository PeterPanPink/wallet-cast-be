"""Channel operations."""

from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from loguru import logger

from app.shared.domain.entity_change import dt_to_ms, utc_now
from app.schemas import Channel
from app.schemas.user_configs import UserConfigs
from app.utils.app_errors import AppError, AppErrorCode, HttpStatusCode

from ...utils.idgen import new_channel_id
from ._base import BaseService
from .channel_models import (
    ChannelCreateParams,
    ChannelListResponse,
    ChannelResponse,
    ChannelUpdateParams,
    UserConfigsUpdateParams,
)


class ChannelOperations(BaseService):
    """Channel-related operations."""

    async def create_channel(
        self,
        params: ChannelCreateParams,
    ) -> ChannelResponse:
        """
        Create a channel for the requesting user.

        Returns ChannelResponse on success, raises AppError on validation errors.
        """
        if not params.title:
            raise AppError(
                errcode=AppErrorCode.E_INVALID_REQUEST,
                errmesg="Title is required",
                status_code=HttpStatusCode.BAD_REQUEST,
            )
        if not params.location:
            raise AppError(
                errcode=AppErrorCode.E_INVALID_REQUEST,
                errmesg="Location is required",
                status_code=HttpStatusCode.BAD_REQUEST,
            )

        channel_id = new_channel_id()
        now = utc_now()

        # Create Channel document with defaults
        channel = Channel(
            channel_id=channel_id,
            user_id=params.user_id,
            title=params.title,
            location=params.location,
            description=params.description,
            cover=params.cover,
            lang=params.lang,
            category_ids=params.category_ids,
            created_at=now,
            updated_at=now,
        )

        logger.debug(f"Creating channel: {channel.model_dump(exclude={'id'})}")
        await channel.insert()

        return ChannelResponse(**channel.model_dump(exclude={"id"}, mode="json"))

    async def update_channel(
        self,
        channel_id: str,
        user_id: str,
        params: ChannelUpdateParams,
    ) -> ChannelResponse:
        """
        Update channel metadata for the given user.

        When title, description, or cover are updated, also updates all active
        sessions for this channel and synchronizes with External Live platform if needed.

        Returns ChannelResponse.
        Raises AppError if channel not found/unauthorized.
        Raises ValueError for validation errors.
        """
        # Find the channel
        channel = await Channel.find_one(
            Channel.channel_id == channel_id,
            Channel.user_id == user_id,
        )
        if not channel:
            logger.warning(f"Channel {channel_id} not found for user {user_id}")
            raise AppError(
                errcode=AppErrorCode.E_CHANNEL_NOT_FOUND,
                errmesg=f"Channel not found: {channel_id}",
                status_code=HttpStatusCode.NOT_FOUND,
            )

        # Track changes for legacy audit
        changed_keys: list[str] = []

        # Get updates dict excluding unset fields only
        # Note: exclude_none=False to allow clearing fields by setting them to null
        updates = params.model_dump(exclude_unset=True)

        # Update simple fields
        for field, value in updates.items():
            if getattr(channel, field, None) != value:
                setattr(channel, field, value)
                changed_keys.append(field)

        # Update timestamp
        channel.updated_at = utc_now()

        # Save changes
        if changed_keys:
            logger.debug(f"Updating channel {channel_id}: {changed_keys}")
            await channel.save()

            # Check if title, description, or cover changed - sync to active sessions
            sync_fields = {"title", "description", "cover"}
            changed_sync_fields = sync_fields.intersection(changed_keys)

            if changed_sync_fields:
                await self._sync_active_sessions(channel_id, updates, changed_sync_fields)

        return ChannelResponse(**channel.model_dump(exclude={"id"}, mode="json"))

    async def get_channel(
        self,
        channel_id: str,
        user_id: str | None = None,
    ) -> ChannelResponse:
        """
        Get a single channel by ID with optional user ownership check.

        Returns ChannelResponse.
        Raises AppError if channel not found.
        """
        query_conditions = [Channel.channel_id == channel_id]
        if user_id:
            query_conditions.append(Channel.user_id == user_id)

        channel = await Channel.find_one(*query_conditions)
        if not channel:
            raise AppError(
                errcode=AppErrorCode.E_CHANNEL_NOT_FOUND,
                errmesg=f"Channel not found: {channel_id}",
                status_code=HttpStatusCode.NOT_FOUND,
            )

        return ChannelResponse(**channel.model_dump(exclude={"id"}, mode="json"))

    async def list_channels(
        self,
        cursor: str | None = None,
        page_size: int = 20,
        user_id: str | None = None,
    ) -> ChannelListResponse:
        """
        Return paginated channels with optional filters.

        Returns ChannelListResponse with channels and next_cursor.
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

        if user_id:
            conditions.append(Channel.user_id == user_id)

        # Handle cursor pagination
        if cursor:
            try:
                from beanie.operators import LT, And, Or

                c_ms_str, c_oid_str = cursor.split("|", 1)
                c_ms = int(c_ms_str)
                c_dt = datetime.fromtimestamp(c_ms / 1000, tz=timezone.utc)
                c_oid = ObjectId(c_oid_str)
                # Cursor condition: (created_at < c_dt) OR (created_at == c_dt AND _id < c_oid)
                cursor_condition = Or(
                    LT(Channel.created_at, c_dt),
                    And(Channel.created_at == c_dt, LT(Channel.id, c_oid)),
                )
                conditions.append(cursor_condition)
            except Exception as e:
                logger.warning(f"Invalid cursor format: {cursor}, error: {e}")

        # Execute query with Beanie's native find
        from pymongo import DESCENDING

        query = Channel.find(*conditions) if conditions else Channel.find()
        channels_list = (
            await query.sort([("created_at", DESCENDING), ("_id", DESCENDING)])  # type: ignore
            .limit(page_size + 1)
            .to_list()
        )

        # Determine next cursor
        next_cursor = None
        if len(channels_list) > page_size:
            last_doc = channels_list[page_size - 1]
            next_cursor = f"{dt_to_ms(last_doc.created_at)}|{last_doc.id!s}"
            channels_list = channels_list[:page_size]

        # Convert to ChannelResponse models
        channels = [
            ChannelResponse(**ch.model_dump(exclude={"id"}, mode="json")) for ch in channels_list
        ]

        return ChannelListResponse(channels=channels, next_cursor=next_cursor)

    async def delete_channel(
        self,
        channel_id: str,
        user_id: str,
    ) -> bool:
        """
        Delete a channel.

        Returns True if deleted, False if not found.
        """
        channel = await Channel.find_one(
            Channel.channel_id == channel_id,
            Channel.user_id == user_id,
        )
        if not channel:
            return False

        await channel.delete()

        logger.info(f"Deleted channel {channel_id} for user {user_id}")
        return True

    async def get_user_configs(
        self,
        channel_id: str,
        user_id: str,
    ) -> UserConfigs:
        """Return user-level audio configs for a channel."""
        channel = await Channel.find_one(
            Channel.channel_id == channel_id,
            Channel.user_id == user_id,
        )
        if not channel:
            raise AppError(
                errcode=AppErrorCode.E_CHANNEL_NOT_FOUND,
                errmesg=f"Channel not found: {channel_id}",
                status_code=HttpStatusCode.NOT_FOUND,
            )

        if not channel.user_configs:
            channel.user_configs = UserConfigs()
            await channel.save()

        return channel.user_configs

    async def update_user_configs(
        self,
        channel_id: str,
        user_id: str,
        params: UserConfigsUpdateParams,
    ) -> UserConfigs:
        """Update user-level audio configs for a channel."""
        channel = await Channel.find_one(
            Channel.channel_id == channel_id,
            Channel.user_id == user_id,
        )
        if not channel:
            raise AppError(
                errcode=AppErrorCode.E_CHANNEL_NOT_FOUND,
                errmesg=f"Channel not found: {channel_id}",
                status_code=HttpStatusCode.NOT_FOUND,
            )

        if not channel.user_configs:
            channel.user_configs = UserConfigs()

        updates = params.model_dump(exclude_unset=True, exclude_none=True)
        if not updates:
            return channel.user_configs

        for field, value in updates.items():
            setattr(channel.user_configs, field, value)

        channel.updated_at = utc_now()
        await channel.save()

        return channel.user_configs

    async def _sync_active_sessions(
        self,
        channel_id: str,
        updates: dict[str, Any],
        changed_fields: set[str],
    ) -> None:
        """Sync title, description, cover changes to active sessions and External Live.

        This method:
        1. Finds all active sessions for the channel
        2. Updates their title, description, and cover fields
        3. Syncs to External Live if the session has a post_id
        """
        from beanie.operators import In

        from app.schemas import Session
        from app.schemas.session_state import SessionState

        # Find all active sessions for this channel
        active_sessions = await Session.find(
            Session.channel_id == channel_id,
            In(Session.status, SessionState.active_states()),
        ).to_list()

        if not active_sessions:
            logger.debug(f"No active sessions found for channel {channel_id}")
            return

        logger.info(
            f"Syncing {len(active_sessions)} active session(s) for channel {channel_id} "
            f"with fields: {changed_fields}"
        )

        # Update each active session
        for session in active_sessions:
            session_changed = False
            session_update_fields: dict[Any, Any] = {}

            # Update the changed fields in the session
            for field in changed_fields:
                if field in updates:
                    old_value = getattr(session, field, None)
                    new_value = updates[field]
                    if old_value != new_value:
                        setattr(session, field, new_value)
                        session_changed = True
                        session_field = getattr(Session, field, None)
                        if session_field is not None:
                            session_update_fields[session_field] = new_value

            if session_changed:
                session.updated_at = utc_now()
                session_update_fields[Session.updated_at] = session.updated_at
                await session.partial_update_session_with_version_check(
                    session_update_fields,
                    max_retry_on_conflicts=2,
                )

                logger.info(
                    f"Updated session {session.session_id} fields {changed_fields} "
                    f"from channel {channel_id}"
                )

                # Sync to External Live if the session has a post_id (is live)
                if session.runtime and session.runtime.post_id:
                    await self._sync_session_to_external_live(session)

    async def _sync_session_to_external_live(self, session) -> None:
        """Sync session metadata to External Live platform."""
        from app.app_config import get_app_environ_config
        from app.services.integrations.external_live.external_live_client import ExternalLiveClient
        from app.services.integrations.external_live.external_live_schemas import AdminUpdateLiveBody

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
            # Log error but don't fail the channel update
            logger.error(
                f"Failed to sync session {session.session_id} to External Live: {e}",
                exc_info=True,
            )
