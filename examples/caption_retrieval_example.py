"""Example: Retrieve captions via API in different formats.

This example demonstrates how to:
1. Get transcripts in JSON format
2. Download captions in WebVTT format
3. Get HLS playlist with subtitle tracks
"""

import asyncio
import os

import httpx
from dotenv import load_dotenv

load_dotenv()

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
AUTH_TOKEN = os.getenv("AUTH_TOKEN", "")


async def get_transcripts_json(session_id: str):
    """Get transcripts in JSON format."""
    url = f"{API_BASE_URL}/session/egress/caption/{session_id}/transcripts"

    headers = {
        "Authorization": f"Bearer {AUTH_TOKEN}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        result = response.json()

    print("✓ Transcripts retrieved (JSON):")
    print(f"  Session ID: {result['results']['session_id']}")
    print(f"  Total Count: {result['results']['total_count']}")
    print(f"  Language Filter: {result['results']['language_filter']}")
    print("\n  First 3 transcripts:")

    for idx, transcript in enumerate(result["results"]["transcripts"][:3], 1):
        print(f"\n  {idx}. [{transcript['start_time']:.2f}s - {transcript['end_time']:.2f}s]")
        print(f"     Text: {transcript['text']}")
        print(f"     Language: {transcript['language']}")
        if transcript.get("translations"):
            print(f"     Translations: {list(transcript['translations'].keys())}")

    return result


async def get_captions_webvtt(session_id: str, language: str | None = None):
    """Get captions in WebVTT format."""
    url = f"{API_BASE_URL}/session/egress/caption/{session_id}/captions.vtt"

    params = {}
    if language:
        params["language"] = language

    headers = {
        "Authorization": f"Bearer {AUTH_TOKEN}",
    }

    async with httpx.AsyncClient() as client:
        response = await client.get(url, params=params, headers=headers)
        response.raise_for_status()
        vtt_content = response.text

    print(f"\n✓ WebVTT captions retrieved (language: {language or 'original'}):")
    print(f"  Content-Type: {response.headers.get('content-type')}")
    print(f"  Size: {len(vtt_content)} bytes")
    print("\n  Preview (first 500 chars):")
    print(f"  {vtt_content[:500]}")

    # Optionally save to file
    filename = f"captions_{session_id}_{language or 'original'}.vtt"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(vtt_content)
    print(f"\n  ✓ Saved to {filename}")

    return vtt_content


async def get_captions_m3u8(session_id: str, languages: list[str] | None = None):
    """Get HLS playlist with subtitle tracks."""
    url = f"{API_BASE_URL}/session/egress/caption/{session_id}/captions.m3u8"

    params: dict[str, str | list[str]] = {
        "base_url": API_BASE_URL,
    }
    if languages:
        params["languages"] = languages

    headers = {
        "Authorization": f"Bearer {AUTH_TOKEN}",
    }

    async with httpx.AsyncClient() as client:
        response = await client.get(url, params=params, headers=headers)
        response.raise_for_status()
        m3u8_content = response.text

    print("\n✓ M3U8 playlist retrieved:")
    print(f"  Content-Type: {response.headers.get('content-type')}")
    print(f"  Size: {len(m3u8_content)} bytes")
    print("\n  Content:")
    print(f"  {m3u8_content}")

    # Optionally save to file
    filename = f"captions_{session_id}.m3u8"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(m3u8_content)
    print(f"\n  ✓ Saved to {filename}")

    return m3u8_content


async def main():
    """Main function."""
    import argparse

    parser = argparse.ArgumentParser(description="Caption Retrieval API Example")
    parser.add_argument("--session-id", required=True, help="Session ID")
    parser.add_argument(
        "--format",
        choices=["json", "vtt", "m3u8", "all"],
        default="all",
        help="Output format",
    )
    parser.add_argument(
        "--language",
        help="Language code for translated captions (e.g., es, fr, ja)",
    )
    parser.add_argument(
        "--languages",
        nargs="+",
        help="List of language codes for M3U8 playlist (e.g., es fr ja)",
    )

    args = parser.parse_args()

    if not AUTH_TOKEN:
        print("Error: AUTH_TOKEN environment variable not set")
        return

    try:
        print(f"📺 Retrieving captions for session: {args.session_id}\n")
        print("=" * 60)

        if args.format in ["json", "all"]:
            await get_transcripts_json(args.session_id)
            print("\n" + "=" * 60)

        if args.format in ["vtt", "all"]:
            await get_captions_webvtt(args.session_id, language=args.language)
            print("\n" + "=" * 60)

        if args.format in ["m3u8", "all"]:
            await get_captions_m3u8(args.session_id, languages=args.languages)
            print("\n" + "=" * 60)

        print("\n✅ All caption formats retrieved successfully!")

    except httpx.HTTPStatusError as e:
        print(f"\n❌ HTTP Error: {e.response.status_code}")
        print(f"Response: {e.response.text}")
    except Exception as e:
        print(f"\n❌ Error: {e}")


if __name__ == "__main__":
    asyncio.run(main())
