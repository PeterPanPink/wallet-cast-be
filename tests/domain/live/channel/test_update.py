"""Tests for channel update operations."""

import pytest

from app.domain.live.channel.channel_domain import ChannelService
from app.domain.live.channel.channel_models import ChannelCreateParams, ChannelUpdateParams
from app.schemas import Channel
from app.utils.flc_errors import FlcError, FlcErrorCode


@pytest.mark.usefixtures("clear_collections")
class TestUpdateChannel:
    """Tests for channel update operations."""

    @pytest.fixture
    def service(self) -> ChannelService:
        """Create channel service instance."""
        return ChannelService()

    @pytest.fixture
    async def existing_channel(self, beanie_db, service: ChannelService) -> tuple[str, str]:
        """Create an existing channel and return (channel_id, user_id)."""
        params = ChannelCreateParams(
            user_id="user_update_test",
            title="Original Title",
            location="US",
            description="Original description",
            cover="https://example.com/original.jpg",
        )
        result = await service.create_channel(params)
        return result.channel_id, result.user_id

    async def test_update_channel_title(
        self,
        beanie_db,
        service: ChannelService,
        existing_channel: tuple[str, str],
    ):
        """Test updating channel title."""
        channel_id, user_id = existing_channel

        params = ChannelUpdateParams(title="Updated Title")
        result = await service.update_channel(channel_id, user_id, params)

        assert result.title == "Updated Title"
        assert result.description == "Original description"  # Unchanged

    async def test_update_channel_description(
        self,
        beanie_db,
        service: ChannelService,
        existing_channel: tuple[str, str],
    ):
        """Test updating channel description."""
        channel_id, user_id = existing_channel

        params = ChannelUpdateParams(description="New description")
        result = await service.update_channel(channel_id, user_id, params)

        assert result.description == "New description"
        assert result.title == "Original Title"  # Unchanged

    async def test_update_channel_cover(
        self,
        beanie_db,
        service: ChannelService,
        existing_channel: tuple[str, str],
    ):
        """Test updating channel cover."""
        channel_id, user_id = existing_channel

        params = ChannelUpdateParams(cover="https://example.com/new.jpg")
        result = await service.update_channel(channel_id, user_id, params)

        assert result.cover == "https://example.com/new.jpg"

    async def test_update_channel_multiple_fields(
        self,
        beanie_db,
        service: ChannelService,
        existing_channel: tuple[str, str],
    ):
        """Test updating multiple fields at once."""
        channel_id, user_id = existing_channel

        params = ChannelUpdateParams(
            title="New Title",
            description="New description",
            cover="https://example.com/new.jpg",
        )
        result = await service.update_channel(channel_id, user_id, params)

        assert result.title == "New Title"
        assert result.description == "New description"
        assert result.cover == "https://example.com/new.jpg"

    async def test_update_channel_updated_at_changes(
        self,
        beanie_db,
        service: ChannelService,
        existing_channel: tuple[str, str],
    ):
        """Test that updated_at timestamp changes on update."""
        channel_id, user_id = existing_channel

        # Get original timestamp
        original = await Channel.find_one(Channel.channel_id == channel_id)
        assert original is not None
        original_updated_at = original.updated_at

        params = ChannelUpdateParams(title="New Title")
        result = await service.update_channel(channel_id, user_id, params)

        assert result.updated_at >= original_updated_at

    async def test_update_channel_not_found(
        self,
        beanie_db,
        service: ChannelService,
    ):
        """Test updating non-existent channel raises FlcError."""
        params = ChannelUpdateParams(title="New Title")

        with pytest.raises(FlcError) as exc_info:
            await service.update_channel("non_existent_id", "user_123", params)
        assert exc_info.value.errcode == FlcErrorCode.E_CHANNEL_NOT_FOUND

    async def test_update_channel_wrong_user(
        self,
        beanie_db,
        service: ChannelService,
        existing_channel: tuple[str, str],
    ):
        """Test updating channel with wrong user raises FlcError."""
        channel_id, _ = existing_channel

        params = ChannelUpdateParams(title="Hacker Title")

        with pytest.raises(FlcError) as exc_info:
            await service.update_channel(channel_id, "wrong_user", params)
        assert exc_info.value.errcode == FlcErrorCode.E_CHANNEL_NOT_FOUND

    async def test_update_channel_no_changes(
        self,
        beanie_db,
        service: ChannelService,
        existing_channel: tuple[str, str],
    ):
        """Test updating channel with no changes succeeds."""
        channel_id, user_id = existing_channel

        # Empty update params
        params = ChannelUpdateParams()
        result = await service.update_channel(channel_id, user_id, params)

        assert result.title == "Original Title"  # Unchanged

    async def test_update_channel_persists_to_db(
        self,
        beanie_db,
        service: ChannelService,
        existing_channel: tuple[str, str],
    ):
        """Test that updates are persisted to database."""
        channel_id, user_id = existing_channel

        params = ChannelUpdateParams(title="Persisted Title")
        await service.update_channel(channel_id, user_id, params)

        # Re-fetch from database
        saved = await Channel.find_one(Channel.channel_id == channel_id)
        assert saved is not None
        assert saved.title == "Persisted Title"

    async def test_update_channel_syncs_to_active_sessions(
        self,
        beanie_db,
        service: ChannelService,
    ):
        """Test that updating channel title/description/cover syncs to active sessions."""
        from app.domain.live.session.session_domain import SessionService
        from app.domain.live.session.session_models import SessionCreateParams
        from app.schemas import Session

        # Create a channel
        channel_params = ChannelCreateParams(
            user_id="user_sync_test",
            title="Original Channel Title",
            location="US",
            description="Original Channel Description",
            cover="https://example.com/original.jpg",
        )
        channel = await service.create_channel(channel_params)

        # Create an active session for this channel
        session_service = SessionService()
        session_params = SessionCreateParams(
            channel_id=channel.channel_id,
            user_id=channel.user_id,
        )
        session = await session_service.create_session(session_params)

        # Verify session inherited channel values
        assert session.title == "Original Channel Title"
        assert session.description == "Original Channel Description"
        assert session.cover == "https://example.com/original.jpg"

        # Update the channel
        update_params = ChannelUpdateParams(
            title="Updated Channel Title",
            description="Updated Channel Description",
            cover="https://example.com/updated.jpg",
        )
        await service.update_channel(channel.channel_id, channel.user_id, update_params)

        # Verify session was updated
        updated_session = await Session.find_one(Session.session_id == session.session_id)
        assert updated_session is not None
        assert updated_session.title == "Updated Channel Title"
        assert updated_session.description == "Updated Channel Description"
        assert updated_session.cover == "https://example.com/updated.jpg"

    async def test_update_channel_only_syncs_to_active_sessions(
        self,
        beanie_db,
        service: ChannelService,
    ):
        """Test that channel updates only sync to active sessions, not stopped ones."""
        from app.cw.domain.entity_change import utc_now
        from app.domain.live.session.session_domain import SessionService
        from app.domain.live.session.session_models import SessionCreateParams
        from app.schemas import Session
        from app.schemas.session_state import SessionState

        # Create a channel
        channel_params = ChannelCreateParams(
            user_id="user_stopped_test",
            title="Original Title",
            location="US",
        )
        channel = await service.create_channel(channel_params)

        # Create a stopped session
        stopped_session = Session(
            session_id="se_stopped_test",
            room_id="ro_stopped_test",
            channel_id=channel.channel_id,
            user_id=channel.user_id,
            title="Original Title",
            status=SessionState.STOPPED,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        await stopped_session.insert()

        # Create an active session
        session_service = SessionService()
        active_params = SessionCreateParams(
            channel_id=channel.channel_id,
            user_id=channel.user_id,
        )
        active_session = await session_service.create_session(active_params)

        # Update the channel
        update_params = ChannelUpdateParams(title="Updated Title")
        await service.update_channel(channel.channel_id, channel.user_id, update_params)

        # Verify stopped session was NOT updated
        stopped = await Session.find_one(Session.session_id == "se_stopped_test")
        assert stopped is not None
        assert stopped.title == "Original Title"  # Should remain unchanged

        # Verify active session WAS updated
        active = await Session.find_one(Session.session_id == active_session.session_id)
        assert active is not None
        assert active.title == "Updated Title"
