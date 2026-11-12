"""Tests for reading and sending commands the API advertises."""

from __future__ import annotations

import pytest

from custom_components.vicare_extras import commands, thermostats
from custom_components.vicare_extras.errors import ViCareExtrasError

from . import fakes

ACCESSOR = fakes.FakeAccessor(fakes.INSTALLATION_ID, fakes.GATEWAY_SERIAL, "RoomControl-1")


def setpoint_feature(**kwargs) -> dict:
    return fakes.feature(
        "rooms.0.temperature.levels.normal.perceived",
        {"temperature": {"type": "number", "unit": "celsius", "value": 21}},
        "RoomControl-1",
        fakes.number_command("setTemperature", "targetTemperature", **kwargs),
    )


def test_number_command_is_read_from_the_feature() -> None:
    command = commands.number_command(setpoint_feature(), ("setTemperature",))
    assert command == commands.NumberCommand(
        feature="rooms.0.temperature.levels.normal.perceived",
        name="setTemperature",
        param="targetTemperature",
        minimum=8,
        maximum=30,
        step=0.5,
    )


def test_real_fixture_commands_are_not_offered() -> None:
    """The Vitocal fixture lists command names without details: not usable."""
    for feature in fakes.vitocal_features():
        for name in feature["commands"]:
            assert commands.number_command(feature, (name,)) is None


@pytest.mark.parametrize(
    "feature",
    [
        None,
        {},
        {"feature": "x"},
        {"feature": "x", "commands": {}},
        {"feature": "x", "commands": {"setTemperature": None}},
        setpoint_feature(executable=False),
        # No parameter, two required parameters, a non-numeric parameter.
        {"feature": "x", "commands": {"setTemperature": {"isExecutable": True, "params": {}}}},
        {
            "feature": "x",
            "commands": {
                "setTemperature": {
                    "isExecutable": True,
                    "params": {
                        "a": {"type": "number", "required": True},
                        "b": {"type": "number", "required": True},
                    },
                }
            },
        },
        {
            "feature": "x",
            "commands": {"setTemperature": {"isExecutable": True, "params": {"a": {"type": "string", "required": True}}}},
        },
    ],
)
def test_commands_that_are_missing_or_not_executable_are_not_offered(feature) -> None:
    assert commands.number_command(feature, ("setTemperature",)) is None


def test_other_command_names_are_ignored() -> None:
    assert commands.number_command(setpoint_feature(), ("setTargetTemperature",)) is None


def test_execute_sends_exactly_one_command() -> None:
    service = fakes.FakeCommandService(fakes.gateway_payload())
    command = commands.number_command(setpoint_feature(), ("setTemperature",))

    assert commands.execute(service, ACCESSOR, command, 21.5) == 21.5

    assert service.commands == [
        (
            "RoomControl-1",
            "rooms.0.temperature.levels.normal.perceived",
            "setTemperature",
            {"targetTemperature": 21.5},
        )
    ]
    assert service.api_calls == 0  # no read was triggered
    # The cache of the built-in integration is left alone: emptying it would
    # make the built-in integration fetch again (a second API call).
    assert service.cache_clears == 0
    assert service._cache is not None


def test_execute_falls_back_to_the_service_method() -> None:
    """No ViCareService base class: the service's own setProperty is used."""
    service = fakes.FakeOtherCommandService(fakes.gateway_payload())
    command = commands.number_command(setpoint_feature(), ("setTemperature",))
    assert commands.execute(service, ACCESSOR, command, 20) == 20
    assert len(service.commands) == 1


def test_whole_numbers_are_sent_as_integers() -> None:
    service = fakes.FakeCommandService(fakes.gateway_payload())
    command = commands.number_command(setpoint_feature(), ("setTemperature",))
    commands.execute(service, ACCESSOR, command, 22.0)
    assert service.commands[0][3] == {"targetTemperature": 22}
    assert isinstance(service.commands[0][3]["targetTemperature"], int)


@pytest.mark.parametrize("value", [7.5, 30.5, -1, "warm", None, True])
def test_values_outside_the_api_limits_are_not_sent(value) -> None:
    service = fakes.FakeCommandService(fakes.gateway_payload())
    command = commands.number_command(setpoint_feature(), ("setTemperature",))
    with pytest.raises(ViCareExtrasError) as err:
        commands.execute(service, ACCESSOR, command, value)
    assert err.value.translation_key == "value_out_of_range"
    assert err.value.validation
    assert err.value.placeholders["min"] == "8"
    assert err.value.placeholders["max"] == "30"
    assert service.commands == []


@pytest.mark.parametrize(
    ("answer", "key"),
    [
        (fakes.PyViCareCommandError("COMMAND_EXECUTION_ERROR"), "command_failed"),
        (fakes.PyViCareRateLimitError(), "rate_limited"),
        (fakes.PyViCareInternalServerError("boom"), "server_error"),
        (RuntimeError("boom"), "unexpected_error"),
        ({"statusCode": 502, "extendedPayload": {"reason": "INTERNAL_SERVER_ERROR"}}, "command_failed"),
        ({"statusCode": 400, "message": "bad"}, "command_failed"),
        ({"data": {"success": False, "reason": "COMMAND_EXECUTION_ERROR"}}, "command_failed"),
    ],
)
def test_failures_are_mapped(answer, key) -> None:
    service = fakes.FakeCommandService(fakes.gateway_payload(), answer)
    command = commands.number_command(setpoint_feature(), ("setTemperature",))
    with pytest.raises(ViCareExtrasError) as err:
        commands.execute(service, ACCESSOR, command, 21)
    assert err.value.translation_key == key
    assert not err.value.validation
    assert len(service.commands) == 1  # not retried


def test_execute_without_service_or_accessor() -> None:
    command = commands.number_command(setpoint_feature(), ("setTemperature",))
    for service, accessor in ((object(), ACCESSOR), (fakes.FakeCommandService(None), None)):
        with pytest.raises(ViCareExtrasError) as err:
            commands.execute(service, accessor, command, 21)
        assert err.value.translation_key == "vicare_incompatible"


# ------------------------------------------------------------ thermostat model


def by_name(features: list[dict]) -> dict:
    return {f["feature"]: f for f in features}


def test_room_setpoint_prefers_the_writable_feature() -> None:
    # perceived is listed first but only normal.heating can be written.
    features = by_name(fakes.room_features(0, writable="temperature.levels.normal.heating"))
    setpoint = thermostats.room_setpoint(features, 0)
    assert setpoint.feature == "rooms.0.temperature.levels.normal.heating"
    assert setpoint.value == 21
    assert setpoint.command.name == "setTemperature"
    assert setpoint.command.param == "targetTemperature"

    features = by_name(fakes.room_features(0, writable="temperature.levels.normal.perceived"))
    assert thermostats.room_setpoint(features, 0).feature == "rooms.0.temperature.levels.normal.perceived"


def test_room_setpoint_read_only_when_nothing_is_writable() -> None:
    setpoint = thermostats.room_setpoint(by_name(fakes.room_features(0)), 0)
    assert setpoint.feature == "rooms.0.temperature.levels.normal.perceived"
    assert setpoint.command is None

    not_executable = by_name(
        fakes.room_features(0, writable="temperature.levels.normal.perceived", executable=False)
    )
    assert thermostats.room_setpoint(not_executable, 0).command is None
    assert thermostats.room_setpoint({}, 0) is None
    assert thermostats.room_setpoint(by_name(fakes.room_control_only_flags()), 0) is None


def test_room_setpoint_of_the_vitoconnect_layout() -> None:
    """PyViCare's TRV fixture: the command sits on operating.programs.normalHeating."""
    feature = fakes.feature(
        "rooms.0.operating.programs.normalHeating",
        {"active": {"type": "boolean", "value": True}, "temperature": {"type": "number", "unit": "celsius", "value": 20}},
        "RoomControl-1",
        fakes.number_command("setTemperature", "targetTemperature"),
    )
    setpoint = thermostats.room_setpoint({feature["feature"]: feature}, 0)
    assert setpoint.value == 20
    assert setpoint.command is not None


@pytest.mark.parametrize(
    ("demand", "action"),
    [("heating", "heating"), ("cooling", "cooling"), ("energySaving", "idle"), ("none", "idle"), (None, None)],
)
def test_room_action(demand, action) -> None:
    features = {}
    if demand is not None:
        features["rooms.0.operating.state"] = fakes.feature(
            "rooms.0.operating.state", {"demand": {"type": "string", "value": demand}}, "RoomControl-1"
        )
    assert thermostats.room_action(features, 0) == action


def test_room_actors_and_room_of_device() -> None:
    features = by_name(
        [
            *fakes.room_features(0, "Bad"),
            *fakes.room_features(1, "Wohnzimmer", actors=(fakes.TRV_DEVICE_ID, "zigbee-cs")),
        ]
    )
    assert thermostats.room_actors(features, 0) == []
    assert thermostats.room_actors(features, 1) == [fakes.TRV_DEVICE_ID, "zigbee-cs"]
    assert thermostats.room_of_device(features, fakes.TRV_DEVICE_ID) == (1, "Wohnzimmer")
    assert thermostats.room_of_device(features, "zigbee-unknown") is None
    assert thermostats.room_actors({"rooms.0": {"properties": {"actors": {"value": "odd"}}}}, 0) == []


def test_trv_model() -> None:
    features = by_name(fakes.trv_features())
    assert thermostats.is_trv(features)
    setpoint = thermostats.trv_setpoint(features)
    assert (setpoint.feature, setpoint.prop, setpoint.value) == ("trv.temperature", "value", 20)
    assert setpoint.command == commands.NumberCommand("trv.temperature", "setTargetTemperature", "temperature", 8, 30, 0.5)
    assert thermostats.sensor_value(features["device.sensors.temperature"]) == 20.8
    assert thermostats.trv_valve_position(features) == 17
    assert thermostats.trv_action(features) == "heating"
    assert thermostats.trv_action(by_name(fakes.trv_features(valve=0))) == "idle"

    assert not thermostats.is_trv(by_name(fakes.vitocal_features()))
    assert thermostats.trv_setpoint({}) is None
    assert thermostats.trv_action({}) is None


@pytest.mark.parametrize("status", ["notConnected", "error", None])
def test_trv_without_usable_temperature(status) -> None:
    """Seen in the field: a thermostat that reports no actual temperature."""
    features = by_name(fakes.trv_features(temperature_status=status))
    assert thermostats.sensor_value(features.get("device.sensors.temperature")) is None
    assert thermostats.sensor_value(None) is None
    assert thermostats.trv_setpoint(features).value == 20  # the setpoint still works
