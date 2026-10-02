#!/usr/bin/env python3

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


INPUT_FILE = Path("Input/topic.txt")
OUTPUT_DIR = Path("output/story")
OUTPUT_FILE = OUTPUT_DIR / "story.json"

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

MODEL = os.environ.get(
    "GEMINI_MODEL",
    "gemini-3.5-flash-lite"
)

MAX_RETRIES = 5
INITIAL_BACKOFF = 8
MAX_BACKOFF = 90


def clean_value(value):
    value = value.strip()

    if "#" in value:
        value = value.split("#", 1)[0].strip()

    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        value = value[1:-1]

    return value.strip()


def read_config():
    if not INPUT_FILE.exists():
        raise RuntimeError(f"Missing input file: {INPUT_FILE}")

    config = {}

    text = INPUT_FILE.read_text(encoding="utf-8")

    for raw_line in text.splitlines():
        line = raw_line.strip()

        if not line:
            continue

        if line.startswith("#"):
            continue

        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip().upper()

        if key == "STORY_TEXT":
            continue

        config[key] = clean_value(value)

    return config, text


def extract_story_text(raw_text):
    match = re.search(
        r'STORY_TEXT\s*=\s*"""(.*?)"""',
        raw_text,
        flags=re.DOTALL,
    )

    if match:
        return match.group(1).strip()

    match = re.search(
        r"STORY_TEXT\s*=\s*'''(.*?)'''",
        raw_text,
        flags=re.DOTALL,
    )

    if match:
        return match.group(1).strip()

    return ""


def read_int(config, key, default):
    value = config.get(key, str(default))

    match = re.match(r"^\d+", value)

    if not match:
        return default

    number = int(match.group(0))

    return number if number > 0 else default


def normalize_format(config):
    value = config.get("FORMAT", "full").lower().strip()

    if value not in ("short", "full"):
        return "full"

    return value


def build_short_prompt(config, topic, story_text, parts, scenes):
    title = config.get("TITLE", topic)

    return f"""
You are an expert short-form cinematic storyteller.

Create an ORIGINAL short-video story.

IMPORTANT:
This is NOT a shortened version of a long video.
Do NOT summarize a full story.
Do NOT simply select scenes from a longer story.
The short must have its OWN beginning, middle, climax and ending.

TITLE:
{title}

TOPIC:
{topic}

USER STORY TEXT:
{story_text if story_text else "(No additional story text provided.)"}

FORMAT:
SHORT VERTICAL VIDEO

TARGET:
A fast-paced cinematic short designed for approximately 45–90 seconds.

MANDATORY STORY STRUCTURE:

1. COLD HOOK
Start immediately with a shocking, mysterious, emotional or curiosity-driven moment.
The first sentence must create a strong unanswered question.

2. SETUP
Give only the minimum information needed to understand what is happening.

3. MYSTERY / SUSPENSE
Introduce a question, secret, danger, contradiction or unexplained event.

4. ESCALATION
Increase tension.
Every scene must add new information or raise the stakes.
Do not repeat information.

5. REVEAL
Reveal an important clue or unexpected truth.

6. FINAL TWIST / PAYOFF
The ending must provide a satisfying reveal, emotional punch, irony,
or unexpected reversal.
Do NOT simply stop because the available footage ended.

7. FINAL BEAT
End with a memorable final line or visual moment.
The ending must feel intentionally written for a short video.

SHORT-FORM RULES:

- No slow introduction.
- No "once upon a time" opening unless absolutely necessary.
- No generic exposition.
- No filler scenes.
- No repeated dialogue.
- No scene should exist only to provide background.
- Every scene must either reveal, escalate, misdirect or pay off.
- The first 3 seconds must contain a hook.
- The final 5–8 seconds must contain the strongest payoff/twist.
- The story must feel complete even though it is short.
- Do not reference a "full video".
- Do not say "watch the full story".
- Do not make the short feel like Part 1 of a longer video unless the topic itself requires it.
- Use natural Hindi.
- Characters should behave like real people in a real-world environment.
- Keep the story cinematic and emotionally believable.

SCENE COUNT:
Exactly {parts} part(s), with exactly {scenes} scenes per part.

TOTAL SCENES:
Exactly {parts * scenes} scenes.

Each scene should be approximately 3–7 seconds of visual storytelling.

OUTPUT MUST BE VALID JSON ONLY.

Use this exact structure:

{{
  "status": "completed",
  "format": "short",
  "title": "{title}",
  "topic": "{topic}",
  "story_type": "original_short_form",
  "hook": "Strong opening hook",
  "ending_type": "twist_or_payoff",
  "parts": [
    {{
      "part": 1,
      "title": "Part title",
      "scenes": [
        {{
          "scene": 1,
          "purpose": "hook",
          "narration": "Hindi narration",
          "visual": "Detailed cinematic real-world visual description",
          "dialogue": "",
          "suspense": "What unanswered question or tension exists"
        }}
      ]
    }}
  ]
}}

Remember:
The short must be written specifically as a short.
It must NOT be a compressed copy of a full-length story.
"""


def build_full_prompt(config, topic, story_text, parts, scenes):
    title = config.get("TITLE", topic)

    return f"""
You are an expert cinematic storyteller.

Create a complete long-form story.

TITLE:
{title}

TOPIC:
{topic}

USER STORY TEXT:
{story_text if story_text else "(No additional story text provided.)"}

FORMAT:
FULL VIDEO

Create a coherent beginning, development, climax and ending.

The story must have:
- Strong opening
- Character introduction
- Clear conflict
- Escalation
- Emotional development
- Climax
- Resolution

Do not write a short-video summary.

SCENE COUNT:
Exactly {parts} part(s), with exactly {scenes} scenes per part.

TOTAL SCENES:
Exactly {parts * scenes} scenes.

Each scene must move the story forward.

Use natural Hindi.
Characters should behave like real people in a real-world environment.
Keep visual descriptions cinematic and realistic.

OUTPUT MUST BE VALID JSON ONLY.

Use this exact structure:

{{
  "status": "completed",
  "format": "full",
  "title": "{title}",
  "topic": "{topic}",
  "story_type": "long_form",
  "parts": [
    {{
      "part": 1,
      "title": "Part title",
      "scenes": [
        {{
          "scene": 1,
          "purpose": "opening",
          "narration": "Hindi narration",
          "visual": "Detailed cinematic real-world visual description",
          "dialogue": "",
          "suspense": ""
        }}
      ]
    }}
  ]
}}
"""


def call_gemini(prompt):
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not set")

    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{MODEL}:generateContent?key={GEMINI_API_KEY}"
    )

    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "text": prompt
                    }
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.85,
            "topP": 0.95,
            "maxOutputTokens": 30000,
        },
    }

    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
        },
        method="POST",
    )

    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(
                request,
                timeout=180,
            ) as response:
                raw = response.read().decode("utf-8")

            result = json.loads(raw)

            candidates = result.get("candidates", [])

            if not candidates:
                raise RuntimeError(
                    f"Gemini returned no candidates: {raw[:1000]}"
                )

            parts_data = (
                candidates[0]
                .get("content", {})
                .get("parts", [])
            )

            text_parts = []

            for part in parts_data:
                if isinstance(part, dict) and "text" in part:
                    text_parts.append(part["text"])

            text = "\n".join(text_parts).strip()

            if not text:
                raise RuntimeError("Gemini returned empty text")

            return text

        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")

            last_error = RuntimeError(
                f"Gemini HTTP {exc.code}: {body[:1000]}"
            )

            if exc.code not in (429, 500, 502, 503, 504):
                raise last_error

            if attempt < MAX_RETRIES:
                delay = min(
                    INITIAL_BACKOFF * (2 ** (attempt - 1)),
                    MAX_BACKOFF,
                )

                print(
                    f"Gemini temporary error HTTP {exc.code}. "
                    f"Retrying in {delay}s..."
                )

                time.sleep(delay)

        except Exception as exc:
            last_error = exc

            if attempt < MAX_RETRIES:
                delay = min(
                    INITIAL_BACKOFF * (2 ** (attempt - 1)),
                    MAX_BACKOFF,
                )

                print(
                    f"Gemini request failed: {exc}. "
                    f"Retrying in {delay}s..."
                )

                time.sleep(delay)

    raise last_error or RuntimeError("Gemini request failed")


def extract_json(text):
    text = text.strip()

    if text.startswith("```"):
        text = re.sub(
            r"^```(?:json)?\s*",
            "",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(r"\s*```$", "", text)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")

    if start == -1 or end == -1 or end <= start:
        raise RuntimeError("Gemini response does not contain valid JSON")

    candidate = text[start:end + 1]

    try:
        return json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Could not parse Gemini JSON: {exc}"
        )


def validate_story(data, config, expected_format):
    if not isinstance(data, dict):
        raise RuntimeError("Story output is not a JSON object")

    if data.get("status") != "completed":
        data["status"] = "completed"

    actual_format = str(data.get("format", "")).lower().strip()

    if actual_format != expected_format:
        raise RuntimeError(
            f"Wrong story format. Expected {expected_format}, "
            f"got {actual_format}"
        )

    parts_expected = read_int(config, "PARTS", 1)
    scenes_expected = read_int(config, "SCENES", 10)

    parts = data.get("parts")

    if not isinstance(parts, list):
        raise RuntimeError("Story has no valid parts array")

    if len(parts) != parts_expected:
        raise RuntimeError(
            f"Expected {parts_expected} parts, got {len(parts)}"
        )

    total_scenes = 0

    for part_index, part in enumerate(parts, start=1):
        if not isinstance(part, dict):
            raise RuntimeError(
                f"Part {part_index} is not an object"
            )

        scenes = part.get("scenes")

        if not isinstance(scenes, list):
            raise RuntimeError(
                f"Part {part_index} has no scenes"
            )

        if len(scenes) != scenes_expected:
            raise RuntimeError(
                f"Part {part_index}: expected "
                f"{scenes_expected} scenes, got {len(scenes)}"
            )

        for scene_index, scene in enumerate(scenes, start=1):
            if not isinstance(scene, dict):
                raise RuntimeError(
                    f"Part {part_index} Scene {scene_index} "
                    f"is not an object"
                )

            narration = str(scene.get("narration", "")).strip()
            visual = str(scene.get("visual", "")).strip()

            if not narration:
                raise RuntimeError(
                    f"Missing narration for Part "
                    f"{part_index} Scene {scene_index}"
                )

            if not visual:
                raise RuntimeError(
                    f"Missing visual for Part "
                    f"{part_index} Scene {scene_index}"
                )

            scene["scene"] = scene_index

            if expected_format == "short":
                purpose = str(scene.get("purpose", "")).strip()

                if not purpose:
                    scene["purpose"] = "story"

        part["part"] = part_index

        total_scenes += len(scenes)

    expected_total = parts_expected * scenes_expected

    if total_scenes != expected_total:
        raise RuntimeError(
            f"Expected {expected_total} total scenes, "
            f"got {total_scenes}"
        )

    if expected_format == "short":
        hook = str(data.get("hook", "")).strip()

        if not hook:
            raise RuntimeError(
                "Short story is missing its hook"
            )

        data["story_type"] = "original_short_form"

    else:
        data["story_type"] = "long_form"

    return data


def main():
    print("=" * 60)
    print("        GENERATING STORY")
    print("=" * 60)

    config, raw_text = read_config()

    topic = config.get("TOPIC", "").strip()

    if not topic:
        raise RuntimeError("TOPIC is missing from Input/topic.txt")

    expected_format = normalize_format(config)

    parts = read_int(config, "PARTS", 1)
    scenes = read_int(config, "SCENES", 10)

    story_text = extract_story_text(raw_text)

    title = config.get("TITLE", topic)

    print(f"Title : {title}")
    print(f"Topic : {topic}")
    print(f"Format: {expected_format}")
    print(f"Parts : {parts}")
    print(f"Scenes: {scenes}")
    print()

    if expected_format == "short":
        print("SHORT MODE:")
        print("  Original short-form story")
        print("  Hook -> Suspense -> Escalation -> Twist -> Payoff")
        print("  NOT a cut-down version of the full story")
        print()

        prompt = build_short_prompt(
            config,
            topic,
            story_text,
            parts,
            scenes,
        )

    else:
        print("FULL MODE:")
        print("  Long-form cinematic story")
        print()

        prompt = build_full_prompt(
            config,
            topic,
            story_text,
            parts,
            scenes,
        )

    response_text = call_gemini(prompt)

    data = extract_json(response_text)

    data = validate_story(
        data,
        config,
        expected_format,
    )

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    data["_generation"] = {
        "format": expected_format,
        "title": title,
        "topic": topic,
        "parts": parts,
        "scenes_per_part": scenes,
        "total_scenes": parts * scenes,
        "story_type": (
            "original_short_form"
            if expected_format == "short"
            else "long_form"
        ),
        "generated_by": MODEL,
    }

    OUTPUT_FILE.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print()
    print("=" * 60)
    print("STORY GENERATION SUCCESS")
    print("=" * 60)
    print(f"Output: {OUTPUT_FILE}")
    print(f"Format: {expected_format}")
    print(f"Total scenes: {parts * scenes}")

    if expected_format == "short":
        print("Story type: ORIGINAL SHORT-FORM")
        print("Hook: VERIFIED")
        print("Ending payoff/twist: REQUIRED")

    print("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
