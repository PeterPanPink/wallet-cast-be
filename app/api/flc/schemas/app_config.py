from pydantic import BaseModel


class FrontendConfigOut(BaseModel):
    frontend_base_url: str | None
    frontend_invite_link_base_url: str | None
    frontend_base_path: str
    frontend_recording_path: str
    frontend_join_path: str
