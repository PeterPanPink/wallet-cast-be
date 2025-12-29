"""Unit tests for External Live API schemas."""

import json

import pytest

from app.services.integrations.external_live.external_live_schemas import AdminStartLiveBody


class TestAdminStartLiveBody:
    """Tests for AdminStartLiveBody schema serialization/deserialization."""

    @pytest.fixture
    def example_json(self) -> str:
        """Example JSON from External Live API."""
        return """{
  "user_id": "zaqqaz",
  "channel": {
    "channelId": "ch_01kc6brrk6700agd1h5fnbyx5s",
    "dsc": null,
    "img": "group1/livetest/2025/11/16/03/09f84ec0-02b7-125a-dcd1-bddfffdec757/bcc5667786d6bd1b25e7c4d8a42e8550.jpg",
    "lang": "en",
    "ttl": "zaqqaz's livestream 2025-12-11-092711",
    "categoryIds": ["gaming", "politics"],
    "location": "AG",
    "autoStart": false
  },
  "session": {
    "sid": "se_01kc6brrk6700agd1h5fnbyx5t",
    "url": "https://stream.mux.com/ftxkhkWmTzq8Pr89kz02GQMPUUAMPoZ4rDKDzk3fw02qo.m3u8",
    "animatedUrl": "https://image.mux.com/ftxkhkWmTzq8Pr89kz02GQMPUUAMPoZ4rDKDzk3fw02qo/animated.gif?width=640&fps=5",
    "thumbnailUrl": "https://image.mux.com/ftxkhkWmTzq8Pr89kz02GQMPUUAMPoZ4rDKDzk3fw02qo/thumbnail.jpg?width=853&height=480&fit_mode=smartcrop&time=60",
    "thumbnails": "https://image.mux.com/ftxkhkWmTzq8Pr89kz02GQMPUUAMPoZ4rDKDzk3fw02qo/storyboard.vtt",
    "mux_stream_id": "1bgmIA1RuTkB01iohG00iqgB8bQMdZItSkrTZ4014Vfppw",
    "mux_rtmp_ingest_url": "rtmps://global-live.mux.com:443/app/7a9620e3-fab0-cfa0-aa2f-e76c9136267e"
  }
}"""

    def test_deserialize_and_reserialize(self, example_json: str) -> None:
        """Test that deserializing and re-serializing produces the same JSON."""
        # Parse original JSON
        original_dict = json.loads(example_json)

        # Deserialize to Pydantic model
        model = AdminStartLiveBody.model_validate(original_dict)

        # Re-serialize to dict using default settings
        reserialized_dict = model.model_dump()

        # Normalize both by converting to JSON strings (this handles field ordering)
        original_json_normalized = json.dumps(original_dict, sort_keys=True)
        reserialized_json_normalized = json.dumps(reserialized_dict, sort_keys=True)

        # Compare the normalized JSON strings
        assert reserialized_json_normalized == original_json_normalized, (
            f"Reserialized dict does not match original.\n"
            f"Original: {json.dumps(original_dict, indent=2, sort_keys=True)}\n"
            f"Reserialized: {json.dumps(reserialized_dict, indent=2, sort_keys=True)}"
        )

        # Verify exact field counts (no more, no less)
        assert len(reserialized_dict) == 3  # user_id, channel, session
        assert (
            len(reserialized_dict["channel"]) == 8
        )  # channelId, dsc, img, lang, ttl, categoryIds, location, autoStart
        assert (
            len(reserialized_dict["session"]) == 7
        )  # sid, url, animatedUrl, thumbnailUrl, thumbnails, mux_stream_id, mux_rtmp_ingest_url

    def test_deserialize_with_python_names(self, example_json: str) -> None:
        """Test that we can access fields using Python names after deserialization."""
        original_dict = json.loads(example_json)
        model = AdminStartLiveBody.model_validate(original_dict)

        # Verify we can access fields using Python names
        assert model.user_id == "zaqqaz"
        assert model.channel.channel_id == "ch_01kc6brrk6700agd1h5fnbyx5s"
        assert model.channel.ttl == "zaqqaz's livestream 2025-12-11-092711"
        assert (
            model.channel.img
            == "group1/livetest/2025/11/16/03/09f84ec0-02b7-125a-dcd1-bddfffdec757/bcc5667786d6bd1b25e7c4d8a42e8550.jpg"
        )
        assert model.channel.lang == "en"
        assert model.channel.category_ids == ["gaming", "politics"]
        assert model.channel.location == "AG"
        assert model.channel.dsc is None
        assert model.channel.auto_start is False

        assert model.session.session_id == "se_01kc6brrk6700agd1h5fnbyx5t"
        assert (
            model.session.url
            == "https://stream.mux.com/ftxkhkWmTzq8Pr89kz02GQMPUUAMPoZ4rDKDzk3fw02qo.m3u8"
        )
        assert (
            model.session.animated_url
            == "https://image.mux.com/ftxkhkWmTzq8Pr89kz02GQMPUUAMPoZ4rDKDzk3fw02qo/animated.gif?width=640&fps=5"
        )
        assert (
            model.session.thumbnail_url
            == "https://image.mux.com/ftxkhkWmTzq8Pr89kz02GQMPUUAMPoZ4rDKDzk3fw02qo/thumbnail.jpg?width=853&height=480&fit_mode=smartcrop&time=60"
        )
        assert (
            model.session.thumbnails
            == "https://image.mux.com/ftxkhkWmTzq8Pr89kz02GQMPUUAMPoZ4rDKDzk3fw02qo/storyboard.vtt"
        )
        assert model.session.mux_stream_id == "1bgmIA1RuTkB01iohG00iqgB8bQMdZItSkrTZ4014Vfppw"
        assert (
            model.session.mux_rtmp_ingest_url
            == "rtmps://global-live.mux.com:443/app/7a9620e3-fab0-cfa0-aa2f-e76c9136267e"
        )

    def test_serialize_with_aliases(self) -> None:
        """Test that serializing with aliases produces correct field names."""
        from app.services.integrations.external_live.external_live_schemas import ChannelConfig, SessionConfig

        model = AdminStartLiveBody(
            user_id="test_user",
            channel=ChannelConfig.model_validate(
                {
                    "channelId": "ch_123",
                    "ttl": "Test Stream",
                    "img": "test.jpg",
                    "lang": "en",
                    "categoryIds": ["gaming"],
                    "location": "US",
                    "dsc": "Test description",
                    "autoStart": True,
                }
            ),
            session=SessionConfig.model_validate(
                {
                    "sid": "se_456",
                    "url": "https://example.com/stream.m3u8",
                    "animatedUrl": "https://example.com/animated.gif",
                    "thumbnailUrl": "https://example.com/thumb.jpg",
                    "thumbnails": "https://example.com/storyboard.vtt",
                    "mux_stream_id": "mux_789",
                    "mux_rtmp_ingest_url": "rtmps://example.com/app/key",
                }
            ),
        )

        # Serialize with default settings
        serialized = model.model_dump()

        # Verify alias names are used in output
        assert "channelId" in serialized["channel"]
        assert "categoryIds" in serialized["channel"]
        assert "autoStart" in serialized["channel"]
        assert "sid" in serialized["session"]
        assert "animatedUrl" in serialized["session"]
        assert "thumbnailUrl" in serialized["session"]

        # Verify Python names are not in output
        assert "channel_id" not in serialized["channel"]
        assert "category_ids" not in serialized["channel"]
        assert "auto_start" not in serialized["channel"]
        assert "session_id" not in serialized["session"]
        assert "animated_url" not in serialized["session"]
        assert "thumbnail_url" not in serialized["session"]

        # Verify exact field counts (no more, no less)
        assert len(serialized) == 3  # user_id, channel, session
        assert (
            len(serialized["channel"]) == 8
        )  # channelId, ttl, img, lang, categoryIds, location, dsc, autoStart
        assert (
            len(serialized["session"]) == 7
        )  # sid, mux_stream_id, mux_rtmp_ingest_url, url, animatedUrl, thumbnailUrl, thumbnails

    def test_schema_fields_match_example(self, example_json: str) -> None:
        """Test that schema fields exactly match example JSON fields (no more, no less)."""
        from app.services.integrations.external_live.external_live_schemas import ChannelConfig, SessionConfig

        original_dict = json.loads(example_json)

        # Get serialized field names from Pydantic models (using aliases)
        def get_schema_fields(model_class: type) -> set[str]:
            """Get serialized field names from Pydantic model (alias if defined, else field name)."""
            fields = set()
            for field_name, field_info in model_class.model_fields.items():
                # Use alias if defined, otherwise use field name
                alias = field_info.alias
                fields.add(alias if alias else field_name)
            return fields

        # Get expected fields from example JSON
        example_top_level_fields = set(original_dict.keys())
        example_channel_fields = set(original_dict["channel"].keys())
        example_session_fields = set(original_dict["session"].keys())

        # Get schema fields
        schema_top_level_fields = get_schema_fields(AdminStartLiveBody)
        schema_channel_fields = get_schema_fields(ChannelConfig)
        schema_session_fields = get_schema_fields(SessionConfig)

        # Compare top-level fields
        assert schema_top_level_fields == example_top_level_fields, (
            f"Top-level fields mismatch.\n"
            f"Schema fields: {sorted(schema_top_level_fields)}\n"
            f"Example fields: {sorted(example_top_level_fields)}\n"
            f"Missing in schema: {sorted(example_top_level_fields - schema_top_level_fields)}\n"
            f"Extra in schema: {sorted(schema_top_level_fields - example_top_level_fields)}"
        )

        # Compare channel fields
        assert schema_channel_fields == example_channel_fields, (
            f"Channel fields mismatch.\n"
            f"Schema fields: {sorted(schema_channel_fields)}\n"
            f"Example fields: {sorted(example_channel_fields)}\n"
            f"Missing in schema: {sorted(example_channel_fields - schema_channel_fields)}\n"
            f"Extra in schema: {sorted(schema_channel_fields - example_channel_fields)}"
        )

        # Compare session fields
        assert schema_session_fields == example_session_fields, (
            f"Session fields mismatch.\n"
            f"Schema fields: {sorted(schema_session_fields)}\n"
            f"Example fields: {sorted(example_session_fields)}\n"
            f"Missing in schema: {sorted(example_session_fields - schema_session_fields)}\n"
            f"Extra in schema: {sorted(schema_session_fields - example_session_fields)}"
        )
