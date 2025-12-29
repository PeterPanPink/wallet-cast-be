"""Example of querying transcripts from MongoDB.

This example shows how to query and retrieve transcripts for a session.
"""

import asyncio

from app.shared.storage.mongo import get_mongo_client
from app.schemas import Transcript
from app.schemas.init import init_beanie_odm


async def example_query_transcripts():
    """Example: Query transcripts for a session."""
    # Initialize MongoDB connection
    mongo_client = get_mongo_client("flc_primary")
    database = mongo_client.get_database()
    await init_beanie_odm(database)

    # Example 1: Get all transcripts for a session, ordered by time
    session_id = "se_01JCPZ7G8M9KN2Q1W3Y4X5Z6A7"
    transcripts = (
        await Transcript.find(Transcript.session_id == session_id).sort("start_time").to_list()
    )

    print(f"Found {len(transcripts)} transcripts for session {session_id}")
    for t in transcripts:
        print(f"[{t.start_time:.2f}s - {t.end_time:.2f}s] {t.text}")

    # Example 2: Get transcripts within a time range
    start_range = 10.0  # 10 seconds
    end_range = 30.0  # 30 seconds
    time_range_transcripts = await Transcript.find(
        Transcript.session_id == session_id,
        Transcript.start_time >= start_range,
        Transcript.end_time <= end_range,
    ).to_list()

    print(f"\nTranscripts between {start_range}s and {end_range}s:")
    for t in time_range_transcripts:
        print(f"[{t.start_time:.2f}s] {t.text}")

    # Example 3: Get transcript count by session
    count = await Transcript.find(Transcript.session_id == session_id).count()
    print(f"\nTotal transcript count: {count}")

    # Example 4: Get high-confidence transcripts (confidence > 0.9)
    high_confidence = (
        await Transcript.find(
            Transcript.session_id == session_id,
            Transcript.confidence != None,  # noqa: E711
        )
        .find(Transcript.confidence > 0.9)  # type: ignore[operator]
        .to_list()
    )

    print(f"\nHigh confidence transcripts: {len(high_confidence)}")

    # Example 5: Get the latest transcripts across all sessions
    latest_transcripts = await Transcript.find_all().sort("-created_at").limit(10).to_list()

    print("\nLatest 10 transcripts across all sessions:")
    for t in latest_transcripts:
        print(f"[{t.session_id}] {t.text[:50]}...")


if __name__ == "__main__":
    asyncio.run(example_query_transcripts())
