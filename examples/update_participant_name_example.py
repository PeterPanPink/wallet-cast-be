"""Example: Update participant display name in an RTC session (sanitized demo).

This example demonstrates how to update a participant's display name
using the /flc/session/ingress/update_participant_name endpoint.

Prerequisites:
- A running WalletCast demo backend server (or a stubbed local instance)
- An active session with a room
- A valid authentication token for the participant

Reference (redacted):
    https://<redacted-rtc-provider-docs>/managing-participants#updateparticipant
"""

import asyncio

import httpx


async def update_participant_name_example():
    """Update a participant's display name in a session."""

    # Configuration
    api_base_url = "http://localhost:8000"
    auth_token = "PLACEHOLDER_AUTH_TOKEN"  # Public demo placeholder

    # Session and participant details
    room_id = "your-room-id"  # Or use session_id instead
    identity = "guest-123"  # Must match the authenticated user's identity
    new_name = "John Doe"

    # Prepare request
    url = f"{api_base_url}/flc/session/ingress/update_participant_name"
    headers = {
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json",
    }
    payload = {
        "room_id": room_id,  # Or "session_id": "your-session-id"
        "identity": identity,
        "name": new_name,
    }

    # Make request
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload, headers=headers)

        if response.status_code == 200:
            data = response.json()
            print("✅ Successfully updated participant name!")
            print(f"Identity: {data['results']['identity']}")
            print(f"New name: {data['results']['name']}")
            print(f"Participant SID: {data['results']['sid']}")
        else:
            print(f"❌ Failed to update participant name: {response.status_code}")
            print(response.json())


async def update_own_name_in_session():
    """Example workflow: Guest joins a session and updates their name."""

    api_base_url = "http://localhost:8000"
    auth_token = "guest-auth-token"

    # Step 1: Get guest token to join session
    print("Step 1: Getting guest access token...")
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{api_base_url}/flc/session/ingress/get_guest_token",
            json={
                "room_id": "my-livestream",
                "display_name": "Guest",  # Required - initial display name
                "can_publish": False,
            },
            headers={"Authorization": f"Bearer {auth_token}"},
        )

        if response.status_code == 200:
            token_data = response.json()
            token_data["results"]["token"]
            room_name = token_data["results"]["room_name"]
            print(f"✅ Got access token for room: {room_name}")
        else:
            print("❌ Failed to get access token")
            return

    # Step 2: Connect to RTC room (client-side, not shown here)
    print("Step 2: Connect to RTC room with a client SDK...")
    print("  (See provider client SDK documentation)")

    # Step 3: Update display name after joining
    print("Step 3: Updating display name...")
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{api_base_url}/flc/session/ingress/update_participant_name",
            json={
                "room_id": "my-livestream",
                "identity": "guest-123",  # Must match your identity
                "name": "Alice Johnson",  # New name
            },
            headers={"Authorization": f"Bearer {auth_token}"},
        )

        if response.status_code == 200:
            data = response.json()
            print(f"✅ Updated name to: {data['results']['name']}")
            print("All participants will see the new name!")
        else:
            print(f"❌ Failed to update name: {response.status_code}")


if __name__ == "__main__":
    # Run example
    asyncio.run(update_participant_name_example())

    # Or run the full workflow
    # asyncio.run(update_own_name_in_session())
