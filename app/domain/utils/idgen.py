from ulid import ULID


def new_ulid(prefix: str | None = None) -> str:
    value = str(ULID()).lower()
    return f"{prefix}{value}" if prefix else value


def new_channel_id() -> str:
    return new_ulid("ch_")


def new_post_id() -> str:
    return new_ulid("ps_")


def new_session_id() -> str:
    return new_ulid("se_")


def new_room_id() -> str:
    return new_ulid("ro_")
