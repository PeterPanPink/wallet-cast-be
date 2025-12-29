# Room and Session Relationship

This document describes the relationship between RTC **Rooms** and domain **Sessions** in this demo.

## Overview

In this demo, a **Session** is our domain entity representing a single broadcast lifecycle (tied to egress),
while a **Room** is a persistent RTC resource that handles real-time communication. The relationship is:

- **Many Sessions : One Room**: A single `room_id` can have multiple Sessions over its lifetime
- **Room is persistent**: The RTC Provider Room persists across session boundaries while the host remains connected
- **Session is transient**: Each Session represents one egress lifecycle (start → live → stop)
- **Automatic rebinding**: When a Session ends (egress stops), the backend automatically creates a new Session bound to the same Room

## ID Formats

| Entity  | Prefix | Example                         | Description                           |
| ------- | ------ | ------------------------------- | ------------------------------------- |
| Session | `se_`  | `se_01jcpz7g8m9kn2q1w3y4x5z6a7` | Internal session identifier           |
| Room    | `ro_`  | `ro_01jcpz7g8m9kn2q1w3y4x5z6a7` | RTC room name (stored in Session) |
| Channel | `ch_`  | `ch_01jcpz7g8m9kn2q1w3y4x5z6a7` | Parent channel identifier             |

Both IDs are ULIDs (Universally Unique Lexicographically Sortable Identifiers) with their respective prefix.

## Session Schema

```python
class Session(Document):
    session_id: Indexed(str, unique=True)  # Primary identifier
    room_id: Indexed(str, unique=True)     # RTC room name
    channel_id: str                        # Parent channel
    user_id: str                           # Owner
    status: SessionState                   # Current state
    # ... other fields
```

Both `session_id` and `room_id` are unique indexes. A Session lookup can happen via either:

- `Session.session_id == session_id` - for API operations
- `Session.room_id == room_id` - for RTC webhook handling

## Lifecycle

### Creation

When `create_session()` is called:

1. Generate new `session_id` with `se_` prefix
2. Generate new `room_id` with `ro_` prefix
3. Create Session document with `status=IDLE`
4. RTC Provider Room is NOT created yet (lazy creation)

```
Channel → create_session() → Session(session_id, room_id, status=IDLE)
```

### Room Creation (On-Demand)

The RTC Provider Room is created when:

1. **Host requests access token**: The room is created before returning the token
2. **Explicitly via API**: `POST /session/room` creates the room

```
Session(IDLE) → create_room(room_id) → RTC Provider Room created
              → host joins           → Session(READY)
```

### Going Live

```
Session(READY) → start_live() → Streaming Provider stream created
                              → RTC Provider egress started
                              → Session(PUBLISHING)
               → Streaming Provider webhook (active) → Session(LIVE)
```

### Ending and Automatic Session Recreation

```
Session(LIVE) → end_session() → Egress stopped → Session(ENDING)
              → Streaming Provider webhook (idle/disconnected) → Session(STOPPED)
              → Backend auto-creates new Session(READY) with same room_id
              → Room remains active (host still connected)
```

When an egress ends, the Session transitions to STOPPED, but the **Room continues to exist**. The backend automatically creates a new Session bound to the same Room, allowing the host to start a new broadcast without rejoining.

### Session Recreation (Automatic)

When a session stops (egress ends), the backend automatically creates a new session **reusing the same `room_id`**:

```python
# From _sessions.py::recreate_session_from_stopped()
new_session = Session(
    session_id=new_session_id(),        # NEW session ID
    room_id=stopped_session.room_id,    # SAME room ID (reused)
    status=SessionState.READY,
    # ... copy other fields from stopped session
)
```

This enables:

- **Continuous room presence**: Host stays in the room, viewers stay connected
- **Fresh session per broadcast**: Each egress gets its own session for analytics/recording
- **Seamless multi-broadcast**: Host can do multiple broadcasts without rejoining

### Room Deletion

The Room is only deleted when:

- Host explicitly leaves/disconnects
- Room times out due to inactivity (empty_timeout)
- Admin forcefully deletes the room

## State Machine

```
                    ┌─────────────────────────────────────┐
                    │         Room persists               │
                    ▼                                     │
IDLE → READY → PUBLISHING → LIVE → ENDING → STOPPED ─────┘
  ↓      ↓         ↓                          │
CANCELLED  CANCELLED  CANCELLED               ▼
                                        New Session(READY)
                                        (same room_id)
```

The Room persists while the host is connected. Sessions cycle through their lifecycle, with new Sessions automatically created when egress ends. See [SESSION_STATE.md](SESSION_STATE.md) for details.

## Key Operations by ID

### Using `session_id`

- API endpoints (create, update, get, delete)
- Client-facing operations
- Admin operations

```python
session = await Session.find_one(Session.session_id == session_id)
```

### Using `room_id`

- RTC token generation (room name)
- RTC webhooks (room.name from event)
- RTC room operations (create, delete)
- Streaming egress configuration

```python
# Find session from RTC webhook
session = await Session.find_one(
    Session.room_id == room_id,
    In(Session.status, SessionState.active_states()),
)
```

## RTC Provider Integration (Sanitized Demo)

### Room Name = room_id

The RTC Provider room name is always the Session's `room_id`:

```python
# Creating room (pseudo-code)
await rtc_provider.create_room(room_name=session.room_id)

# Generating token (pseudo-code)
token = rtc_service.create_access_token(
    identity=user_id,
    room=session.room_id,  # room_id used as room name
    name=display_name,
)

# Starting egress to streaming provider (pseudo-code)
await rtc_provider.start_room_composite_egress(
    room_name=session.room_id,
    rtmp_url=streaming_rtmp_url,
)
```

### Webhook Correlation

RTC provider webhooks include `room.name` which is the `room_id`:

```python
# app/api/webhooks/rtc.py (sanitized path example)
async def handle_participant_joined(event: WebhookEvent):
    room_name = event.room.name  # This is the room_id
    session = await Session.find_one(Session.room_id == room_name)
    await session.set({Session.status: SessionState.READY})
```

## Summary

| Aspect          | session_id                          | room_id                         |
| --------------- | ----------------------------------- | ------------------------------- |
| Purpose         | Internal/API identifier             | RTC resource identifier         |
| Uniqueness      | Globally unique                     | Globally unique                 |
| Prefix          | `se_`                               | `ro_`                           |
| Reusability     | Never reused                        | Reused across multiple sessions |
| Lifecycle       | One per egress                      | Persists while host connected   |
| Used by         | API, Admin, Analytics               | RTC, Streaming, Webhooks        |
| Created when    | `create_session()` or auto-recreate | `create_session()` (first time) |
| RTC mapping     | N/A                                 | `room.name` = `room_id`         |

The separation allows:

1. **Clean API boundaries**: `session_id` for external APIs
2. **RTC integration**: `room_id` as room name for all RTC operations
3. **Session continuity**: Same `room_id` spans multiple sessions (multiple broadcasts)
4. **Webhook handling**: Lookup session by `room_id` from RTC events
5. **Analytics isolation**: Each broadcast has its own `session_id` for tracking
