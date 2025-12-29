from datetime import datetime

import yaml
from fastapi import APIRouter, Depends
from loguru import logger
from pydantic import BaseModel, Field, ValidationError

from app.cw.api.errors import E_INVALID_PARAMS
from app.cw.api.utils import ApiFailure, ApiSuccess, api_failure, verify_api_key

router = APIRouter()


class RateLimitConfig(BaseModel):
    refill_rate: float = Field(..., description="The refill rate of the rate limit", gt=0.0)
    capacity: float = Field(..., description="The capacity of the rate limit", gt=0.0)


class DefaultServiceConfig(BaseModel):
    model_config = {"extra": "forbid"}


class YamlConvertParams(BaseModel):
    yaml: str = Field(..., description="The YAML to convert")
    ssid: str = Field(..., description="The id of the conversion session")


def format_pydantic_errors(errors):
    return "<br>".join(
        [
            f"{error['msg']}: type={error['type']} loc={'.'.join([str(x) for x in error['loc']]) or 'None'}"
            for error in errors
        ]
    )


@router.get("/admin/yaml/example/{code}", response_model=ApiSuccess | ApiFailure)
async def admin_yaml_example(code: str, _: None = Depends(verify_api_key)):
    if code == "datacheck":
        text = f"""
# ------------------------------------------------------------
# Configs: wallet-cast-demo-{code}
# Created: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
# ------------------------------------------------------------
# Main switch to enable data check api
enable: false

# Data check rules
rules:
  - name: 01-host-info-from-cbe-user-to-flc-host
    source:
      find_data:
        collection: cbe_replica.user
        query_keys: _id
      save_data:
        path: $$
        from_dict:
          key: $$key
          value:
            user_id:   $$val._id
            bgimg:     $$val.bgimg
            ico:       $$val.ico
            infl:      $$val.infl
            lang:      $$val.lang
            location:  $$val.location
            website:   $$val.website
            status:    $$val.status
            username:  $$val.username
            ousername: $$val.ousername
            dsc:       $$val.dsc
            cdate:     $$val.cdate
            udate:     $$val.udate
    target:
      find_data:
        collection: flc_primary.flc_host
        query_keys: user_id
      save_data:
        path: $$
        from_dict:
          key: $$key
          value:
            user_id:   $$val.user_id
            bgimg:     $$val.bgimg
            ico:       $$val.ico
            infl:      $$val.infl
            lang:      $$val.lang
            location:  $$val.location
            website:   $$val.website
            status:    $$val.status
            username:  $$val.username
            ousername: $$val.ousername
            dsc:       $$val.dsc
            cdate:     $$val.cdate
            udate:     $$val.udate
  - name: 02-host-auth-from-cbe-user-to-flc-auth
    source:
      find_data:
        collection: cbe_replica.user
        query_keys: _id
      save_data:
        path: $$
        from_dict:
          key: $$key
          value:
            user_id:         $$val._id
            roles:           $$val.roles
            cdate:           $$val.cdate
            udate:           $$val.udate
            fg_app_disabled: $$val.fg_app_disabled
    target:
      find_data:
        collection: flc_primary.flc_auth
        query_keys: user_id
      save_data:
        path: $$
        from_dict:
          key: $$key
          value:
            user_id:         $$val.user_id
            roles:           $$val.roles
            udate:           $$val.udate
            fg_app_disabled: $$val.fg_app_disabled
  - name: 03-lv-configs-from-cbe-user-to-flc-channel
    source:
      find_data:
        collection: cbe_replica.user
        query_keys: _id
      save_data:
        path: lv_configs.channelConfigs
        from_dict:
          key: $$key
          value:
            channel_id:   $$val.channelId
            auto_start:   $$val.autoStart
            is_muted:     $$val.isMuted
            description:  $$val.dsc
            category_ids: $$val.categoryIds
            location:     $$val.location
            cover:        $$val.img
            title:        $$val.ttl
            lang:         $$val.lang
    target:
      find_data:
        collection: flc_primary.flc_channel
        query_keys: user_id
      save_data:
        path: $$
        from_list:
          key: $$val.channel_id
          value:
            channel_id:   $$val.channel_id
            auto_start:   $$val.auto_start
            category_ids: $$val.category_ids
            cover:        $$val.cover
            description:  $$val.description
            is_muted:     $$val.is_muted
            lang:         $$val.lang
            location:     $$val.location
            title:        $$val.title
  - name: 04-channel-from-lvm-channels-to-flc-channel
    source:
      find_data:
        collection: lvm_replica.channels
        query_keys: userUUID
      save_data:
        path: $$
        from_list:
          key:
            concat: ['configs.mux.', $$val.chanId]
          value:
            rtmp_url:       $$val.rtmpUrl
            stream_key:     $$val.metadata.streamKey
            playback_url:   $$val.metadata.previewUrl
            playback_id:    $$val.metadata.playbackId
            live_stream_id: $$val.metadata.liveStreamId
    target:
      find_data:
        collection: flc_primary.flc_channel
        query_keys: user_id
      save_data:
        path: configs.mux
        from_dict:
          key: $$key
          value:
            rtmp_url:       $$val.rtmp_url
            stream_key:     $$val.stream_key
            playback_url:   $$val.playback_url
            playback_id:    $$val.playback_id
            live_stream_id: $$val.live_stream_id
    """
    elif code == "default":
        # Generate example from default model
        default_config = DefaultServiceConfig()
        config_dict = default_config.model_dump(exclude_none=False, exclude_defaults=False)
        yaml_content = yaml.dump(config_dict, default_flow_style=False, sort_keys=False)

        text = f"""# ------------------------------------------------------------
# Configs: wallet-cast-demo-{code}
# Created: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
# ------------------------------------------------------------
{yaml_content}"""
    else:
        return api_failure(E_INVALID_PARAMS, errmesg=f"Invalid code: {code}")

    return ApiSuccess(results=text)


@router.post("/admin/yaml/convert/{code}", response_model=ApiSuccess | ApiFailure)
async def admin_yaml_convert(
    code: str, params: YamlConvertParams, _: None = Depends(verify_api_key)
):
    logger.debug("start convert: ssid={}, yaml=\n{}", params.ssid, params.yaml)
    try:
        logger.warning("params: {}", params.yaml)
        parsed_data = yaml.safe_load(params.yaml)
        if code == "default":
            model_data = DefaultServiceConfig.model_validate(parsed_data)
        else:
            return api_failure("E_CONFIG_CODE_NOT_FOUND", errmesg=f"Invalid code: {code}")

        results = model_data.model_dump(exclude_none=False, exclude_defaults=False)
        logger.debug("converted: ssid={}, json={}", params.ssid, results)

        return ApiSuccess(results=results)
    except ValidationError as e:
        return api_failure("E_CONFIG_FORMAT_INVALID", errmesg=format_pydantic_errors(e.errors()))
    except Exception as e:
        return api_failure(errmesg=e)
