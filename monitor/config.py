"""Read and check pipelines.json. Anything wrong raises ConfigError with a clear message."""

import json

NUMBER_FIELDS = ["interval_hours", "freshness_hours", "band_percent"]


# One error type for a bad config file, so the command line can show it nicely.
class ConfigError(ValueError):
    pass


# True for a real number above zero. We exclude True/False, because Python
# treats them as the numbers 1 and 0.
def is_positive_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


# True for text that is not blank.
def is_text(value):
    return isinstance(value, str) and bool(value.strip())


# Check one pipeline entry. Raises ConfigError if anything is missing or wrong.
# `seen` holds the names we have already read, to catch a name used twice.
def check_pipeline(entry, seen):
    if not isinstance(entry, dict) or not is_text(entry.get("name")):
        raise ConfigError("every pipeline must be an object with a non-empty name")
    name = entry["name"]
    if name in seen:
        raise ConfigError(f"pipeline name used twice: {name}")
    if not is_text(entry.get("owner")):
        raise ConfigError(f"{name}: owner is required")
    for field in NUMBER_FIELDS:
        if not is_positive_number(entry.get(field)):
            raise ConfigError(f"{name}: {field} must be a number greater than 0")
    if entry["band_percent"] > 100:
        raise ConfigError(f"{name}: band_percent must be 100 or less")
    columns = entry.get("required_columns")
    if not isinstance(columns, list) or not columns or not all(is_text(c) for c in columns):
        raise ConfigError(f"{name}: required_columns must be a non-empty list of column names")


# Load the config file and return the list of pipeline dicts.
# A missing file, broken JSON or a bad entry all become a ConfigError.
def load_config(path):
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except OSError as error:
        raise ConfigError(f"cannot read {path}: {error.strerror}") from error
    except json.JSONDecodeError as error:
        raise ConfigError(f"{path} is not valid JSON: {error}") from error
    pipelines = data.get("pipelines") if isinstance(data, dict) else None
    if not isinstance(pipelines, list) or not pipelines:
        raise ConfigError('the file must look like {"pipelines": [...]} with at least one pipeline')
    seen = set()
    for entry in pipelines:
        check_pipeline(entry, seen)
        seen.add(entry["name"])
    return pipelines
