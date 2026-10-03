#!/usr/bin/env python3

"""
Centralized Input configuration.

Input/topic.txt is the single source of truth for the video pipeline.

Supports:
- normal KEY = VALUE settings
- inline comments
- quoted values
- multiline STORY_TEXT = """..."""
"""

from pathlib import Path
import re


INPUT_FILE = Path("Input/topic.txt")

TRUE_VALUES = {
    "true",
    "1",
    "yes",
    "on",
}

FALSE_VALUES = {
    "false",
    "0",
    "no",
    "off",
}


def clean_value(value):
    value = str(value).strip()

    if "#" in value:
        value = value.split("#", 1)[0].strip()

    value = value.strip()

    if len(value) >= 2:
        if (
            (value.startswith('"') and value.endswith('"'))
            or
            (value.startswith("'") and value.endswith("'"))
        ):
            value = value[1:-1]

    return value.strip()


def parse_value(value):
    value = clean_value(value)

    if value == "":
        return ""

    low = value.lower()

    if low in TRUE_VALUES:
        return True

    if low in FALSE_VALUES:
        return False

    if re.fullmatch(r"[+-]?\d+", value):
        try:
            return int(value)
        except ValueError:
            pass

    if re.fullmatch(
        r"[+-]?(?:\d+\.\d*|\d*\.\d+)",
        value
    ):
        try:
            return float(value)
        except ValueError:
            pass

    return value


def load_input_config(path=INPUT_FILE):
    """
    Read complete Input/topic.txt.

    Supports multiline STORY_TEXT.

    Example:

    STORY_TEXT = """
    यह पूरी कहानी यहाँ होगी।
    यह कई lines में हो सकती है।
    """

    All other KEY = VALUE settings are parsed normally.
    """

    path = Path(path)

    if not path.exists():
        raise FileNotFoundError(
            f"Input configuration not found: {path}"
        )

    text = path.read_text(
        encoding="utf-8"
    )

    config = {}

    lines = text.splitlines()

    index = 0

    while index < len(lines):

        raw_line = lines[index]
        line = raw_line.strip()

        # Empty line
        if not line:
            index += 1
            continue

        # Full-line comment
        if line.startswith("#"):
            index += 1
            continue

        # --------------------------------------------------
        # MULTILINE STORY_TEXT
        # --------------------------------------------------

        story_match = re.match(
            r'^STORY_TEXT\s*=\s*("""|\'\'\')',
            line,
            flags=re.IGNORECASE,
        )

        if story_match:

            delimiter = story_match.group(1)

            remainder = line[
                story_match.end():
            ]

            collected = []

            # Closing delimiter is on same line
            if delimiter in remainder:

                end_index = remainder.find(
                    delimiter
                )

                collected.append(
                    remainder[:end_index]
                )

            else:

                collected.append(
                    remainder
                )

                index += 1

                while index < len(lines):

                    current = lines[index]

                    if delimiter in current:

                        end_index = current.find(
                            delimiter
                        )

                        collected.append(
                            current[:end_index]
                        )

                        break

                    collected.append(current)

                    index += 1

            config["STORY_TEXT"] = "\n".join(
                collected
            ).strip()

            index += 1
            continue

        # --------------------------------------------------
        # NORMAL KEY = VALUE
        # --------------------------------------------------

        if "=" not in line:
            index += 1
            continue

        key, value = line.split(
            "=",
            1
        )

        key = key.strip().upper()

        if not key:
            index += 1
            continue

        config[key] = parse_value(value)

        index += 1

    return config


def cfg(config, key, default=None):
    return config.get(
        str(key).upper(),
        default
    )


def cfg_text(config, key, default=""):
    value = cfg(
        config,
        key,
        default
    )

    if value is None:
        return ""

    return str(value).strip()


def cfg_bool(config, key, default=False):
    value = cfg(
        config,
        key,
        default
    )

    if isinstance(value, bool):
        return value

    low = str(value).strip().lower()

    if low in TRUE_VALUES:
        return True

    if low in FALSE_VALUES:
        return False

    return bool(default)


def cfg_int(config, key, default=0):
    value = cfg(
        config,
        key,
        default
    )

    try:
        return int(value)
    except (
        TypeError,
        ValueError
    ):
        return int(default)


def cfg_float(config, key, default=0.0):
    value = cfg(
        config,
        key,
        default
    )

    try:
        return float(value)
    except (
        TypeError,
        ValueError
    ):
        return float(default)


def normalize_format(config):

    value = cfg_text(
        config,
        "FORMAT",
        "full"
    ).lower()

    if value in {
        "short",
        "vertical",
        "reels",
        "youtube_short",
    }:
        return "short"

    if value in {
        "full",
        "horizontal",
        "long",
        "longform",
        "youtube_full",
    }:
        return "full"

    raise ValueError(
        f"Unsupported FORMAT: {value!r}. "
        "Use 'short' or 'full'."
    )


def resolve_topic(config):
    return cfg_text(
        config,
        "TOPIC",
        ""
    )


def resolve_story_text(config):
    return cfg_text(
        config,
        "STORY_TEXT",
        ""
    )


def has_story_text(config):
    return bool(
        resolve_story_text(config)
    )


def has_topic(config):
    return bool(
        resolve_topic(config)
    )


def resolve_title_source(config):

    topic = resolve_topic(config)

    if topic:
        return {
            "source": "input_topic",
            "value": topic,
        }

    story = resolve_story_text(config)

    if story:
        return {
            "source": "story_text",
            "value": story,
        }

    return {
        "source": "missing",
        "value": "",
    }


def get_parts(config):
    return max(
        1,
        cfg_int(
            config,
            "PARTS",
            1
        )
    )


def get_scenes(config):
    return max(
        1,
        cfg_int(
            config,
            "SCENES",
            1
        )
    )


def get_max_retries(config):
    return max(
        1,
        cfg_int(
            config,
            "MAX_RETRIES",
            3
        )
    )


def get_fps(config):

    fps = cfg_int(
        config,
        "FPS",
        24
    )

    if fps <= 0:
        return 24

    return fps


def get_caption_mode(config):

    value = cfg_text(
        config,
        "CAPTIONS",
        "hindi"
    ).lower()

    allowed = {
        "hindi",
        "english",
        "hinglish",
        "none",
        "off",
        "false",
    }

    if value not in allowed:
        return "hindi"

    return value


def get_story_length(config):

    value = cfg_text(
        config,
        "STORY_LENGTH",
        "auto"
    ).lower()

    allowed = {
        "auto",
        "short",
        "medium",
        "long",
    }

    if value not in allowed:
        return "auto"

    return value


def get_scene_duration(config):

    value = cfg_text(
        config,
        "SCENE_DURATION",
        "auto"
    ).lower()

    allowed = {
        "auto",
        "fixed",
    }

    if value not in allowed:
        return "auto"

    return value


def get_failure_policy(config):

    value = cfg_text(
        config,
        "FAILURE_POLICY",
        "retry_then_checkpoint"
    ).lower()

    allowed = {
        "retry_then_checkpoint",
        "skip",
        "stop",
    }

    if value not in allowed:
        return "retry_then_checkpoint"

    return value


def validate_config(config):

    errors = []

    try:
        normalize_format(config)
    except ValueError as exc:
        errors.append(str(exc))

    if get_parts(config) < 1:
        errors.append(
            "PARTS must be >= 1"
        )

    if get_scenes(config) < 1:
        errors.append(
            "SCENES must be >= 1"
        )

    if get_fps(config) < 1:
        errors.append(
            "FPS must be >= 1"
        )

    title_source = resolve_title_source(
        config
    )

    if title_source["source"] == "missing":
        errors.append(
            "TOPIC and STORY_TEXT cannot "
            "both be empty."
        )

    if errors:
        raise ValueError(
            "Invalid Input/topic.txt:\n- "
            + "\n- ".join(errors)
        )

    return True


def print_config_summary(config):

    print("==============================================")
    print("        INPUT CONFIGURATION")
    print("==============================================")

    print(
        f"FORMAT              : "
        f"{normalize_format(config)}"
    )

    print(
        f"AUDIENCE            : "
        f"{cfg_text(config, 'AUDIENCE', 'adult')}"
    )

    print(
        f"TOPIC               : "
        f"{resolve_topic(config) or '[empty]'}"
    )

    print(
        f"STORY_TEXT          : "
        f"{'provided' if has_story_text(config) else 'empty'}"
    )

    print(
        f"PARTS               : "
        f"{get_parts(config)}"
    )

    print(
        f"SCENES              : "
        f"{get_scenes(config)}"
    )

    print(
        f"STORY_LENGTH        : "
        f"{get_story_length(config)}"
    )

    print(
        f"SCENE_DURATION      : "
        f"{get_scene_duration(config)}"
    )

    print(
        f"VOICE               : "
        f"{cfg_text(config, 'VOICE', 'male')}"
    )

    print(
        f"SPEED               : "
        f"{cfg_text(config, 'SPEED', '+0%')}"
    )

    print(
        f"CAPTIONS            : "
        f"{get_caption_mode(config)}"
    )

    print(
        f"VISUAL_STYLE        : "
        f"{cfg_text(config, 'VISUAL_STYLE', 'cinematic_realistic')}"
    )

    print(
        f"REALISM             : "
        f"{cfg_text(config, 'REALISM', 'high')}"
    )

    print(
        f"CHARACTER_BIBLE     : "
        f"{cfg_bool(config, 'CHARACTER_BIBLE', True)}"
    )

    print(
        f"CHARACTER_CONSIST.  : "
        f"{cfg_bool(config, 'CHARACTER_CONSISTENCY', True)}"
    )

    print(
        f"WORLD_CONSISTENCY   : "
        f"{cfg_bool(config, 'WORLD_CONSISTENCY', True)}"
    )

    print(
        f"SCENE_CONTINUITY    : "
        f"{cfg_bool(config, 'SCENE_CONTINUITY', True)}"
    )

    print(
        f"CINEMATIC_CAMERA    : "
        f"{cfg_bool(config, 'CINEMATIC_CAMERA', True)}"
    )

    print(
        f"CAMERA_STYLE        : "
        f"{cfg_text(config, 'CAMERA_STYLE', 'cinematic')}"
    )

    print(
        f"LIGHTING            : "
        f"{cfg_text(config, 'LIGHTING', 'cinematic')}"
    )

    print(
        f"MOOD                : "
        f"{cfg_text(config, 'MOOD', 'dramatic')}"
    )

    print(
        f"QUALITY             : "
        f"{cfg_text(config, 'QUALITY', 'high')}"
    )

    print(
        f"FPS                 : "
        f"{get_fps(config)}"
    )

    print(
        f"MUSIC               : "
        f"{cfg_bool(config, 'MUSIC', True)}"
    )

    print(
        f"MUSIC_STYLE         : "
        f"{cfg_text(config, 'MUSIC_STYLE', 'cinematic')}"
    )

    print(
        f"SFX                 : "
        f"{cfg_bool(config, 'SFX', True)}"
    )

    print(
        f"AMBIENT_SOUND       : "
        f"{cfg_bool(config, 'AMBIENT_SOUND', True)}"
    )

    print(
        f"TRANSITIONS         : "
        f"{cfg_text(config, 'TRANSITIONS', 'cinematic')}"
    )

    print(
        f"WATERMARK           : "
        f"{cfg_bool(config, 'WATERMARK', False)}"
    )

    print(
        f"LOGO                : "
        f"{cfg_bool(config, 'LOGO', False)}"
    )

    print(
        f"RESUME_ENABLED      : "
        f"{cfg_bool(config, 'RESUME_ENABLED', True)}"
    )

    print(
        f"MAX_RETRIES         : "
        f"{get_max_retries(config)}"
    )

    print(
        f"SAVE_CHECKPOINT     : "
        f"{cfg_bool(config, 'SAVE_CHECKPOINT_AFTER_EACH_SCENE', True)}"
    )

    print(
        f"SKIP_COMPLETED      : "
        f"{cfg_bool(config, 'SKIP_COMPLETED_SCENES', True)}"
    )

    print(
        f"FAILURE_POLICY      : "
        f"{get_failure_policy(config)}"
    )

    print("==============================================")


if __name__ == "__main__":

    config = load_input_config()

    validate_config(config)

    print_config_summary(config)
