import json

from pydantic import BaseModel, Field
from fastapi import Query
from typing import Any, Mapping
from fastapi import APIRouter, Request, Depends
from loguru import logger

from ...config import get_dynamic_config
from ...api.utils import (
    ApiSuccess,
    ApiFailure,
    LegacyApiResult,
    LegacyApiError,
    api_failure,
    make_response,
    verify_api_key,
)


router = APIRouter(prefix='/admin/check/data')


class DataCheckResults(BaseModel):
    check_id: str = Field(..., description="The id of the check record in MOT")
    params: dict[str, Any] = Field(default_factory=dict, description="The query parameters used to fetch data")

    source: dict[str, Any] = Field(..., description="The source data to be checked")
    target: dict[str, Any] = Field(..., description="The target data to be checked against")
    change: dict[str, Any] = Field(..., description="The change data to be transformed")
    result: dict[str, Any] = Field(..., description="The result data of the check")
    errors: list[str] | None = Field(default_factory=list, description="The errors occurred or collected during the check")


class DataCheckSuccess(ApiSuccess):
    results: DataCheckResults


dynamic_config = get_dynamic_config()


def _extract_path_segments(key: str) -> list[str]:
    remainder = key[len('params'):]
    remainder = remainder.lstrip('.')
    if not remainder:
        return []
    normalized = remainder.replace('[', '.').replace(']', '.')
    return [segment for segment in normalized.split('.') if segment]


def _merge_nested_dict(target: dict[str, Any], source: Mapping[str, Any]) -> None:
    for key, value in source.items():
        if isinstance(value, Mapping) and isinstance(target.get(key), Mapping):
            _merge_nested_dict(target[key], value)
        else:
            target[key] = value


def _assign_nested_value(target: dict[str, Any], path: list[str], value: Any) -> None:
    current: dict[str, Any] = target
    for segment in path[:-1]:
        next_value = current.get(segment)
        if not isinstance(next_value, dict):
            if isinstance(next_value, Mapping):
                next_value = dict(next_value)
            else:
                next_value = {}
            current[segment] = next_value
        current = next_value
    leaf = path[-1]
    existing = current.get(leaf)
    if existing is None:
        current[leaf] = value
    elif isinstance(existing, list):
        existing.append(value)
    else:
        current[leaf] = [existing, value]


def _parse_query_value(raw_value: str) -> Any:
    stripped = raw_value.strip()
    if not stripped:
        return ''
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return raw_value


def _build_params_from_query(query_params: Mapping[str, str]) -> dict[str, Any]:
    params: dict[str, Any] = {}

    for key, raw_value in getattr(query_params, 'multi_items', lambda: query_params.items())():
        if not isinstance(key, str) or not key.startswith('params'):
            continue

        path = _extract_path_segments(key)
        parsed_value = _parse_query_value(raw_value)

        if not path:
            if not isinstance(parsed_value, Mapping):
                raise ValueError('The "params" parameter must be a JSON object')
            _merge_nested_dict(params, parsed_value)
            continue

        _assign_nested_value(params, path, parsed_value)

    return params


@router.get(
    '/{rule_name}/{check_id}',
    response_model=DataCheckSuccess | ApiFailure | LegacyApiResult | LegacyApiError,
)
async def admin_check_data(
    request: Request,
    rule_name: str,
    check_id: str,
    legacy: bool = Query(default=False),
    _: None = Depends(verify_api_key)
):
    from ...domain.admin.check_data import check_data
    
    try:
        logger.debug('enter path={} method={}', request.url.path, request.method)

        await dynamic_config.reload('datacheck')

        if not dynamic_config.get('enable'):
            failure = api_failure(errcode='E_DATA_CHECK_NOT_ENABLED', errmesg='Data check is not enabled')
            return make_response(failure, legacy)

        rule_to_check = None
        for rule in dynamic_config.get('rules', []):
            if rule_name in rule.get('name', []):
                rule_to_check = rule
                break
        
        if not rule_to_check:
            failure = api_failure(errcode='E_DATA_CHECK_RULE_NOT_FOUND', errmesg=f'Data check rule not found for rule name: {rule_name}')
            return make_response(failure, legacy)
        
        try:
            query_payload = _build_params_from_query(request.query_params)
        except ValueError as exc:
            failure = api_failure(
                errcode='E_DATA_CHECK_QUERY_MISSING',
                errmesg=str(exc),
            )
            return make_response(failure, legacy)

        if not query_payload:
            failure = api_failure(
                errcode='E_DATA_CHECK_QUERY_MISSING',
                errmesg='Required query parameter "params" missing for data check',
            )
            return make_response(failure, legacy)

        result_data = await check_data(request.app.state.mongo_manager, rule_to_check, check_id, query_payload)
        return make_response(DataCheckSuccess(results=result_data), legacy)
    except Exception as e:
        failure = api_failure(errmesg=e)
        return make_response(failure, legacy)
