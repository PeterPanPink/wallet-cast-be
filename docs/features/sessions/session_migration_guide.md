# Session Domain Migration Guide

## Overview

This guide documents the migration from raw MongoDB dictionaries to typed Beanie ODM models and enums for files in `app/domain/live/session/`.

**Status**: `create.py` has been migrated ✅

**Remaining files**:

- `start.py` - Session start logic
- `update.py` - Session update and state machine
- `end.py` - Session end logic
- `list.py` - Session listing and pagination
- `list_user.py` - User-specific session listing
- `preflight.py` - Session preflight checks

## Migration Principles

### 1. Use Beanie Models Instead of Dictionaries

**Before:**

```python
db = mongo_client.get_database()
session_coll = db['cbx_live_session']
session_doc = await session_coll.find_one({'room_id': room_id})
```

**After:**

```python
from app.schemas import Session
session = await Session.find_one(Session.room_id == room_id)
```

### 2. Use Enums for Fixed String Values

**Before:**

```python
if session_doc.get('status') in ['idle', 'ready', 'publishing', 'live', 'ending']:
    # ...
```

**After:**

```python
from app.schemas.session_state import SessionStatus
from beanie.operators import In

active_statuses = [SessionStatus.IDLE, SessionStatus.READY, SessionStatus.PUBLISHING,
                   SessionStatus.LIVE, SessionStatus.ENDING]
if session.status in active_statuses:
    # ...
```

### 3. Use Typed Provider Configs

**Before:**

```python
provider = channel_doc.get('provider', 'livekit')
configs = channel_doc.get('configs') or {}
```

**After:**

```python
from app.api.live.channel.schemas import SessionRuntime, MuxConfig, MediaLiveConfig

config: SessionRuntime | MuxConfig | MediaLiveConfig = channel.config
```

### 4. Replace MongoDB Operations with Beanie Methods

| MongoDB Operation                                                                      | Beanie Equivalent                                   |
| -------------------------------------------------------------------------------------- | --------------------------------------------------- |
| `collection.find_one(filter, projection)`                                              | `Model.find_one(Model.field == value)`              |
| `collection.find(filter).sort(...)`                                                    | `Model.find(Model.field == value).sort(...)`        |
| `collection.insert_one(doc)`                                                           | `model.insert()`                                    |
| `collection.update_one(filter, update)`                                                | `model.save()` or `Model.find_one(...).update(...)` |
| `collection.find_one_and_update(filter, update, return_document=ReturnDocument.AFTER)` | `await model.save()` then return model              |
| `collection.delete_one(filter)`                                                        | `await model.delete()`                              |

### 5. Beanie Query Operators

```python
from beanie.operators import In, Eq, GTE, LTE, And, Or

# $in operator
await Session.find(In(Session.status, [SessionStatus.LIVE, SessionStatus.READY])).to_list()

# Multiple conditions (implicit AND)
await Session.find_one(
    Session.channel_id == channel_id,
    Session.status == SessionStatus.LIVE
)

# Comparison operators
await Session.find(
    Session.created_at >= start_date,
    Session.created_at <= end_date
).to_list()

# $or operator
from beanie.operators import Or
await Session.find(
    Or(
        Session.status == SessionStatus.LIVE,
        Session.status == SessionStatus.READY
    )
).to_list()
```

## File-Specific Migration Instructions

### `start.py` - Session Start Logic

**Key Changes Needed:**

1. **Replace projection constants with model fields:**

   ```python
   # Remove _SESSION_PROJECTION dict
   # Use model.model_dump() or select specific fields in query
   ```

2. **Update session queries:**

   ```python
   # Before
   session_doc = await session_coll.find_one(
       {'room_id': room_id, 'user_id': user_id},
       _SESSION_PROJECTION
   )

   # After
   session = await Session.find_one(
       Session.room_id == room_id,
       Session.user_id == user_id
   )
   ```

3. **State transition checks:**

   ```python
   # Before
   if session_doc.get('status') not in ['idle', 'ready']:
       return api_failure(...)

   # After
   if session.status not in [SessionStatus.IDLE, SessionStatus.READY]:
       return api_failure(...)
   ```

4. **Update operations:**

   ```python
   # Before
   updated_doc = await session_coll.find_one_and_update(
       {'room_id': room_id},
       {'$set': {'status': 'live', 'started_at': utc_now()}},
       return_document=ReturnDocument.AFTER
   )

   # After
   session.status = SessionStatus.LIVE
   session.started_at = utc_now()
   await session.save()
   ```

### `update.py` - Session Update and State Machine

**Key Changes Needed:**

1. **Update SessionStateMachine to use enums:**

   ```python
   from app.schemas.session_state import SessionStatus

   class SessionStateMachine:
       INITIAL_STATE: ClassVar[SessionStatus] = SessionStatus.IDLE
       TERMINAL_STATES: ClassVar[set[SessionStatus]] = {
           SessionStatus.CANCELLED, SessionStatus.STOPPED
       }
       _TRANSITIONS: ClassVar[dict[SessionStatus, set[SessionStatus]]] = {
           SessionStatus.IDLE: {SessionStatus.READY},
           SessionStatus.READY: {SessionStatus.PUBLISHING, SessionStatus.CANCELLED, SessionStatus.IDLE},
           # ...
       }
   ```

2. **Replace string state checks:**

   ```python
   # Before
   def _normalize_state(self, state: str) -> str:
       return state.lower().strip()

   # After
   def _normalize_state(self, state: str | SessionStatus) -> SessionStatus:
       if isinstance(state, SessionStatus):
           return state
       # Convert string to enum
       try:
           return SessionStatus(state.lower().strip())
       except ValueError:
           raise ValueError(f'Invalid session state: {state}')
   ```

3. **Update session fetch and update:**

   ```python
   # Before
   session_doc = await session_coll.find_one({'room_id': room_id})

   # After
   session = await Session.find_one(Session.room_id == room_id)
   ```

### `end.py` - Session End Logic

**Key Changes Needed:**

1. **Similar to start.py - replace collection queries with Beanie:**

   ```python
   # Before
   session_doc = await session_coll.find_one_and_update(
       {'room_id': room_id, 'status': {'$in': ['live', 'ending']}},
       {'$set': {'status': 'stopped', 'stopped_at': utc_now()}},
       return_document=ReturnDocument.AFTER
   )

   # After
   from beanie.operators import In
   session = await Session.find_one(
       Session.room_id == room_id,
       In(Session.status, [SessionStatus.LIVE, SessionStatus.ENDING])
   )
   if session:
       session.status = SessionStatus.STOPPED
       session.stopped_at = utc_now()
       await session.save()
   ```

2. **Provider status updates:**
   ```python
   # Use session.provider_status dict field directly
   session.provider_status = {'medialive': {'channel_state': 'STOPPED'}}
   await session.save()
   ```

### `list.py` - Session Listing and Pagination

**Key Changes Needed:**

1. **Replace raw MongoDB queries with Beanie find:**

   ```python
   # Before
   session_coll = db['cbx_live_session']
   cursor = session_coll.find(criteria).sort('created_at', -1).limit(page_size)

   # After
   from beanie.operators import In
   query = Session.find()
   if channel_id:
       query = query.find(Session.channel_id == channel_id)
   if status_list:
       query = query.find(In(Session.status, status_list))
   sessions = await query.sort(-Session.created_at).limit(page_size).to_list()
   ```

2. **Pagination with cursor:**

   ```python
   # Before
   if cursor:
       cursor_id = ObjectId(cursor)
       criteria.append({'_id': {'$lt': cursor_id}})

   # After
   if cursor:
       cursor_id = ObjectId(cursor)
       query = query.find(Session.id < cursor_id)
   ```

3. **Result serialization:**
   ```python
   # After fetching sessions
   results = []
   for session in sessions:
       session_dict = session.model_dump(exclude={'id', 'revision_id'})
       # Resolve provider config
       session_dict['config'] = _resolve_config(session)
       results.append(session_dict)
   ```

### `preflight.py` - Session Preflight Checks

**Key Changes Needed:**

1. **Active session check:**

   ```python
   # Before
   _ACTIVE_SESSION_STATUS = {"ready", "publishing", "live", "ending", "aborted"}
   active_session = await session_coll.find_one({
       'channel_id': channel_id,
       'status': {'$in': list(_ACTIVE_SESSION_STATUS)}
   })

   # After
   from beanie.operators import In
   active_statuses = [SessionStatus.READY, SessionStatus.PUBLISHING,
                      SessionStatus.LIVE, SessionStatus.ENDING, SessionStatus.ABORTED]
   active_session = await Session.find_one(
       Session.channel_id == channel_id,
       In(Session.status, active_statuses)
   )
   ```

2. **Use get_or_create_session (already migrated):**

   ```python
   # This function in create.py already uses Beanie models
   session_result = await get_or_create_session(mongo_client, params)
   ```

3. **Channel lookups:**

   ```python
   # Before
   channel_doc = await channel_coll.find_one({'channel_id': channel_id})

   # After
   from app.schemas import Channel
   channel = await Channel.find_one(Channel.channel_id == channel_id)
   ```

### `list_user.py` - User-Specific Session Listing

**Similar to `list.py`** but with additional user_id filter:

```python
# Before
criteria.append({'user_id': user_id})

# After
query = Session.find(Session.user_id == user_id)
```

## Common Patterns and Helpers

### 1. Config Resolution Helper

```python
def _resolve_session_config(session: Session) -> dict[str, Any]:
    """Resolve session provider config to dict for API response."""
    if isinstance(session.config, (SessionRuntime, MuxConfig, MediaLiveConfig)):
        return session.config.model_dump(exclude_none=True)
    return session.config if isinstance(session.config, dict) else {}
```

### 2. Session to Dict Conversion

```python
def session_to_dict(session: Session) -> dict[str, Any]:
    """Convert Session model to dict for API response."""
    result = session.model_dump(exclude={'id', 'revision_id'})
    result['config'] = _resolve_session_config(session)
    return result
```

### 3. Backward Compatibility with mongo_client Parameter

Many functions accept `mongo_client: AsyncIOMotorClient` but don't need it with Beanie:

```python
async def some_function(
    mongo_client: AsyncIOMotorClient,  # Keep for backward compatibility
    room_id: str,
) -> dict | ApiFailure:
    # Don't use mongo_client, use Beanie directly
    session = await Session.find_one(Session.room_id == room_id)
    # ...
```

## Testing Strategy

1. **Run tests after each file migration:**

   ```bash
   make test-fast
   ```

2. **Check for type errors:**

   - Pylance will show type errors - many can be ignored if they're about unknown types from Beanie internals
   - Focus on fixing errors in your own code

3. **Test edge cases:**
   - None/null values
   - Empty lists
   - Missing optional fields

## Migration Checklist

For each file, ensure:

- [ ] Import `Session`, `Channel` from `app.schemas`
- [ ] Import `SessionStatus` from `app.schemas.session_state`
- [ ] Import Beanie operators (`In`, etc.) from `beanie.operators`
- [ ] Replace `collection.find_one()` with `Model.find_one()`
- [ ] Replace `collection.find()` with `Model.find()`
- [ ] Replace `collection.insert_one()` with `model.insert()`
- [ ] Replace `collection.update_one()` with `model.save()`
- [ ] Replace string status checks with enum comparisons
- [ ] Replace projection dicts with model field access
- [ ] Update function signatures to use typed models where appropriate
- [ ] Test thoroughly

## Benefits After Migration

✅ **Type Safety**: Catch errors at development time, not runtime  
✅ **IntelliSense**: Better autocomplete in IDE  
✅ **Validation**: Pydantic validates data automatically  
✅ **Maintainability**: Clear contracts via typed models  
✅ **Less Boilerplate**: No manual dict manipulation  
✅ **Consistent**: Single source of truth for schemas

## Notes

- **Beanie uses `id` field**: Access with `session.id`, not `session._id`
- **Enum values**: `SessionStatus.LIVE.value` returns `"live"` string
- **Optional fields**: Beanie models handle None automatically
- **Backwards compatibility**: Functions still return dicts for API responses
- **Performance**: Beanie queries are as fast as raw PyMongo (it's a thin wrapper)

## Reference: create.py Migration Summary

See `app/domain/live/session/create.py` for a complete example of:

- Using Beanie queries with `find_one()` and operators
- Creating documents with `Session()` constructor
- Using enums (`SessionStatus`)
- Type-safe config resolution
- Proper error handling with typed returns

---

**Questions or Issues?** Check existing migrated files or refer to Beanie documentation: https://beanie-odm.dev/
