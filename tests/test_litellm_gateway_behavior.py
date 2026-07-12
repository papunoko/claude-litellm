import asyncio
import importlib
import json
import os
import sys
import tomllib
import unittest
from pathlib import Path
from typing import Any, ClassVar

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


CONFIG_PATH = ROOT / "litellm_config.max-codex-subscriptions.yaml"
START_SCRIPT_PATH = ROOT / "scripts" / "start-litellm-max-codex-gateway.ps1"
TEST_SCRIPT_PATH = ROOT / "scripts" / "test-litellm-max-codex-gateway.ps1"
CLAUDE_CODE_SETTINGS_EXAMPLE_PATH = ROOT / "examples" / "claude-code-settings.json"
CODEX_CONTEXT_BUDGET_EXAMPLE_PATH = ROOT / "examples" / "codex-context-budget.toml"
PATCH_MODULE_NAME = "litellm_callbacks.chatgpt_anthropic_messages"
MISSING = object()
PATCH_ENV_VARS = (
    "CLAUDE_LITELLM_NON_CLAUDE_MODELS",
    "CLAUDE_LITELLM_CONFIG",
)


def capture_litellm_patch_state() -> list[tuple[object, str, object]]:
    from litellm.litellm_core_utils.litellm_logging import Logging
    from litellm.llms.anthropic.experimental_pass_through import utils
    from litellm.llms.anthropic.experimental_pass_through.messages import handler
    from litellm.llms.anthropic.experimental_pass_through.responses_adapters.streaming_iterator import (
        AnthropicResponsesStreamWrapper,
    )
    from litellm.llms.anthropic.experimental_pass_through.responses_adapters.transformation import (
        LiteLLMAnthropicToResponsesAPIAdapter,
    )

    attrs = [
        (handler, "_RESPONSES_API_PROVIDERS"),
        (utils, "normalize_reasoning_effort_value"),
        (utils, "_claude_litellm_chatgpt_effort_patch"),
        (Logging, "_handle_anthropic_messages_response_logging"),
        (Logging, "_claude_litellm_chatgpt_logging_patch"),
        (LiteLLMAnthropicToResponsesAPIAdapter, "translate_messages_to_responses_input"),
        (LiteLLMAnthropicToResponsesAPIAdapter, "translate_tools_to_responses_api"),
        (LiteLLMAnthropicToResponsesAPIAdapter, "translate_response"),
        (LiteLLMAnthropicToResponsesAPIAdapter, "_claude_litellm_web_search_patch"),
        (AnthropicResponsesStreamWrapper, "_process_event"),
        (AnthropicResponsesStreamWrapper, "_claude_litellm_web_search_patch"),
    ]
    return [(obj, name, getattr(obj, name, MISSING)) for obj, name in attrs]


def restore_litellm_patch_state(state: list[tuple[object, str, object]]) -> None:
    for obj, name, value in state:
        if value is MISSING:
            if hasattr(obj, name):
                delattr(obj, name)
        else:
            setattr(obj, name, value)

    sys.modules.pop(PATCH_MODULE_NAME, None)
    package = sys.modules.get("litellm_callbacks")
    if package is not None:
        package.__dict__.pop("chatgpt_anthropic_messages", None)


def load_config() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))


class GatewayConfigTests(unittest.TestCase):
    def test_model_list_is_intentionally_small(self) -> None:
        config = load_config()
        model_names = [entry["model_name"] for entry in config["model_list"]]

        self.assertEqual(
            model_names,
            [
                "claude-opus-4-6",
                "claude-opus-4-7",
                "claude-opus-4-8",
                "claude-fable-5",
                "claude-sonnet-5",
                "claude-haiku-4-5-20251001",
                "claude-codex-gpt-5-5",
                "claude-codex-gpt-5-6",
            ],
        )
        self.assertNotIn("claude-codex-gpt-5-5-medium", model_names)
        self.assertNotIn("claude-chatgpt-gpt-5-4", model_names)
        self.assertNotIn("claude-codex-gpt-5-3-codex", model_names)

    def test_codex_alias_defaults_to_chatgpt_responses_medium(self) -> None:
        config = load_config()
        codex = next(
            entry
            for entry in config["model_list"]
            if entry["model_name"] == "claude-codex-gpt-5-5"
        )

        self.assertEqual(codex["model_info"]["mode"], "responses")
        self.assertEqual(codex["litellm_params"]["model"], "chatgpt/gpt-5.5")
        self.assertEqual(
            codex["litellm_params"]["reasoning"],
            {"effort": "medium"},
        )

    def test_codex_alias_pins_gpt_5_5_context_window(self) -> None:
        config = load_config()
        codex = next(
            entry
            for entry in config["model_list"]
            if entry["model_name"] == "claude-codex-gpt-5-5"
        )
        model_info = codex["model_info"]

        # GPT-5.5 on the Codex / ChatGPT subscription surface is a
        # 400K-total window split 272K input + 128K output. Pin it
        # explicitly so gateway model discovery and LiteLLM token accounting
        # do not over-fill the prompt and 400 a long subagent turn.
        self.assertEqual(model_info["max_input_tokens"], 272000)
        self.assertEqual(model_info["max_output_tokens"], 128000)
        self.assertEqual(model_info["max_tokens"], 128000)
        self.assertEqual(
            model_info["max_input_tokens"] + model_info["max_output_tokens"],
            400000,
        )

    def test_gpt_5_6_alias_defaults_to_sol_responses_medium(self) -> None:
        config = load_config()
        codex = next(
            entry
            for entry in config["model_list"]
            if entry["model_name"] == "claude-codex-gpt-5-6"
        )

        self.assertEqual(codex["model_info"]["mode"], "responses")
        self.assertEqual(codex["litellm_params"]["model"], "chatgpt/gpt-5.6-sol")
        self.assertEqual(
            codex["litellm_params"]["reasoning"],
            {"effort": "medium"},
        )
        # Reuse the proven GPT-5.5 subscription-surface split until a smoke
        # test against the Codex surface proves a bigger budget for 5.6.
        model_info = codex["model_info"]
        self.assertEqual(model_info["max_input_tokens"], 272000)
        self.assertEqual(model_info["max_output_tokens"], 128000)
        self.assertEqual(model_info["max_tokens"], 128000)

    def test_codex_cli_context_budget_example_keeps_32k_headroom(self) -> None:
        with CODEX_CONTEXT_BUDGET_EXAMPLE_PATH.open("rb") as handle:
            config = tomllib.load(handle)

        self.assertEqual(config["model_context_window"], 272000)
        self.assertEqual(config["model_auto_compact_token_limit"], 240000)
        self.assertEqual(
            config["model_context_window"]
            - config["model_auto_compact_token_limit"],
            32000,
        )

    def test_client_authorization_header_is_not_forwarded_to_chatgpt(self) -> None:
        config = load_config()
        forwarded = config["litellm_settings"]["model_group_settings"][
            "forward_client_headers_to_llm_api"
        ]

        self.assertEqual(
            forwarded,
            [
                "claude-opus-4-6",
                "claude-opus-4-7",
                "claude-opus-4-8",
                "claude-fable-5",
                "claude-sonnet-5",
                "claude-haiku-4-5-20251001",
            ],
        )
        self.assertNotIn("claude-codex-gpt-5-5", forwarded)


class StartupScriptTests(unittest.TestCase):
    def test_start_script_lists_required_claude_client_env(self) -> None:
        script = START_SCRIPT_PATH.read_text(encoding="utf-8")

        for expected in [
            '[string]$BindHost = "127.0.0.1"',
            'throw "Set -MasterKey or LITELLM_MASTER_KEY',
            "ANTHROPIC_BASE_URL=http://localhost:$Port",
            "ANTHROPIC_MODEL=claude-codex-gpt-5-6",
            "ANTHROPIC_CUSTOM_HEADERS=x-litellm-api-key: Bearer <LITELLM_MASTER_KEY>",
            "$env:CLAUDE_LITELLM_CONFIG = $ConfigPath",
            "litellm --config $ConfigPath --host $BindHost --port $Port",
            "$ExitCode = $LASTEXITCODE",
            "exit $ExitCode",
            "CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1",
            "claude-opus-4-6",
            "claude-opus-4-7",
            "claude-fable-5",
            "claude-codex-gpt-5-5",
            "ANTHROPIC_DEFAULT_OPUS_MODEL=claude-codex-gpt-5-6",
            "ANTHROPIC_DEFAULT_SONNET_MODEL=claude-sonnet-5",
            "ANTHROPIC_DEFAULT_HAIKU_MODEL=claude-haiku-4-5-20251001",
            "ANTHROPIC_CUSTOM_MODEL_OPTION=claude-codex-gpt-5-6",
            "ANTHROPIC_CUSTOM_MODEL_OPTION_SUPPORTED_CAPABILITIES=effort,xhigh_effort,max_effort,thinking,adaptive_thinking,interleaved_thinking",
            "$ClientOnlyEnvNames = @(",
            '"ANTHROPIC_BASE_URL"',
            '"ANTHROPIC_CUSTOM_HEADERS"',
            '"CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY"',
            "cleared client-only Anthropic env before launching gateway",
            "[Environment]::SetEnvironmentVariable($Name, $null, \"Process\")",
            "finally {",
        ]:
            self.assertIn(expected, script)

        self.assertNotIn(
            "ANTHROPIC_CUSTOM_HEADERS=x-litellm-api-key: Bearer $MasterKey",
            script,
        )
        self.assertNotIn("local-master-key", script)
        self.assertNotIn("claude-codex-gpt-5-5-medium", script)


class TestScriptTests(unittest.TestCase):
    def test_test_script_forwards_unittest_exit_code(self) -> None:
        script = TEST_SCRIPT_PATH.read_text(encoding="utf-8")

        self.assertIn("$TestExitCode = $LASTEXITCODE", script)
        self.assertIn("exit $TestExitCode", script)


class ClaudeCodeSettingsExampleTests(unittest.TestCase):
    def test_example_settings_json_matches_gateway_aliases(self) -> None:
        settings = json.loads(
            CLAUDE_CODE_SETTINGS_EXAMPLE_PATH.read_text(encoding="utf-8")
        )
        env = settings["env"]

        self.assertEqual(settings["model"], "claude-codex-gpt-5-6")
        self.assertEqual(settings["effortLevel"], "medium")
        self.assertEqual(env["ANTHROPIC_BASE_URL"], "http://localhost:4000")
        self.assertEqual(env["ANTHROPIC_MODEL"], "claude-codex-gpt-5-6")
        self.assertEqual(
            env["ANTHROPIC_CUSTOM_HEADERS"],
            "x-litellm-api-key: Bearer <LITELLM_MASTER_KEY>",
        )
        self.assertEqual(env["ANTHROPIC_DEFAULT_OPUS_MODEL"], "claude-opus-4-8")
        self.assertEqual(env["ANTHROPIC_DEFAULT_SONNET_MODEL"], "claude-sonnet-5")
        self.assertEqual(
            env["ANTHROPIC_DEFAULT_HAIKU_MODEL"],
            "claude-haiku-4-5-20251001",
        )
        self.assertEqual(
            env["ANTHROPIC_CUSTOM_MODEL_OPTION"],
            "claude-codex-gpt-5-6",
        )


class ChatGPTAnthropicMessagesPatchTests(unittest.TestCase):
    patch: ClassVar[Any | None] = None
    litellm_patch_state: ClassVar[list[tuple[object, str, object]]] = []
    env_state: ClassVar[dict[str, str | None]] = {}

    @classmethod
    def setUpClass(cls) -> None:
        cls.litellm_patch_state = capture_litellm_patch_state()
        cls.env_state = {name: os.environ.get(name) for name in PATCH_ENV_VARS}
        for name in PATCH_ENV_VARS:
            os.environ.pop(name, None)

        sys.modules.pop(PATCH_MODULE_NAME, None)
        package = sys.modules.get("litellm_callbacks")
        if package is not None:
            package.__dict__.pop("chatgpt_anthropic_messages", None)

        cls.patch = importlib.import_module(PATCH_MODULE_NAME)

    @classmethod
    def tearDownClass(cls) -> None:
        restore_litellm_patch_state(cls.litellm_patch_state)
        for name, value in cls.env_state.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        cls.patch = None

    def test_non_claude_gateway_models_are_derived_from_config(self) -> None:
        config = load_config()

        self.assertEqual(
            self.patch._non_claude_model_names_from_config(config),
            ("claude-codex-gpt-5-5", "claude-codex-gpt-5-6"),
        )

    def test_all_non_claude_gateway_models_are_listed(self) -> None:
        config = {
            "model_list": [
                {
                    "model_name": "claude-opus-4-8",
                    "litellm_params": {"model": "anthropic/claude-opus-4-8"},
                },
                {
                    "model_name": "claude-codex-gpt-5-5",
                    "litellm_params": {"model": "chatgpt/gpt-5.5"},
                },
                {
                    "model_name": "claude-openai-gpt-5",
                    "litellm_params": {"model": "openai/gpt-5"},
                },
            ],
        }

        self.assertEqual(
            self.patch._non_claude_model_names_from_config(config),
            ("claude-codex-gpt-5-5", "claude-openai-gpt-5"),
        )

    def test_chatgpt_provider_uses_responses_route(self) -> None:
        from litellm.llms.anthropic.experimental_pass_through.messages import handler

        self.assertTrue(self.patch._enable_chatgpt_responses_route())
        self.assertIn("chatgpt", handler._RESPONSES_API_PROVIDERS)
        self.assertTrue(handler._should_route_to_responses_api("chatgpt"))

    def test_patch_initialization_fails_fast_when_a_patch_cannot_apply(self) -> None:
        original = self.patch._patch_responses_web_search_translation
        self.patch._patch_responses_web_search_translation = lambda: False
        try:
            with self.assertRaisesRegex(
                RuntimeError,
                "Responses web search translation",
            ):
                self.patch._enable_patches()
        finally:
            self.patch._patch_responses_web_search_translation = original
            self.patch._enable_patches()

    def test_domain_filter_lists_are_trimmed_and_compacted(self) -> None:
        self.assertEqual(
            self.patch._non_empty_string_list(
                [" docs.python.org ", "   ", "", "example.com", 42]
            ),
            ["docs.python.org", "example.com"],
        )

    def test_system_prompt_becomes_responses_instructions(self) -> None:
        from litellm.llms.anthropic.experimental_pass_through.responses_adapters.handler import (
            _build_responses_kwargs,
        )

        kwargs = _build_responses_kwargs(
            max_tokens=100,
            messages=[{"role": "user", "content": "hi"}],
            model="gpt-5.5",
            system="SYSTEM TEXT",
            stream=False,
            extra_kwargs={"custom_llm_provider": "chatgpt"},
        )

        self.assertEqual(kwargs["instructions"], "SYSTEM TEXT")
        self.assertFalse(
            any(
                isinstance(item, dict) and item.get("role") == "system"
                for item in kwargs["input"]
            )
        )

    def test_codex_request_enables_stateless_encrypted_reasoning_replay(self) -> None:
        data = {
            "model": "claude-codex-gpt-5-6",
            "messages": [{"role": "user", "content": "hi"}],
        }

        asyncio.run(
            self.patch.proxy_handler_instance.async_pre_call_hook(
                None,
                None,
                data,
                "anthropic_messages",
            )
        )

        self.assertEqual(data["include"], ["reasoning.encrypted_content"])
        self.assertIs(data["store"], False)

    def test_signed_gpt_thinking_replays_as_a_reasoning_item(self) -> None:
        from litellm.llms.anthropic.experimental_pass_through.responses_adapters.handler import (
            _build_responses_kwargs,
        )

        messages = [
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "thinking",
                        "thinking": "Keep the existing plan.",
                        "signature": "gpt#encrypted-turn-state",
                    },
                    {
                        "type": "tool_use",
                        "id": "call_123",
                        "name": "read_file",
                        "input": {"path": "README.md"},
                    },
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "call_123",
                        "content": "file contents",
                    }
                ],
            },
        ]

        kwargs = _build_responses_kwargs(
            max_tokens=100,
            messages=messages,
            model="gpt-5.6-sol",
            stream=False,
            extra_kwargs={"custom_llm_provider": "chatgpt"},
        )

        self.assertEqual(
            [item["type"] for item in kwargs["input"]],
            ["reasoning", "function_call", "function_call_output"],
        )
        self.assertEqual(
            kwargs["input"][0],
            {
                "type": "reasoning",
                "summary": [
                    {
                        "type": "summary_text",
                        "text": "Keep the existing plan.",
                    }
                ],
                "encrypted_content": "encrypted-turn-state",
            },
        )

    def test_non_gpt_thinking_signature_is_not_replayed_to_openai(self) -> None:
        from litellm.llms.anthropic.experimental_pass_through.responses_adapters.transformation import (
            LiteLLMAnthropicToResponsesAPIAdapter,
        )

        translated = (
            LiteLLMAnthropicToResponsesAPIAdapter()
            .translate_messages_to_responses_input(
                [
                    {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "thinking",
                                "thinking": "Native Claude thought",
                                "signature": "native-claude-signature",
                            }
                        ],
                    }
                ]
            )
        )

        self.assertEqual(translated[0]["type"], "message")
        self.assertFalse(any(item["type"] == "reasoning" for item in translated))

    def test_max_effort_maps_to_xhigh_for_codex_alias(self) -> None:
        data = {
            "model": "claude-codex-gpt-5-5",
            "output_config": {"effort": "max"},
        }

        asyncio.run(
            self.patch.proxy_handler_instance.async_pre_call_hook(
                None,
                None,
                data,
                "anthropic_messages",
            )
        )

        self.assertEqual(data["output_config"]["effort"], "xhigh")
        self.assertEqual(data["thinking"], {"type": "adaptive"})
        self.assertEqual(data["reasoning"], {"effort": "xhigh"})

    def test_max_effort_is_kept_native_for_gpt_5_6_alias(self) -> None:
        # GPT-5.6 supports reasoning.effort=max natively, so the gateway
        # must stop downgrading it to xhigh on the 5.6 alias.
        data = {
            "model": "claude-codex-gpt-5-6",
            "output_config": {"effort": "max"},
        }

        asyncio.run(
            self.patch.proxy_handler_instance.async_pre_call_hook(
                None,
                None,
                data,
                "anthropic_messages",
            )
        )

        self.assertEqual(data["output_config"]["effort"], "max")
        self.assertEqual(data["thinking"], {"type": "adaptive"})
        self.assertEqual(data["reasoning"], {"effort": "max"})

    def test_fast_header_sets_service_tier_fast_for_codex_alias(self) -> None:
        data = {
            "model": "claude-codex-gpt-5-5",
            "proxy_server_request": {
                "headers": {"x-claude-litellm-service-tier": "fast"}
            },
            "messages": [{"role": "user", "content": "hi"}],
        }

        asyncio.run(
            self.patch.proxy_handler_instance.async_pre_call_hook(
                None,
                None,
                data,
                "anthropic_messages",
            )
        )

        self.assertEqual(data["service_tier"], "fast")

    def test_fast_header_does_not_modify_claude_alias(self) -> None:
        data = {
            "model": "claude-opus-4-8",
            "proxy_server_request": {
                "headers": {"x-claude-litellm-service-tier": "fast"}
            },
            "messages": [{"role": "user", "content": "hi"}],
        }

        asyncio.run(
            self.patch.proxy_handler_instance.async_pre_call_hook(
                None,
                None,
                data,
                "anthropic_messages",
            )
        )

        self.assertNotIn("service_tier", data)

    def test_standard_codex_request_does_not_set_service_tier_fast(self) -> None:
        data = {
            "model": "claude-codex-gpt-5-5",
            "messages": [{"role": "user", "content": "hi"}],
        }

        asyncio.run(
            self.patch.proxy_handler_instance.async_pre_call_hook(
                None,
                None,
                data,
                "anthropic_messages",
            )
        )

        self.assertNotIn("service_tier", data)

    def test_config_default_medium_reaches_responses_kwargs(self) -> None:
        from litellm.llms.anthropic.experimental_pass_through.responses_adapters.handler import (
            _build_responses_kwargs,
        )

        kwargs = _build_responses_kwargs(
            max_tokens=100,
            messages=[{"role": "user", "content": "hi"}],
            model="gpt-5.5",
            stream=False,
            extra_kwargs={
                "custom_llm_provider": "chatgpt",
                "reasoning": {"effort": "medium"},
            },
        )

        self.assertEqual(kwargs["reasoning"], {"effort": "medium"})

    def test_session_effort_overrides_config_default(self) -> None:
        from litellm.llms.anthropic.experimental_pass_through.responses_adapters.handler import (
            _build_responses_kwargs,
        )

        kwargs = _build_responses_kwargs(
            max_tokens=100,
            messages=[{"role": "user", "content": "hi"}],
            model="gpt-5.5",
            output_config={"effort": "low"},
            thinking={"type": "adaptive"},
            stream=False,
            extra_kwargs={
                "custom_llm_provider": "chatgpt",
                "reasoning": {"effort": "medium"},
            },
        )

        self.assertEqual(kwargs["reasoning"], {"effort": "low"})

    def test_chatgpt_effort_normalizer_keeps_xhigh_and_maps_max(self) -> None:
        from litellm.llms.anthropic.experimental_pass_through.utils import (
            normalize_reasoning_effort_value,
        )

        self.patch._patch_chatgpt_effort_normalization()

        self.assertEqual(
            normalize_reasoning_effort_value("xhigh", "gpt-5.5", "chatgpt"),
            "xhigh",
        )
        self.assertEqual(
            normalize_reasoning_effort_value("max", "gpt-5.5", "chatgpt"),
            "xhigh",
        )
        self.assertEqual(
            normalize_reasoning_effort_value("minimal", "gpt-5.5", "chatgpt"),
            "low",
        )

    def test_claude_model_effort_is_not_modified_by_codex_hook(self) -> None:
        data = {
            "model": "claude-opus-4-8",
            "output_config": {"effort": "max"},
        }

        asyncio.run(
            self.patch.proxy_handler_instance.async_pre_call_hook(
                None,
                None,
                data,
                "anthropic_messages",
            )
        )

        self.assertEqual(data["output_config"], {"effort": "max"})
        self.assertIn("claude-codex-gpt-5-5", data["system"])

    def test_system_prompt_gets_non_claude_gateway_model_note(self) -> None:
        data = {
            "model": "claude-opus-4-8",
            "system": "BASE SYSTEM",
            "messages": [{"role": "user", "content": "hi"}],
        }

        asyncio.run(
            self.patch.proxy_handler_instance.async_pre_call_hook(
                None,
                None,
                data,
                "anthropic_messages",
            )
        )
        asyncio.run(
            self.patch.proxy_handler_instance.async_pre_call_hook(
                None,
                None,
                data,
                "anthropic_messages",
            )
        )

        self.assertTrue(data["system"].startswith("BASE SYSTEM\n\n"))
        self.assertIn("claude-codex-gpt-5-5", data["system"])
        self.assertIn("non-Claude model aliases", data["system"])
        self.assertIn("/model <alias>", data["system"])
        self.assertEqual(
            data["system"].count("<gateway_available_non_claude_models>"),
            1,
        )
        self.assertEqual(
            data["system"].count("</gateway_available_non_claude_models>"),
            1,
        )

    def test_block_system_prompt_gets_non_claude_gateway_model_note(self) -> None:
        data = {
            "model": "claude-opus-4-8",
            "system": [{"type": "text", "text": "BASE SYSTEM"}],
            "messages": [{"role": "user", "content": "hi"}],
        }

        asyncio.run(
            self.patch.proxy_handler_instance.async_pre_call_hook(
                None,
                None,
                data,
                "anthropic_messages",
            )
        )

        self.assertEqual(data["system"][0], {"type": "text", "text": "BASE SYSTEM"})
        self.assertEqual(data["system"][1]["type"], "text")
        self.assertIn("claude-codex-gpt-5-5", data["system"][1]["text"])

    def test_anthropic_messages_logging_accepts_responses_api_response(self) -> None:
        from litellm.litellm_core_utils.litellm_logging import Logging
        from litellm.types.llms.openai import ResponsesAPIResponse

        self.patch._patch_anthropic_messages_response_logging()
        response = ResponsesAPIResponse.model_construct(
            id="resp_test",
            object="response",
            created_at=0,
            model="gpt-5.5",
            output=[],
            parallel_tool_calls=False,
            tool_choice="auto",
            tools=[],
        )

        logged = Logging._handle_anthropic_messages_response_logging(
            object(),
            response,
        )

        self.assertIs(logged, response)

    def test_removed_codex_aliases_are_not_treated_as_chatgpt_aliases(self) -> None:
        self.assertFalse(
            self.patch._is_chatgpt_request(
                {"model": "claude-codex-gpt-5-5-medium"}
            )
        )
        self.assertFalse(
            self.patch._is_chatgpt_request({"model": "claude-chatgpt-gpt-5-4"})
        )

    def test_empty_thinking_blocks_are_removed_but_valid_blocks_remain(self) -> None:
        messages = [
            {"role": "user", "content": "hi"},
            {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": ""},
                    {"type": "text", "text": "ok"},
                ],
            },
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "thinking",
                        "thinking": "valid",
                        "signature": "sig",
                    }
                ],
            },
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "thinking",
                        "thinking": "",
                        "signature": "gpt#encrypted-without-summary",
                    }
                ],
            },
            {
                "role": "assistant",
                "content": [{"type": "redacted_thinking"}],
            },
        ]

        cleaned = self.patch._strip_empty_thinking_blocks_from_messages(messages)

        self.assertEqual(
            cleaned,
            [
                {"role": "user", "content": "hi"},
                {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "ok"}],
                },
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "thinking",
                            "thinking": "valid",
                            "signature": "sig",
                        }
                    ],
                },
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "thinking",
                            "thinking": "",
                            "signature": "gpt#encrypted-without-summary",
                        }
                    ],
                },
            ],
        )

    def test_empty_web_search_domain_filters_are_removed(self) -> None:
        data = {
            "model": "claude-opus-4-8",
            "tools": [
                {
                    "type": "web_search_20250305",
                    "name": "web_search",
                    "blocked_domains": [],
                    "allowed_domains": [],
                    "max_uses": 5,
                },
                {
                    "type": "web_search_20260318",
                    "name": "restricted_web_search",
                    "allowed_domains": [" docs.example.com ", "   "],
                    "blocked_domains": [" example.com ", "", "   "],
                },
                {
                    "type": "custom_tool",
                    "name": "custom",
                    "input_schema": {"type": "object"},
                    "blocked_domains": [],
                },
            ],
            "messages": [{"role": "user", "content": "hi"}],
        }

        asyncio.run(
            self.patch.proxy_handler_instance.async_pre_call_hook(
                None,
                None,
                data,
                "anthropic_messages",
            )
        )

        self.assertNotIn("blocked_domains", data["tools"][0])
        self.assertNotIn("allowed_domains", data["tools"][0])
        self.assertEqual(data["tools"][0]["max_uses"], 5)
        self.assertEqual(data["tools"][1]["blocked_domains"], ["example.com"])
        self.assertEqual(data["tools"][1]["allowed_domains"], ["docs.example.com"])
        self.assertEqual(data["tools"][2]["blocked_domains"], [])

    def test_anthropic_web_search_tool_maps_to_openai_web_search_for_codex(
        self,
    ) -> None:
        from litellm.llms.anthropic.experimental_pass_through.responses_adapters.handler import (
            _build_responses_kwargs,
        )

        data = {
            "model": "claude-codex-gpt-5-5",
            "tools": [
                {
                    "type": "web_search_20250305",
                    "name": "web_search",
                    "allowed_domains": [" docs.python.org ", "   "],
                    "blocked_domains": [" example.com ", ""],
                    "max_uses": 3,
                    "user_location": {
                        "type": "approximate",
                        "city": "Tokyo",
                        "country": "JP",
                        "ignored": "value",
                    },
                }
            ],
            "messages": [{"role": "user", "content": "hi"}],
        }

        asyncio.run(
            self.patch.proxy_handler_instance.async_pre_call_hook(
                None,
                None,
                data,
                "anthropic_messages",
            )
        )

        kwargs = _build_responses_kwargs(
            max_tokens=100,
            messages=data["messages"],
            model="gpt-5.5",
            tools=data["tools"],
            stream=False,
            extra_kwargs={
                "custom_llm_provider": "chatgpt",
                "include": data["include"],
            },
        )

        self.assertEqual(
            kwargs["tools"],
            [
                {
                    "type": "web_search",
                    "filters": {
                        "allowed_domains": ["docs.python.org"],
                        "blocked_domains": ["example.com"],
                    },
                    "user_location": {
                        "type": "approximate",
                        "city": "Tokyo",
                        "country": "JP",
                    },
                }
            ],
        )
        self.assertEqual(
            kwargs["include"],
            [
                "reasoning.encrypted_content",
                "web_search_call.action.sources",
            ],
        )
        self.assertNotIn("max_uses", kwargs["tools"][0])

    def test_forced_anthropic_web_search_tool_choice_maps_to_openai_web_search(
        self,
    ) -> None:
        from litellm.llms.anthropic.experimental_pass_through.responses_adapters.handler import (
            _build_responses_kwargs,
        )

        data = {
            "model": "claude-codex-gpt-5-5",
            "tools": [
                {
                    "type": "web_search_20250305",
                    "name": "web_search",
                }
            ],
            "tool_choice": {"type": "tool", "name": "web_search"},
            "messages": [{"role": "user", "content": "hi"}],
        }

        asyncio.run(
            self.patch.proxy_handler_instance.async_pre_call_hook(
                None,
                None,
                data,
                "anthropic_messages",
            )
        )

        kwargs = _build_responses_kwargs(
            max_tokens=100,
            messages=data["messages"],
            model="gpt-5.5",
            tools=data["tools"],
            tool_choice=data["tool_choice"],
            stream=False,
            extra_kwargs={
                "custom_llm_provider": "chatgpt",
                "include": data["include"],
            },
        )

        self.assertEqual(kwargs["tools"], [{"type": "web_search"}])
        self.assertEqual(kwargs["tool_choice"], {"type": "web_search"})

    def test_non_streaming_reasoning_is_captured_in_thinking_signature(self) -> None:
        from litellm.llms.anthropic.experimental_pass_through.responses_adapters.transformation import (
            LiteLLMAnthropicToResponsesAPIAdapter,
        )
        from litellm.types.llms.openai import ResponsesAPIResponse

        response = ResponsesAPIResponse.model_construct(
            id="resp_reasoning",
            object="response",
            created_at=0,
            model="gpt-5.6-sol",
            status="completed",
            output=[
                {
                    "type": "reasoning",
                    "id": "rs_123",
                    "summary": [
                        {
                            "type": "summary_text",
                            "text": "Keep the plan across the tool call.",
                        }
                    ],
                    "encrypted_content": "encrypted-turn-state",
                },
                {
                    "type": "function_call",
                    "id": "fc_123",
                    "call_id": "call_123",
                    "name": "read_file",
                    "arguments": '{"path":"README.md"}',
                },
            ],
            parallel_tool_calls=False,
            tool_choice="auto",
            tools=[],
        )

        translated = LiteLLMAnthropicToResponsesAPIAdapter().translate_response(
            response
        )

        self.assertEqual(
            translated["content"][0],
            {
                "type": "thinking",
                "thinking": "Keep the plan across the tool call.",
                "signature": "gpt#encrypted-turn-state",
            },
        )
        self.assertEqual(translated["content"][1]["type"], "tool_use")
        self.assertEqual(translated["content"][1]["id"], "call_123")

    def test_reasoning_without_summary_still_gets_a_replay_signature(self) -> None:
        base_response = {
            "id": "msg_reasoning",
            "type": "message",
            "role": "assistant",
            "model": "gpt-5.6-sol",
            "content": [],
            "usage": {},
            "stop_reason": "end_turn",
        }
        translated = self.patch._translate_responses_api_response_with_web_search(
            {
                "id": "resp_reasoning",
                "model": "gpt-5.6-sol",
                "status": "completed",
                "output": [
                    {
                        "type": "reasoning",
                        "id": "rs_123",
                        "summary": [],
                        "encrypted_content": "encrypted-without-summary",
                    }
                ],
            },
            base_response,
        )

        self.assertEqual(
            translated["content"],
            [
                {
                    "type": "thinking",
                    "thinking": "",
                    "signature": "gpt#encrypted-without-summary",
                }
            ],
        )

    def test_openai_web_search_response_maps_back_to_anthropic_blocks(self) -> None:
        from litellm.llms.anthropic.experimental_pass_through.responses_adapters.transformation import (
            LiteLLMAnthropicToResponsesAPIAdapter,
        )
        from litellm.types.llms.openai import ResponsesAPIResponse

        response = ResponsesAPIResponse.model_construct(
            id="resp_web_search",
            object="response",
            created_at=0,
            model="gpt-5.5",
            status="completed",
            output=[
                {
                    "type": "web_search_call",
                    "id": "ws_123",
                    "status": "completed",
                    "action": {
                        "type": "search",
                        "query": "Claude Shannon birth date",
                        "sources": [
                            {
                                "type": "url",
                                "url": "https://example.com/shannon",
                            }
                        ],
                    },
                },
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "Claude Shannon was born in 1916.",
                            "annotations": [
                                {
                                    "type": "url_citation",
                                    "url": "https://example.com/shannon",
                                    "title": "Claude Shannon",
                                    "start_index": 0,
                                    "end_index": 14,
                                }
                            ],
                        }
                    ],
                },
            ],
            parallel_tool_calls=False,
            tool_choice="auto",
            tools=[],
        )

        translated = LiteLLMAnthropicToResponsesAPIAdapter().translate_response(
            response
        )

        self.assertEqual(translated["content"][0]["type"], "server_tool_use")
        self.assertEqual(translated["content"][0]["id"], "ws_123")
        self.assertEqual(translated["content"][0]["name"], "web_search")
        self.assertEqual(
            translated["content"][0]["input"],
            {"query": "Claude Shannon birth date"},
        )
        self.assertEqual(translated["content"][1]["type"], "web_search_tool_result")
        self.assertEqual(translated["content"][1]["tool_use_id"], "ws_123")
        self.assertEqual(
            translated["content"][1]["content"][0],
            {
                "type": "web_search_result",
                "url": "https://example.com/shannon",
                "title": "Claude Shannon",
                "encrypted_content": "",
            },
        )
        self.assertEqual(translated["content"][2]["type"], "text")
        self.assertEqual(
            translated["content"][2]["citations"][0],
            {
                "type": "web_search_result_location",
                "url": "https://example.com/shannon",
                "title": "Claude Shannon",
                "encrypted_index": "",
                "cited_text": "Claude Shannon",
            },
        )
        self.assertEqual(
            translated["usage"]["server_tool_use"],
            {"web_search_requests": 1},
        )

    def test_streaming_reasoning_signature_round_trips_into_next_request(
        self,
    ) -> None:
        from litellm.llms.anthropic.experimental_pass_through.responses_adapters.streaming_iterator import (
            AnthropicResponsesStreamWrapper,
        )
        from litellm.llms.anthropic.experimental_pass_through.responses_adapters.transformation import (
            LiteLLMAnthropicToResponsesAPIAdapter,
        )

        wrapper = AnthropicResponsesStreamWrapper(
            responses_stream=[],
            model="gpt-5.6-sol",
        )
        wrapper._process_event(
            {
                "type": "response.output_item.added",
                "item": {"type": "reasoning", "id": "rs_123"},
            }
        )
        wrapper._process_event(
            {
                "type": "response.reasoning_summary_text.delta",
                "item_id": "rs_123",
                "delta": "Keep the plan.",
            }
        )
        wrapper._process_event(
            {
                "type": "response.output_item.done",
                "item": {
                    "type": "reasoning",
                    "id": "rs_123",
                    "encrypted_content": "encrypted-turn-state",
                },
            }
        )

        chunks = list(wrapper._chunk_queue)
        signature_delta = next(
            chunk["delta"]
            for chunk in chunks
            if chunk.get("type") == "content_block_delta"
            and chunk.get("delta", {}).get("type") == "signature_delta"
        )
        stop_index = next(
            index
            for index, chunk in enumerate(chunks)
            if chunk.get("type") == "content_block_stop"
        )
        signature_index = next(
            index
            for index, chunk in enumerate(chunks)
            if chunk.get("delta", {}).get("type") == "signature_delta"
        )

        self.assertEqual(
            signature_delta["signature"],
            "gpt#encrypted-turn-state",
        )
        self.assertLess(signature_index, stop_index)

        replayed = (
            LiteLLMAnthropicToResponsesAPIAdapter()
            .translate_messages_to_responses_input(
                [
                    {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "thinking",
                                "thinking": "Keep the plan.",
                                "signature": signature_delta["signature"],
                            }
                        ],
                    }
                ]
            )
        )
        self.assertEqual(replayed[0]["type"], "reasoning")
        self.assertEqual(
            replayed[0]["encrypted_content"],
            "encrypted-turn-state",
        )

    def test_streaming_openai_web_search_response_maps_to_anthropic_events(
        self,
    ) -> None:
        from litellm.llms.anthropic.experimental_pass_through.responses_adapters.streaming_iterator import (
            AnthropicResponsesStreamWrapper,
        )

        wrapper = AnthropicResponsesStreamWrapper(
            responses_stream=[],
            model="gpt-5.5",
        )
        wrapper._process_event(
            {
                "type": "response.output_item.done",
                "item": {
                    "type": "web_search_call",
                    "id": "ws_123",
                    "status": "completed",
                    "action": {
                        "type": "search",
                        "query": "Claude Shannon birth date",
                        "sources": [
                            {
                                "type": "url",
                                "url": "https://example.com/shannon",
                            }
                        ],
                    },
                },
            }
        )
        wrapper._process_event(
            {
                "type": "response.completed",
                "response": {
                    "status": "completed",
                    "output": [
                        {
                            "type": "web_search_call",
                            "id": "ws_123",
                            "status": "completed",
                        }
                    ],
                },
            }
        )

        chunks = list(wrapper._chunk_queue)

        self.assertEqual(
            chunks[0]["content_block"],
            {
                "type": "server_tool_use",
                "id": "ws_123",
                "name": "web_search",
                "input": {"query": "Claude Shannon birth date"},
            },
        )
        self.assertEqual(chunks[2]["content_block"]["type"], "web_search_tool_result")
        self.assertEqual(chunks[2]["content_block"]["tool_use_id"], "ws_123")
        message_delta = next(
            chunk for chunk in chunks if chunk.get("type") == "message_delta"
        )
        self.assertEqual(
            message_delta["usage"]["server_tool_use"],
            {"web_search_requests": 1},
        )


if __name__ == "__main__":
    unittest.main()
