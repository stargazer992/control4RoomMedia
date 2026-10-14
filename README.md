Control4 integration extension for my media room

Code from: https://github.com/kdkavanagh/home-assistant-core/tree/dev/homeassistant/components/control4

## Fork notes

Fork maintained by stargazer992.

- **1.4.3 / 1.4.4**: replaced the deprecated `via_device` / `async_get_device` device-registry calls (removed in Home Assistant 2027.8.0), which had stopped the light and media_player entities loading.
- **1.5.0**: optional per-room **bass, treble and balance** sliders for a Triad AMS 24x24 audio matrix. The AMS has its own TCP protocol (port 52000), separate from the Control4 director. Edit `TRIAD_HOST` and `TRIAD_OUTPUTS` in `custom_components/control4/const.py` (amp output number to room name); leave `TRIAD_HOST` empty to turn the sliders off. Values are read back from the amp at startup and every 5 minutes.
