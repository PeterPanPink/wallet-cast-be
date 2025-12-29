from fastapi import APIRouter
from .utils import ApiSuccess


router = APIRouter()


@router.get('/health', response_model=ApiSuccess)
async def health():
    return ApiSuccess(results="OK")
