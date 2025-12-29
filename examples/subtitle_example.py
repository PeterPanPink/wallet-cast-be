"""Example: Enable subtitle/translation for an RTC session (sanitized demo).

This example demonstrates how to use the subtitle API endpoints.

Usage:
    # Enable subtitles
    python examples/subtitle_example.py --mode subtitle --room-id rm_123

    # Enable translation
    python examples/subtitle_example.py --mode translation --room-id rm_123 --target-language French --enable-tts

    # Check status
    python examples/subtitle_example.py --status --room-id rm_123

    # Disable
    python examples/subtitle_example.py --disable --room-id rm_123
"""

import argparse
import asyncio
import os

import httpx
from dotenv import load_dotenv

# Optional local override (do not commit). This demo repo ships without dotfiles.
load_dotenv("env.local", override=False)

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
AUTH_TOKEN = os.getenv("AUTH_TOKEN", "")


async def enable_subtitle(
    room_id: str,
    mode: str = "subtitle",
    target_language: str | None = None,
    enable_tts: bool = False,
):
    """Enable subtitle or translation for a session."""
    url = f"{API_BASE_URL}/session/subtitle/enable"

    payload = {
        "room_id": room_id,
        "mode": mode,
        "enable_tts": enable_tts,
    }

    if target_language:
        payload["target_language"] = target_language

    headers = {
        "Authorization": f"Bearer {AUTH_TOKEN}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        result = response.json()

    print("✓ Subtitle enabled successfully:")
    print(f"  Room ID: {result['results']['room_id']}")
    print(f"  Mode: {result['results']['mode']}")
    print(f"  Status: {result['results']['status']}")

    return result


async def disable_subtitle(room_id: str):
    """Disable subtitle for a session."""
    url = f"{API_BASE_URL}/session/subtitle/disable"

    payload = {"room_id": room_id}

    headers = {
        "Authorization": f"Bearer {AUTH_TOKEN}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        result = response.json()

    print("✓ Subtitle disabled successfully:")
    print(f"  Room ID: {result['results']['room_id']}")
    print(f"  Status: {result['results']['status']}")

    return result


async def get_status(room_id: str):
    """Get subtitle status for a session."""
    url = f"{API_BASE_URL}/session/subtitle/status"

    payload = {"room_id": room_id}

    headers = {
        "Authorization": f"Bearer {AUTH_TOKEN}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        result = response.json()

    print("✓ Subtitle status:")
    print(f"  Room ID: {result['results']['room_id']}")
    print(f"  Enabled: {result['results']['enabled']}")

    if result["results"]["enabled"]:
        print(f"  Mode: {result['results'].get('mode', 'N/A')}")
        print(f"  Status: {result['results'].get('status', 'N/A')}")

        if result["results"].get("target_language"):
            print(f"  Target Language: {result['results']['target_language']}")

        print(f"  TTS Enabled: {result['results'].get('enable_tts', False)}")

    return result


async def main():
    """Main function."""
    parser = argparse.ArgumentParser(description="Subtitle/Translation API Example")
    parser.add_argument("--room-id", required=True, help="Room ID")
    parser.add_argument(
        "--mode",
        choices=["subtitle", "translation"],
        default="subtitle",
        help="Mode: subtitle or translation",
    )
    parser.add_argument(
        "--target-language",
        help="Target language for translation (e.g., French, Spanish)",
    )
    parser.add_argument(
        "--enable-tts",
        action="store_true",
        help="Enable TTS output (voice)",
    )
    parser.add_argument(
        "--disable",
        action="store_true",
        help="Disable subtitle",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Check subtitle status",
    )

    args = parser.parse_args()

    if not AUTH_TOKEN:
        print("Error: AUTH_TOKEN environment variable not set")
        return

    try:
        if args.disable:
            await disable_subtitle(args.room_id)
        elif args.status:
            await get_status(args.room_id)
        else:
            if args.mode == "translation" and not args.target_language:
                print("Error: --target-language is required for translation mode")
                return

            await enable_subtitle(
                room_id=args.room_id,
                mode=args.mode,
                target_language=args.target_language,
                enable_tts=args.enable_tts,
            )

    except httpx.HTTPStatusError as exc:
        print(f"✗ HTTP error: {exc.response.status_code}")
        print(f"  Response: {exc.response.text}")
    except Exception as exc:
        print(f"✗ Error: {exc}")


if __name__ == "__main__":
    asyncio.run(main())
