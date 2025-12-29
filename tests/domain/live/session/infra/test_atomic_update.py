"""Tests for Session optimistic locking methods."""

from datetime import datetime, timezone

import pytest

from app.schemas import Session, SessionState
from app.schemas.session_runtime import SessionRuntime
from app.utils.app_errors import AppError, AppErrorCode


@pytest.mark.usefixtures("clear_collections")
class TestSaveSessionWithVersionCheck:
    """Tests for save_session_with_version_check method."""

    async def test_save_session_success_first_update(self, beanie_db):
        """Test successful save on first update (version 1 -> 2)."""
        # Arrange
        session = Session(
            session_id="se_version_test",
            room_id="version-test-room",
            channel_id="ch_test",
            user_id="u.test",
            status=SessionState.IDLE,
            runtime=SessionRuntime(),
            version=1,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        # Modify session
        session.status = SessionState.READY

        # Act
        result = await session.save_session_with_version_check()

        # Assert
        assert result is True
        assert session.version == 2

        # Verify DB state
        saved = await Session.find_one(Session.session_id == "se_version_test")
        assert saved is not None
        assert saved.status == SessionState.READY
        assert saved.version == 2

    async def test_save_session_success_subsequent_updates(self, beanie_db):
        """Test successful save on subsequent updates (version 2 -> 3)."""
        # Arrange
        session = Session(
            session_id="se_subsequent",
            room_id="subsequent-room",
            channel_id="ch_test",
            user_id="u.test",
            status=SessionState.READY,
            runtime=SessionRuntime(),
            version=2,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        # Modify session
        session.status = SessionState.PUBLISHING

        # Act
        result = await session.save_session_with_version_check()

        # Assert
        assert result is True
        assert session.version == 3

        # Verify DB state
        saved = await Session.find_one(Session.session_id == "se_subsequent")
        assert saved is not None
        assert saved.status == SessionState.PUBLISHING
        assert saved.version == 3

    async def test_save_session_version_conflict(self, beanie_db):
        """Test version conflict raises AppError when another update occurred."""
        # Arrange
        session = Session(
            session_id="se_conflict",
            room_id="conflict-room",
            channel_id="ch_test",
            user_id="u.test",
            status=SessionState.IDLE,
            runtime=SessionRuntime(),
            version=1,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        # Simulate concurrent update: update the DB directly to version 2
        collection = Session.get_pymongo_collection()
        await collection.update_one(
            {"session_id": "se_conflict"},
            {"$set": {"version": 2, "status": "ready"}},
        )

        # Now try to save with stale session (still at version 1)
        session.status = SessionState.PUBLISHING

        # Act & Assert
        with pytest.raises(AppError) as exc_info:
            await session.save_session_with_version_check()

        assert exc_info.value.errcode == AppErrorCode.E_SESSION_VERSION_CONFLICT
        assert "Version conflict" in exc_info.value.errmesg

    async def test_save_session_backward_compatibility_none_version(self, beanie_db):
        """Test backward compatibility when session has no version field (None)."""
        # Arrange - Insert session without version field using PyMongo directly
        collection = Session.get_pymongo_collection()
        await collection.insert_one(
            {
                "session_id": "se_no_version",
                "room_id": "no-version-room",
                "channel_id": "ch_test",
                "user_id": "u.test",
                "status": "idle",
                "runtime": {},
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
                # Note: no 'version' field
            }
        )

        # Fetch session through Beanie (version should default to 1)
        session = await Session.find_one(Session.session_id == "se_no_version")
        assert session is not None

        # Modify session
        session.status = SessionState.READY

        # Act
        result = await session.save_session_with_version_check()

        # Assert
        assert result is True
        assert session.version == 2

        # Verify DB state
        saved = await Session.find_one(Session.session_id == "se_no_version")
        assert saved is not None
        assert saved.status == SessionState.READY
        assert saved.version == 2

    async def test_save_session_increments_version_correctly(self, beanie_db):
        """Test that version is incremented correctly on each save."""
        # Arrange
        session = Session(
            session_id="se_increment",
            room_id="increment-room",
            channel_id="ch_test",
            user_id="u.test",
            status=SessionState.IDLE,
            runtime=SessionRuntime(),
            version=1,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        # First update
        session.status = SessionState.READY
        await session.save_session_with_version_check()
        assert session.version == 2

        # Second update - need to refetch to get updated session
        session = await Session.find_one(Session.session_id == "se_increment")
        assert session is not None
        session.status = SessionState.PUBLISHING
        await session.save_session_with_version_check()
        assert session.version == 3

        # Third update
        session = await Session.find_one(Session.session_id == "se_increment")
        assert session is not None
        session.status = SessionState.LIVE
        await session.save_session_with_version_check()
        assert session.version == 4

        # Verify final DB state
        saved = await Session.find_one(Session.session_id == "se_increment")
        assert saved is not None
        assert saved.version == 4
        assert saved.status == SessionState.LIVE

    async def test_save_session_preserves_all_fields(self, beanie_db):
        """Test that save preserves all session fields correctly."""
        # Arrange
        runtime = SessionRuntime()
        runtime.post_id = "test_post_id"
        runtime.live_playback_url = "https://example.com/live"

        session = Session(
            session_id="se_preserve",
            room_id="preserve-room",
            channel_id="ch_test",
            user_id="u.test",
            title="Test Title",
            description="Test Description",
            lang="en",
            status=SessionState.IDLE,
            runtime=runtime,
            version=1,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        # Modify only status
        session.status = SessionState.READY

        # Act
        await session.save_session_with_version_check()

        # Assert - all other fields should be preserved
        saved = await Session.find_one(Session.session_id == "se_preserve")
        assert saved is not None
        assert saved.title == "Test Title"
        assert saved.description == "Test Description"
        assert saved.lang == "en"
        assert saved.runtime.post_id == "test_post_id"
        assert saved.runtime.live_playback_url == "https://example.com/live"

    async def test_save_session_conflict_error_contains_session_info(self, beanie_db):
        """Test that version conflict error message contains useful info."""
        # Arrange
        session = Session(
            session_id="se_error_info",
            room_id="error-info-room",
            channel_id="ch_test",
            user_id="u.test",
            status=SessionState.IDLE,
            runtime=SessionRuntime(),
            version=1,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        # Simulate concurrent update
        collection = Session.get_pymongo_collection()
        await collection.update_one(
            {"session_id": "se_error_info"},
            {"$set": {"version": 5, "status": "live"}},
        )

        # Act & Assert
        with pytest.raises(AppError) as exc_info:
            await session.save_session_with_version_check()

        error = exc_info.value
        assert "se_error_info" in error.errmesg
        assert "Expected version: 1" in error.errmesg
        assert "Current version: 5" in error.errmesg


@pytest.mark.usefixtures("clear_collections")
class TestPartialUpdateSessionWithVersionCheck:
    """Tests for partial_update_session_with_version_check method."""

    async def test_partial_update_success(self, beanie_db):
        """Test successful partial update with version increment."""
        runtime = SessionRuntime()
        runtime.post_id = "partial_post_id"

        session = Session(
            session_id="se_partial",
            room_id="partial-room",
            channel_id="ch_test",
            user_id="u.test",
            title="Original Title",
            description="Original Description",
            status=SessionState.IDLE,
            runtime=runtime,
            version=1,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        result = await session.partial_update_session_with_version_check(
            {Session.status: SessionState.READY, Session.title: "Updated Title"},
        )

        assert result is True
        assert session.version == 2

        saved = await Session.find_one(Session.session_id == "se_partial")
        assert saved is not None
        assert saved.status == SessionState.READY
        assert saved.title == "Updated Title"
        assert saved.description == "Original Description"
        assert saved.runtime.post_id == "partial_post_id"

    async def test_partial_update_version_conflict(self, beanie_db):
        """Test version conflict on partial update."""
        session = Session(
            session_id="se_partial_conflict",
            room_id="partial-conflict-room",
            channel_id="ch_test",
            user_id="u.test",
            status=SessionState.IDLE,
            runtime=SessionRuntime(),
            version=1,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        collection = Session.get_pymongo_collection()
        await collection.update_one(
            {"session_id": "se_partial_conflict"},
            {"$set": {"version": 2}},
        )

        with pytest.raises(AppError) as exc_info:
            await session.partial_update_session_with_version_check(
                {Session.status: SessionState.LIVE},
            )

        assert exc_info.value.errcode == AppErrorCode.E_SESSION_VERSION_CONFLICT

    async def test_partial_update_backward_compatibility_none_version(self, beanie_db):
        """Test partial update for session with missing version field."""
        collection = Session.get_pymongo_collection()
        await collection.insert_one(
            {
                "session_id": "se_partial_no_version",
                "room_id": "no-version-room",
                "channel_id": "ch_test",
                "user_id": "u.test",
                "status": "idle",
                "runtime": {},
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            }
        )

        session = await Session.find_one(Session.session_id == "se_partial_no_version")
        assert session is not None

        result = await session.partial_update_session_with_version_check(
            {Session.status: SessionState.READY},
        )

        assert result is True
        assert session.version == 2

        saved = await Session.find_one(Session.session_id == "se_partial_no_version")
        assert saved is not None
        assert saved.status == SessionState.READY
        assert saved.version == 2

    async def test_partial_update_rejects_version_in_updates(self, beanie_db):
        """Test that providing Session.version in updates raises AppError."""
        session = Session(
            session_id="se_version_in_updates",
            room_id="version-in-updates-room",
            channel_id="ch_test",
            user_id="u.test",
            status=SessionState.IDLE,
            runtime=SessionRuntime(),
            version=1,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        with pytest.raises(AppError) as exc_info:
            await session.partial_update_session_with_version_check(
                {Session.version: 99},
            )

        assert exc_info.value.errcode == AppErrorCode.E_INVALID_REQUEST
        assert "updates must not include Session.version" in exc_info.value.errmesg

    async def test_partial_update_rejects_invalid_max_retry(self, beanie_db):
        """Test that max_retry_on_conflicts outside 0-10 raises AppError."""
        session = Session(
            session_id="se_invalid_retry",
            room_id="invalid-retry-room",
            channel_id="ch_test",
            user_id="u.test",
            status=SessionState.IDLE,
            runtime=SessionRuntime(),
            version=1,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        with pytest.raises(AppError) as exc_info:
            await session.partial_update_session_with_version_check(
                {Session.title: "New Title"},
                max_retry_on_conflicts=11,
            )
        assert exc_info.value.errcode == AppErrorCode.E_INVALID_REQUEST
        assert "max_retry_on_conflicts must be between 0 and 10" in exc_info.value.errmesg

        with pytest.raises(AppError) as exc_info:
            await session.partial_update_session_with_version_check(
                {Session.title: "New Title"},
                max_retry_on_conflicts=-1,
            )
        assert exc_info.value.errcode == AppErrorCode.E_INVALID_REQUEST
        assert "max_retry_on_conflicts must be between 0 and 10" in exc_info.value.errmesg

    async def test_partial_update_rejects_retry_with_status_field(self, beanie_db):
        """Test that status updates with retries raise AppError (status is critical)."""
        session = Session(
            session_id="se_status_no_retry",
            room_id="status-no-retry-room",
            channel_id="ch_test",
            user_id="u.test",
            status=SessionState.IDLE,
            runtime=SessionRuntime(),
            version=1,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        with pytest.raises(AppError) as exc_info:
            await session.partial_update_session_with_version_check(
                {Session.status: SessionState.READY},
                max_retry_on_conflicts=1,
            )

        assert exc_info.value.errcode == AppErrorCode.E_INVALID_REQUEST
        assert "retries not allowed when updating status" in exc_info.value.errmesg

    async def test_partial_update_allows_status_with_zero_retry(self, beanie_db):
        """Test that status updates succeed when max_retry_on_conflicts=0."""
        session = Session(
            session_id="se_status_zero_retry",
            room_id="status-zero-retry-room",
            channel_id="ch_test",
            user_id="u.test",
            status=SessionState.IDLE,
            runtime=SessionRuntime(),
            version=1,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        result = await session.partial_update_session_with_version_check(
            {Session.status: SessionState.READY},
            max_retry_on_conflicts=0,
        )

        assert result is True
        saved = await Session.find_one(Session.session_id == "se_status_zero_retry")
        assert saved is not None
        assert saved.status == SessionState.READY

    async def test_partial_update_allows_non_status_with_retry(self, beanie_db):
        """Test that non-status field updates allow retries."""
        session = Session(
            session_id="se_non_status_retry",
            room_id="non-status-retry-room",
            channel_id="ch_test",
            user_id="u.test",
            status=SessionState.IDLE,
            runtime=SessionRuntime(),
            version=1,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        result = await session.partial_update_session_with_version_check(
            {Session.title: "Updated Title"},
            max_retry_on_conflicts=3,
        )

        assert result is True
        saved = await Session.find_one(Session.session_id == "se_non_status_retry")
        assert saved is not None
        assert saved.title == "Updated Title"


@pytest.mark.usefixtures("clear_collections")
class TestPartialUpdateWithRetry:
    """Tests for partial_update_session_with_version_check with max_retry_on_conflicts."""

    async def test_retry_success_after_one_conflict(self, beanie_db):
        """Test successful update after one retry due to version conflict."""
        session = Session(
            session_id="se_retry_success",
            room_id="retry-success-room",
            channel_id="ch_test",
            user_id="u.test",
            status=SessionState.IDLE,
            runtime=SessionRuntime(),
            version=1,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        # Simulate concurrent update - bump version to 2
        collection = Session.get_pymongo_collection()
        await collection.update_one(
            {"session_id": "se_retry_success"},
            {"$set": {"version": 2}},
        )

        # Try with retry - should succeed on second attempt
        result = await session.partial_update_session_with_version_check(
            {Session.title: "Updated Title"},
            max_retry_on_conflicts=1,
        )

        assert result is True
        assert session.version == 3  # 2 + 1 after retry

        saved = await Session.find_one(Session.session_id == "se_retry_success")
        assert saved is not None
        assert saved.title == "Updated Title"
        assert saved.version == 3

    async def test_retry_fails_after_max_retries_exhausted(self, beanie_db):
        """Test failure when all retries are exhausted due to continuous conflicts."""
        from unittest.mock import patch

        session = Session(
            session_id="se_retry_exhausted",
            room_id="retry-exhausted-room",
            channel_id="ch_test",
            user_id="u.test",
            status=SessionState.IDLE,
            runtime=SessionRuntime(),
            version=1,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        collection = Session.get_pymongo_collection()

        # Simulate first conflict
        await collection.update_one(
            {"session_id": "se_retry_exhausted"},
            {"$set": {"version": 100}},
        )

        # Mock Session.get to return a session, then bump version before next attempt
        original_get = Session.get
        call_count = 0

        async def get_and_bump(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = await original_get(*args, **kwargs)
            # Bump version after each refresh to cause continuous conflicts
            await collection.update_one(
                {"session_id": "se_retry_exhausted"},
                {"$inc": {"version": 1}},
            )
            return result

        with (
            patch.object(Session, "get", side_effect=get_and_bump),
            pytest.raises(AppError) as exc_info,
        ):
            # Try with limited retries - should fail
            await session.partial_update_session_with_version_check(
                {Session.title: "Updated Title"},
                max_retry_on_conflicts=2,  # 3 total attempts
            )

        assert exc_info.value.errcode == AppErrorCode.E_SESSION_VERSION_CONFLICT

    async def test_retry_zero_means_no_retry(self, beanie_db):
        """Test that max_retry_on_conflicts=0 means no retry (default behavior)."""
        session = Session(
            session_id="se_no_retry",
            room_id="no-retry-room",
            channel_id="ch_test",
            user_id="u.test",
            status=SessionState.IDLE,
            runtime=SessionRuntime(),
            version=1,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        # Simulate concurrent update
        collection = Session.get_pymongo_collection()
        await collection.update_one(
            {"session_id": "se_no_retry"},
            {"$set": {"version": 2}},
        )

        # Try with no retry - should fail immediately
        with pytest.raises(AppError) as exc_info:
            await session.partial_update_session_with_version_check(
                {Session.status: SessionState.READY},
                max_retry_on_conflicts=0,
            )

        assert exc_info.value.errcode == AppErrorCode.E_SESSION_VERSION_CONFLICT

    async def test_retry_success_on_last_attempt(self, beanie_db):
        """Test successful update on the last retry attempt."""
        session = Session(
            session_id="se_last_attempt",
            room_id="last-attempt-room",
            channel_id="ch_test",
            user_id="u.test",
            status=SessionState.IDLE,
            runtime=SessionRuntime(),
            version=1,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        # Bump version once to cause first attempt to fail
        collection = Session.get_pymongo_collection()
        await collection.update_one(
            {"session_id": "se_last_attempt"},
            {"$set": {"version": 2}},
        )

        # With max_retry_on_conflicts=1, we have 2 attempts total
        # First attempt fails (version mismatch), second attempt succeeds
        result = await session.partial_update_session_with_version_check(
            {Session.title: "Updated Title"},
            max_retry_on_conflicts=1,
        )

        assert result is True
        assert session.version == 3

    async def test_retry_updates_local_session_version(self, beanie_db):
        """Test that retry correctly updates local session version from DB."""
        session = Session(
            session_id="se_version_refresh",
            room_id="version-refresh-room",
            channel_id="ch_test",
            user_id="u.test",
            status=SessionState.IDLE,
            runtime=SessionRuntime(),
            version=1,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        # Bump version significantly
        collection = Session.get_pymongo_collection()
        await collection.update_one(
            {"session_id": "se_version_refresh"},
            {"$set": {"version": 10}},
        )

        # With retry, should refresh version from DB
        result = await session.partial_update_session_with_version_check(
            {Session.title: "Updated Title"},
            max_retry_on_conflicts=1,
        )

        assert result is True
        assert session.version == 11  # 10 + 1 after successful retry

    async def test_no_retry_when_first_attempt_succeeds(self, beanie_db):
        """Test that no retry happens when first attempt succeeds."""
        session = Session(
            session_id="se_first_success",
            room_id="first-success-room",
            channel_id="ch_test",
            user_id="u.test",
            status=SessionState.IDLE,
            runtime=SessionRuntime(),
            version=1,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        # No version conflict - should succeed on first attempt
        result = await session.partial_update_session_with_version_check(
            {Session.title: "Updated Title"},
            max_retry_on_conflicts=5,
        )

        assert result is True
        assert session.version == 2  # Only incremented once

        saved = await Session.find_one(Session.session_id == "se_first_success")
        assert saved is not None
        assert saved.title == "Updated Title"
        assert saved.version == 2
