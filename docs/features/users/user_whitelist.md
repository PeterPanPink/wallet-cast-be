# User Whitelist

This demo uses a Redis Set to control which users can access the API.

## Redis Configuration

- **Key**: `wallet-cast-demo:user_whitelist`
- **Type**: Set
- **Database**: 2 (configured via `REDIS_URL_FLC_MAJOR`)

## Behavior

All API endpoints using `CurrentUser` dependency check the whitelist:

1. If the set contains `"ALL"` → all authenticated users are allowed
2. If the set contains the specific `user_id` → that user is allowed
3. Otherwise → returns `E_NOT_WHITELISTED` (403)

## Redis Commands

```bash
# Connect to Redis (local docker)
docker exec -it wallet-cast-demo-local-redis-1 redis-cli -n 2

# Allow all users
SADD wallet-cast-demo:user_whitelist "ALL"

# Allow specific users
SADD wallet-cast-demo:user_whitelist "user123" "user456"

# Remove "ALL" (switch to whitelist mode)
SREM wallet-cast-demo:user_whitelist "ALL"

# Remove a specific user
SREM wallet-cast-demo:user_whitelist "user123"

# List all whitelisted entries
SMEMBERS wallet-cast-demo:user_whitelist

# Check if a user is whitelisted
SISMEMBER wallet-cast-demo:user_whitelist "user123"

# Clear whitelist entirely
DEL wallet-cast-demo:user_whitelist
```
