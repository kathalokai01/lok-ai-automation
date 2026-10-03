#!/usr/bin/env python3

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from input_config import (
    load_input_config,
    validate_config,
    cfg_bool,
    cfg_text,
    get_parts,
    get_scenes,
    get_story_length,
    normalize_format,
    resolve_topic,
    resolve_story_text,
)


OUTPUT_DIR = Path("output/story")
OUTPUT_FILE = OUTPUT_DIR / "story.json"
TITLE_FILE = OUTPUT_DIR / "final_title.txt"

GEMINI_API_KEY = os.environ.get(
    "GEMINI_API_KEY",
    "",
).strip()

MODEL = os.environ.get(
    "GEMINI_MODEL",
    "gemini-3.5-flash-lite",
)

MAX_RETRIES = 5
INITIAL_BACKOFF = 8
MAX_BACKOFF = 90


def clean_title(title):
    title = str(title or "").strip()

    title = re.sub(
        r"^['\"]+|['\"]+$",
        "",
        title,
    )

    title = re.sub(
        r"^(title|शीर्षक)\s*:\s*",
        "",
        title,
        flags=re.IGNORECASE,
    )

    title = re.sub(
        r"\s+",
        " ",
        title,
    )

    return title.strip()


def extract_json(text):
    text = text.strip()

    if text.startswith("```"):
        text = re.sub(
            r"^```(?:json)?\s*",
            "",
            text,
            flags=re.IGNORECASE,
        )

        text = re.sub(
            r"\s*```$",
            "",
            text,
        )

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")

    if start == -1 or end == -1 or end <= start:
        raise RuntimeError(
            "Gemini response does not contain valid JSON"
        )

    candidate = text[start:end + 1]

    try:
        return json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Could not parse Gemini JSON: {exc}"
        )


def call_gemini(prompt):
    if not GEMINI_API_KEY:
        raise RuntimeError(
            "GEMINI_API_KEY is not set"
        )

    url = (
        "https://generativelanguage.googleapis.com/"
        "v1beta/models/"
        f"{MODEL}:generateContent"
        f"?key={GEMINI_API_KEY}"
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

    data = json.dumps(
        payload,
        ensure_ascii=False,
    ).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
        },
        method="POST",
    )

    last_error = None

    for attempt in range(
        1,
        MAX_RETRIES + 1,
    ):
        try:

            with urllib.request.urlopen(
                request,
                timeout=180,
            ) as response:

                raw = response.read().decode(
                    "utf-8"
                )

            result = json.loads(raw)

            candidates = result.get(
                "candidates",
                [],
            )

            if not candidates:
                raise RuntimeError(
                    "Gemini returned no candidates"
                )

            parts_data = (
                candidates[0]
                .get("content", {})
                .get("parts", [])
            )

            text_parts = []

            for part in parts_data:

                if (
                    isinstance(part, dict)
                    and "text" in part
                ):
                    text_parts.append(
                        part["text"]
                    )

            text = "\n".join(
                text_parts
            ).strip()

            if not text:
                raise RuntimeError(
                    "Gemini returned empty text"
                )

            return text

        except urllib.error.HTTPError as exc:

            body = exc.read().decode(
                "utf-8",
                errors="replace",
            )

            last_error = RuntimeError(
                f"Gemini HTTP {exc.code}: "
                f"{body[:1000]}"
            )

            if exc.code not in {
                429,
                500,
                502,
                503,
                504,
            }:
                raise last_error

            if attempt < MAX_RETRIES:

                delay = min(
                    INITIAL_BACKOFF
                    * (2 ** (attempt - 1)),
                    MAX_BACKOFF,
                )

                print(
                    f"Gemini temporary error "
                    f"HTTP {exc.code}. "
                    f"Retrying in {delay}s..."
                )

                time.sleep(delay)

        except Exception as exc:

            last_error = exc

            if attempt < MAX_RETRIES:

                delay = min(
                    INITIAL_BACKOFF
                    * (2 ** (attempt - 1)),
                    MAX_BACKOFF,
                )

                print(
                    f"Gemini request failed: "
                    f"{exc}. "
                    f"Retrying in {delay}s..."
                )

                time.sleep(delay)

    raise last_error or RuntimeError(
        "Gemini request failed"
    )


def generate_title_from_story(
    story_text,
    audience,
):
    """
    Generate the final title only when TOPIC is empty.

    This title becomes the canonical title for
    the complete pipeline.
    """

    prompt = f"""
You are creating the final title for a video story.

USER STORY:
{story_text}

AUDIENCE:
{audience}

Create ONE natural, memorable Hindi video title.

Rules:
- Return only the title.
- No explanation.
- No quotation marks.
- No hashtags.
- Do not add "Title:".
- Do not invent a completely different story.
- The title must accurately represent the supplied story.
- Keep it concise and suitable for YouTube.

TITLE:
"""

    response = call_gemini(prompt)

    title = clean_title(response)

    if not title:
        raise RuntimeError(
            "AI generated an empty title"
        )

    return title


def build_common_context(
    config,
    title,
    topic,
    story_text,
    expected_format,
    parts,
    scenes,
):
    audience = cfg_text(
        config,
        "AUDIENCE",
        "adult",
    )

    story_length = get_story_length(
        config
    )

    part_hook = cfg_bool(
        config,
        "PART_HOOK",
        True,
    )

    part_suspense = cfg_bool(
        config,
        "PART_SUSPENSE",
        True,
    )

    final_resolution = cfg_bool(
        config,
        "FINAL_RESOLUTION",
        True,
    )

    return f"""
FINAL TITLE:
{title}

INPUT TOPIC:
{topic if topic else "(TOPIC was empty)"}

USER STORY TEXT:
{story_text if story_text else "(No user story text provided.)"}

FORMAT:
{expected_format}

AUDIENCE:
{audience}

STORY LENGTH:
{story_length}

PARTS:
{parts}

SCENES PER PART:
{scenes}

PART HOOK REQUIRED:
{str(part_hook).lower()}

PART SUSPENSE REQUIRED:
{str(part_suspense).lower()}

FINAL RESOLUTION REQUIRED:
{str(final_resolution).lower()}
"""


def build_short_prompt(
    config,
    title,
    topic,
    story_text,
    parts,
    scenes,
):
    common = build_common_context(
        config,
        title,
        topic,
        story_text,
        "short",
        parts,
        scenes,
    )

    part_hook = cfg_bool(
        config,
        "PART_HOOK",
        True,
    )

    part_suspense = cfg_bool(
        config,
        "PART_SUSPENSE",
        True,
    )

    final_resolution = cfg_bool(
        config,
        "FINAL_RESOLUTION",
        True,
    )

    hook_rule = (
        "EVERY PART must begin with a strong "
        "hook."
        if part_hook
        else
        "Do not force a separate hook at every "
        "part."
    )

    suspense_rule = (
        "Every part except the final part must "
        "end with an unanswered question, "
        "reversal, danger or cliffhanger."
        if part_suspense
        else
        "Suspense should be used naturally "
        "without mandatory part cliffhangers."
    )

    resolution_rule = (
        "The final part must contain a complete "
        "resolution and intentional final beat."
        if final_resolution
        else
        "The ending may remain open if the story "
        "naturally requires it."
    )

    return f"""
You are an expert short-form cinematic storyteller.

Create an ORIGINAL short-video story.

{common}

CRITICAL:
This is NOT a shortened version of a full video.

Do NOT:
- write a long-form story and cut it down
- summarize a hypothetical full story
- select random scenes from a longer story
- make the ending feel accidentally cut off
- tell viewers to watch a full version

The short must be independently written from beginning
to ending.

SHORT STORY DESIGN:

1. COLD HOOK
The first scene must immediately create curiosity,
danger, emotion, mystery or a surprising situation.

2. FAST SETUP
Only essential context should be provided.

3. MYSTERY
Introduce an unanswered question, secret,
contradiction, danger or unexplained event.

4. ESCALATION
Every scene must add new information,
raise stakes, reveal a clue, misdirect the viewer
or change the situation.

5. REVEAL
Reveal an important truth or clue.

6. FINAL PAYOFF
The story must intentionally pay off the central
question.

7. FINAL BEAT
End with a memorable final sentence or visual beat.

PART RULES:

{hook_rule}

{suspense_rule}

{resolution_rule}

SHORT-FORM RULES:

- The opening must work within the first few seconds.
- No unnecessary introduction.
- No filler scenes.
- No repeated information.
- No generic exposition.
- Every scene must have a purpose.
- The final scenes must feel deliberately written.
- The short must feel complete.
- Natural Hindi narration.
- Real-world human behavior.
- Cinematic realistic visual descriptions.
- No cartoon/comic/anime visual language.

SCENE COUNT:

Exactly {parts} part(s).

Exactly {scenes} scenes per part.

Exactly {parts * scenes} total scenes.

OUTPUT JSON ONLY.

Required structure:

{{
  "status": "completed",
  "format": "short",
  "title": "{title}",
  "topic": "{topic}",
  "story_type": "original_short_form",
  "hook": "Opening hook",
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
          "visual": "Detailed realistic cinematic visual",
          "dialogue": "",
          "suspense": "Question or tension"
        }}
      ]
    }}
  ]
}}
"""


def build_full_prompt(
    config,
    title,
    topic,
    story_text,
    parts,
    scenes,
):
    common = build_common_context(
        config,
        title,
        topic,
        story_text,
        "full",
        parts,
        scenes,
    )

    part_hook = cfg_bool(
        config,
        "PART_HOOK",
        True,
    )

    part_suspense = cfg_bool(
        config,
        "PART_SUSPENSE",
        True,
    )

    final_resolution = cfg_bool(
        config,
        "FINAL_RESOLUTION",
        True,
    )

    hook_rule = (
        "Each part must have a strong opening hook."
        if part_hook
        else
        "Use natural openings without forcing "
        "a separate hook."
    )

    suspense_rule = (
        "Every part except the final part should "
        "end with meaningful suspense/cliffhanger."
        if part_suspense
        else
        "Use suspense naturally where appropriate."
    )

    resolution_rule = (
        "The final part must fully resolve the "
        "central conflict."
        if final_resolution
        else
        "Do not force a complete resolution if "
        "the supplied story intentionally remains open."
    )

    return f"""
You are an expert long-form cinematic storyteller.

Create a complete original long-form story.

{common}

The story must NOT be written like a short-form
summary.

STRUCTURE:

- Strong opening
- Character introduction
- Situation establishment
- Central conflict
- Rising tension
- Emotional development
- Major turning points
- Climax
- Resolution

PART RULES:

{hook_rule}

{suspense_rule}

{resolution_rule}

CONTINUITY:

- Characters must remain logically consistent.
- Locations must remain consistent.
- Actions must connect between scenes.
- Time progression must make sense.
- Each scene must move the story forward.
- Avoid repetitive scenes.

VISUAL WRITING:

- Real people.
- Real-world environments.
- Cinematic live-action visual descriptions.
- Believable human behavior.
- Natural physical actions.
- No unnecessary cartoon/comic/anime language.

LANGUAGE:

Use natural Hindi narration.

SCENE COUNT:

Exactly {parts} part(s).

Exactly {scenes} scenes per part.

Exactly {parts * scenes} total scenes.

OUTPUT JSON ONLY.

Required structure:

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
          "visual": "Detailed realistic cinematic visual",
          "dialogue": "",
          "suspense": ""
        }}
      ]
    }}
  ]
}}
"""


def validate_story(
    data,
    config,
    expected_format,
    title,
    topic,
):
    if not isinstance(data, dict):
        raise RuntimeError(
            "Story output is not a JSON object"
        )

    data["status"] = "completed"

    actual_format = str(
        data.get("format", "")
    ).lower().strip()

    if actual_format != expected_format:
        raise RuntimeError(
            f"Wrong story format. "
            f"Expected {expected_format}, "
            f"got {actual_format}"
        )

    parts_expected = get_parts(
        config
    )

    scenes_expected = get_scenes(
        config
    )

    parts = data.get("parts")

    if not isinstance(parts, list):
        raise RuntimeError(
            "Story has no valid parts array"
        )

    if len(parts) != parts_expected:
        raise RuntimeError(
            f"Expected {parts_expected} parts, "
            f"got {len(parts)}"
        )

    total_scenes = 0

    for part_index, part in enumerate(
        parts,
        start=1,
    ):

        if not isinstance(part, dict):
            raise RuntimeError(
                f"Part {part_index} "
                "is not an object"
            )

        scene_list = part.get(
            "scenes"
        )

        if not isinstance(
            scene_list,
            list,
        ):
            raise RuntimeError(
                f"Part {part_index} "
                "has no scenes"
            )

        if len(scene_list) != scenes_expected:
            raise RuntimeError(
                f"Part {part_index}: "
                f"expected {scenes_expected} "
                f"scenes, got "
                f"{len(scene_list)}"
            )

        for scene_index, scene in enumerate(
            scene_list,
            start=1,
        ):

            if not isinstance(
                scene,
                dict,
            ):
                raise RuntimeError(
                    f"Part {part_index} "
                    f"Scene {scene_index} "
                    "is not an object"
                )

            narration = str(
                scene.get(
                    "narration",
                    "",
                )
            ).strip()

            visual = str(
                scene.get(
                    "visual",
                    "",
                )
            ).strip()

            if not narration:
                raise RuntimeError(
                    f"Missing narration for "
                    f"Part {part_index} "
                    f"Scene {scene_index}"
                )

            if not visual:
                raise RuntimeError(
                    f"Missing visual for "
                    f"Part {part_index} "
                    f"Scene {scene_index}"
                )

            scene["scene"] = scene_index

            if expected_format == "short":

                if not str(
                    scene.get(
                        "purpose",
                        "",
                    )
                ).strip():

                    scene["purpose"] = (
                        "story"
                    )

        part["part"] = part_index

        total_scenes += len(
            scene_list
        )

    expected_total = (
        parts_expected
        * scenes_expected
    )

    if total_scenes != expected_total:
        raise RuntimeError(
            f"Expected {expected_total} "
            f"total scenes, got "
            f"{total_scenes}"
        )

    # The final title must always be the
    # canonical title selected before generation.
    data["title"] = title
    data["topic"] = topic
    data["format"] = expected_format

    if expected_format == "short":

        hook = str(
            data.get(
                "hook",
                "",
            )
        ).strip()

        if not hook:
            raise RuntimeError(
                "Short story is missing "
                "its hook"
            )

        data["story_type"] = (
            "original_short_form"
        )

    else:

        data["story_type"] = (
            "long_form"
        )

    return data


def main():

    print("=" * 60)
    print("        GENERATING STORY")
    print("=" * 60)

    config = load_input_config()

    validate_config(
        config
    )

    expected_format = normalize_format(
        config
    )

    topic = resolve_topic(
        config
    )

    story_text = resolve_story_text(
        config
    )

    parts = get_parts(
        config
    )

    scenes = get_scenes(
        config
    )

    audience = cfg_text(
        config,
        "AUDIENCE",
        "adult",
    )

    # --------------------------------------------------
    # FINAL TITLE
    # --------------------------------------------------

    if topic:

        title = clean_title(
            topic
        )

        title_source = (
            "INPUT TOPIC"
        )

    elif story_text:

        print(
            "TOPIC is empty."
        )

        print(
            "Generating final title "
            "from STORY_TEXT..."
        )

        title = generate_title_from_story(
            story_text,
            audience,
        )

        title_source = (
            "AI GENERATED FROM STORY_TEXT"
        )

    else:

        raise RuntimeError(
            "Both TOPIC and STORY_TEXT "
            "are empty."
        )

    if not title:
        raise RuntimeError(
            "Final title is empty."
        )

    print()
    print(
        f"Final title  : {title}"
    )
    print(
        f"Title source : {title_source}"
    )
    print(
        f"Topic        : "
        f"{topic or '[empty]'}"
    )
    print(
        f"Format       : "
        f"{expected_format}"
    )
    print(
        f"Parts        : {parts}"
    )
    print(
        f"Scenes/part  : {scenes}"
    )
    print(
        f"Total scenes : "
        f"{parts * scenes}"
    )
    print(
        f"Story length : "
        f"{get_story_length(config)}"
    )
    print()

    # --------------------------------------------------
    # BUILD FORMAT-SPECIFIC STORY
    # --------------------------------------------------

    if expected_format == "short":

        print(
            "SHORT MODE:"
        )

        print(
            "  Original short-form story"
        )

        print(
            "  Hook -> Mystery -> "
            "Escalation -> Reveal -> "
            "Payoff"
        )

        print(
            "  NOT a cut-down full video"
        )

        prompt = build_short_prompt(
            config,
            title,
            topic,
            story_text,
            parts,
            scenes,
        )

    else:

        print(
            "FULL MODE:"
        )

        print(
            "  Complete long-form story"
        )

        prompt = build_full_prompt(
            config,
            title,
            topic,
            story_text,
            parts,
            scenes,
        )

    # --------------------------------------------------
    # GEMINI GENERATION
    # --------------------------------------------------

    response_text = call_gemini(
        prompt
    )

    data = extract_json(
        response_text
    )

    data = validate_story(
        data,
        config,
        expected_format,
        title,
        topic,
    )

    # --------------------------------------------------
    # SAVE
    # --------------------------------------------------

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    data["_generation"] = {
        "format": expected_format,
        "title": title,
        "title_source": title_source,
        "topic": topic,
        "story_text_provided": bool(
            story_text
        ),
        "audience": audience,
        "story_length": get_story_length(
            config
        ),
        "parts": parts,
        "scenes_per_part": scenes,
        "total_scenes": (
            parts * scenes
        ),
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

    # Canonical title for all later
    # packaging/rendering scripts.
    TITLE_FILE.write_text(
        title,
        encoding="utf-8",
    )

    print()
    print("=" * 60)
    print("STORY GENERATION SUCCESS")
    print("=" * 60)

    print(
        f"Story output : "
        f"{OUTPUT_FILE}"
    )

    print(
        f"Final title  : "
        f"{TITLE_FILE}"
    )

    print(
        f"Format       : "
        f"{expected_format}"
    )

    print(
        f"Total scenes : "
        f"{parts * scenes}"
    )

    if expected_format == "short":

        print(
            "Story type   : "
            "ORIGINAL SHORT-FORM"
        )

        print(
            "Hook         : VERIFIED"
        )

        print(
            "Ending       : "
            "PAYOFF/TWIST REQUIRED"
        )

    else:

        print(
            "Story type   : LONG-FORM"
        )

    print("=" * 60)


if __name__ == "__main__":

    try:
        main()

    except Exception as exc:

        print(
            f"ERROR: {exc}",
            file=sys.stderr,
        )

        sys.exit(1)
