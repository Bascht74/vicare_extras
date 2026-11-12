"""Minimal stand-in for voluptuous, only for the unit tests in this folder.

Implements just the pieces services.py uses. It is NOT the validation engine
Home Assistant runs (probatio, aliased as voluptuous), so passing tests here
say nothing about that engine.
"""

from __future__ import annotations

_UNDEFINED = object()


class Invalid(Exception):
    """Validation error."""


class MultipleInvalid(Invalid):
    """Validation error."""


class _Marker:
    def __init__(self, schema, default=_UNDEFINED):
        self.schema = schema
        self.default = default

    def __hash__(self):
        return hash(self.schema)

    def __eq__(self, other):
        return self.schema == (other.schema if isinstance(other, _Marker) else other)


class Optional(_Marker):
    """Optional key."""


class Required(_Marker):
    """Required key."""


def _validate(validator, value):
    if isinstance(validator, type):
        if not isinstance(value, validator):
            raise Invalid(f"expected {validator.__name__}")
        return value
    return validator(value)


class Schema:
    """Dict schema."""

    def __init__(self, schema, extra=None):
        self.schema = schema

    def __call__(self, data):
        if not isinstance(data, dict):
            raise Invalid("expected a dictionary")
        result = {}
        known = set()
        for marker, validator in self.schema.items():
            key = marker.schema if isinstance(marker, _Marker) else marker
            known.add(key)
            if key in data:
                try:
                    result[key] = _validate(validator, data[key])
                except Invalid as err:
                    raise MultipleInvalid(f"{err} @ data['{key}']") from err
            elif isinstance(marker, Required):
                raise MultipleInvalid(f"required key not provided @ data['{key}']")
            elif isinstance(marker, _Marker) and marker.default is not _UNDEFINED:
                result[key] = marker.default
        if extra := set(data) - known:
            raise MultipleInvalid(f"extra keys not allowed @ data['{sorted(extra)[0]}']")
        return result


def All(*validators):  # noqa: N802
    def validate(value):
        for validator in validators:
            value = _validate(validator, value)
        return value

    return validate


def Any(*validators):  # noqa: N802
    def validate(value):
        for validator in validators:
            try:
                return _validate(validator, value)
            except Invalid:
                continue
        raise Invalid("no valid alternative")

    return validate


def Coerce(type_):  # noqa: N802
    def validate(value):
        try:
            return type_(value)
        except (TypeError, ValueError) as err:
            raise Invalid(f"expected {type_.__name__}") from err

    return validate


def Range(min=None, max=None):  # noqa: A002, N802
    def validate(value):
        if min is not None and value < min:
            raise Invalid(f"value must be at least {min}")
        if max is not None and value > max:
            raise Invalid(f"value must be at most {max}")
        return value

    return validate
