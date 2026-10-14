"""Constants for the Control4 integration."""

DOMAIN = "control4"

DEFAULT_SCAN_INTERVAL = 5
MIN_SCAN_INTERVAL = 1

CONF_ACCOUNT = "account"
CONF_DIRECTOR = "director"
CONF_DIRECTOR_SW_VERSION = "director_sw_version"
CONF_DIRECTOR_MODEL = "director_model"
CONF_DIRECTOR_ALL_ITEMS = "director_all_items"
CONF_UI_CONFIGURATION = "ui_configuration"
CONF_CONTROLLER_UNIQUE_ID = "controller_unique_id"

CONF_CONFIG_LISTENER = "config_listener"

CONTROL4_ENTITY_TYPE = 7

# ---------------------------------------------------------------------------
# Triad AMS 24x24 audio matrix - per-output bass / treble / balance (optional)
# ---------------------------------------------------------------------------
# The AMS answers a plain TCP protocol on its own port, separate from the
# Control4 director. Leave TRIAD_HOST empty to disable the Triad sliders.
TRIAD_HOST = "192.168.104.98"
TRIAD_PORT = 52000
TRIAD_CONNECT_TIMEOUT = 3.0  # seconds to open the TCP connection
TRIAD_REPLY_TIMEOUT = 2.0  # seconds to wait for each reply
TRIAD_POLL_INTERVAL = 300  # seconds between read-backs of all mapped outputs

# Amp output (zero-based wire byte; byte 0 is "Out[1]" on the amp) -> room name.
# Found by nudging each room's volume and seeing which output moved. Outputs
# that are not listed get no sliders.
TRIAD_OUTPUTS = {
    0: "Living Room",
    1: "Master Bedroom",
    2: "Laundry",
    3: "Her Bathroom",
    4: "Kitchen",
    5: "Dining",
    6: "Family Room",
    7: "Patio",
    8: "Pool",
    9: "Bar",
}
