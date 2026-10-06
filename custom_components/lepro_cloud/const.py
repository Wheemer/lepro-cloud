"""Constants for the Lepro Cloud integration."""

from homeassistant.const import Platform

DOMAIN = "lepro_cloud"
PLATFORMS = [Platform.LIGHT, Platform.SWITCH]

CONF_REGION = "region"

REGIONS = {
    "north_america": "api-na-iot.lepro.com",
    "europe": "api-eu-iot.lepro.com",
    "far_east": "api-fe-iot.lepro.com",
}
REGION_DISCOVERY_HOST = "api-iot.lepro.com"

APP_NAME = "Lepro"
APP_VERSION = "1.0.9.269"
DEFAULT_LANGUAGE = "en"

MQTT_TOPIC_PREFIX = "le"
