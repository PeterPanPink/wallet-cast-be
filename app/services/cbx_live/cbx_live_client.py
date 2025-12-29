import httpx
from loguru import logger

from app.cw.config import config
from app.services.cbx_live.cbx_live_schemas import (
    AdminStartLiveBody,
    AdminStopLiveBody,
    AdminUpdateLiveBody,
    CbxLiveApiResponse,
)


class CbxLiveClient:
    def __init__(self, base_url: str, api_key: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def _build_headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.api_key:
            headers["X-Api-Key"] = self.api_key
        if extra:
            headers.update(extra)
        return headers

    async def admin_start_live(self, body: AdminStartLiveBody) -> CbxLiveApiResponse:
        """Call Admin Start Live endpoint."""
        demo_mode = str(config.get("DEMO_MODE", "true")).strip().lower() == "true"
        if demo_mode:
            logger.info("CBX client DEMO_MODE=true: returning stubbed start_live response")
            # Minimal, demo-safe response shape
            return CbxLiveApiResponse.model_validate(
                {
                    "success": True,
                    "results": {"post_id": "post_demo_001"},
                    "errcode": None,
                    "errmesg": None,
                }
            )

        url = f"{self.base_url}/api/v1/admin/live/start"
        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                json=body.model_dump(),
                headers=self._build_headers(),
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()
            logger.debug(f"admin_start_live response: {data}")
            try:
                return CbxLiveApiResponse.model_validate(data)
            except Exception:
                logger.exception("Failed to validate admin_start_live response")
                raise

    async def admin_stop_live(self, body: AdminStopLiveBody) -> None:
        """Call Admin Stop Live endpoint."""
        demo_mode = str(config.get("DEMO_MODE", "true")).strip().lower() == "true"
        if demo_mode:
            logger.info("CBX client DEMO_MODE=true: stubbed stop_live (no-op)")
            return

        url = f"{self.base_url}/api/v1/admin/live/stop"
        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                json=body.model_dump(),
                headers=self._build_headers(),
                timeout=30,
            )
            response.raise_for_status()

    async def admin_update_live(self, body: AdminUpdateLiveBody) -> None:
        """Call Admin Update Live endpoint.

        Updates the title, description, and/or cover of an existing live stream.
        Response schema is not strictly defined, but we try to log any errors.
        """
        demo_mode = str(config.get("DEMO_MODE", "true")).strip().lower() == "true"
        if demo_mode:
            logger.info("CBX client DEMO_MODE=true: stubbed update_live (no-op)")
            return

        url = f"{self.base_url}/api/v1/admin/live/update"
        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                json=body.model_dump(exclude_none=True),
                headers=self._build_headers(),
                timeout=30,
            )
            response.raise_for_status()

            # Try to extract error info from response if present
            try:
                data = response.json()
                errcode = data.get("errcode")
                errmesg = data.get("errmesg")
                if errcode:
                    logger.error(f"CBX admin/live/update error: {errcode} - {errmesg}")
            except Exception:
                pass  # Ignore JSON parsing errors
