"""Example: Generate RTC Provider access tokens (sanitized demo).

This script demonstrates how to use the RTC provider service wrapper to generate access tokens
for clients to join RTC rooms.

Prerequisites:
    1. Install dependencies: uv sync
    2. Set environment variables in env.local (do not commit):
       RTC_PROVIDER_URL=https://<redacted-rtc-provider>
       RTC_PROVIDER_API_KEY=PLACEHOLDER_RTC_PROVIDER_API_KEY
       RTC_PROVIDER_API_SECRET=PLACEHOLDER_RTC_PROVIDER_API_SECRET

Run:
    uv run python examples/livekit_token_example.py
"""

import asyncio

from app.services.cw_livekit import livekit_service


async def main():
    """Generate and display RTC access tokens."""

    print("RTC Token Generation Example")
    print("=" * 50)

    # Example 1: Basic token for a specific room (skip capacity check for demo)
    print("\n1. Basic token for a specific room:")
    try:
        token = await livekit_service.create_access_token(
            identity="user-123",
            room="my-livestream-room",
            name="John Doe",
            check_capacity=False,  # Skip capacity check for demo
        )
        print(f"   Token: {token[:50]}...")
        print(f"   Length: {len(token)} characters")
    except Exception as e:
        print(f"   Error: {e}")

    # Example 2: Token with custom metadata
    print("\n2. Token with custom metadata:")
    try:
        token = await livekit_service.create_access_token(
            identity="host-456",
            room="live-session-001",
            name="Jane Host",
            metadata='{"role": "host", "level": "premium"}',
            check_capacity=False,  # Skip capacity check for demo
        )
        print(f"   Token: {token[:50]}...")
    except Exception as e:
        print(f"   Error: {e}")

    # Example 3: Token with limited permissions (subscriber only)
    print("\n3. Subscriber-only token (cannot publish):")
    try:
        token = await livekit_service.create_access_token(
            identity="viewer-789",
            room="watch-only-room",
            name="Bob Viewer",
            can_publish=False,
            can_publish_data=False,
            check_capacity=False,  # Skip capacity check for demo
        )
        print(f"   Token: {token[:50]}...")
    except Exception as e:
        print(f"   Error: {e}")

    # Example 4: Token without room restriction (no capacity check needed)
    print("\n4. Token that can join any room:")
    try:
        token = await livekit_service.create_access_token(
            identity="admin-000",
            room=None,
            name="Admin User",  # Can join any room
        )
        print(f"   Token: {token[:50]}...")
    except Exception as e:
        print(f"   Error: {e}")

    print("\n" + "=" * 50)
    print("Example completed!")
    print("\nNote: These tokens can be passed to an RTC client SDK")
    print("to authenticate and join rooms.")


if __name__ == "__main__":
    asyncio.run(main())
