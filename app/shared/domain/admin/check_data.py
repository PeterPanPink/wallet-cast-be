from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

from bson import ObjectId
from loguru import logger

from ...storage.mongo import MongoManager

from .rule_specs import FindSpec, build_rule_specs, evaluate_rule_template


async def check_data(
    mongo_manager: MongoManager,
    rule: dict[str, Any],
    check_id: str,
    query_params: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    params = dict(query_params or {})
    source_params_raw = params.get('source')
    target_params_raw = params.get('target')

    source_params = dict(source_params_raw) if isinstance(source_params_raw, Mapping) else {}
    target_params = dict(target_params_raw) if isinstance(target_params_raw, Mapping) else {}

    params['source'] = source_params
    params['target'] = target_params
    logger.debug(
        'run check_data for rule {}, source_params={}, target_params={}, check_id {}',
        rule,
        source_params,
        target_params,
        check_id,
    )

    errors: list[str] = []
    rule_name = str(rule.get('name') or '')

    specs = build_rule_specs(rule)
    source_find_spec: FindSpec = specs['source']['find']
    target_find_spec: FindSpec = specs['target']['find']

    source_task = asyncio.create_task(
        _fetch_document(
            mongo_manager,
            source_find_spec,
            'source',
            rule_name,
            errors,
            source_params,
        )
    )
    target_task = asyncio.create_task(
        _fetch_document(
            mongo_manager,
            target_find_spec,
            'target',
            rule_name,
            errors,
            target_params,
        )
    )

    source_doc, target_doc = await asyncio.gather(source_task, target_task)

    source_save_spec = specs['source']['save']
    target_save_spec = specs['target']['save']

    source_glom_data = source_save_spec.apply(source_doc or {})
    target_glom_data = target_save_spec.apply(target_doc or {})

    source_flat = _flatten_document(source_doc)
    target_flat = _flatten_document(target_doc)

    change_docs = await _fetch_change_documents(
        mongo_manager, target_find_spec, target_doc, rule_name, errors
    )

    result_section = {
        'source': {
            'glom_data': source_glom_data,
            'glom_spec': specs['source']['save'].glom_spec,
        },
        'target': {
            'glom_data': target_glom_data,
            'glom_spec': specs['target']['save'].glom_spec,
        },
    }

    if source_glom_data != target_glom_data:
        errors.append('data mismatch')

    return {
        'check_id': check_id,
        'params': params,
        'source': source_flat,
        'target': target_flat,
        'change': change_docs,
        'result': result_section,
        'errors': errors,
    }


async def _fetch_document(
    mongo_manager: MongoManager,
    find_spec: FindSpec,
    role: str,
    rule_name: str,
    errors: list[str],
    query_filter: Mapping[str, Any] | None = None,
) -> Mapping[str, Any] | None:
    if not find_spec:
        raise ValueError(f'{role} find_data missing for rule {rule_name}')

    try:
        query = _build_query(find_spec, query_filter)
    except ValueError as exc:
        raise ValueError(f'{role}: {exc}') from exc

    try:
        client = mongo_manager.get_client(find_spec.client_label)
        document = await client.get_database()[find_spec.collection].find_one(query)
    except Exception as exc:  # pragma: no cover
        errors.append(f'Failed to query {role} ({find_spec.collection}) with {query}: {exc}')
        return None

    if not document:
        errors.append(f'{role} document not found for {find_spec.collection} with {query}')
        return None

    return document


async def _fetch_change_documents(
    mongo_manager: MongoManager,
    target_find: FindSpec,
    target_doc: Mapping[str, Any] | None,
    rule_name: str,
    errors: list[str],
) -> dict[str, Any]:
    if not isinstance(target_doc, Mapping):
        return {}

    change_meta = target_doc.get('_c')
    if not isinstance(change_meta, Mapping) or not change_meta:
        errors.append('missing change')
        return {}

    client = mongo_manager.get_client(target_find.client_label)
    db = client.get_database()

    tasks: list[asyncio.Task] = []
    for name, meta in change_meta.items():
        if not isinstance(meta, Mapping):
            errors.append(f'invalid change metadata for {name}')
            continue
        bid = meta.get('bid')
        eid = meta.get('eid')
        cid = meta.get('cid')
        if bid is None or eid is None or cid is None:
            errors.append(f'invalid change metadata for {name}')
            continue

        query = {'bid': bid, 'eid': eid, 'cid': cid}

        async def _fetch_single(collection_name: str, query_filter: dict[str, Any]):
            try:
                doc = await db[collection_name].find_one(query_filter)
                return collection_name, doc, None
            except Exception as exc:  # pragma: no cover
                return collection_name, None, exc

        tasks.append(asyncio.create_task(_fetch_single(str(name), query)))

    change_docs: dict[str, Any] = {}
    if not tasks:
        return change_docs

    for coro in asyncio.as_completed(tasks):
        name, doc, err = await coro
        if err:
            errors.append(f'failed to fetch change {name}: {err}')
            continue
        if not doc:
            errors.append(f'missing change {name}')
            continue
        change_docs[name] = _flatten_document(doc)

    if not change_docs:
        return change_docs

    return dict(sorted(change_docs.items(), key=lambda item: item[0]))


def _build_query(
    find_spec: FindSpec,
    query_filter: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    filters = dict(query_filter or {})
    context = {'params': filters, 'query': filters}

    override_value: Any | None = None
    if find_spec.value_template is not None:
        if find_spec.query_keys and len(find_spec.query_keys) != 1:
            raise ValueError('filter_value supports only a single query key')
        override_value = evaluate_rule_template(find_spec.value_template, context)

    query: dict[str, Any] = {}
    missing_keys: list[str] = []

    if find_spec.query_keys:
        for key in find_spec.query_keys:
            if not key:
                raise ValueError('query key resolved to empty value')
            if override_value is not None:
                query[key] = override_value
                continue
            if key not in filters:
                missing_keys.append(key)
                continue
            query[key] = filters[key]
        if missing_keys:
            raise ValueError(f'params value missing for query key "{missing_keys[0]}"')
    else:
        if not filters and override_value is None:
            raise ValueError('params value missing for query')

    # Merge remaining filters so we respect the provided query dict.
    for key, value in filters.items():
        query.setdefault(key, value)

    if not query and override_value is not None and find_spec.query_keys:
        # Override without provided filters scenario
        query[find_spec.query_keys[0]] = override_value

    if not query:
        raise ValueError('query resolved to empty payload')

    return query


def _flatten_document(document: Mapping[str, Any] | None) -> dict[str, str]:
    if not isinstance(document, Mapping):
        return {}

    flat: dict[str, str] = {}

    def _recurse(value: Any, prefix: str) -> None:
        if isinstance(value, Mapping):
            for key, val in value.items():
                key_str = str(key)
                new_prefix = f'{prefix}.{key_str}' if prefix else key_str
                _recurse(val, new_prefix)
        elif isinstance(value, list):
            for index, val in enumerate(value):
                new_prefix = f'{prefix}.{index}' if prefix else str(index)
                _recurse(val, new_prefix)
        else:
            if prefix:
                flat[prefix] = _stringify(value)

    _recurse(document, '')
    return dict(sorted(flat.items(), key=lambda item: item[0]))


def _stringify(value: Any) -> str:
    if isinstance(value, ObjectId):
        return str(value)
    if value is None:
        return 'None'
    return str(value)
