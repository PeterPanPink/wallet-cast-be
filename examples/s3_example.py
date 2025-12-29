"""Example usage of the storage service for caption file uploads.

This example demonstrates how to:
1. Upload caption VTT files
2. Upload caption M3U8 playlist files
3. Delete specific files
4. Clean up all session files
5. Check file existence
"""

import asyncio

from app.services.integrations.s3_storage import s3_service


async def main() -> None:
    """Run object storage service examples."""
    print("=== Object Storage Service Example ===\n")

    session_id = "example-session-123"

    # Example 1: Upload a VTT caption file
    print("1. Uploading VTT caption file...")
    vtt_content = """WEBVTT

00:00:00.000 --> 00:00:05.000
Hello, this is a test caption.

00:00:05.000 --> 00:00:10.000
This demonstrates caption upload to object storage.
"""

    vtt_url = await s3_service.upload_caption_text(
        session_id=session_id,
        filename="captions.vtt",
        content=vtt_content,
        content_type="text/vtt",
    )
    print(f"   VTT uploaded: {vtt_url}\n")

    # Example 2: Upload an M3U8 playlist file
    print("2. Uploading M3U8 playlist file...")
    m3u8_content = """#EXTM3U
#EXT-X-VERSION:3
#EXT-X-TARGETDURATION:10

#EXTINF:10.0,
captions-0.vtt
#EXTINF:10.0,
captions-1.vtt
#EXT-X-ENDLIST
"""

    m3u8_url = await s3_service.upload_caption_text(
        session_id=session_id,
        filename="captions.m3u8",
        content=m3u8_content,
        content_type="application/x-mpegURL",
    )
    print(f"   M3U8 uploaded: {m3u8_url}\n")

    # Example 3: Upload with custom metadata
    print("3. Uploading with custom metadata...")
    segment_url = await s3_service.upload_caption_text(
        session_id=session_id,
        filename="captions-0.vtt",
        content=vtt_content,
        metadata={
            "segment_index": "0",
            "duration": "10",
            "language": "en",
        },
    )
    print(f"   Segment uploaded: {segment_url}\n")

    # Example 4: Check if file exists
    print("4. Checking file existence...")
    exists = await s3_service.check_file_exists(session_id, "captions.vtt")
    print(f"   captions.vtt exists: {exists}\n")

    # Example 5: Get URL without uploading
    print("5. Getting file URL...")
    url = s3_service.get_caption_url(session_id, "captions-0.vtt")
    print(f"   URL: {url}\n")

    # Example 6: Delete specific file
    print("6. Deleting specific file...")
    deleted = await s3_service.delete_caption_file(session_id, "captions-0.vtt")
    print(f"   Deleted: {deleted}\n")

    # Example 7: Clean up all session files
    print("7. Cleaning up all session files...")
    count = await s3_service.delete_session_captions(session_id)
    print(f"   Deleted {count} files\n")

    print("=== Example Complete ===")


if __name__ == "__main__":
    asyncio.run(main())
