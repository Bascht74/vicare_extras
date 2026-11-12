"""Stub of homeassistant.helpers.service."""


def async_register_admin_service(
    hass, domain, service, service_func, schema=None, supports_response=None
):
    """Register like the real helper and remember that it is admin only."""
    hass.services.async_register(
        domain, service, service_func, schema=schema, supports_response=supports_response
    )
    hass.services.registered[(domain, service)]["admin"] = True
