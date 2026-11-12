"""Constants for the ViCare Extras integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "vicare_extras"
VICARE_DOMAIN: Final = "vicare"

# --- Sensors -----------------------------------------------------------------
# How often the cached payload of the built-in integration is looked at.
# Looking at the cache is a plain attribute read and never causes an API call.
#
# Deliberately not 60 seconds: the built-in integration refreshes every 60
# seconds per gateway and its cache is empty while the request is running. Two
# timers with the same period keep their phase, so a look that falls into that
# gap once would fall into it every time. With 55 seconds the phase moves on
# and (while a request takes under 5 seconds) at most one look in twelve can
# meet the gap. A missed look only means the previous snapshot is kept.
UPDATE_INTERVAL_SECONDS: Final = 55
# A snapshot is reused for this long while the built-in integration has no
# cached payload (it empties its cache for the duration of each refresh).
MAX_SNAPSHOT_AGE_SECONDS: Final = 900
# Message lists exposed as sensor attributes are capped to keep states small.
MESSAGE_LIST_LIMIT: Final = 25

DEVICE_TYPE_HEATING: Final = "heating"

FEATURE_CONSUMPTION_DHW: Final = "heating.power.consumption.dhw"
FEATURE_CONSUMPTION_HEATING: Final = "heating.power.consumption.heating"
FEATURE_CONSUMPTION_TOTAL: Final = "heating.power.consumption.total"
FEATURE_PRODUCTION_DHW: Final = "heating.heat.production.summary.dhw"
FEATURE_PRODUCTION_HEATING: Final = "heating.heat.production.summary.heating"
FEATURE_MESSAGES_STATUS: Final = "device.messages.status.raw"
FEATURE_MESSAGES_INFO: Final = "device.messages.info.raw"
FEATURE_MESSAGES_SERVICE: Final = "device.messages.service.raw"

WATCHED_FEATURES: Final = frozenset(
    {
        FEATURE_CONSUMPTION_DHW,
        FEATURE_CONSUMPTION_HEATING,
        FEATURE_CONSUMPTION_TOTAL,
        FEATURE_PRODUCTION_DHW,
        FEATURE_PRODUCTION_HEATING,
        FEATURE_MESSAGES_STATUS,
        FEATURE_MESSAGES_INFO,
        FEATURE_MESSAGES_SERVICE,
    }
)

# --- Event history -----------------------------------------------------------
# Paths are relative to PyViCare's API_BASE_URL (https://.../iot/v2).
# The first one is the documented endpoint, the second one (hyphenated) is an
# older spelling that is only tried when the first one answers "not found".
EVENT_HISTORY_PATHS: Final = (
    "/eventhistory/installations/{installation_id}/events",
    "/events-history/installations/{installation_id}/events",
)

DEFAULT_LAST_N_DAYS: Final = 30
MAX_LAST_N_DAYS: Final = 365
DEFAULT_LIMIT: Final = 1000
MAX_LIMIT: Final = 1000
DEFAULT_MAX_PAGES: Final = 5
MAX_MAX_PAGES: Final = 20

# --- Actions -----------------------------------------------------------------
SERVICE_GET_EVENT_HISTORY: Final = "get_event_history"
SERVICE_GET_FEATURES: Final = "get_features"

ATTR_LAST_N_DAYS: Final = "last_n_days"
ATTR_LIMIT: Final = "limit"
ATTR_MAX_PAGES: Final = "max_pages"
ATTR_INSTALLATION_ID: Final = "installation_id"
ATTR_EVENT_TYPE: Final = "event_type"
ATTR_GATEWAY_SERIALS: Final = "gateway_serials"
ATTR_EDITED_BY: Final = "edited_by"
ATTR_CURSOR: Final = "cursor"

ATTR_DEVICE_ID: Final = "device_id"
ATTR_VICARE_DEVICE_ID: Final = "vicare_device_id"
ATTR_DEVICE_TYPE: Final = "device_type"
ATTR_PREFIX: Final = "prefix"
ATTR_FULL: Final = "full"

# get_features waits this long for the built-in integration to finish a
# refresh (its cache is empty while the refresh request is running).
CACHE_WAIT_ATTEMPTS: Final = 6
CACHE_WAIT_SECONDS: Final = 1.0

# Key in hass.data for the event history path that worked last time.
DATA_EVENT_HISTORY_PATH: Final = "event_history_path"
