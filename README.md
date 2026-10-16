Control4 integration extension for my media room

Code from: https://github.com/kdkavanagh/home-assistant-core/tree/dev/homeassistant/components/control4

## Fork notes

Fork maintained by stargazer992.

- **1.4.3 / 1.4.4**: replaced the deprecated `via_device` / `async_get_device` device-registry calls (removed in Home Assistant 2027.8.0), which had stopped the light and media_player entities loading.
- **1.4.5**: same loading fix as 1.4.4, with the optional Triad AMS slider code (1.5.0) removed. Lights and room media players only.
- **1.4.6**: fixed the Options dialog (`config_entry` can no longer be set in the options flow's `__init__` on current Home Assistant).
