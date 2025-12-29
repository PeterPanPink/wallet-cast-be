#!/usr/bin/env python3
"""Example: Using segmented VTT captions with HLS streaming.

This example demonstrates how to fetch and use segmented VTT captions
for a live streaming session.
"""

import asyncio

import httpx


async def fetch_caption_playlist(session_id: str, language: str | None = None):
    """Fetch the M3U8 playlist for captions.

    Args:
        session_id: Session ID to get captions for
        language: Optional language code (e.g., 'es', 'fr')

    Returns:
        M3U8 playlist content as string
    """
    base_url = "http://localhost:8000/api/v1"
    url = f"{base_url}/flc/session/egress/caption/{session_id}/captions.m3u8"

    params = {}
    if language:
        params["language"] = language

    async with httpx.AsyncClient() as client:
        response = await client.get(url, params=params)
        response.raise_for_status()
        return response.text


async def fetch_caption_segment(session_id: str, segment_num: int, language: str | None = None):
    """Fetch a specific VTT caption segment.

    Args:
        session_id: Session ID
        segment_num: Segment number (media sequence)
        language: Optional language code

    Returns:
        VTT segment content as string
    """
    base_url = "http://localhost:8000/api/v1"
    url = f"{base_url}/flc/session/egress/caption/{session_id}/captions-{segment_num}.vtt"

    params = {}
    if language:
        params["language"] = language

    async with httpx.AsyncClient() as client:
        response = await client.get(url, params=params)
        response.raise_for_status()
        return response.text


def parse_m3u8_segments(playlist_content: str) -> list[int]:
    """Parse segment numbers from M3U8 playlist.

    Args:
        playlist_content: M3U8 playlist content

    Returns:
        List of segment numbers
    """
    segments = []
    for line in playlist_content.split("\n"):
        if line.startswith("/") or line.startswith("http"):
            # Extract segment number from URL
            # Format: .../captions-123.vtt
            if "captions-" in line:
                segment_str = line.split("captions-")[1].split(".vtt")[0].split("?")[0]
                segments.append(int(segment_str))
    return segments


async def example_fetch_all_segments():
    """Example: Fetch all caption segments for a session."""
    session_id = "se_example_123"

    # Step 1: Get the M3U8 playlist
    print(f"Fetching caption playlist for session: {session_id}")
    playlist = await fetch_caption_playlist(session_id)
    print("\n=== M3U8 Playlist ===")
    print(playlist)

    # Step 2: Parse segment numbers
    segment_nums = parse_m3u8_segments(playlist)
    print(f"\n=== Found {len(segment_nums)} segments ===")
    print(f"Segment numbers: {segment_nums[:5]}...{segment_nums[-5:]}")

    # Step 3: Fetch first segment
    if segment_nums:
        first_segment = segment_nums[0]
        print(f"\n=== Fetching segment {first_segment} ===")
        vtt_content = await fetch_caption_segment(session_id, first_segment)
        print(vtt_content)


async def example_fetch_translated_captions():
    """Example: Fetch Spanish translated captions."""
    session_id = "se_example_123"
    language = "es"

    print(f"Fetching Spanish captions for session: {session_id}")

    # Get Spanish playlist
    playlist = await fetch_caption_playlist(session_id, language=language)
    print("\n=== Spanish M3U8 Playlist ===")
    print(playlist)

    # Parse and fetch first Spanish segment
    segment_nums = parse_m3u8_segments(playlist)
    if segment_nums:
        first_segment = segment_nums[0]
        vtt_content = await fetch_caption_segment(session_id, first_segment, language=language)
        print(f"\n=== Spanish Segment {first_segment} ===")
        print(vtt_content)


async def example_live_caption_monitoring():
    """Example: Monitor captions in real-time during a live stream."""
    session_id = "se_example_123"
    last_segment_num = -1

    print(f"Monitoring captions for session: {session_id}")
    print("Press Ctrl+C to stop\n")

    try:
        while True:
            # Fetch latest playlist
            playlist = await fetch_caption_playlist(session_id)
            segment_nums = parse_m3u8_segments(playlist)

            if segment_nums:
                latest_segment = segment_nums[-1]

                # Check if there's a new segment
                if latest_segment > last_segment_num:
                    print(f"\n=== New Segment: {latest_segment} ===")
                    vtt_content = await fetch_caption_segment(session_id, latest_segment)

                    # Extract and display caption text
                    lines = vtt_content.split("\n")
                    for _i, line in enumerate(lines):
                        if (
                            line
                            and not line.startswith("WEBVTT")
                            and "-->" not in line
                            and not line.isdigit()
                        ):
                            print(f"  {line}")

                    last_segment_num = latest_segment

            # Poll every 2 seconds
            await asyncio.sleep(2)

    except KeyboardInterrupt:
        print("\n\nStopped monitoring.")


async def example_segment_time_info():
    """Example: Calculate time ranges for segments."""
    SEGMENT_DURATION = 4.0

    print("=== Segment Time Ranges ===\n")

    for seg_num in range(10):
        start_time = seg_num * SEGMENT_DURATION
        end_time = start_time + SEGMENT_DURATION

        # Format as HH:MM:SS
        start_min = int(start_time // 60)
        start_sec = start_time % 60
        end_min = int(end_time // 60)
        end_sec = end_time % 60

        print(
            f"Segment {seg_num:3d}: [{start_min:02d}:{start_sec:05.2f} - {end_min:02d}:{end_sec:05.2f})"
        )


async def example_html5_video_integration():
    """Example: HTML5 video player integration code."""
    session_id = "se_example_123"

    html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>HLS Video with VTT Captions</title>
</head>
<body>
    <h1>Live Stream with Captions</h1>

    <video id="player" width="1280" height="720" controls>
        <source src="https://example.com/video.m3u8" type="application/x-mpegURL">

        <!-- Original captions -->
        <track
            kind="subtitles"
            src="http://localhost:8000/api/v1/flc/session/egress/caption/{session_id}/captions.m3u8"
            srclang="en"
            label="English"
            default>

        <!-- Spanish captions -->
        <track
            kind="subtitles"
            src="http://localhost:8000/api/v1/flc/session/egress/caption/{session_id}/captions.m3u8?language=es"
            srclang="es"
            label="Español">

        <!-- French captions -->
        <track
            kind="subtitles"
            src="http://localhost:8000/api/v1/flc/session/egress/caption/{session_id}/captions.m3u8?language=fr"
            srclang="fr"
            label="Français">
    </video>

    <script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
    <script>
        const video = document.getElementById('player');
        const videoSrc = 'https://example.com/video.m3u8';

        if (Hls.isSupported()) {{
            const hls = new Hls();
            hls.loadSource(videoSrc);
            hls.attachMedia(video);
        }} else if (video.canPlayType('application/vnd.apple.mpegurl')) {{
            video.src = videoSrc;
        }}
    </script>
</body>
</html>
    """

    print("=== HTML5 Video Player Integration ===\n")
    print(html)


if __name__ == "__main__":
    # Choose which example to run
    print("VTT Segmentation Examples")
    print("=" * 50)
    print("\nAvailable examples:")
    print("1. Fetch all segments")
    print("2. Fetch translated captions")
    print("3. Live caption monitoring")
    print("4. Segment time info")
    print("5. HTML5 video integration")

    choice = input("\nSelect example (1-5): ")

    if choice == "1":
        asyncio.run(example_fetch_all_segments())
    elif choice == "2":
        asyncio.run(example_fetch_translated_captions())
    elif choice == "3":
        asyncio.run(example_live_caption_monitoring())
    elif choice == "4":
        asyncio.run(example_segment_time_info())
    elif choice == "5":
        asyncio.run(example_html5_video_integration())
    else:
        print("Invalid choice")
