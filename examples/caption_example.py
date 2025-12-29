"""Example: Enable caption/translation for an RTC session (sanitized demo).

This example demonstrates how to use the caption API endpoints.

Usage:
    # Enable captions
    python examples/caption_example.py --mode caption --room-id rm_123

    # Enable translation
    python examples/caption_example.py --mode translation --room-id rm_123 --target-language French --enable-tts

    # Check status
    python examples/caption_example.py --status --room-id rm_123

    # Disable
    python examples/caption_example.py --disable --room-id rm_123
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


async def enable_caption(
    room_id: str,
    mode: str = "caption",
    target_language: str | None = None,
    enable_tts: bool = False,
):
    """Enable caption or translation for a session."""
    url = f"{API_BASE_URL}/session/caption/enable"

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

    print("✓ Caption enabled successfully:")
    print(f"  Room ID: {result['results']['room_id']}")
    print(f"  Mode: {result['results']['mode']}")
    print(f"  Status: {result['results']['status']}")

    return result


async def disable_caption(room_id: str):
    """Disable caption for a session."""
    url = f"{API_BASE_URL}/session/caption/disable"

    payload = {"room_id": room_id}

    headers = {
        "Authorization": f"Bearer {AUTH_TOKEN}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        result = response.json()

    print("✓ Caption disabled successfully:")
    print(f"  Room ID: {result['results']['room_id']}")
    print(f"  Status: {result['results']['status']}")

    return result


async def get_status(room_id: str):
    """Get caption status for a session."""
    url = f"{API_BASE_URL}/session/caption/status"

    payload = {"room_id": room_id}

    headers = {
        "Authorization": f"Bearer {AUTH_TOKEN}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        result = response.json()

    print("✓ Caption status:")
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
    parser = argparse.ArgumentParser(description="Caption/Translation API Example")
    parser.add_argument("--room-id", required=True, help="Room ID")
    parser.add_argument(
        "--mode",
        choices=["caption", "translation"],
        default="caption",
        help="Mode: caption or translation",
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
        help="Disable caption",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Check caption status",
    )

    args = parser.parse_args()

    if not AUTH_TOKEN:
        print("Error: AUTH_TOKEN environment variable not set")
        return

    try:
        if args.disable:
            await disable_caption(args.room_id)
        elif args.status:
            await get_status(args.room_id)
        else:
            if args.mode == "translation" and not args.target_language:
                print("Error: --target-language is required for translation mode")
                return

            await enable_caption(
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
