"""The OpenAI Conversation integration."""

from __future__ import annotations

from pathlib import Path
from types import MappingProxyType

import openai
from openai.types.images_response import ImagesResponse
from openai.types.responses import (
    EasyInputMessageParam,
    Response,
    ResponseInputMessageContentListParam,
    ResponseInputParam,
    ResponseInputTextParam,
)
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import CONF_API_KEY, Platform
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import (
    ConfigEntryNotReady,
    HomeAssistantError,
    ServiceValidationError,
)
from homeassistant.helpers import (
    config_validation as cv,
    device_registry as dr,
    entity_registry as er,
    selector,
)
from homeassistant.helpers.httpx_client import get_async_client
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_CHAT_MODEL,
    CONF_FILENAMES,
    CONF_MAX_TOKENS,
    CONF_PROMPT,
    CONF_REASONING_EFFORT,
    CONF_TEMPERATURE,
    CONF_TOP_P,
    DEFAULT_AI_TASK_NAME,
    DEFAULT_NAME,
    DOMAIN,
    LOGGER,
    RECOMMENDED_AI_TASK_OPTIONS,
    RECOMMENDED_CHAT_MODEL,
    RECOMMENDED_MAX_TOKENS,
    RECOMMENDED_REASONING_EFFORT,
    RECOMMENDED_TEMPERATURE,
    RECOMMENDED_TOP_P,
)
from .entity import async_prepare_files_for_prompt

SERVICE_GENERATE_IMAGE = "generate_image"
SERVICE_GENERATE_CONTENT = "generate_content"

PLATFORMS = (Platform.AI_TASK, Platform.CONVERSATION)
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

# LLM: Type alias for config entries that store OpenAI client in runtime_data
# This provides type safety for accessing the authenticated OpenAI client
type OpenAIConfigEntry = ConfigEntry[openai.AsyncClient]


# LLM: Function for asynchronous setup of the integration.
# USERNOTE: Invoked in setup.py's _async_setup_component() function.
# Integration ROLE:
# - Provides programmatic (non-conversational) API access for generating content and images using OpenAI's APIs, independent of the conversation agent.
# - Provides direct access to DALL-E capabilities outside conversation flow.
# Features:
# - Registers `generate_content` service (ChatGPT-like interaction with optional files)
# - Registers `generate_image` service (DALL·E 3 image generation)
# - Enforces valid config entry for authentication and runtime context
# - Performs file validation, multimodal support, and safe executor-based I/O
# Caveats:
# - Requires an existing config entry (configured via UI)
# - Does NOT rely on YAML setup (even though it uses `async_setup`)
# - Complements `async_setup_entry` and is used in tandem with config entry lifecycle
async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up OpenAI Conversation."""
    await async_migrate_integration(hass)

    # USERNOTE: Service handler for DALL-E image generation
    # - Allows users to generate images via Home Assistant services
    async def render_image(call: ServiceCall) -> ServiceResponse:
        """Render an image with dall-e."""
        # USERNOTE: Extract the config entry ID from the request data.
        entry_id = call.data["config_entry"]
        entry = hass.config_entries.async_get_entry(entry_id)

        # LLM: Ensure the config entry exists and belongs to this domain
        # This prevents cross-domain service calls and ensures proper client access
        if entry is None or entry.domain != DOMAIN:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_config_entry",
                translation_placeholders={"config_entry": entry_id},
            )

        # LLM: Retrieve the authenticated OpenAI client from config entry runtime data
        client: openai.AsyncClient = entry.runtime_data

        try:
            # LLM: Call OpenAI DALL-E API with user-specified parameters
            # Uses DALL-E 3 model with fixed settings for simplicity
            response: ImagesResponse = await client.images.generate(
                model="dall-e-3",
                prompt=call.data[CONF_PROMPT],
                size=call.data["size"],
                quality=call.data["quality"],
                style=call.data["style"],
                response_format="url",
                n=1,
            )
        except openai.OpenAIError as err:
            raise HomeAssistantError(f"Error generating image: {err}") from err

        # LLM: Validate that OpenAI returned a usable image URL
        # API can succeed but return empty data in edge cases
        if not response.data or not response.data[0].url:
            raise HomeAssistantError("No image returned")

        # USERNOTE: Exclude the Base64-encoded representation of the image binary
        # Because we have configured to have openai return the url only anyway.
        return response.data[0].model_dump(exclude={"b64_json"})

    # LLM: Service handler for ChatGPT content generation
    # Provides direct access to GPT models with file attachment support
    # Handles multi-modal inputs, validates file permissions and types
    async def send_prompt(call: ServiceCall) -> ServiceResponse:
        """Send a prompt to ChatGPT and return the response."""
        # USERNOTE: The user is expected to select a config entry from the UI
        # Or provide a config entry ID (e.g., "c7bcd133ef104fa4b0b61e51aaad01e9") when calling the service via YAML, REST API, or automation.
        entry_id = call.data["config_entry"]
        entry = hass.config_entries.async_get_entry(entry_id)

        # USERNOTE: Return service validation error if the config entry is invalid.
        if entry is None or entry.domain != DOMAIN:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_config_entry",
                translation_placeholders={"config_entry": entry_id},
            )

        # Get first conversation subentry for options
        conversation_subentry = next(
            (
                sub
                for sub in entry.subentries.values()
                if sub.subentry_type == "conversation"
            ),
            None,
        )
        if not conversation_subentry:
            raise ServiceValidationError("No conversation configuration found")

        model: str = conversation_subentry.data.get(
            CONF_CHAT_MODEL, RECOMMENDED_CHAT_MODEL
        )
        client: openai.AsyncClient = entry.runtime_data

        # USERNOTE: Extract user prompt from the service call request payload.
        content: ResponseInputMessageContentListParam = [
            ResponseInputTextParam(type="input_text", text=call.data[CONF_PROMPT])
        ]

        if filenames := call.data.get(CONF_FILENAMES):
            for filename in filenames:
                if not hass.config.is_allowed_path(filename):
                    raise HomeAssistantError(
                        f"Cannot read `{filename}`, no access to path; "
                        "`allowlist_external_dirs` may need to be adjusted in "
                        "`configuration.yaml`"
                    )

            content.extend(
                await async_prepare_files_for_prompt(
                    hass, [Path(filename) for filename in filenames]
                )
            )

        # USERNOTE: Form a user message for openAI
        messages: ResponseInputParam = [
            EasyInputMessageParam(type="message", role="user", content=content)
        ]

        model_args = {
            "model": model,
            "input": messages,
            "max_output_tokens": conversation_subentry.data.get(
                CONF_MAX_TOKENS, RECOMMENDED_MAX_TOKENS
            ),
            "top_p": conversation_subentry.data.get(CONF_TOP_P, RECOMMENDED_TOP_P),
            "temperature": conversation_subentry.data.get(
                CONF_TEMPERATURE, RECOMMENDED_TEMPERATURE
            ),
            "user": call.context.user_id,
            "store": False,
        }

        if model.startswith("o"):
            model_args["reasoning"] = {
                "effort": conversation_subentry.data.get(
                    CONF_REASONING_EFFORT, RECOMMENDED_REASONING_EFFORT
                )
            }

        try:
            response: Response = await client.responses.create(**model_args)

        except openai.OpenAIError as err:
            raise HomeAssistantError(f"Error generating content: {err}") from err
        except FileNotFoundError as err:
            raise HomeAssistantError(f"Error generating content: {err}") from err

        return {"text": response.output_text}

    # USERNOTE: Register the content generation service with Home Assistant
    # Enables programmatic access to GPT models with multi-modal support
    # Service name: openai_conversation.generate_content
    # USERNOTE: Example YAML config:
    # service: openai_conversation.generate_content
    # data:
    #   config_entry: <entry_id>
    #   prompt: "Explain how a rocket engine works."
    #   filenames:
    #     - /config/docs/rocket_specs.pdf
    hass.services.async_register(
        DOMAIN,
        SERVICE_GENERATE_CONTENT,
        # USERNOTE: Handler function
        send_prompt,
        # USERNOTE: Schema to validate the service call data.
        schema=vol.Schema(
            {
                vol.Required("config_entry"): selector.ConfigEntrySelector(
                    {
                        "integration": DOMAIN,
                    }
                ),
                vol.Required(CONF_PROMPT): cv.string,
                # USERNOTE: Filenames list is normalized using cv.ensure_list.
                vol.Optional(CONF_FILENAMES, default=[]): vol.All(
                    cv.ensure_list, [cv.string]
                ),
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )

    # USERNOTE: Register the image generation service with Home Assistant
    # Provides direct access to DALL-E capabilities outside conversation flow
    # USERNOTE: Example YAML config:
    # service: openai_conversation.generate_image
    # data:
    #   config_entry: <entry_id>
    #   prompt: "A futuristic city at sunset"
    #   size: "1024x1792"
    #   quality: "hd"
    #   style: "vivid"
    hass.services.async_register(
        DOMAIN,
        SERVICE_GENERATE_IMAGE,
        render_image,
        schema=vol.Schema(
            {
                vol.Required("config_entry"): selector.ConfigEntrySelector(
                    {
                        "integration": DOMAIN,
                    }
                ),
                vol.Required(CONF_PROMPT): cv.string,
                vol.Optional("size", default="1024x1024"): vol.In(
                    ("1024x1024", "1024x1792", "1792x1024")
                ),
                vol.Optional("quality", default="standard"): vol.In(("standard", "hd")),
                vol.Optional("style", default="vivid"): vol.In(("vivid", "natural")),
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )

    return True


# LLM: Config entry setup function - the main entry point for modern integrations
# Purpose: Initializes OpenAI client, validates credentials, and sets up platforms
async def async_setup_entry(hass: HomeAssistant, entry: OpenAIConfigEntry) -> bool:
    """Set up OpenAI Conversation from a config entry."""
    # LLM: Create authenticated OpenAI client using stored API key
    # Uses Home Assistant's HTTP client for consistent networking behavior
    client = openai.AsyncOpenAI(
        # USERNOTE: Expected to be the openai api key from data dict of the config entry.
        api_key=entry.data[CONF_API_KEY],
        http_client=get_async_client(hass),
    )

    # Cache current platform data which gets added to each request (caching done by library)
    # USERNOTE: OpenAI client lazily builds headers on first request, this eargly starts building the headers and prevents delays when we actually make the first request, which would then be cached using `@lru_cache(maxsize=None)` internally.
    # USERNOTE: Use executor as it could be a CPU bound blocking operation:
    # - Fetching OS/environment-level details
    # - Possibly disk I/O for user-agent templates
    _ = await hass.async_add_executor_job(client.platform_headers)

    try:
        # LLM: Validate API credentials by attempting to list available models
        # Uses short timeout to fail fast on connectivity or auth issues
        await hass.async_add_executor_job(client.with_options(timeout=10.0).models.list)
    except openai.AuthenticationError as err:
        # LLM: Log auth errors but don't raise - allows retry during reconfigure
        LOGGER.error("Invalid API key: %s", err)
        return False
    except openai.OpenAIError as err:
        # LLM: Temporary failures should trigger config entry retry mechanism
        raise ConfigEntryNotReady(err) from err

    # LLM: Store authenticated client in runtime data for platform access
    # This makes the client available to conversation entities and services
    # USERNOTE: Purpose:
    # - Prevents repeated re-initialization of expensive objects like API clients.
    # - Ensures service handlers and platforms can access the same initialized resources.
    entry.runtime_data = client

    # USERNOTE: - Load platform modules into DATA_COMPONENTS (components) in memory cache
    # USERNOTE: - Ensure the platform's root integrations (e.g. conversation) are loaded into DATA_INTEGRATIONS cache.
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(async_update_options))

    return True


# LLM: Config entry unload function for clean integration shutdown to properly tears down platforms and cleans up resources.
# USERNOTE: Must mirror the setup process to avoid orphaned entities
# USERNOTE: Ensures graceful integration lifecycle management
async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload OpenAI."""
    # LLM: Unload all platforms that were set up during entry setup
    # This removes the conversation entity and cleans up registrations
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_update_options(hass: HomeAssistant, entry: OpenAIConfigEntry) -> None:
    """Update options."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_migrate_integration(hass: HomeAssistant) -> None:
    """Migrate integration entry structure."""

    entries = hass.config_entries.async_entries(DOMAIN)
    if not any(entry.version == 1 for entry in entries):
        return

    api_keys_entries: dict[str, ConfigEntry] = {}
    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)

    for entry in entries:
        use_existing = False
        subentry = ConfigSubentry(
            data=entry.options,
            subentry_type="conversation",
            title=entry.title,
            unique_id=None,
        )
        if entry.data[CONF_API_KEY] not in api_keys_entries:
            use_existing = True
            api_keys_entries[entry.data[CONF_API_KEY]] = entry

        parent_entry = api_keys_entries[entry.data[CONF_API_KEY]]

        hass.config_entries.async_add_subentry(parent_entry, subentry)
        conversation_entity = entity_registry.async_get_entity_id(
            "conversation",
            DOMAIN,
            entry.entry_id,
        )
        if conversation_entity is not None:
            entity_registry.async_update_entity(
                conversation_entity,
                config_entry_id=parent_entry.entry_id,
                config_subentry_id=subentry.subentry_id,
                new_unique_id=subentry.subentry_id,
            )

        device = device_registry.async_get_device(
            identifiers={(DOMAIN, entry.entry_id)}
        )
        if device is not None:
            device_registry.async_update_device(
                device.id,
                new_identifiers={(DOMAIN, subentry.subentry_id)},
                add_config_subentry_id=subentry.subentry_id,
                add_config_entry_id=parent_entry.entry_id,
            )
            if parent_entry.entry_id != entry.entry_id:
                device_registry.async_update_device(
                    device.id,
                    remove_config_entry_id=entry.entry_id,
                )
            else:
                device_registry.async_update_device(
                    device.id,
                    remove_config_entry_id=entry.entry_id,
                    remove_config_subentry_id=None,
                )

        if not use_existing:
            await hass.config_entries.async_remove(entry.entry_id)
        else:
            hass.config_entries.async_update_entry(
                entry,
                title=DEFAULT_NAME,
                options={},
                version=2,
                minor_version=2,
            )


async def async_migrate_entry(hass: HomeAssistant, entry: OpenAIConfigEntry) -> bool:
    """Migrate entry."""
    LOGGER.debug("Migrating from version %s:%s", entry.version, entry.minor_version)

    if entry.version > 2:
        # This means the user has downgraded from a future version
        return False

    if entry.version == 2 and entry.minor_version == 1:
        # Correct broken device migration in Home Assistant Core 2025.7.0b0-2025.7.0b1
        device_registry = dr.async_get(hass)
        for device in dr.async_entries_for_config_entry(
            device_registry, entry.entry_id
        ):
            device_registry.async_update_device(
                device.id,
                remove_config_entry_id=entry.entry_id,
                remove_config_subentry_id=None,
            )

        hass.config_entries.async_update_entry(entry, minor_version=2)

    if entry.version == 2 and entry.minor_version == 2:
        hass.config_entries.async_add_subentry(
            entry,
            ConfigSubentry(
                data=MappingProxyType(RECOMMENDED_AI_TASK_OPTIONS),
                subentry_type="ai_task_data",
                title=DEFAULT_AI_TASK_NAME,
                unique_id=None,
            ),
        )
        hass.config_entries.async_update_entry(entry, minor_version=3)

    LOGGER.debug(
        "Migration to version %s:%s successful", entry.version, entry.minor_version
    )

    return True
