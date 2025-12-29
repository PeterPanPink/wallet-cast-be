"""Example: Starting a caption agent with translation support.

This example demonstrates how to start a caption agent that translates
transcripts into multiple languages and saves them to the database.
"""

import asyncio

from app.cw.storage.mongo import get_mongo_client
from app.schemas.init import init_beanie_odm
from app.schemas.transcript import Transcript
from app.workers.caption_agent_worker import start_caption_agent
from app.workers.caption_agent_worker import worker as caption_worker


async def start_caption_agent_with_translation():
    """Start a caption agent with translation enabled."""
    async with caption_worker:
        # Enqueue caption agent start task with translation languages
        task = await start_caption_agent.enqueue(
            {
                "session_id": "se_example_session_123",
                "translation_languages": ["Spanish", "French", "Japanese", "Korean"],
            }
        )

        if task:
            print(f"Caption agent job enqueued: {task.id}")
            print("   Session ID: se_example_session_123")
            print("   Translation languages: Spanish, French, Japanese, Korean")
            print("\nThe agent will:")
            print("   1. Join the RTC Provider room associated with the session")
            print("   2. Transcribe audio in real-time")
            print("   3. Translate each transcript to the specified languages")
            print("   4. Save transcripts with translations to a document database")

            # Check job result
            await asyncio.sleep(2)
            job_result = await task.result(timeout=5)
            print(f"\nJob result: {job_result}")
        else:
            print("Failed to enqueue caption agent job")


async def query_transcript_with_translations():
    """Query transcripts and display translations."""
    # Initialize document database (demo)
    mongo_client = get_mongo_client("primary")
    database = mongo_client.get_database()
    await init_beanie_odm(database)

    # Query recent transcripts with translations
    transcripts = (
        await Transcript.find({"translations": {"$ne": None}})
        .sort("-created_at")
        .limit(5)
        .to_list()
    )

    if not transcripts:
        print("No transcripts with translations found.")
        return

    print(f"\n📋 Found {len(transcripts)} transcripts with translations:\n")

    for transcript in transcripts:
        print(f"Original ({transcript.language or 'unknown'}): {transcript.text}")
        print(f"   Time: {transcript.start_time:.2f}s - {transcript.end_time:.2f}s")
        print(f"   Confidence: {transcript.confidence:.2%}")

        if transcript.translations:
            print("   Translations:")
            for lang, text in transcript.translations.items():
                print(f"      {lang}: {text}")
        print()


if __name__ == "__main__":
    print("Caption Translation Example")
    print("=" * 60)

    # Example 1: Start caption agent with translation
    print("\n1. Starting caption agent with translation...")
    asyncio.run(start_caption_agent_with_translation())

    # Example 2: Query transcripts with translations
    print("\n2. Querying transcripts with translations...")
    asyncio.run(query_transcript_with_translations())
