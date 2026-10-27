"""Config flow for the Zmorph integration."""

from typing import Any

import probatio
from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
)

from .client import (
    ZMorphClient,
    ZMorphOffline,
    ZMorphProtocolError,
    identified_by_uuid,
    machine_unique_id,
    resolve_unique_id,
)
from .const import (
    CONF_MAX_PROBE_INTERVAL,
    CONF_MIN_PROBE_INTERVAL,
    DEFAULT_HOST,
    DEFAULT_MAX_PROBE_INTERVAL,
    DEFAULT_MIN_PROBE_INTERVAL,
    DEFAULT_PORT,
    DOMAIN,
    LOGGER,
    MAX_PROBE_INTERVAL_LIMIT,
    MIN_PROBE_INTERVAL_LIMIT,
)
from .coordinator import ZMorphConfigEntry
from .models import ZMorphIdentity

CONFIG_SCHEMA = probatio.Schema(
    {
        probatio.Required(CONF_HOST, default=DEFAULT_HOST): TextSelector(),
        probatio.Required(CONF_PORT, default=DEFAULT_PORT): NumberSelector(
            NumberSelectorConfig(min=1, max=65535, mode=NumberSelectorMode.BOX)
        ),
    }
)

# The probe ladder is behaviour, not connection, so it lives in the options.
OPTIONS_SCHEMA = probatio.Schema(
    {
        probatio.Required(
            CONF_MIN_PROBE_INTERVAL, default=DEFAULT_MIN_PROBE_INTERVAL
        ): NumberSelector(
            NumberSelectorConfig(
                min=MIN_PROBE_INTERVAL_LIMIT,
                max=MAX_PROBE_INTERVAL_LIMIT,
                step=5,
                unit_of_measurement="s",
                mode=NumberSelectorMode.BOX,
            )
        ),
        probatio.Required(
            CONF_MAX_PROBE_INTERVAL, default=DEFAULT_MAX_PROBE_INTERVAL
        ): NumberSelector(
            NumberSelectorConfig(
                min=MIN_PROBE_INTERVAL_LIMIT,
                max=MAX_PROBE_INTERVAL_LIMIT,
                step=5,
                unit_of_measurement="s",
                mode=NumberSelectorMode.BOX,
            )
        ),
    }
)


class ZMorphConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Zmorph."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a flow started by the user.

        The machine is off most of the day, so a missing answer does not stop the
        setup: it is recorded, and the integration starts probing. An answer that
        is not controller output does stop it, because that host is something
        else and no amount of probing will change that.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            host = str(user_input[CONF_HOST]).strip()
            port = int(user_input[CONF_PORT])

            identity, errors = await self._check_address(host, port)

            # A machine that is off cannot identify itself, so the address becomes
            # its id. That is recorded before the abort check, which needs an id.
            await self.async_set_unique_id(resolve_unique_id(identity, host, port))
            self._abort_if_unique_id_configured()

            if not errors:
                return self.async_create_entry(
                    title=host,
                    data={CONF_HOST: host, CONF_PORT: port},
                    options={
                        CONF_MIN_PROBE_INTERVAL: DEFAULT_MIN_PROBE_INTERVAL,
                        CONF_MAX_PROBE_INTERVAL: DEFAULT_MAX_PROBE_INTERVAL,
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(CONFIG_SCHEMA, user_input),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Move an existing entry to another address."""
        errors: dict[str, str] = {}
        entry = self._get_reconfigure_entry()

        if user_input is not None:
            host = str(user_input[CONF_HOST]).strip()
            port = int(user_input[CONF_PORT])
            identity, errors = await self._check_address(host, port)

            if not errors:
                current_id = entry.unique_id or machine_unique_id(
                    str(entry.data[CONF_HOST]), int(entry.data[CONF_PORT])
                )
                new_id = current_id

                if identity is not None:
                    candidate = resolve_unique_id(identity, host, port)
                    if identified_by_uuid(current_id) and candidate != current_id:
                        # The entry knows this machine by its firmware UUID, and the
                        # machine that answered carries a different one, or none at
                        # all. That is another device: taking it over would move
                        # every entity of the real machine to a different printer.
                        return self.async_abort(reason="unique_id_mismatch")
                    # An entry added while the machine was off is identified by its
                    # address. Now that a UUID is on the table, the entry keeps it.
                    new_id = candidate
                elif not identified_by_uuid(current_id):
                    # Nothing answered, so the address stays the id and moves with
                    # the entry the user just corrected.
                    new_id = resolve_unique_id(None, host, port)

                if new_id != current_id:
                    await self.async_set_unique_id(new_id)
                    self._abort_if_unique_id_configured()

                return self.async_update_reload_and_abort(
                    entry,
                    unique_id=new_id,
                    data_updates={CONF_HOST: host, CONF_PORT: port},
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                CONFIG_SCHEMA, {**entry.data, **(user_input or {})}
            ),
            errors=errors,
        )

    async def _check_address(
        self, host: str, port: int
    ) -> tuple[ZMorphIdentity | None, dict[str, str]]:
        """Ask an address whether a Zmorph lives there.

        Returns:
            (identity, errors): the identity the machine offered, or None when it
            did not answer, plus the form error to show when the address belongs
            to something that is not a controller.
        """
        client = ZMorphClient(async_get_clientsession(self.hass), host=host, port=port)

        try:
            await client.probe()
        except ZMorphOffline:
            # The machine is off more often than not: that is not a reason to
            # refuse the entry, and nothing here depends on the answer.
            LOGGER.debug("No answer from %s:%s during setup; adding anyway", host, port)
            return None, {}
        except ZMorphProtocolError:
            LOGGER.debug("%s:%s answered, but is not a Zmorph", host, port)
            return None, {"base": "not_a_zmorph"}

        return await client.fetch_identity(), {}

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ZMorphConfigEntry,
    ) -> ZMorphOptionsFlow:
        """Create the options flow of an entry."""
        return ZMorphOptionsFlow()


class ZMorphOptionsFlow(OptionsFlowWithReload):
    """Handle the probe ladder of one Zmorph entry.

    Home Assistant reloads the entry after the options change, so the new
    intervals take effect without a restart.
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the probe intervals."""
        errors: dict[str, str] = {}

        if user_input is not None:
            minimum = int(user_input[CONF_MIN_PROBE_INTERVAL])
            maximum = int(user_input[CONF_MAX_PROBE_INTERVAL])
            if maximum < minimum:
                errors[CONF_MAX_PROBE_INTERVAL] = "max_below_min"
            else:
                return self.async_create_entry(data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                OPTIONS_SCHEMA, {**self.config_entry.options, **(user_input or {})}
            ),
            errors=errors,
        )
