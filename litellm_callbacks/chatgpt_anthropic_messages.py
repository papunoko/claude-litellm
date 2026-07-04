"""Route LiteLLM's Anthropic-compatible messages endpoint to Responses for ChatGPT.

Claude Code talks to gateways through Anthropic `/v1/messages`, where system
instructions are a top-level `system` field. LiteLLM already has an Anthropic
Messages -> Responses adapter that maps that field to Responses `instructions`,
but LiteLLM 1.89.4 only enables the path for the `openai` provider. The official
`chatgpt/` provider is Responses-native too, so include it in that route.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Iterable

from litellm.integrations.custom_logger import CustomLogger


_CHATGPT_MODEL_NAMES = {"claude-codex-gpt-5-5"}
_CHATGPT_MODEL_PREFIXES = ("chatgpt/",)
_FAST_SERVICE_TIER_HEADER = "x-claude-litellm-service-tier"
_NON_CLAUDE_MODELS_ENV = "CLAUDE_LITELLM_NON_CLAUDE_MODELS"
_LITELLM_CONFIG_ENV = "CLAUDE_LITELLM_CONFIG"
_DEFAULT_CONFIG_FILENAMES = ("litellm_config.max-codex-subscriptions.yaml",)
_NON_CLAUDE_MODELS_SYSTEM_TAG = "gateway_available_non_claude_models"
_NON_CLAUDE_MODELS_SYSTEM_MARKER = f"<{_NON_CLAUDE_MODELS_SYSTEM_TAG}>"
_NON_CLAUDE_MODEL_NAMES_CACHE: tuple[str, ...] | None = None
_WEB_SEARCH_TOOL_PREFIX = "web_search_"
_WEB_SEARCH_DOMAIN_FILTER_KEYS = ("allowed_domains", "blocked_domains")
_OPENAI_WEB_SEARCH_SOURCES_INCLUDE = "web_search_call.action.sources"


def _enable_chatgpt_responses_route() -> bool:
    try:
        from litellm.llms.anthropic.experimental_pass_through.messages import (
            handler as messages_handler,
        )
    except ImportError:
        return False

    providers = getattr(messages_handler, "_RESPONSES_API_PROVIDERS", frozenset())
    if "chatgpt" not in providers:
        messages_handler._RESPONSES_API_PROVIDERS = frozenset(
            [*providers, "chatgpt"]
        )

    return "chatgpt" in messages_handler._RESPONSES_API_PROVIDERS


def _patch_chatgpt_effort_normalization() -> bool:
    try:
        from litellm.llms.anthropic.experimental_pass_through import utils
    except ImportError:
        return False

    if getattr(utils, "_claude_litellm_chatgpt_effort_patch", False):
        return True

    original = utils.normalize_reasoning_effort_value

    def normalize_reasoning_effort_value(
        effort: str,
        model: str,
        custom_llm_provider: str | None = None,
    ) -> str:
        model_name = model or ""
        provider = custom_llm_provider or ""
        if provider == "chatgpt" or model_name.startswith("chatgpt/"):
            if effort == "max":
                return "xhigh"
            if effort == "xhigh":
                return "xhigh"
            if effort == "minimal":
                return "low"
            return effort

        return original(
            effort,
            model,
            custom_llm_provider=custom_llm_provider,
        )

    utils.normalize_reasoning_effort_value = normalize_reasoning_effort_value
    utils._claude_litellm_chatgpt_effort_patch = True
    return True


def _patch_anthropic_messages_response_logging() -> bool:
    try:
        from litellm.litellm_core_utils import litellm_logging
        from litellm.types.llms.openai import ResponsesAPIResponse
    except ImportError:
        return False

    logging_cls = getattr(litellm_logging, "Logging", None)
    if logging_cls is None:
        return False

    if getattr(logging_cls, "_claude_litellm_chatgpt_logging_patch", False):
        return True

    original = getattr(logging_cls, "_handle_anthropic_messages_response_logging", None)
    if original is None:
        return False

    def _handle_anthropic_messages_response_logging(
        self: Any,
        result: Any,
    ) -> Any:
        if isinstance(result, ResponsesAPIResponse):
            return result

        return original(self, result)

    logging_cls._handle_anthropic_messages_response_logging = (
        _handle_anthropic_messages_response_logging
    )
    logging_cls._claude_litellm_chatgpt_logging_patch = True
    return True


def _is_anthropic_web_search_tool(tool: Any) -> bool:
    if not isinstance(tool, dict):
        return False

    tool_type = tool.get("type")
    return isinstance(tool_type, str) and tool_type.startswith(_WEB_SEARCH_TOOL_PREFIX)


def _non_empty_string_list(value: Any) -> list[str] | None:
    if not isinstance(value, list):
        return None

    items = [
        item.strip()
        for item in value
        if isinstance(item, str) and item.strip()
    ]
    return items or None


def _translate_anthropic_web_search_tool_to_openai(tool: Any) -> dict[str, Any] | None:
    if not _is_anthropic_web_search_tool(tool):
        return None

    openai_tool: dict[str, Any] = {"type": "web_search"}

    filters: dict[str, list[str]] = {}
    for key in _WEB_SEARCH_DOMAIN_FILTER_KEYS:
        values = _non_empty_string_list(tool.get(key))
        if values:
            filters[key] = values
    if filters:
        openai_tool["filters"] = filters

    user_location = tool.get("user_location")
    if isinstance(user_location, dict):
        location = {
            key: value
            for key, value in user_location.items()
            if key in {"type", "city", "region", "country", "timezone"}
            and value is not None
        }
        if location:
            openai_tool["user_location"] = location

    search_context_size = tool.get("search_context_size")
    if isinstance(search_context_size, str) and search_context_size:
        openai_tool["search_context_size"] = search_context_size

    return openai_tool


def _get_value(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def _response_output_items(response: Any) -> list[Any]:
    output = _get_value(response, "output", [])
    return output if isinstance(output, list) else []


def _response_item_type(item: Any) -> str:
    return str(_get_value(item, "type", "") or "")


def _response_item_id(item: Any) -> str:
    value = _get_value(item, "id")
    return str(value or "srvtoolu_openai_web_search")


def _action_to_dict(action: Any) -> dict[str, Any]:
    if isinstance(action, dict):
        return dict(action)

    data: dict[str, Any] = {}
    for key in ("type", "query", "queries", "url", "pattern", "sources"):
        value = getattr(action, key, None)
        if value is not None:
            data[key] = value
    return data


def _web_search_action_input(action: Any) -> dict[str, Any]:
    action_dict = _action_to_dict(action)
    action_type = action_dict.get("type")

    if action_type == "search":
        query = action_dict.get("query")
        if not isinstance(query, str) or not query:
            queries = action_dict.get("queries")
            if isinstance(queries, list):
                query = " ".join(str(item) for item in queries if item)
        return {"query": query or ""}

    if action_type == "open_page":
        return {"url": str(action_dict.get("url") or "")}

    if action_type == "find_in_page":
        return {
            "url": str(action_dict.get("url") or ""),
            "pattern": str(action_dict.get("pattern") or ""),
        }

    return {}


def _annotation_dict(annotation: Any) -> dict[str, Any]:
    if isinstance(annotation, dict):
        return dict(annotation)

    data: dict[str, Any] = {}
    for key in ("type", "url", "title", "start_index", "end_index"):
        value = getattr(annotation, key, None)
        if value is not None:
            data[key] = value
    return data


def _url_citation_data(annotation: Any) -> dict[str, Any] | None:
    annotation_data = _annotation_dict(annotation)
    if annotation_data.get("type") != "url_citation":
        return None

    nested = annotation_data.get("url_citation")
    if isinstance(nested, dict):
        merged = dict(nested)
        for key in ("url", "title", "start_index", "end_index"):
            if key in annotation_data and key not in merged:
                merged[key] = annotation_data[key]
        return merged

    return annotation_data


def _text_part_annotations(part: Any) -> list[Any]:
    annotations = _get_value(part, "annotations", [])
    return annotations if isinstance(annotations, list) else []


def _collect_url_titles_from_response(response: Any) -> dict[str, str]:
    titles: dict[str, str] = {}
    for item in _response_output_items(response):
        if _response_item_type(item) != "message":
            continue
        content = _get_value(item, "content", [])
        if not isinstance(content, list):
            continue
        for part in content:
            for annotation in _text_part_annotations(part):
                citation = _url_citation_data(annotation)
                if not citation:
                    continue
                url = citation.get("url")
                title = citation.get("title")
                if isinstance(url, str) and isinstance(title, str) and title:
                    titles[url] = title

    return titles


def _anthropic_citations_from_openai_annotations(
    text: str,
    annotations: Iterable[Any],
) -> list[dict[str, Any]]:
    citations: list[dict[str, Any]] = []
    for annotation in annotations:
        citation = _url_citation_data(annotation)
        if not citation:
            continue

        start = citation.get("start_index")
        end = citation.get("end_index")
        cited_text = ""
        if isinstance(start, int) and isinstance(end, int) and 0 <= start <= end:
            cited_text = text[start:end]

        citations.append(
            {
                "type": "web_search_result_location",
                "url": str(citation.get("url") or ""),
                "title": str(citation.get("title") or ""),
                "encrypted_index": "",
                "cited_text": cited_text,
            }
        )

    return citations


def _web_search_sources_from_action(action: Any) -> list[Any]:
    action_dict = _action_to_dict(action)
    sources = action_dict.get("sources")
    return sources if isinstance(sources, list) else []


def _web_search_tool_result_content(
    action: Any,
    url_titles: dict[str, str],
) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    for source in _web_search_sources_from_action(action):
        url = _get_value(source, "url")
        if not isinstance(url, str) or not url or url in seen_urls:
            continue
        seen_urls.add(url)
        content.append(
            {
                "type": "web_search_result",
                "url": url,
                "title": url_titles.get(url, ""),
                "encrypted_content": "",
            }
        )

    return content


def _web_search_blocks_from_responses_item(
    item: Any,
    url_titles: dict[str, str],
) -> list[dict[str, Any]]:
    action = _get_value(item, "action", {})
    tool_use_id = _response_item_id(item)
    return [
        {
            "type": "server_tool_use",
            "id": tool_use_id,
            "name": "web_search",
            "input": _web_search_action_input(action),
        },
        {
            "type": "web_search_tool_result",
            "tool_use_id": tool_use_id,
            "content": _web_search_tool_result_content(action, url_titles),
        },
    ]


def _translate_responses_api_response_with_web_search(
    response: Any,
    base_response: Any,
) -> Any:
    output_items = _response_output_items(response)
    has_web_search = any(
        _response_item_type(item) == "web_search_call" for item in output_items
    )
    has_url_citations = bool(_collect_url_titles_from_response(response))
    if not has_web_search and not has_url_citations:
        return base_response

    content: list[dict[str, Any]] = []
    stop_reason = _get_value(base_response, "stop_reason", "end_turn")
    url_titles = _collect_url_titles_from_response(response)
    web_search_requests = 0

    for item in output_items:
        item_type = _response_item_type(item)
        if item_type == "reasoning":
            summaries = _get_value(item, "summary", [])
            if isinstance(summaries, list):
                for summary in summaries:
                    text = _get_value(summary, "text", "")
                    if text:
                        content.append(
                            {
                                "type": "thinking",
                                "thinking": str(text),
                                "signature": None,
                            }
                        )
        elif item_type == "message":
            message_content = _get_value(item, "content", [])
            if not isinstance(message_content, list):
                continue
            for part in message_content:
                if _response_item_type(part) != "output_text":
                    continue
                text = str(_get_value(part, "text", "") or "")
                block: dict[str, Any] = {"type": "text", "text": text}
                citations = _anthropic_citations_from_openai_annotations(
                    text,
                    _text_part_annotations(part),
                )
                if citations:
                    block["citations"] = citations
                content.append(block)
        elif item_type == "function_call":
            import json

            arguments = _get_value(item, "arguments", "{}")
            try:
                input_data = json.loads(arguments) if arguments else {}
            except (json.JSONDecodeError, TypeError):
                input_data = {}
            content.append(
                {
                    "type": "tool_use",
                    "id": _get_value(item, "call_id")
                    or _get_value(item, "id", ""),
                    "name": _get_value(item, "name", ""),
                    "input": input_data,
                }
            )
            stop_reason = "tool_use"
        elif item_type == "web_search_call":
            content.extend(_web_search_blocks_from_responses_item(item, url_titles))
            web_search_requests += 1

    if _get_value(response, "status") == "incomplete":
        stop_reason = "max_tokens"

    if isinstance(base_response, dict):
        translated = dict(base_response)
        usage = dict(translated.get("usage") or {})
    else:
        translated = {
            "id": _get_value(base_response, "id", _get_value(response, "id", "")),
            "type": "message",
            "role": "assistant",
            "model": _get_value(base_response, "model", _get_value(response, "model")),
            "stop_sequence": None,
        }
        usage = dict(_get_value(base_response, "usage", {}) or {})

    if web_search_requests:
        server_tool_use = dict(usage.get("server_tool_use") or {})
        server_tool_use["web_search_requests"] = (
            int(server_tool_use.get("web_search_requests") or 0)
            + web_search_requests
        )
        usage["server_tool_use"] = server_tool_use

    translated["content"] = content
    translated["usage"] = usage
    translated["stop_reason"] = stop_reason
    return translated


def _stream_event_type(event: Any) -> str:
    return str(_get_value(event, "type", "") or "")


def _stream_event_item(event: Any) -> Any:
    return _get_value(event, "item")


def _append_stream_content_block(wrapper: Any, content_block: dict[str, Any]) -> None:
    block_index = wrapper._next_block_index()
    wrapper._chunk_queue.append(
        {
            "type": "content_block_start",
            "index": block_index,
            "content_block": content_block,
        }
    )
    wrapper._chunk_queue.append({"type": "content_block_stop", "index": block_index})


def _patch_responses_web_search_translation() -> bool:
    try:
        from litellm.llms.anthropic.experimental_pass_through.responses_adapters import (
            streaming_iterator,
            transformation,
        )
    except ImportError:
        return False

    adapter_cls = getattr(
        transformation,
        "LiteLLMAnthropicToResponsesAPIAdapter",
        None,
    )
    wrapper_cls = getattr(streaming_iterator, "AnthropicResponsesStreamWrapper", None)
    if adapter_cls is None or wrapper_cls is None:
        return False

    if not getattr(adapter_cls, "_claude_litellm_web_search_patch", False):
        original_translate_tools = adapter_cls.translate_tools_to_responses_api
        original_translate_tool_choice = adapter_cls.translate_tool_choice_to_responses_api
        original_translate_response = adapter_cls.translate_response

        def translate_tools_to_responses_api(
            self: Any,
            tools: list[Any],
        ) -> list[dict[str, Any]]:
            translated: list[dict[str, Any]] = []
            for tool in tools:
                openai_web_search = _translate_anthropic_web_search_tool_to_openai(
                    tool
                )
                if openai_web_search is not None:
                    translated.append(openai_web_search)
                    continue
                translated.extend(original_translate_tools(self, [tool]))
            return translated

        def translate_tool_choice_to_responses_api(tool_choice: Any) -> Any:
            if isinstance(tool_choice, dict):
                choice_type = str(tool_choice.get("type") or "")
                choice_name = str(tool_choice.get("name") or "")
                if (
                    choice_type.startswith(_WEB_SEARCH_TOOL_PREFIX)
                    or (
                        choice_type == "tool"
                        and (
                            choice_name == "web_search"
                            or choice_name.startswith(_WEB_SEARCH_TOOL_PREFIX)
                        )
                    )
                ):
                    return {"type": "web_search"}

            return original_translate_tool_choice(tool_choice)

        def translate_response(self: Any, response: Any) -> Any:
            base_response = original_translate_response(self, response)
            return _translate_responses_api_response_with_web_search(
                response,
                base_response,
            )

        adapter_cls.translate_tools_to_responses_api = translate_tools_to_responses_api
        adapter_cls.translate_tool_choice_to_responses_api = staticmethod(
            translate_tool_choice_to_responses_api
        )
        adapter_cls.translate_response = translate_response
        adapter_cls._claude_litellm_web_search_patch = True

    if not getattr(wrapper_cls, "_claude_litellm_web_search_patch", False):
        original_process_event = wrapper_cls._process_event

        def _process_event(self: Any, event: Any) -> None:
            event_type = _stream_event_type(event)
            item = _stream_event_item(event)
            item_type = _response_item_type(item)

            if (
                event_type == "response.output_item.added"
                and item_type == "web_search_call"
            ):
                return

            if (
                event_type == "response.output_item.done"
                and item_type == "web_search_call"
            ):
                url_titles: dict[str, str] = {}
                for block in _web_search_blocks_from_responses_item(item, url_titles):
                    _append_stream_content_block(self, block)
                return

            original_process_event(self, event)

            if event_type not in (
                "response.completed",
                "response.failed",
                "response.incomplete",
            ):
                return

            response_obj = _get_value(event, "response")
            web_search_requests = sum(
                1
                for output_item in _response_output_items(response_obj)
                if _response_item_type(output_item) == "web_search_call"
            )
            if not web_search_requests:
                return

            for queued in reversed(self._chunk_queue):
                if isinstance(queued, dict) and queued.get("type") == "message_delta":
                    usage = dict(queued.get("usage") or {})
                    server_tool_use = dict(usage.get("server_tool_use") or {})
                    server_tool_use["web_search_requests"] = (
                        int(server_tool_use.get("web_search_requests") or 0)
                        + web_search_requests
                    )
                    usage["server_tool_use"] = server_tool_use
                    queued["usage"] = usage
                    break

        wrapper_cls._process_event = _process_event
        wrapper_cls._claude_litellm_web_search_patch = True

    return True


def _enable_patches() -> bool:
    failed = [
        name
        for name, enable in (
            ("chatgpt Responses route", _enable_chatgpt_responses_route),
            ("chatgpt effort normalization", _patch_chatgpt_effort_normalization),
            (
                "Anthropic messages response logging",
                _patch_anthropic_messages_response_logging,
            ),
            (
                "Responses web search translation",
                _patch_responses_web_search_translation,
            ),
        )
        if not enable()
    ]
    if failed:
        raise RuntimeError(
            "Failed to enable LiteLLM compatibility patch(es): "
            + ", ".join(failed)
        )

    return True


def _is_empty_thinking_block(block: Any) -> bool:
    if not isinstance(block, dict):
        return False

    block_type = block.get("type")
    if block_type == "thinking":
        thinking = block.get("thinking")
        return not isinstance(thinking, str) or thinking == ""

    if block_type == "redacted_thinking":
        data = block.get("data")
        return not isinstance(data, str) or data == ""

    return False


def _split_model_names(value: str) -> tuple[str, ...]:
    names = [
        part.strip()
        for part in value.replace(";", ",").replace("\n", ",").split(",")
        if part.strip()
    ]
    return tuple(dict.fromkeys(names))


def _is_non_claude_upstream_model(model: Any, custom_llm_provider: Any = None) -> bool:
    provider = str(custom_llm_provider or "").strip().lower()
    model_name = str(model or "").strip()

    if provider:
        return provider != "anthropic"

    if "/" in model_name:
        return model_name.split("/", 1)[0].lower() != "anthropic"

    return bool(model_name) and not model_name.startswith("claude-")


def _non_claude_model_names_from_config(config: dict[str, Any]) -> tuple[str, ...]:
    names: list[str] = []

    model_list = config.get("model_list")
    if not isinstance(model_list, list):
        return ()

    for entry in model_list:
        if not isinstance(entry, dict):
            continue

        model_name = str(entry.get("model_name") or "").strip()
        litellm_params = entry.get("litellm_params")
        if not model_name or not isinstance(litellm_params, dict):
            continue

        if _is_non_claude_upstream_model(
            litellm_params.get("model"),
            litellm_params.get("custom_llm_provider"),
        ):
            names.append(model_name)

    return tuple(dict.fromkeys(names))


def _read_non_claude_model_names_from_config(path: Path) -> tuple[str, ...]:
    try:
        import yaml
    except ImportError:
        return ()

    try:
        config = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return ()

    if not isinstance(config, dict):
        return ()

    return _non_claude_model_names_from_config(config)


def _candidate_config_paths() -> tuple[Path, ...]:
    paths: list[Path] = []
    env_path = os.getenv(_LITELLM_CONFIG_ENV)
    if env_path:
        paths.append(Path(env_path))

    cwd = Path.cwd()
    repo_root = Path(__file__).resolve().parents[1]
    for filename in _DEFAULT_CONFIG_FILENAMES:
        paths.append(cwd / filename)
        paths.append(repo_root / filename)

    resolved: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path.resolve()) if path.exists() else str(path)
        if key in seen:
            continue
        seen.add(key)
        resolved.append(path)

    return tuple(resolved)


def _discover_non_claude_gateway_model_names() -> tuple[str, ...]:
    env_models = os.getenv(_NON_CLAUDE_MODELS_ENV)
    if env_models:
        return _split_model_names(env_models)

    for path in _candidate_config_paths():
        if not path.exists():
            continue

        models = _read_non_claude_model_names_from_config(path)
        if models:
            return models

    return tuple(sorted(_CHATGPT_MODEL_NAMES))


def _get_non_claude_gateway_model_names() -> tuple[str, ...]:
    global _NON_CLAUDE_MODEL_NAMES_CACHE

    if _NON_CLAUDE_MODEL_NAMES_CACHE is None:
        _NON_CLAUDE_MODEL_NAMES_CACHE = _discover_non_claude_gateway_model_names()

    return _NON_CLAUDE_MODEL_NAMES_CACHE


def _build_non_claude_models_system_prompt(model_names: Iterable[str]) -> str:
    models = "\n".join(f"- {name}" for name in model_names)
    return (
        f"{_NON_CLAUDE_MODELS_SYSTEM_MARKER}\n"
        "The LiteLLM gateway also exposes the following non-Claude model "
        f"aliases:\n{models}\n\n"
        "When relevant, you may tell the user they can switch to one of these "
        "aliases with `/model <alias>`. Continue using the current model "
        "unless the user explicitly switches.\n"
        f"</{_NON_CLAUDE_MODELS_SYSTEM_TAG}>"
    )


def _system_prompt_has_non_claude_models_note(system: Any) -> bool:
    if isinstance(system, str):
        return _NON_CLAUDE_MODELS_SYSTEM_MARKER in system

    if isinstance(system, list):
        for block in system:
            if isinstance(block, str) and _NON_CLAUDE_MODELS_SYSTEM_MARKER in block:
                return True
            if (
                isinstance(block, dict)
                and _NON_CLAUDE_MODELS_SYSTEM_MARKER in str(block.get("text") or "")
            ):
                return True

    return False


def _append_non_claude_models_note_to_system(data: dict[str, Any]) -> None:
    model_names = _get_non_claude_gateway_model_names()
    if not model_names:
        return

    system = data.get("system")
    if _system_prompt_has_non_claude_models_note(system):
        return

    note = _build_non_claude_models_system_prompt(model_names)
    if isinstance(system, str):
        data["system"] = f"{system.rstrip()}\n\n{note}" if system else note
    elif isinstance(system, list):
        data["system"] = [*system, {"type": "text", "text": note}]
    elif system is None:
        data["system"] = note


def _strip_empty_thinking_blocks_from_messages(messages: Iterable[Any]) -> list[Any]:
    cleaned: list[Any] = []

    for message in messages:
        if not isinstance(message, dict):
            cleaned.append(message)
            continue

        content = message.get("content")
        if not isinstance(content, list):
            cleaned.append(message)
            continue

        filtered_content = [
            block for block in content if not _is_empty_thinking_block(block)
        ]
        if not filtered_content:
            continue

        if len(filtered_content) == len(content):
            cleaned.append(message)
        else:
            cleaned.append({**message, "content": filtered_content})

    return cleaned


def _strip_empty_web_search_domain_filters_from_tools(tools: Iterable[Any]) -> list[Any]:
    cleaned: list[Any] = []

    for tool in tools:
        if not isinstance(tool, dict):
            cleaned.append(tool)
            continue

        tool_type = str(tool.get("type") or "")
        if not tool_type.startswith(_WEB_SEARCH_TOOL_PREFIX):
            cleaned.append(tool)
            continue

        filtered_tool = dict(tool)
        for key in _WEB_SEARCH_DOMAIN_FILTER_KEYS:
            value = filtered_tool.get(key)
            if isinstance(value, list):
                values = _non_empty_string_list(value)
                if values:
                    filtered_tool[key] = values
                else:
                    filtered_tool.pop(key, None)

        cleaned.append(filtered_tool)

    return cleaned


def _sanitize_anthropic_messages_request(data: dict) -> None:
    messages = data.get("messages")
    if isinstance(messages, list):
        data["messages"] = _strip_empty_thinking_blocks_from_messages(messages)

    tools = data.get("tools")
    if isinstance(tools, list):
        data["tools"] = _strip_empty_web_search_domain_filters_from_tools(tools)


def _request_uses_anthropic_web_search(data: dict[str, Any]) -> bool:
    tools = data.get("tools")
    return isinstance(tools, list) and any(
        _is_anthropic_web_search_tool(tool) for tool in tools
    )


def _ensure_openai_web_search_sources_included(
    data: dict[str, Any],
    model: str | None = None,
) -> None:
    if not _is_chatgpt_request(data, model=model):
        return
    if not _request_uses_anthropic_web_search(data):
        return

    include = data.get("include")
    if include is None:
        data["include"] = [_OPENAI_WEB_SEARCH_SOURCES_INCLUDE]
        return

    if isinstance(include, list):
        if _OPENAI_WEB_SEARCH_SOURCES_INCLUDE not in include:
            data["include"] = [*include, _OPENAI_WEB_SEARCH_SOURCES_INCLUDE]
        return

    data["include"] = [include, _OPENAI_WEB_SEARCH_SOURCES_INCLUDE]


def _is_chatgpt_request(data: dict, model: str | None = None) -> bool:
    model_name = str(data.get("model") or model or "")
    if model_name in _CHATGPT_MODEL_NAMES:
        return True
    if model_name.startswith(_CHATGPT_MODEL_PREFIXES):
        return True

    litellm_params = data.get("litellm_params")
    if isinstance(litellm_params, dict):
        return litellm_params.get("custom_llm_provider") == "chatgpt"

    return False


def _normalize_chatgpt_effort(effort: Any) -> str | None:
    if not isinstance(effort, str):
        return None

    normalized = effort.lower()
    if normalized == "max":
        return "xhigh"
    if normalized == "minimal":
        return "low"
    if normalized in {"low", "medium", "high", "xhigh", "none"}:
        return normalized

    return None


def _extract_effort(data: dict) -> str | None:
    output_config = data.get("output_config")
    if isinstance(output_config, dict):
        effort = _normalize_chatgpt_effort(output_config.get("effort"))
        if effort:
            return effort

    reasoning = data.get("reasoning")
    if isinstance(reasoning, dict):
        effort = _normalize_chatgpt_effort(reasoning.get("effort"))
        if effort:
            return effort

    return None


def _apply_chatgpt_effort(data: dict, model: str | None = None) -> None:
    if not _is_chatgpt_request(data, model=model):
        return

    effort = _extract_effort(data)
    if not effort:
        return

    output_config = data.get("output_config")
    if not isinstance(output_config, dict):
        output_config = {}
    data["output_config"] = {**output_config, "effort": effort}

    thinking = data.get("thinking")
    if not isinstance(thinking, dict) or thinking.get("type") in (None, "disabled"):
        data["thinking"] = {"type": "adaptive"}

    reasoning = data.get("reasoning")
    if not isinstance(reasoning, dict):
        reasoning = {}
    data["reasoning"] = {**reasoning, "effort": effort}


def _header_value(headers: Any, name: str) -> str | None:
    if not isinstance(headers, dict):
        return None

    lower_name = name.lower()
    for key, value in headers.items():
        if str(key).lower() == lower_name:
            return str(value)

    return None


def _request_header_value(data: dict, name: str) -> str | None:
    proxy_request = data.get("proxy_server_request")
    if isinstance(proxy_request, dict):
        for key in ("headers", "request_headers"):
            value = _header_value(proxy_request.get(key), name)
            if value is not None:
                return value

    for key in ("headers", "request_headers", "extra_headers"):
        value = _header_value(data.get(key), name)
        if value is not None:
            return value

    return None


def _is_fast_chatgpt_request(data: dict) -> bool:
    service_tier = data.get("service_tier")
    if isinstance(service_tier, str) and service_tier.lower() == "fast":
        return True

    header_value = _request_header_value(data, _FAST_SERVICE_TIER_HEADER)
    return isinstance(header_value, str) and header_value.lower() == "fast"


def _apply_chatgpt_fast_mode(data: dict, model: str | None = None) -> None:
    if not _is_chatgpt_request(data, model=model):
        return

    if not _is_fast_chatgpt_request(data):
        return

    data["service_tier"] = "fast"


class ChatGPTAnthropicMessagesPatch(CustomLogger):
    def __init__(self) -> None:
        self.enabled = _enable_patches()
        print(
            "[litellm] enabled Anthropic /v1/messages -> Responses routing "
            "and effort mapping for chatgpt provider"
        )

    async def async_pre_request_hook(
        self,
        model: str,
        messages: list[dict],
        kwargs: dict,
    ) -> dict:
        _enable_patches()
        _ensure_openai_web_search_sources_included(kwargs, model=model)
        _apply_chatgpt_effort(kwargs, model=model)
        _apply_chatgpt_fast_mode(kwargs, model=model)
        return kwargs

    async def async_pre_call_hook(
        self,
        user_api_key_dict: Any,
        cache: Any,
        data: dict,
        call_type: str,
    ) -> dict:
        _enable_patches()
        _sanitize_anthropic_messages_request(data)
        _ensure_openai_web_search_sources_included(data)
        if call_type == "anthropic_messages":
            _append_non_claude_models_note_to_system(data)
        _apply_chatgpt_effort(data)
        _apply_chatgpt_fast_mode(data)
        return data


proxy_handler_instance = ChatGPTAnthropicMessagesPatch()
