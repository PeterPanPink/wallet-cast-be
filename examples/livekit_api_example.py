"""Example: RTC Room Management API (sanitized demo).

This script demonstrates the RTC provider service wrapper pattern.
The service provides specific methods instead of a generic API client,
making usage patterns explicit and discoverable.

Prerequisites:
    1. Install dependencies: uv sync
    2. Set environment variables in env.local (do not commit):
       RTC_PROVIDER_URL=https://<redacted-rtc-provider>
       RTC_PROVIDER_API_KEY=PLACEHOLDER_RTC_PROVIDER_API_KEY
       RTC_PROVIDER_API_SECRET=PLACEHOLDER_RTC_PROVIDER_API_SECRET

Run:
    uv run python examples/livekit_api_example.py
"""

import asyncio

from app.services.integrations.livekit_service import livekit_service


async def main():
    """Demonstrate RTC provider service operations."""

    print("RTC Provider Service Example")
    print("=" * 50)

    try:
        # Example 1: Update room metadata
        print("\n1. Updating room metadata:")
        try:
            room_info = await livekit_service.update_room_metadata(
                room="test-room",
                metadata='{"layout":"grid","theme":"dark"}',
            )
            print(f"   Updated room: {room_info.name}")
            print(f"   Room SID: {room_info.sid}")
            print(f"   Metadata: {room_info.metadata}")
        except Exception as e:
            print(f"   Error: {e}")

        # Example 2: Create access token
        print("\n2. Creating access token:")
        try:
            token = await livekit_service.create_access_token(
                identity="user-123",
                room="test-room",
                name="John Doe",
                metadata='{"role":"host"}',
                check_capacity=False,  # Skip capacity check for demo
            )
            print(f"   Token created: {token[:50]}...")
        except Exception as e:
            print(f"   Error: {e}")

        # Note: For other RTC operations (create/list/delete rooms, etc.),
        # specific methods will be added to the service as needed.
        # This keeps the API surface explicit and usage patterns discoverable.

    except ImportError:
        print("\nError: livekit-api package not installed")
        print("Install it with: pip install livekit-api")
        return
    except ValueError as e:
        print(f"\nConfiguration error: {e}")
        return
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        return

    print("\n" + "=" * 50)
    print("Example completed!")


if __name__ == "__main__":
    asyncio.run(main())
