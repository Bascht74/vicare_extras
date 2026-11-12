#!/usr/bin/env python3
"""Static consistency checks for the integration (no Home Assistant needed).

Run from the repository root:  python scripts/check_consistency.py

Checks
* every JSON file parses; strings.json equals translations/en.json;
  en and de have exactly the same keys;
* every error key raised in the code exists in all translations and the
  placeholders passed in the code match the ones used in the messages;
* sensor translation keys, icons, services.yaml fields, action schemas and
  config flow keys agree with the translations;
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

# --- sensors ------------------------------------------------------------------
sensor_keys: set[str] = set()
for node in ast.walk(sources[COMPONENT / "sensor.py"]):
    if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "ViCareExtrasSensorDescription":
        values = {kw.arg: kw.value.value for kw in node.keywords if isinstance(kw.value, ast.Constant)}
        check(values.get("key") == values.get("translation_key"), f"sensor {values}: key != translation_key")
        sensor_keys.add(values["translation_key"])
check(len(sensor_keys) == 6, f"expected 6 sensor descriptions, found {sorted(sensor_keys)}")
for language, content in all_texts.items():
    translated = set(content.get("entity", {}).get("sensor", {}))
    check(translated == sensor_keys, f"{language}: entity.sensor keys {sorted(translated)} != {sorted(sensor_keys)}")
    for key, value in content.get("entity", {}).get("sensor", {}).items():
        check(bool(value.get("name")), f"{language}: entity.sensor.{key} has no name")
icons = loaded[COMPONENT / "icons.json"]
check(set(icons["entity"]["sensor"]) == sensor_keys, "icons.json sensor keys differ from the sensors")

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

# --- config flow --------------------------------------------------------------
flow_source = (COMPONENT / "config_flow.py").read_text(encoding="utf-8")
for language, content in all_texts.items():
    for reason in re.findall(r'reason="(\w+)"', flow_source):
        check(reason in content["config"]["abort"], f"{language}: config.abort.{reason} missing")
    for step in re.findall(r'step_id="(\w+)"', flow_source):
        check(step in content["config"]["step"], f"{language}: config.step.{step} missing")

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
    f"{len(sensor_keys)} sensors, {len(services_yaml)} actions, "
    f"languages: {', '.join(sorted(translations))}"
)
