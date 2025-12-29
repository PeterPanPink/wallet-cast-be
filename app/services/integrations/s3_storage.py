"""AWS S3 helper service.

This module provides a thin wrapper around boto3 S3 operations for uploading
and managing caption VTT/M3U8 files.

Usage:
    from app.services.integrations.s3_storage import s3_service

    # Upload VTT file
    url = await s3_service.upload_caption_file(
        session_id="session-123",
        filename="captions.vtt",
        content=b"WEBVTT\\n\\n...",
        content_type="text/vtt"
    )

    # Upload M3U8 playlist
    url = await s3_service.upload_caption_file(
        session_id="session-123",
        filename="captions.m3u8",
        content=b"#EXTM3U\\n...",
        content_type="application/vnd.apple.mpegurl"
    )

    # Delete caption files for a session
    await s3_service.delete_session_captions(session_id="session-123")
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import BinaryIO

import aioboto3
from botocore.exceptions import ClientError

from app.shared.config import config
from app.utils.app_errors import AppError, AppErrorCode, HttpStatusCode

logger = logging.getLogger(__name__)


class S3Service:
    """Service wrapper for AWS S3 operations.

    This service provides async methods for uploading and managing caption files
    (VTT, M3U8, etc.) to S3 buckets.
    """

    def __init__(self) -> None:
        self._session = None
        self._bucket_name = None
        self._demo_mode = str(config.get("DEMO_MODE", "true")).strip().lower() == "true"
        logger.info("S3Service initialized")

    def _get_session(self) -> aioboto3.Session:
        """Get or create aioboto3 session."""
        if self._session is None:
            aws_access_key = config.get("AWS_ACCESS_KEY_ID")
            aws_secret_key = config.get("AWS_SECRET_ACCESS_KEY")
            aws_region = config.get("AWS_REGION", "us-east-1")

            if not aws_access_key or not aws_secret_key:
                raise AppError(
                    errcode=AppErrorCode.E_INVALID_REQUEST,
                    errmesg="AWS credentials not configured",
                    status_code=HttpStatusCode.BAD_REQUEST,
                )

            self._session = aioboto3.Session(
                aws_access_key_id=aws_access_key,
                aws_secret_access_key=aws_secret_key,
                region_name=aws_region,
            )
            logger.info(f"S3 session created for region: {aws_region}")

        return self._session

    @asynccontextmanager
    async def _get_client(self) -> AsyncIterator:  # type: ignore[misc]
        """Get async S3 client context manager."""
        session = self._get_session()
        async with session.client("s3") as client:  # type: ignore[attr-defined]
            yield client

    def _get_bucket_name(self) -> str:
        """Get S3 bucket name from config."""
        if self._bucket_name is None:
            self._bucket_name = config.get("S3_CAPTION_BUCKET")
            if not self._bucket_name:
                raise AppError(
                    errcode=AppErrorCode.E_INVALID_REQUEST,
                    errmesg="S3_CAPTION_BUCKET not configured",
                    status_code=HttpStatusCode.BAD_REQUEST,
                )
        return self._bucket_name

    def _get_object_key(self, session_id: str, filename: str) -> str:
        """Generate S3 object key for caption file.

        Args:
            session_id: Session identifier
            filename: File name (e.g., "captions.vtt", "captions-1.vtt", "captions.m3u8")

        Returns:
            S3 object key (e.g., "captions/session-123/captions.vtt")
        """
        prefix = config.get("S3_CAPTION_PREFIX", "captions")
        return f"{prefix}/{session_id}/{filename}"

    async def upload_caption_file(
        self,
        session_id: str,
        filename: str,
        content: bytes | BinaryIO,
        content_type: str = "text/vtt",
        cache_control: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> str:
        """Upload caption file to S3.

        Args:
            session_id: Session identifier
            filename: File name (e.g., "captions.vtt", "captions-1.vtt")
            content: File content as bytes or file-like object
            content_type: MIME type (default: "text/vtt")
            cache_control: Cache-Control header value
            metadata: Additional metadata to store with the object

        Returns:
            Public URL of the uploaded file

        Raises:
            ClientError: If upload fails
        """
        key = self._get_object_key(session_id, filename)

        # Demo-safe stub: return a deterministic fake URL without performing any upload.
        if self._demo_mode:
            bucket = config.get("S3_CAPTION_BUCKET") or "demo-bucket"
            region = config.get("AWS_REGION", "us-east-1")
            url = f"https://{bucket}.s3.{region}.amazonaws.com/{key}"
            logger.info(f"S3Service DEMO_MODE=true: stubbed upload {key} -> {url}")
            return url

        bucket = self._get_bucket_name()

        extra_args = {
            "ContentType": content_type,
        }

        # Add cache control for better CDN/browser caching
        if cache_control:
            extra_args["CacheControl"] = cache_control
        else:
            # Default: cache for 1 minute for active streams, 1 hour for completed
            extra_args["CacheControl"] = "public, max-age=60"

        # Add metadata if provided
        if metadata:
            extra_args["Metadata"] = metadata  # type: ignore[typeddict-item]

        try:
            async with self._get_client() as client:
                # Upload file
                if isinstance(content, bytes):
                    await client.put_object(
                        Bucket=bucket,
                        Key=key,
                        Body=content,
                        **extra_args,
                    )
                else:
                    await client.upload_fileobj(
                        content,
                        bucket,
                        key,
                        ExtraArgs=extra_args,
                    )

            # Generate public URL
            region = config.get("AWS_REGION", "us-east-1")
            url = f"https://{bucket}.s3.{region}.amazonaws.com/{key}"

            logger.info(f"Uploaded caption file: {key} -> {url}")
            return url

        except ClientError as e:
            logger.error(f"Failed to upload caption file {key}: {e}")
            raise

    async def upload_caption_text(
        self,
        session_id: str,
        filename: str,
        content: str,
        content_type: str = "text/vtt",
        cache_control: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> str:
        """Upload caption text content to S3.

        Convenience method for uploading text content (VTT, M3U8, etc.).

        Args:
            session_id: Session identifier
            filename: File name
            content: Text content
            content_type: MIME type
            cache_control: Cache-Control header value
            metadata: Additional metadata

        Returns:
            Public URL of the uploaded file
        """
        return await self.upload_caption_file(
            session_id=session_id,
            filename=filename,
            content=content.encode("utf-8"),
            content_type=content_type,
            cache_control=cache_control,
            metadata=metadata,
        )

    async def delete_caption_file(self, session_id: str, filename: str) -> bool:
        """Delete a specific caption file from S3.

        Args:
            session_id: Session identifier
            filename: File name to delete

        Returns:
            True if deleted successfully, False otherwise
        """
        key = self._get_object_key(session_id, filename)
        if self._demo_mode:
            logger.info("S3Service DEMO_MODE=true: stubbed delete_caption_file (no-op)")
            return True

        bucket = self._get_bucket_name()

        try:
            async with self._get_client() as client:
                await client.delete_object(Bucket=bucket, Key=key)
            logger.info(f"Deleted caption file: {key}")
            return True
        except ClientError as e:
            logger.error(f"Failed to delete caption file {key}: {e}")
            return False

    async def delete_session_captions(self, session_id: str) -> int:
        """Delete all caption files for a session.

        Args:
            session_id: Session identifier

        Returns:
            Number of files deleted
        """
        if self._demo_mode:
            logger.info("S3Service DEMO_MODE=true: stubbed delete_session_captions (no-op)")
            return 0

        bucket = self._get_bucket_name()
        prefix = self._get_object_key(session_id, "")

        try:
            async with self._get_client() as client:
                # List all objects with the session prefix
                response = await client.list_objects_v2(Bucket=bucket, Prefix=prefix)

                if "Contents" not in response:
                    logger.info(f"No caption files found for session: {session_id}")
                    return 0

                # Delete all objects
                objects = [{"Key": obj["Key"]} for obj in response["Contents"]]
                await client.delete_objects(
                    Bucket=bucket,
                    Delete={"Objects": objects},
                )

                count = len(objects)
                logger.info(f"Deleted {count} caption files for session: {session_id}")
                return count

        except ClientError as e:
            logger.error(f"Failed to delete session captions for {session_id}: {e}")
            return 0

    def get_caption_url(self, session_id: str, filename: str) -> str:
        """Generate public URL for a caption file.

        Args:
            session_id: Session identifier
            filename: File name

        Returns:
            Public URL of the file
        """
        bucket = self._get_bucket_name()
        key = self._get_object_key(session_id, filename)
        region = config.get("AWS_REGION", "us-east-1")

        return f"https://{bucket}.s3.{region}.amazonaws.com/{key}"

    async def check_file_exists(self, session_id: str, filename: str) -> bool:
        """Check if a caption file exists in S3.

        Args:
            session_id: Session identifier
            filename: File name

        Returns:
            True if file exists, False otherwise
        """
        bucket = self._get_bucket_name()
        key = self._get_object_key(session_id, filename)

        try:
            async with self._get_client() as client:
                await client.head_object(Bucket=bucket, Key=key)
            return True
        except ClientError:
            return False

    async def upload_caption_files_batch(
        self,
        session_id: str,
        files: list[tuple[str, str, str]],
        cache_control: str | None = None,
    ) -> dict[str, str]:
        """Upload multiple caption files to S3 in batch.

        Args:
            session_id: Session identifier
            files: List of (filename, content, content_type) tuples
            cache_control: Cache-Control header value

        Returns:
            Dict mapping filename to public URL

        Raises:
            ClientError: If any upload fails
        """
        import asyncio

        async def upload_one(filename: str, content: str, content_type: str) -> tuple[str, str]:
            url = await self.upload_caption_text(
                session_id=session_id,
                filename=filename,
                content=content,
                content_type=content_type,
                cache_control=cache_control,
            )
            return filename, url

        # Upload all files concurrently
        tasks = [upload_one(f, c, ct) for f, c, ct in files]
        results = await asyncio.gather(*tasks)

        return dict(results)


# Singleton instance
s3_service = S3Service()
