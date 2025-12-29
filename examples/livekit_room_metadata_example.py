"""Example script demonstrating the room metadata update endpoint (sanitized demo).

This script shows how to update RTC room metadata via the API endpoint.
"""

import asyncio
import json
from typing import Any

import httpx

# Configuration
API_BASE = "http://localhost:8000"  # Adjust for your deployment
ENDPOINT = f"{API_BASE}/api/v1/session/ingress/update_room_metadata"


async def update_room_metadata(room_name: str, metadata: dict[str, Any]) -> dict[str, Any]:
    """Update room metadata via the API endpoint.

    Args:
        room_name: Name of the room to update
        metadata: Dictionary of metadata to set (will be JSON serialized)

    Returns:
        API response with updated room information

    Raises:
        httpx.HTTPStatusError: If the request fails
    """
    async with httpx.AsyncClient() as client:
        response = await client.post(
            ENDPOINT,
            json={
                "room": room_name,
                "metadata": json.dumps(metadata),
            },
            headers={"Content-Type": "application/json"},
        )
        response.raise_for_status()
        return response.json()


async def main():
    """Example usage of the room metadata update endpoint."""
    try:
        # Example 1: Update layout mode
        print("Example 1: Update layout mode to grid")
        result = await update_room_metadata(
            room_name="test-room",
            metadata={
                "layout": "grid",
                "theme": "dark",
            },
        )
        print(f"✓ Success: {json.dumps(result, indent=2)}")

        # Example 2: Update with more complex metadata
        print("\nExample 2: Update with complex metadata")
        result = await update_room_metadata(
            room_name="test-room",
            metadata={
                "layout": "speaker",
                "theme": "light",
                "settings": {
                    "showChat": True,
                    "showParticipants": True,
                    "maxVideoQuality": "1080p",
                },
                "customData": {
                    "sessionId": "abc-123",
                    "hostId": "user-456",
                },
            },
        )
        print(f"✓ Success: {json.dumps(result, indent=2)}")

    except httpx.HTTPStatusError as e:
        print(f"✗ HTTP Error: {e.response.status_code}")
        print(f"  Response: {e.response.text}")
    except Exception as e:
        print(f"✗ Error: {e}")


if __name__ == "__main__":
    asyncio.run(main())
