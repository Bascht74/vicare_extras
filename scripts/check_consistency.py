#!/usr/bin/env python3
"""Static consistency checks for the integration (no Home Assistant needed).

Run from the repository root:  python scripts/check_consistency.py

Checks
* every JSON file parses; strings.json equals translations/en.json;
  en and de have exactly the same keys;
* every error key raised in the code exists in all translations and the
  placeholders passed in the code match the ones used in the messages;
* entity keys of specs.py, their names (placeholders), enum states, icons,
  services.yaml fields, action schemas, config flow and options flow keys
  agree with the translations;
* the message code table is valid, up to date, marks unconfirmed texts and
  is built from this project's own wording file only;
* the platforms set up in __init__.py exist, and the climate entities'
  unique id suffix does not collide with an entity key;
* manifest.json has the keys Home Assistant and HACS need.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
import re
import sys

import yaml

ROOT = Path(__file__).resolve().parent.parent
COMPONENT = ROOT / "custom_components" / "vicare_extras"
PLACEHOLDER = re.compile(r"\{(\w+)\}")

errors: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        errors.append(message)


def flat_keys(data: dict, prefix: str = "") -> set[str]:
    keys: set[str] = set()
    for key, value in data.items():
        if isinstance(value, dict):
            keys |= flat_keys(value, f"{prefix}{key}.")
        else:
            keys.add(f"{prefix}{key}")
    return keys


# --- JSON ---------------------------------------------------------------------
json_files = [*COMPONENT.rglob("*.json"), ROOT / "hacs.json"]
loaded: dict[Path, dict] = {}
for path in json_files:
    try:
        loaded[path] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        errors.append(f"{path.relative_to(ROOT)}: invalid JSON: {err}")
if errors:
    print("\n".join(errors))
    sys.exit(1)

strings = loaded[COMPONENT / "strings.json"]
translations = {
    path.stem: loaded[path] for path in sorted((COMPONENT / "translations").glob("*.json"))
}
check({"en", "de"} <= set(translations), "translations/en.json and de.json are required")
check(strings == translations.get("en"), "strings.json differs from translations/en.json")
for language, content in translations.items():
    missing = flat_keys(strings) - flat_keys(content)
    extra = flat_keys(content) - flat_keys(strings)
    check(not missing, f"{language}.json misses keys: {sorted(missing)}")
    check(not extra, f"{language}.json has unknown keys: {sorted(extra)}")
all_texts = {"strings": strings, **translations}

# --- error keys and placeholders ---------------------------------------------
used_errors: dict[str, set[frozenset[str]]] = {}
sources = {path: ast.parse(path.read_text(encoding="utf-8")) for path in COMPONENT.glob("*.py")}
for path, tree in sources.items():
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "id", getattr(node.func, "attr", None))
        if name == "ViCareExtrasError":
            first = node.args[0] if node.args else None
            if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
                errors.append(f"{path.name}:{node.lineno}: error key is not a literal")
                continue
            placeholders: frozenset[str] = frozenset()
            if len(node.args) > 1 and isinstance(node.args[1], ast.Dict):
                placeholders = frozenset(
                    key.value for key in node.args[1].keys if isinstance(key, ast.Constant)
                )
            used_errors.setdefault(first.value, set()).add(placeholders)
        for keyword in node.keywords:
            if keyword.arg == "translation_key" and isinstance(keyword.value, ast.Constant):
                placeholders = frozenset()
                for other in node.keywords:
                    if other.arg == "translation_placeholders" and isinstance(other.value, ast.Dict):
                        placeholders = frozenset(
                            key.value for key in other.value.keys if isinstance(key, ast.Constant)
                        )
                if name in ("HomeAssistantError", "ServiceValidationError"):
                    used_errors.setdefault(keyword.value.value, set()).add(placeholders)

for language, content in all_texts.items():
    exceptions = content.get("exceptions", {})
    for key, placeholder_sets in used_errors.items():
        if key not in exceptions:
            errors.append(f"{language}: exception '{key}' used in code but not translated")
            continue
        in_message = frozenset(PLACEHOLDER.findall(exceptions[key]["message"]))
        for placeholders in placeholder_sets:
            check(
                placeholders == in_message,
                f"{language}: exception '{key}': code passes {sorted(placeholders)}, "
                f"message uses {sorted(in_message)}",
            )
    unused = set(exceptions) - set(used_errors)
    check(not unused, f"{language}: exceptions never raised: {sorted(unused)}")

# --- entities ---------------------------------------------------------------
import importlib.util  # noqa: E402

_module_spec = importlib.util.spec_from_file_location("vicare_extras_specs", COMPONENT / "specs.py")
specs = importlib.util.module_from_spec(_module_spec)
sys.modules["vicare_extras_specs"] = specs
_module_spec.loader.exec_module(specs)  # specs.py has no imports of its own package

sensor_specs = [spec for spec in specs.ALL_SPECS if spec.platform == specs.PLATFORM_SENSOR]
binary_specs = [spec for spec in specs.ALL_SPECS if spec.platform == specs.PLATFORM_BINARY_SENSOR]
all_keys = [spec.key for spec in specs.ALL_SPECS] + [spec.key for spec in specs.SPECIAL_SPECS]
check(len(all_keys) == len(set(all_keys)), "duplicate entity keys in specs.py")
sensor_keys = {spec.key for spec in sensor_specs} | {spec.key for spec in specs.SPECIAL_SPECS}
binary_keys = {spec.key for spec in binary_specs}
# Unique ids of entities that exist in installations of 0.1.0 must not change.
for legacy in (
    "power_consumption_dhw_history",
    "power_consumption_heating_history",
    "power_consumption_total_history",
    "heat_production_dhw_summary",
    "heat_production_heating_summary",
    "messages",
):
    check(legacy in sensor_keys, f"sensor '{legacy}' of version 0.1.0 is missing")

numbering = {spec.key: spec.numbering for spec in (*specs.ALL_SPECS, *specs.SPECIAL_SPECS)}
room_keys = {spec.key for spec in specs.ROOM_SPECS}


def expected_placeholders(key: str) -> set[str]:
    if key in room_keys or numbering[key] == specs.NUMBER_NONE:
        return set()
    return {"suffix"} if numbering[key] == specs.NUMBER_SUFFIX else {"number"}


def constant_tuple(path: Path, name: str) -> tuple[str, ...]:
    """Resolve a module level tuple of string constants without importing."""
    tree = sources[path]
    values = {
        target.id: node.value.value
        for node in tree.body
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", None) == name:
            return tuple(
                values[item.id] if isinstance(item, ast.Name) else item.value
                for item in node.value.elts
            )
    raise KeyError(name)


enum_states: dict[str, set[str]] = {key: set(states) for key, states in specs.ENUM_STATES.items()}
enum_states["operating_state"] = set(constant_tuple(COMPONENT / "derived.py", "OPERATING_STATES"))
for spec in specs.SPECIAL_SPECS:
    if spec.kind == specs.SPECIAL_SCHEDULE:
        enum_states[spec.key] = set(specs.SCHEDULE_STATES)
for spec in specs.ALL_SPECS:
    if spec.kind == specs.KIND_ENUM:
        check(spec.key in enum_states, f"enum sensor '{spec.key}' has no entry in ENUM_STATES")

for language, content in all_texts.items():
    for domain, keys in (("sensor", sensor_keys), ("binary_sensor", binary_keys)):
        translated = content.get("entity", {}).get(domain, {})
        check(set(translated) == keys, f"{language}: entity.{domain} keys differ: missing {sorted(keys - set(translated))}, unknown {sorted(set(translated) - keys)}")
        for key, value in translated.items():
            name = value.get("name") or ""
            check(bool(name), f"{language}: entity.{domain}.{key} has no name")
            if key in numbering:
                check(set(PLACEHOLDER.findall(name)) == expected_placeholders(key), f"{language}: entity.{domain}.{key}: name '{name}' must use placeholders {sorted(expected_placeholders(key))}")
            states = set(value.get("state", {}))
            check(states == enum_states.get(key, set()), f"{language}: entity.{domain}.{key}: states differ: missing {sorted(enum_states.get(key, set()) - states)}, unknown {sorted(states - enum_states.get(key, set()))}")
    unknown_domains = set(content.get("entity", {})) - {"sensor", "binary_sensor"}
    check(not unknown_domains, f"{language}: entity translations for unknown platforms {sorted(unknown_domains)}")
icons = loaded[COMPONENT / "icons.json"]
check(set(icons["entity"]["sensor"]) <= sensor_keys, "icons.json has unknown sensor keys")
check(set(icons["entity"].get("binary_sensor", {})) <= binary_keys, "icons.json has unknown binary sensor keys")

# --- message code table -------------------------------------------------------
table_path = COMPONENT / "data" / "message_codes.json"
table = loaded.get(table_path, {})
codes = table.get("codes", {})
check(len(codes) > 400, "message code table is missing or too small")
table_sources = table.get("sources", {})
for name, meta in table_sources.items():
    check(isinstance(meta.get("verified"), bool), f"message table: source {name} needs 'verified': true/false")
    check(bool(meta.get("meaning_from")), f"message table: source {name} needs 'meaning_from'")
    # Only Viessmann documents count as confirmation.
    check(meta.get("verified") is name.startswith("viessmann"), f"message table: source {name}: 'verified' must be true exactly for Viessmann documents")
for code, entry in codes.items():
    check(re.fullmatch(r"[AFIPS]\.[1-9]\d*", code) is not None, f"message table: bad code {code!r}")
    text = entry.get("de") or ""
    check(bool(text), f"message table: {code} has no German text")
    source = entry.get("source")
    check(source in table_sources, f"message table: {code} has unknown source")
    source_verified = table_sources.get(source, {}).get("verified")
    # Unconfirmed texts must carry the flag, confirmed ones must not.
    check(
        ("verified" in entry) is (source_verified is False) and entry.get("verified", False) is False,
        f"message table: {code}: 'verified': false must be set exactly for unconfirmed sources",
    )
    if str(source).startswith("viessmann"):
        # Own wording: no quotation marks of the manuals, no trailing period.
        check(not set(text) & set('„“”"'), f"message table: {code} contains quotation marks")
        check(text == text.strip() and not text.endswith("."), f"message table: {code}: untidy text {text!r}")
source_files = sorted(path.name for path in (ROOT / "scripts" / "message_sources").iterdir())
check(source_files == ["messages_de.txt"], f"scripts/message_sources must only hold messages_de.txt (own wording), found {source_files}")
check("verified" in (COMPONENT / "messages.py").read_text(encoding="utf-8"), "messages.py does not handle 'verified'")
import subprocess  # noqa: E402

built = subprocess.run([sys.executable, str(ROOT / "scripts" / "build_message_codes.py"), "--check"], capture_output=True, text=True, check=False)
check(built.returncode == 0, f"message table is stale: {built.stdout.strip()}")

# --- actions ------------------------------------------------------------------
services_yaml = yaml.safe_load((COMPONENT / "services.yaml").read_text(encoding="utf-8"))
const_values = {
    target.id: node.value.value
    for node in ast.walk(sources[COMPONENT / "const.py"])
    if isinstance(node, ast.AnnAssign) and isinstance(node.value, ast.Constant)
    for target in [node.target]
}
schema_fields: dict[str, set[str]] = {}
for node in ast.walk(sources[COMPONENT / "services.py"]):
    if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "").endswith("_SCHEMA"):
        fields = {
            const_values[call.args[0].id]
            for call in ast.walk(node.value)
            if isinstance(call, ast.Call)
            and getattr(call.func, "attr", None) in ("Optional", "Required")
            and isinstance(call.args[0], ast.Name)
        }
        schema_fields[node.targets[0].id.removesuffix("_SCHEMA").lower()] = fields
check(set(schema_fields) == set(services_yaml), f"schemas {sorted(schema_fields)} != services.yaml {sorted(services_yaml)}")
check(set(icons["services"]) == set(services_yaml), "icons.json services differ from services.yaml")
for service, definition in services_yaml.items():
    yaml_fields = set(definition.get("fields", {}))
    check(yaml_fields == schema_fields.get(service), f"{service}: services.yaml fields {sorted(yaml_fields)} != schema {sorted(schema_fields.get(service, []))}")
    for language, content in all_texts.items():
        text = content.get("services", {}).get(service)
        if text is None:
            errors.append(f"{language}: action '{service}' not translated")
            continue
        check(bool(text.get("name")) and bool(text.get("description")), f"{language}: action '{service}' needs name and description")
        check(set(text.get("fields", {})) == yaml_fields, f"{language}: action '{service}' fields {sorted(text.get('fields', {}))} != {sorted(yaml_fields)}")
for language, content in all_texts.items():
    check(set(content.get("services", {})) == set(services_yaml), f"{language}: translated actions differ from services.yaml")

# --- config flow and options flow ---------------------------------------------
flow_tree = sources[COMPONENT / "config_flow.py"]
flow_steps: dict[str, set[str]] = {"config": set(), "options": set()}
flow_aborts: dict[str, set[str]] = {"config": set(), "options": set()}
for node in flow_tree.body:
    if not isinstance(node, ast.ClassDef):
        continue
    bases = {getattr(base, "id", getattr(base, "attr", "")) for base in node.bases}
    section = "options" if any(base.startswith("OptionsFlow") for base in bases) else "config"
    for call in ast.walk(node):
        if not isinstance(call, ast.Call):
            continue
        for keyword in call.keywords:
            if isinstance(keyword.value, ast.Constant) and keyword.arg == "step_id":
                flow_steps[section].add(keyword.value.value)
            if isinstance(keyword.value, ast.Constant) and keyword.arg == "reason":
                flow_aborts[section].add(keyword.value.value)
check(flow_steps["config"] == {"user"}, f"config flow steps: {sorted(flow_steps['config'])}")
check(flow_steps["options"] == {"init"}, f"options flow steps: {sorted(flow_steps['options'])}")
# Keys of OPTIONS_SCHEMA: vol.Optional(CONST) / vol.Required(CONST).
option_fields: set[str] = set()
for node in flow_tree.body:
    if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", None) == "OPTIONS_SCHEMA":
        option_fields = {
            const_values[call.args[0].id]
            for call in ast.walk(node.value)
            if isinstance(call, ast.Call)
            and getattr(call.func, "attr", None) in ("Optional", "Required")
            and isinstance(call.args[0], ast.Name)
        }
check(bool(option_fields), "config_flow.py: OPTIONS_SCHEMA has no fields")
for language, content in all_texts.items():
    for section in ("config", "options"):
        texts = content.get(section, {})
        for reason in flow_aborts[section]:
            check(reason in texts.get("abort", {}), f"{language}: {section}.abort.{reason} missing")
        check(set(texts.get("step", {})) == flow_steps[section], f"{language}: {section}.step keys {sorted(texts.get('step', {}))} != {sorted(flow_steps[section])}")
    init = content.get("options", {}).get("step", {}).get("init", {})
    check(bool(init.get("title")) and bool(init.get("description")), f"{language}: options.step.init needs title and description")
    check(set(init.get("data", {})) == option_fields, f"{language}: options.step.init.data {sorted(init.get('data', {}))} != schema {sorted(option_fields)}")
    check(set(init.get("data_description", {})) == option_fields, f"{language}: options.step.init.data_description {sorted(init.get('data_description', {}))} != schema {sorted(option_fields)}")
option_min, option_max = const_values.get("MIN_VICARE_POLL_INTERVAL"), const_values.get("MAX_VICARE_POLL_INTERVAL")
check(option_min == 60 and option_max == 900, "poll interval option must be limited to 60..900 s")
for language, content in all_texts.items():
    description = content["options"]["step"]["init"]["data_description"].get("vicare_poll_interval", "")
    check(str(option_min) in description and str(option_max) in description, f"{language}: the poll interval description must name the limits {option_min} and {option_max}")

# --- platforms ----------------------------------------------------------------
platforms: list[str] = []
for node in sources[COMPONENT / "__init__.py"].body:
    target = node.target if isinstance(node, ast.AnnAssign) else (node.targets[0] if isinstance(node, ast.Assign) else None)
    if getattr(target, "id", None) == "PLATFORMS":
        platforms = [item.attr.lower() for item in node.value.elts]
check(sorted(platforms) == ["binary_sensor", "climate", "sensor"], f"PLATFORMS is {platforms}")
for platform in platforms:
    check((COMPONENT / f"{platform}.py").is_file(), f"platform file {platform}.py missing")
climate_values = {
    target.id: node.value.value
    for node in sources[COMPONENT / "climate.py"].body
    if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
    for target in node.targets
    if isinstance(target, ast.Name)
}
climate_suffix = climate_values.get("UNIQUE_SUFFIX")
check(climate_suffix == "climate", "climate.py: UNIQUE_SUFFIX must stay 'climate' (unique ids)")
check(climate_suffix not in all_keys, "climate unique id suffix collides with an entity key")

# --- manifest -----------------------------------------------------------------
manifest = loaded[COMPONENT / "manifest.json"]
for key in ("domain", "name", "version", "config_flow", "dependencies", "integration_type", "iot_class", "documentation", "issue_tracker", "codeowners"):
    check(key in manifest, f"manifest.json: '{key}' missing")
check(manifest.get("domain") == "vicare_extras" == const_values.get("DOMAIN"), "manifest domain != const DOMAIN")
check(manifest.get("dependencies") == ["vicare"], "manifest must depend on vicare")
check(manifest.get("config_flow") is True, "manifest config_flow must be true")
check(not manifest.get("requirements"), "manifest must not pin requirements (PyViCare comes with vicare)")
check(re.fullmatch(r"\d+\.\d+\.\d+", str(manifest.get("version"))) is not None, "manifest version must be x.y.z")

if errors:
    print("\n".join(f"FAIL: {error}" for error in errors))
    sys.exit(1)
print(
    f"OK: {len(json_files)} JSON files, {len(used_errors)} error keys, "
    f"{len(sensor_keys)} sensor keys, {len(binary_keys)} binary sensor keys, "
    f"{len(codes)} message codes, {len(services_yaml)} actions, "
    f"languages: {', '.join(sorted(translations))}"
)
