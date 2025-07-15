## Description
In development, we start up HASS instance by running `hass -c config`, which will invoke the `homeassistant.__main__.py:main()`.


## Call flows

`homeassistant.__main__.py:main() -> runner.run() -> setup_and_run_hass() -> bootstrap.async_setup_hass() -> loader.async_setup(), bootstrap.async_from_config_dict() e.g.`


### When does components being set up?

It is done as part of the `bootstrap.async_from_config_dict()`, we do `asyncio.gather()` for a list of  `setup.async_setup_component()` eager tasks to set up all core components eagerly.

#### How is the integration loaded for set up?
IT is loaded from `loader.py:Integration:async_get_component()` which is the entity and facade of integrationS itself.

## Files Description

### loader.py

