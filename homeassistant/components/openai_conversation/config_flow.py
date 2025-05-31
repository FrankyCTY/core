"""Config flow for OpenAI Conversation integration."""

from __future__ import annotations

from collections.abc import Mapping
import json
import logging
from types import MappingProxyType
from typing import Any

import openai
import voluptuous as vol
from voluptuous_openapi import convert

from homeassistant.components.zone import ENTITY_ID_HOME
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import (
    ATTR_LATITUDE,
    ATTR_LONGITUDE,
    CONF_API_KEY,
    CONF_LLM_HASS_API,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm
from homeassistant.helpers.httpx_client import get_async_client
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TemplateSelector,
)
from homeassistant.helpers.typing import VolDictType

from .const import (
    CONF_CHAT_MODEL,
    CONF_MAX_TOKENS,
    CONF_PROMPT,
    CONF_REASONING_EFFORT,
    CONF_RECOMMENDED,
    CONF_TEMPERATURE,
    CONF_TOP_P,
    CONF_WEB_SEARCH,
    CONF_WEB_SEARCH_CITY,
    CONF_WEB_SEARCH_CONTEXT_SIZE,
    CONF_WEB_SEARCH_COUNTRY,
    CONF_WEB_SEARCH_REGION,
    CONF_WEB_SEARCH_TIMEZONE,
    CONF_WEB_SEARCH_USER_LOCATION,
    DOMAIN,
    RECOMMENDED_CHAT_MODEL,
    RECOMMENDED_MAX_TOKENS,
    RECOMMENDED_REASONING_EFFORT,
    RECOMMENDED_TEMPERATURE,
    RECOMMENDED_TOP_P,
    RECOMMENDED_WEB_SEARCH,
    RECOMMENDED_WEB_SEARCH_CONTEXT_SIZE,
    RECOMMENDED_WEB_SEARCH_USER_LOCATION,
    UNSUPPORTED_MODELS,
    WEB_SEARCH_MODELS,
)

_LOGGER = logging.getLogger(__name__)

# LLM: Schema for initial user setup requiring only the OpenAI API key
# This minimal schema keeps the initial setup simple while allowing advanced configuration later
STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_API_KEY): str,
    }
)

# LLM: Default configuration options applied when a new integration entry is created
# These recommended settings provide sensible defaults for most users while enabling core features
RECOMMENDED_OPTIONS = {
    CONF_RECOMMENDED: True,
    CONF_LLM_HASS_API: llm.LLM_API_ASSIST,
    CONF_PROMPT: llm.DEFAULT_INSTRUCTIONS_PROMPT,
}


# LLM: Validates OpenAI API credentials by attempting to connect and list available models
# Purpose: Ensures the provided API key can authenticate with OpenAI before saving the configuration
async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> None:
    """Validate the user input allows us to connect.

    Data has the keys from STEP_USER_DATA_SCHEMA with values provided by the user.
    """
    # LLM: Create OpenAI client with user's API key using Home Assistant's HTTP client for proxy support
    client = openai.AsyncOpenAI(
        api_key=data[CONF_API_KEY], http_client=get_async_client(hass)
    )
    # LLM: Test API connectivity by listing models with a 10-second timeout
    # This is a lightweight operation that validates both authentication and network connectivity
    # FIXME: There seems to bug where the openai_sdk models.list is not throwing error on invalid API key.
    return await hass.async_add_executor_job(client.with_options(timeout=10.0).models.list)


class OpenAIConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for OpenAI Conversation."""

    VERSION = 1

    # LLM: Handles the initial setup step where users provide their OpenAI API key
    # This collects and validates API credentials, creates integration entry on success
    # It returns form on first visit, validates and creates entry on submission
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        # LLM: On first visit, display the API key input form to the user
        # USERNOTE: This gather user input to create the config entry.
        if user_input is None:
            return self.async_show_form(
                step_id="user", data_schema=STEP_USER_DATA_SCHEMA
            )

        errors: dict[str, str] = {}

        try:
            await validate_input(self.hass, user_input)
        except openai.APIConnectionError:
            errors["base"] = "cannot_connect"
        except openai.AuthenticationError:
            errors["base"] = "invalid_auth"
        except Exception:
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"
        else:
            # LLM: Validation successful - create the integration entry with recommended default options
            # This completes the initial setup and makes the integration available for use
            return self.async_create_entry(
                title="ChatGPT",
                data=user_input,
                options=RECOMMENDED_OPTIONS,
            )

        # USERNOTE: If there is exception, this shows form again with error messages for user to retry with correct API key
        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    # USERNOTE: This configure the option flow, and allow the config entry's options to be edited.
    # USERNOTE: An Options Flow is a user interface-driven setup wizard (flow) that allows editing runtime configuration options of an integration after it has been installed.
    # https://developers.home-assistant.io/docs/config_entries_options_flow_handler
    @staticmethod
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> OptionsFlow:
        """Create the options flow."""
        return OpenAIOptionsFlow(config_entry)


# USERNOTE: This configure the option flow, and allow the config entry's options to be edited.
# USERNOTE: An Options Flow is a user interface-driven setup wizard (flow) that allows editing runtime configuration options of an integration after it has been installed.
# https://developers.home-assistant.io/docs/config_entries_options_flow_handler
class OpenAIOptionsFlow(OptionsFlow):
    """OpenAI config flow options handler."""

    # LLM: Initializes options flow with state tracking for dynamic UI rendering
    # Purpose: Sets up flow state and remembers current recommended mode setting
    # Role in Scope: Constructor that prepares the flow for handling user configuration changes
    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize options flow."""
        # LLM: Track the recommended setting to detect UI mode changes
        # This enables toggling between simple and advanced configuration interfaces
        self.last_rendered_recommended = config_entry.options.get(
            CONF_RECOMMENDED, False
        )

    # LLM: Main options flow step that handles both simple and advanced configuration modes
    # Purpose: Presents appropriate UI based on recommended mode and validates configuration changes
    # Role in Scope: Central options management with validation for model compatibility and feature support
    # Caveats: Re-renders form when switching modes, validates web search model support, handles location data
    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        options: dict[str, Any] | MappingProxyType[str, Any] = self.config_entry.options
        errors: dict[str, str] = {}

        if user_input is not None:
            # USERNOTE: Check if user changed the recommended mode toggle
            # - If no change: Validate option form and display error if violated, then create entry with latest entry options.
            # - If recommend option has changed since last render:  Option "recommend" defaults to true, but if user confiures it to false in the option flow, we want to re-render option form with more advanced data schema.
            if user_input[CONF_RECOMMENDED] == self.last_rendered_recommended:
                # LLM: Same mode - validate the configuration and save if valid
                
                # USERNOTE: Remove LLM_HASS_API if not provided to avoid storing empty values
                if not user_input.get(CONF_LLM_HASS_API):
                    user_input.pop(CONF_LLM_HASS_API, None)
                
                # USERNOTE: Validate that selected model is supported by the integration
                if user_input.get(CONF_CHAT_MODEL) in UNSUPPORTED_MODELS:
                    errors[CONF_CHAT_MODEL] = "model_not_supported"

                # USERNOTE: Validate web search configuration compatibility
                if user_input.get(CONF_WEB_SEARCH):
                    # USERNOTE: Check if selected model supports web search functionality
                    if (
                        user_input.get(CONF_CHAT_MODEL, RECOMMENDED_CHAT_MODEL)
                        not in WEB_SEARCH_MODELS
                    ):
                        errors[CONF_WEB_SEARCH] = "web_search_not_supported"
                    # USERNOTE: If user location is enabled, fetch location data for better search results
                    elif user_input.get(CONF_WEB_SEARCH_USER_LOCATION):
                        # USERNOTE: Use OpenAI to determine approximate location from Home Assistant coordinates
                        user_input.update(await self.get_location_data())

                # USERNOTE: Save entry options configuration if no validation errors occurred
                if not errors:
                    # USERNOTE: Upsert config entry
                    return self.async_create_entry(title="", data=user_input)
            else:
                # USERNOTE: Get user toggled recommended mode to prepare to re-render with new mode settings.
                # - Re-rendering allows showing/hiding advanced options based on user preference.
                self.last_rendered_recommended = user_input[CONF_RECOMMENDED]

                # USERNOTE: Ensure core settings have sensible defaults, and not broken due to expected user request options.
                # - This default options will then be used to configure the data schema for the option form, and the new form will
                # be re-rendered on the client side with the new data schema.
                options = {
                    CONF_RECOMMENDED: user_input[CONF_RECOMMENDED],
                    CONF_PROMPT: user_input.get(
                        CONF_PROMPT, llm.DEFAULT_INSTRUCTIONS_PROMPT
                    ),
                    CONF_LLM_HASS_API: user_input.get(CONF_LLM_HASS_API),
                }

        # USERNOTE: Prepare configure form's data schema, and configure UI selectors such as use of template, select, bool.
        # - Based on the config entry's option "CONF_RECOMMENDED", prepare simplified/advanced configure schema.
        schema = openai_config_option_schema(self.hass, options)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(schema),
            errors=errors,
        )

    # USERNOTE: Determines user's approximate location for enhanced web search results
    # - Uses OpenAI to convert Home Assistant coordinates into city/region names for search context
    # - Enhances web search accuracy by providing location-aware search results
    async def get_location_data(self) -> dict[str, str]:
        """Get approximate location data of the user."""
        location_data: dict[str, str] = {}
        
        # USERNOTE: Get user home location.
        # - "zone.home" is a built-in Zone entity representing user home location
        zone_home = self.hass.states.get(ENTITY_ID_HOME)
        if zone_home is not None:
            # USERNOTE: Create OpenAI client to perform coordinate-to-location conversion Get user home location.
            client = openai.AsyncOpenAI(
                api_key=self.config_entry.data[CONF_API_KEY],
                http_client=get_async_client(self.hass),
            )
            
            # USERNOTE: Define schema for structured location output from OpenAI
            # This ensures we get consistent city and region information
            location_schema = vol.Schema(
                {
                    vol.Optional(
                        CONF_WEB_SEARCH_CITY,
                        description="Free text input for the city, e.g. `San Francisco`",
                    ): str,
                    vol.Optional(
                        CONF_WEB_SEARCH_REGION,
                        description="Free text input for the region, e.g. `California`",
                    ): str,
                }
            )
            
            # USERNOTE: Query OpenAI to convert coordinates to human-readable location
            # This provides context for web searches without exposing exact coordinates
            response = await client.responses.create(
                model=RECOMMENDED_CHAT_MODEL,
                input=[
                    {
                        "role": "system",
                        "content": "Where are the following coordinates located: "
                        f"({zone_home.attributes[ATTR_LATITUDE]},"
                        f" {zone_home.attributes[ATTR_LONGITUDE]})?",
                    }
                ],
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "approximate_location",
                        "description": "Approximate location data of the user "
                        "for refined web search results",
                        "schema": convert(location_schema),
                        "strict": False,
                    }
                },
                store=False,
            )
            
            # USERNOTE: Parse and validate the OpenAI response using our schema
            location_data = location_schema(json.loads(response.output_text) or {})

        # USERNOTE: Add additional location context from Home Assistant configuration
        # - Country & timezone
        if self.hass.config.country:
            location_data[CONF_WEB_SEARCH_COUNTRY] = self.hass.config.country
        location_data[CONF_WEB_SEARCH_TIMEZONE] = self.hass.config.time_zone

        _LOGGER.debug("Location data: %s", location_data)

        return location_data


# USERNOTE: Prepare configure form's data schema, and configure UI selectors such as use of template, select, bool.
# - Based on the config entry's option "CONF_RECOMMENDED", prepare simplified/advanced configure schema.
def openai_config_option_schema(
    hass: HomeAssistant,
    options: Mapping[str, Any],
) -> VolDictType:
    """Return a schema for OpenAI completion options."""
    # USERNOTE: Build list of available Home Assistant LLM APIs for user selection
    # - Currently only support "Assist API"
    hass_apis: list[SelectOptionDict] = [
        SelectOptionDict(
            label=api.name,
            value=api.id,
        )
        for api in llm.async_get_apis(hass)
    ]
    
    # USERNOTE: Ensure the suggested LLM apis is in LIST
    # Example: "assist" -> ["assist"]
    if (suggested_llm_apis := options.get(CONF_LLM_HASS_API)) and isinstance(
        suggested_llm_apis, str
    ):
        suggested_llm_apis = [suggested_llm_apis]
    
    # USERNOTE: Prepare data schema for the configure option flow
    schema: VolDictType = {
        vol.Optional(
            CONF_PROMPT,
            description={
                "suggested_value": options.get(
                    CONF_PROMPT, llm.DEFAULT_INSTRUCTIONS_PROMPT
                )
            },
        ): TemplateSelector(),
        vol.Optional(
            CONF_LLM_HASS_API,
            description={"suggested_value": suggested_llm_apis},
        ): SelectSelector(SelectSelectorConfig(options=hass_apis, multiple=True)),
        vol.Required(
            CONF_RECOMMENDED, default=options.get(CONF_RECOMMENDED, False)
        ): bool,
    }

    # USERNOTE: Return simplified schema if user prefers recommended settings
    # - Based on CONF_RECOMMENDED flag, default to TRUE.
    # USERNOTE: Can be configured in config entry via YAML config to update "recommend" to false.
    if options.get(CONF_RECOMMENDED):
        return schema

    # USERNOTE: Add advanced configuration options for power users that do not want to use recommended schema.
    # - These settings provide fine-grained control over OpenAI model behavior
    schema.update(
        {
            vol.Optional(
                CONF_CHAT_MODEL,
                description={"suggested_value": options.get(CONF_CHAT_MODEL)},
                default=RECOMMENDED_CHAT_MODEL,
            ): str,
            vol.Optional(
                CONF_MAX_TOKENS,
                description={"suggested_value": options.get(CONF_MAX_TOKENS)},
                default=RECOMMENDED_MAX_TOKENS,
            ): int,
            vol.Optional(
                CONF_TOP_P,
                description={"suggested_value": options.get(CONF_TOP_P)},
                default=RECOMMENDED_TOP_P,
            ): NumberSelector(NumberSelectorConfig(min=0, max=1, step=0.05)),
            vol.Optional(
                CONF_TEMPERATURE,
                description={"suggested_value": options.get(CONF_TEMPERATURE)},
                default=RECOMMENDED_TEMPERATURE,
            ): NumberSelector(NumberSelectorConfig(min=0, max=2, step=0.05)),
            vol.Optional(
                CONF_REASONING_EFFORT,
                description={"suggested_value": options.get(CONF_REASONING_EFFORT)},
                default=RECOMMENDED_REASONING_EFFORT,
            ): SelectSelector(
                SelectSelectorConfig(
                    options=["low", "medium", "high"],
                    translation_key=CONF_REASONING_EFFORT,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional(
                CONF_WEB_SEARCH,
                description={"suggested_value": options.get(CONF_WEB_SEARCH)},
                default=RECOMMENDED_WEB_SEARCH,
            ): bool,
            vol.Optional(
                CONF_WEB_SEARCH_CONTEXT_SIZE,
                description={
                    "suggested_value": options.get(CONF_WEB_SEARCH_CONTEXT_SIZE)
                },
                default=RECOMMENDED_WEB_SEARCH_CONTEXT_SIZE,
            ): SelectSelector(
                SelectSelectorConfig(
                    options=["low", "medium", "high"],
                    translation_key=CONF_WEB_SEARCH_CONTEXT_SIZE,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional(
                CONF_WEB_SEARCH_USER_LOCATION,
                description={
                    "suggested_value": options.get(CONF_WEB_SEARCH_USER_LOCATION)
                },
                default=RECOMMENDED_WEB_SEARCH_USER_LOCATION,
            ): bool,
        }
    )
    return schema
