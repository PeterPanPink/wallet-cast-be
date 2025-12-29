"""Helpers to convert rule configuration into executable specs.

The rule format declares how to find data in MongoDB and how to reshape it for
comparison.  We translate that structure into callable specs built on top of
``glom`` so we rely on the real transformation semantics instead of reimplementing
them in-house.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from glom import T, glom
from glom.core import GlomError


@dataclass
class FindSpec:
    """Minimal spec describing how to locate a Mongo document."""

    client_label: str
    collection: str
    query_keys: tuple[str, ...]
    value_template: Any | None = None


@dataclass
class SaveSpec:
    """Spec describing how to extract and reshape data from a document."""

    path_spec: Any
    transform_type: str
    key_spec: Any
    value_spec: Any
    collect: str
    flatten: bool
    sort_keys: bool
    raw_path: str
    raw_key_template: Any
    raw_value_template: Any

    def apply(self, data: Any) -> dict[str, Any]:
        """Execute the spec on ``data`` and return the reshaped mapping."""

        try:
            source = glom(data, self.path_spec, default=None, skip_exc=GlomError)
        except GlomError:
            source = None

        if source is None:
            collected: Mapping[str, Any] = {}
        else:
            if self.transform_type == 'from_dict':
                collected = _collect_from_dict(
                    source, data, self.key_spec, self.value_spec, self.collect
                )
            else:
                collected = _collect_from_list(
                    source, data, self.key_spec, self.value_spec, self.collect
                )

        result: Mapping[str, Any] = collected
        if not isinstance(result, Mapping):
            result = {'value': result}

        result = _collapse_collected(result)
        if not isinstance(result, Mapping):
            result = {'value': result}

        if self.flatten:
            result = _flatten_mapping(result)

        if self.sort_keys:
            result = dict(sorted(result.items(), key=lambda item: item[0]))

        return result

    @property
    def glom_spec(self) -> dict[str, Any]:
        """Expose the human-readable specification used to build this save spec."""

        return {
            'path': self.raw_path,
            'type': self.transform_type,
            'key_template': self.raw_key_template,
            'value_template': self.raw_value_template,
            'collect': self.collect,
            'flatten': self.flatten,
            'sort_keys': self.sort_keys,
        }


def build_find_spec(config: Mapping[str, Any]) -> FindSpec:
    """Convert ``find_data`` config into a simple ``FindSpec``."""

    raw_collection = str(config.get('collection', '')).strip()
    if not raw_collection:
        raise ValueError('find_data.collection is required')

    if '.' not in raw_collection:
        raise ValueError('find_data.collection must use "<client_label>.<collection>" format')

    client_label, collection = raw_collection.split('.', 1)
    client_label = client_label.strip()
    collection = collection.strip()

    if not client_label or not collection:
        raise ValueError('find_data.collection must include both client label and collection name')

    query_keys = _extract_query_keys(config)
    if not query_keys:
        raise ValueError('find_data.query_keys is required')

    return FindSpec(
        client_label=client_label,
        collection=collection,
        query_keys=tuple(query_keys),
        value_template=config.get('filter_value'),
    )


def _extract_query_keys(config: Mapping[str, Any]) -> list[str]:
    raw_keys = config.get('query_keys')
    if raw_keys is not None:
        return _normalize_query_keys(raw_keys)

    legacy_filter = config.get('filter_key')
    if legacy_filter is None:
        return []

    return _normalize_query_keys(legacy_filter)


def _normalize_query_keys(raw: Any) -> list[str]:
    context = _template_context()

    def _coerce(value: Any) -> str:
        evaluated = _evaluate_template(value, context)
        key = str(evaluated).strip()
        if not key:
            raise ValueError('find_data.query_keys resolved to empty value')
        return key

    if isinstance(raw, str):
        parts = [part.strip() for part in raw.split(',') if part.strip()]
        if not parts:
            parts = [raw.strip()]
        return [_coerce(part) for part in parts]

    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
        return [_coerce(part) for part in raw]

    return [_coerce(raw)]


def build_save_spec(config: Mapping[str, Any]) -> SaveSpec:
    """Convert ``save_data`` config into a callable ``SaveSpec``."""

    raw_path = str(config.get('path', '$$')).strip() or '$$'
    path_spec = _compile_path_spec(raw_path)

    flatten = _as_bool(config.get('flatten'), default=False)
    sort_keys = _as_bool(config.get('sort_keys'), default=True)
    collect = str(config.get('collect') or 'dict')

    if 'from_dict' in config:
        from_dict_config = config['from_dict']
        key_template = from_dict_config.get('key')
        value_template = from_dict_config.get('value')
        if key_template is None or value_template is None:
            raise ValueError('from_dict requires both "key" and "value" templates')

        return SaveSpec(
            path_spec=path_spec,
            transform_type='from_dict',
            key_spec=_compile_glom_template(key_template),
            value_spec=_compile_glom_template(value_template),
            collect=collect,
            flatten=flatten,
            sort_keys=sort_keys,
            raw_path=raw_path,
            raw_key_template=key_template,
            raw_value_template=value_template,
        )

    if 'from_list' in config:
        from_list_config = config['from_list']
        key_template = from_list_config.get('key')
        value_template = from_list_config.get('value')
        if key_template is None or value_template is None:
            raise ValueError('from_list requires both "key" and "value" templates')

        return SaveSpec(
            path_spec=path_spec,
            transform_type='from_list',
            key_spec=_compile_glom_template(key_template),
            value_spec=_compile_glom_template(value_template),
            collect=collect,
            flatten=flatten,
            sort_keys=sort_keys,
            raw_path=raw_path,
            raw_key_template=key_template,
            raw_value_template=value_template,
        )

    raise ValueError('Unsupported save_data configuration: expected from_dict or from_list')


def build_rule_specs(rule: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Build find/save specs for both source and target parts of a rule."""

    rule_name = str(rule.get('name') or '')

    def _validate_section(section: str, config: Any) -> Mapping[str, Any]:
        if not isinstance(config, Mapping):
            raise ValueError(f'{section} configuration missing for rule {rule_name}')
        return config

    source_config = _validate_section('source', rule.get('source'))
    target_config = _validate_section('target', rule.get('target'))

    def _extract_find(section: str, config: Mapping[str, Any]) -> Mapping[str, Any]:
        find_data = config.get('find_data')
        if not isinstance(find_data, Mapping):
            raise ValueError(f'{section}.find_data missing for rule {rule_name}')
        collection_value = str(find_data.get('collection') or '').strip()
        if not collection_value:
            raise ValueError(f'{section}.find_data.collection missing for rule {rule_name}')
        if '.' not in collection_value:
            raise ValueError(
                f'{section}.find_data.collection must use "<client_label>.<collection>" format for rule {rule_name}'
            )
        if find_data.get('query_keys') is None and find_data.get('filter_key') is None:
            raise ValueError(f'{section}.find_data.query_keys missing for rule {rule_name}')
        return find_data

    def _extract_save(section: str, config: Mapping[str, Any]) -> Mapping[str, Any]:
        save_data = config.get('save_data')
        if not isinstance(save_data, Mapping):
            raise ValueError(f'{section}.save_data missing for rule {rule_name}')
        return save_data

    source_find_config = _extract_find('source', source_config)
    source_save_config = _extract_save('source', source_config)

    source_specs = {
        'find': build_find_spec(source_find_config),
        'save': build_save_spec(source_save_config),
    }

    target_find_config = _extract_find('target', target_config)
    target_save_config = _extract_save('target', target_config)

    target_specs = {
        'find': build_find_spec(target_find_config),
        'save': build_save_spec(target_save_config),
    }

    return {'source': source_specs, 'target': target_specs}


def execute_rule_on_data(
    rule: Mapping[str, Any],
    source_data: Any,
    target_data: Any,
) -> dict[str, Any]:
    """Apply the generated save specs to ``source_data`` and ``target_data``."""

    specs = build_rule_specs(rule)
    source_result = specs['source']['save'].apply(source_data)
    target_result = specs['target']['save'].apply(target_data)

    return {
        'source': source_result,
        'target': target_result,
        'source_glom_spec': specs['source']['save'].glom_spec,
        'target_glom_spec': specs['target']['save'].glom_spec,
    }


def _compile_path_spec(path: str) -> Any:
    if path in ('', '$$', '@', None):
        return T
    return path


def _compile_glom_template(template: Any) -> Any:
    if isinstance(template, str):
        expr = template.strip()
        if expr.startswith('$$'):
            parts = [segment for segment in expr[2:].split('.') if segment]
            if not parts:
                return T

            base = parts[0]
            tail = parts[1:]

            def _build(base_spec: Any) -> Any:
                current = base_spec
                for part in tail:
                    current = current[part]
                return current

            mapping: dict[str, Any] = {
                'key': T['key'],
                'val': T['val'],
                'root': T['root'],
                'container': T['container'],
                'doc': T['doc'],
            }
            base_spec = mapping.get(base, T[base])
            return _build(base_spec)
        return template

    if isinstance(template, Mapping):
        return {key: _compile_glom_template(value) for key, value in template.items()}

    if isinstance(template, Sequence) and not isinstance(template, (str, bytes, bytearray)):
        return [_compile_glom_template(item) for item in template]

    return template


def _evaluate_glom_template(template: Any, context: Mapping[str, Any]) -> Any:
    if hasattr(template, 'glomit'):
        try:
            return glom(context, template, default=None, skip_exc=GlomError)
        except GlomError:
            return None

    if isinstance(template, Mapping):
        return {key: _evaluate_glom_template(value, context) for key, value in template.items()}

    if isinstance(template, Sequence) and not isinstance(template, (str, bytes, bytearray)):
        return [_evaluate_glom_template(item, context) for item in template]

    return template


def _flatten_mapping(data: Any) -> dict[str, Any]:
    flat: dict[str, Any] = {}

    def _recurse(obj: Any, prefix: str) -> None:
        if isinstance(obj, Mapping):
            for key, value in obj.items():
                key_str = str(key)
                new_prefix = f'{prefix}.{key_str}' if prefix else key_str
                _recurse(value, new_prefix)
        elif isinstance(obj, Sequence) and not isinstance(obj, (str, bytes, bytearray)):
            for index, value in enumerate(obj):
                new_prefix = f'{prefix}.{index}' if prefix else str(index)
                _recurse(value, new_prefix)
        else:
            if not prefix:
                raise ValueError('Cannot flatten non-mapping root value')
            flat[prefix] = obj

    _recurse(data, '')
    return flat


def evaluate_rule_template(template: Any, context: Mapping[str, Any] | None = None) -> Any:
    return _evaluate_template(template, _template_context(context))


def _evaluate_template(template: Any, context: Mapping[str, Any]) -> Any:
    if isinstance(template, str):
        template = template.strip()
        if template.startswith('$$'):
            return _resolve_placeholder(template[2:], context)
        return template

    if isinstance(template, Mapping):
        if _is_concat_template(template):
            parts = template.get('concat', [])
            evaluated = [_evaluate_template(part, context) for part in parts]
            return ''.join('' if part is None else str(part) for part in evaluated)

        return {key: _evaluate_template(value, context) for key, value in template.items()}

    if isinstance(template, Sequence) and not isinstance(template, (str, bytes, bytearray)):
        return [_evaluate_template(item, context) for item in template]

    return template


def _resolve_placeholder(placeholder: str, context: Mapping[str, Any]) -> Any:
    if not placeholder:
        raise ValueError('Empty placeholder is not supported')

    if placeholder == 'key':
        return context.get('key')

    if placeholder.startswith('val'):
        value = context.get('val')
        return _resolve_object_path(value, placeholder[3:].lstrip('.'))

    if placeholder.startswith('params'):
        params = context.get('params')
        return _resolve_object_path(params, placeholder[6:].lstrip('.'))

    if placeholder.startswith('query'):
        params = context.get('query')
        return _resolve_object_path(params, placeholder[5:].lstrip('.'))

    raise ValueError(f'Unsupported placeholder: {placeholder}')


def _template_context(overrides: Mapping[str, Any] | None = None) -> dict[str, Any]:
    base = {'key': None, 'val': None, 'root': None, 'params': None, 'query': None}
    if overrides:
        base.update(overrides)
    return base


def _is_concat_template(template: Mapping[str, Any]) -> bool:
    if len(template) != 1:
        return False
    key = next(iter(template.keys()))
    return key == 'concat'


def _as_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {'1', 'true', 'yes', 'on'}
    return bool(value)


def _resolve_object_path(obj: Any, path: str) -> Any:
    if not path:
        return obj

    current = obj
    for part in path.split('.'):
        if isinstance(current, Mapping):
            current = current.get(part)
        elif isinstance(current, Sequence) and part.isdigit():
            current = current[int(part)]
        else:
            current = getattr(current, part, None)
    return current


def execute_save(config: Mapping[str, Any], data: Any) -> dict[str, Any]:
    """Convenience helper: build and immediately execute a save spec."""

    spec = build_save_spec(config)
    return spec.apply(data)


def _collect_from_dict(
    source: Any,
    document: Any,
    key_spec: Any,
    value_spec: Any,
    collect: str,
) -> Mapping[str, Any]:
    if not isinstance(source, Mapping):
        return {}

    pairs = _build_pairs(source.items(), source, document, key_spec, value_spec)
    if not pairs:
        pairs = _build_pairs([(None, source)], source, document, key_spec, value_spec)

    return _finalize_pairs(pairs, collect)


def _collect_from_list(
    source: Any,
    document: Any,
    key_spec: Any,
    value_spec: Any,
    collect: str,
) -> Mapping[str, Any]:
    iterable: list[tuple[Any | None, Any]]
    if isinstance(source, Mapping):
        iterable = list(enumerate(source.values()))
    elif isinstance(source, Sequence) and not isinstance(source, (str, bytes, bytearray)):
        iterable = list(enumerate(source))
    else:
        iterable = []

    if not iterable:
        return {}

    pairs = _build_pairs(iterable, source, document, key_spec, value_spec)
    return _finalize_pairs(pairs, collect)


def _build_pairs(
    iterable: Sequence[tuple[Any | None, Any]],
    container: Any,
    document: Any,
    key_spec: Any,
    value_spec: Any,
) -> list[tuple[Any | None, Any]]:
    pairs: list[tuple[Any | None, Any]] = []

    for raw_key, raw_value in iterable:
        context = {
            'key': raw_key,
            'val': raw_value,
            'root': container,
            'container': container,
            'doc': document,
        }
        new_key = _evaluate_glom_template(key_spec, context)
        new_value = _evaluate_glom_template(value_spec, context)
        normalized_value = _normalize_flat_output(new_value)
        if _is_all_none(normalized_value):
            continue
        pairs.append((new_key, normalized_value))

    return pairs


def _finalize_pairs(
    pairs: Sequence[tuple[Any | None, Any]],
    collect: str,
) -> Mapping[str, Any]:
    if collect not in (None, 'dict'):
        raise ValueError(f'Unsupported collect mode: {collect}')

    result: dict[str, Any] = {}
    for key, value in pairs:
        if key is None:
            if isinstance(value, Mapping):
                result.update(value)
            else:
                result[str(len(result))] = value
        else:
            result[str(key)] = value

    return result


def _collapse_collected(value: Mapping[str, Any]) -> Mapping[str, Any] | Any:
    if not isinstance(value, Mapping):
        return value

    if not value:
        return value

    first_key = next(iter(value))
    first_value = value[first_key]

    if len(value) == 1 and isinstance(first_value, Mapping):
        collapsed = _collapse_collected(first_value)
        if isinstance(collapsed, Mapping):
            return collapsed
        return {first_key: collapsed}

    if all(isinstance(item, Mapping) for item in value.values()):
        normalized_first = _normalize_flat_output(first_value)
        if all(_normalize_flat_output(item) == normalized_first for item in value.values()):
            return first_value

    return value


def _is_all_none(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, Mapping):
        return all(_is_all_none(item) for item in value.values())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return all(_is_all_none(item) for item in value)
    return False


def _normalize_flat_output(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _normalize_flat_output(val) for key, val in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_normalize_flat_output(item) for item in value]
    if _is_object_id(value):
        return str(value)
    return value


def _is_object_id(value: Any) -> bool:
    return value.__class__.__name__ == 'ObjectId'
