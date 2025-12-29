"""
Test MongoDB/Beanie fixtures to verify they work correctly.

This file also serves as an example of how to use the fixtures.
"""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.schemas import Channel, Session, SessionState


def unique_id(prefix: str = "") -> str:
    """Generate a unique ID for test data to avoid collisions."""
    return f"{prefix}{uuid4().hex[:8]}"


# -----------------------------------------------------------------------------
# Basic Beanie CRUD Tests
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_beanie_initialized(beanie_db):
    """Verify Beanie is properly initialized with test database."""
    assert beanie_db is not None
    # Beanie should be ready to use
    count = await Channel.count()
    assert count >= 0  # Just verify we can query


@pytest.mark.asyncio
async def test_create_channel(beanie_db):
    """Test creating a Channel document."""
    channel_id = unique_id("ch_")
    now = datetime.now(timezone.utc)

    channel = Channel(
        channel_id=channel_id,
        user_id="u.test_user",
        title="Test Channel",
        location="US",
        created_at=now,
        updated_at=now,
    )
    await channel.insert()

    # Verify it was saved
    found = await Channel.find_one(Channel.channel_id == channel_id)
    assert found is not None
    assert found.title == "Test Channel"
    assert found.user_id == "u.test_user"


@pytest.mark.asyncio
async def test_create_session(beanie_db):
    """Test creating a Session document."""
    session_id = unique_id("se_")
    room_id = unique_id("ro_")
    channel_id = unique_id("ch_")
    now = datetime.now(timezone.utc)

    session = Session(
        session_id=session_id,
        room_id=room_id,
        channel_id=channel_id,
        user_id="u.test_user",
        status=SessionState.IDLE,
        created_at=now,
        updated_at=now,
    )
    await session.insert()

    # Verify using Beanie query
    found = await Session.find_one(Session.room_id == room_id)
    assert found is not None
    assert found.session_id == session_id
    assert found.status == SessionState.IDLE


@pytest.mark.asyncio
async def test_update_session(beanie_db):
    """Test updating a Session document."""
    session_id = unique_id("se_")
    room_id = unique_id("ro_")
    channel_id = unique_id("ch_")
    now = datetime.now(timezone.utc)

    session = Session(
        session_id=session_id,
        room_id=room_id,
        channel_id=channel_id,
        user_id="u.test_user",
        status=SessionState.IDLE,
        created_at=now,
        updated_at=now,
    )
    await session.insert()

    # Update status using Beanie's save method
    session.status = SessionState.LIVE
    session.started_at = now
    await session.save()

    # Verify update
    updated = await Session.find_one(Session.session_id == session_id)
    assert updated is not None
    assert updated.status == SessionState.LIVE
    assert updated.started_at is not None


@pytest.mark.asyncio
async def test_query_sessions(beanie_db):
    """Test querying multiple Session documents."""
    user_id = unique_id("u_query_")
    now = datetime.now(timezone.utc)

    # Create multiple sessions - each needs unique channel_id due to
    # channel_id_active_unique index (one active session per channel)
    session_ids = []
    for i in range(3):
        session_id = unique_id(f"se_query_{i}_")
        room_id = unique_id(f"ro_query_{i}_")
        channel_id = unique_id(f"ch_query_{i}_")  # Unique per session
        session_ids.append(session_id)

        session = Session(
            session_id=session_id,
            room_id=room_id,
            channel_id=channel_id,
            user_id=user_id,  # Same user for all
            status=SessionState.IDLE if i < 2 else SessionState.LIVE,
            created_at=now,
            updated_at=now,
        )
        await session.insert()

    # Query idle sessions for this user
    idle_sessions = await Session.find(
        Session.user_id == user_id,
        Session.status == SessionState.IDLE,
    ).to_list()

    assert len(idle_sessions) == 2

    # Query live sessions for this user
    live_sessions = await Session.find(
        Session.user_id == user_id,
        Session.status == SessionState.LIVE,
    ).to_list()

    assert len(live_sessions) == 1


@pytest.mark.asyncio
async def test_delete_session(beanie_db):
    """Test deleting a Session document."""
    session_id = unique_id("se_delete_")
    room_id = unique_id("ro_delete_")
    channel_id = unique_id("ch_delete_")
    now = datetime.now(timezone.utc)

    session = Session(
        session_id=session_id,
        room_id=room_id,
        channel_id=channel_id,
        user_id="u.test_user",
        status=SessionState.IDLE,
        created_at=now,
        updated_at=now,
    )
    await session.insert()

    # Verify it exists
    found = await Session.find_one(Session.session_id == session_id)
    assert found is not None

    # Delete it
    await found.delete()

    # Verify it's gone
    deleted = await Session.find_one(Session.session_id == session_id)
    assert deleted is None


# -----------------------------------------------------------------------------
# Tests with Clean Collections (Isolated)
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clean_db_starts_empty(clean_beanie_db):
    """Test that clean_beanie_db fixture provides empty collections."""
    channel_count = await Channel.count()
    session_count = await Session.count()

    assert channel_count == 0
    assert session_count == 0


@pytest.mark.asyncio
async def test_isolated_channel_creation(clean_beanie_db):
    """Test creating channels with isolated (clean) database."""
    channel_id = unique_id("ch_isolated_")
    now = datetime.now(timezone.utc)

    # Create a channel
    channel = Channel(
        channel_id=channel_id,
        user_id="u.isolated_user",
        title="Isolated Test Channel",
        location="JP",
        created_at=now,
        updated_at=now,
    )
    await channel.insert()

    # Should be exactly 1 channel (since we started clean)
    count = await Channel.count()
    assert count == 1


@pytest.mark.usefixtures("clear_collections")
@pytest.mark.asyncio
async def test_with_explicit_clear(beanie_db):
    """
    Example of explicitly opting into collection clearing.

    Use @pytest.mark.usefixtures("clear_collections") when you want
    to ensure a clean state but don't need the db reference.
    """
    # Collections are cleared before this test runs
    count = await Session.count()
    assert count == 0

    # Create a session
    session_id = unique_id("se_clear_")
    room_id = unique_id("ro_clear_")
    channel_id = unique_id("ch_clear_")
    now = datetime.now(timezone.utc)

    session = Session(
        session_id=session_id,
        room_id=room_id,
        channel_id=channel_id,
        user_id="u.test",
        created_at=now,
        updated_at=now,
    )
    await session.insert()

    count = await Session.count()
    assert count == 1


# -----------------------------------------------------------------------------
# Example: Testing Business Logic with Beanie
# -----------------------------------------------------------------------------


async def update_session_status(
    session_id: str,
    new_status: SessionState,
) -> Session | None:
    """Example business function that updates session status."""
    session = await Session.find_one(Session.session_id == session_id)
    if not session:
        return None

    session.status = new_status
    session.updated_at = datetime.now(timezone.utc)

    if new_status == SessionState.LIVE:
        session.started_at = datetime.now(timezone.utc)
    elif new_status == SessionState.STOPPED:
        session.stopped_at = datetime.now(timezone.utc)

    await session.save()
    return session


@pytest.mark.asyncio
async def test_update_session_status_service(clean_beanie_db):
    """Test a business function that uses Beanie models."""
    session_id = unique_id("se_svc_")
    room_id = unique_id("ro_svc_")
    channel_id = unique_id("ch_svc_")
    now = datetime.now(timezone.utc)

    # Setup: create a session
    session = Session(
        session_id=session_id,
        room_id=room_id,
        channel_id=channel_id,
        user_id="u.service_user",
        status=SessionState.IDLE,
        created_at=now,
        updated_at=now,
    )
    await session.insert()

    # Test: update status to LIVE
    updated = await update_session_status(session_id, SessionState.LIVE)

    assert updated is not None
    assert updated.status == SessionState.LIVE
    assert updated.started_at is not None

    # Verify in database
    found = await Session.find_one(Session.session_id == session_id)
    assert found is not None
    assert found.status == SessionState.LIVE


@pytest.mark.asyncio
async def test_update_nonexistent_session(clean_beanie_db):
    """Test updating a session that doesn't exist."""
    result = await update_session_status("nonexistent_id", SessionState.LIVE)
    assert result is None
