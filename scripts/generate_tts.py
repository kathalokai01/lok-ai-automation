#!/usr/bin/env python3

import asyncio
import json
import re
import subprocess
from pathlib import Path

from input_config import (
    load_input_config,
    cfg_bool,
    cfg_text,
    get_parts,
    get_scenes,
    get_max_retries,
    get_failure_policy,
    normalize_format,
)


NARRATION = Path("output/narration/narration.json")
OUT = Path("output/narration/audio")
MANIFEST = Path("output/narration/audio_jobs.json")


VOICE_MAP = {
    "male": [
        "hi-IN-MadhurNeural",
        "hi-IN-SwaraNeural",
    ],
    "female": [
        "hi-IN-SwaraNeural",
        "hi-IN-MadhurNeural",
    ],
}


# ============================================================
# HELPERS
# ============================================================

def save_manifest(data):
    MANIFEST.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temp = Path(
        f"{MANIFEST}.tmp"
    )

    temp.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    temp.replace(MANIFEST)


def parse_rate(value):
    match = re.search(
        r"([+-]?\d+(?:\.\d+)?)\s*%",
        str(value or ""),
    )

    if not match:
        return "+0%"

    number = float(
        match.group(1)
    )

    if number == 0:
        return "+0%"

    if number > 0:
        return f"+{number:g}%"

    return f"{number:g}%"


def get_duration(path):
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    return round(
        float(result.stdout.strip()),
        3,
    )


def valid_audio(path):
    if not path.is_file():
        return False

    if path.stat().st_size <= 1000:
        return False

    try:
        duration = get_duration(path)

        return duration > 0.05

    except Exception:
        return False


def scene_key(item):
    try:
        return (
            int(item.get("part")),
            int(item.get("scene")),
        )
    except Exception:
        return None


def expected_scene_keys(parts, scenes_per_part):
    return {
        (part, scene)
        for part in range(
            1,
            parts + 1,
        )
        for scene in range(
            1,
            scenes_per_part + 1,
        )
    }


# ============================================================
# EDGE TTS
# ============================================================

async def synthesize(
    text,
    voice,
    rate,
    output,
):
    import edge_tts

    communicate = edge_tts.Communicate(
        text=text,
        voice=voice,
        rate=rate,
    )

    await communicate.save(
        str(output)
    )


async def synthesize_with_retry(
    text,
    voices,
    rate,
    output,
    max_retries,
):
    attempts = []

    total_attempts = max(
        1,
        max_retries,
    )

    for attempt_number in range(
        1,
        total_attempts + 1,
    ):

        for voice in voices:

            attempt = {
                "attempt": attempt_number,
                "voice": voice,
                "rate": rate,
            }

            attempts.append(
                attempt
            )

            output.unlink(
                missing_ok=True
            )

            print(
                f"  TRY {attempt_number}/{total_attempts} "
                f"{voice} | rate={rate}"
            )

            try:
                await synthesize(
                    text,
                    voice,
                    rate,
                    output,
                )

                if valid_audio(
                    output
                ):
                    attempt["status"] = (
                        "completed"
                    )

                    return (
                        voice,
                        rate,
                        attempts,
                    )

                attempt["status"] = (
                    "invalid_audio"
                )

            except Exception as exc:

                attempt["status"] = (
                    "failed"
                )

                attempt["error"] = str(
                    exc
                )

                print(
                    f"  ERROR: {exc}"
                )

            output.unlink(
                missing_ok=True
            )

        if attempt_number < total_attempts:

            delay = min(
                2 ** attempt_number,
                15,
            )

            print(
                f"  Retry wait: {delay}s"
            )

            await asyncio.sleep(
                delay
            )

    raise RuntimeError(
        "All TTS attempts failed."
    )


# ============================================================
# MAIN
# ============================================================

async def main():

    print(
        "=============================================="
    )
    print(
        "             TTS GENERATION"
    )
    print(
        "=============================================="
    )

    if not NARRATION.is_file():
        print(
            "ERROR: narration.json not found."
        )
        return 1

    # --------------------------------------------------------
    # CENTRALIZED INPUT
    # --------------------------------------------------------

    config = load_input_config()

    video_format = normalize_format(
        cfg_text(
            config,
            "FORMAT",
            "short",
        )
    )

    requested_voice = cfg_text(
        config,
        "VOICE",
        "male",
    ).strip().lower()

    configured_speed = parse_rate(
        cfg_text(
            config,
            "SPEED",
            "+0%",
        )
    )

    captions = cfg_text(
        config,
        "CAPTIONS",
        "hindi",
    )

    parts = get_parts(
        config
    )

    scenes_per_part = get_scenes(
        config
    )

    max_retries = get_max_retries(
        config
    )

    failure_policy = get_failure_policy(
        config
    )

    resume_enabled = cfg_bool(
        config,
        "RESUME_ENABLED",
        True,
    )

    skip_completed = cfg_bool(
        config,
        "SKIP_COMPLETED_SCENES",
        True,
    )

    checkpoint_each_scene = cfg_bool(
        config,
        "SAVE_CHECKPOINT_AFTER_EACH_SCENE",
        True,
    )

    music_enabled = cfg_bool(
        config,
        "MUSIC",
        True,
    )

    sfx_enabled = cfg_bool(
        config,
        "SFX",
        True,
    )

    ambient_enabled = cfg_bool(
        config,
        "AMBIENT_SOUND",
        True,
    )

    # --------------------------------------------------------
    # VOICE
    # --------------------------------------------------------

    voices = VOICE_MAP.get(
        requested_voice
    )

    if not voices:
        print(
            f"ERROR: Unsupported VOICE: "
            f"{requested_voice}"
        )

        print(
            "Supported voices: male, female"
        )

        return 1

    # --------------------------------------------------------
    # LOAD NARRATION
    # --------------------------------------------------------

    try:
        data = json.loads(
            NARRATION.read_text(
                encoding="utf-8"
            )
        )

    except Exception as exc:
        print(
            f"ERROR: Could not read narration.json: "
            f"{exc}"
        )
        return 1

    scenes = data.get(
        "scenes",
        [],
    )

    if not isinstance(
        scenes,
        list,
    ) or not scenes:

        print(
            "ERROR: No narration scenes found."
        )
        return 1

    expected_total = (
        parts * scenes_per_part
    )

    if len(scenes) != expected_total:

        print(
            "ERROR: Narration scene count "
            "does not match Input."
        )

        print(
            f"Expected: {expected_total}"
        )

        print(
            f"Found: {len(scenes)}"
        )

        return 1

    # --------------------------------------------------------
    # EXACT SCENE VALIDATION
    # --------------------------------------------------------

    expected_keys = expected_scene_keys(
        parts,
        scenes_per_part,
    )

    actual_keys = set()

    for item in scenes:

        key = scene_key(
            item
        )

        if key is None:
            print(
                "ERROR: Invalid narration scene "
                "number."
            )
            return 1

        actual_keys.add(
            key
        )

    missing = sorted(
        expected_keys - actual_keys
    )

    extra = sorted(
        actual_keys - expected_keys
    )

    if missing:

        print(
            f"ERROR: Missing narration scenes: "
            f"{missing}"
        )

        return 1

    if extra:

        print(
            f"ERROR: Unexpected narration scenes: "
            f"{extra}"
        )

        return 1

    # --------------------------------------------------------
    # CONFIG SUMMARY
    # --------------------------------------------------------

    print()
    print(
        "=============== TTS CONFIG ==============="
    )
    print(
        f"FORMAT              : {video_format}"
    )
    print(
        f"VOICE               : {requested_voice}"
    )
    print(
        f"VOICE FALLBACK      : {', '.join(voices)}"
    )
    print(
        f"SPEED               : {configured_speed}"
    )
    print(
        f"CAPTIONS            : {captions}"
    )
    print(
        f"PARTS               : {parts}"
    )
    print(
        f"SCENES/PART         : {scenes_per_part}"
    )
    print(
        f"TOTAL SCENES        : {expected_total}"
    )
    print(
        f"MAX_RETRIES         : {max_retries}"
    )
    print(
        f"RESUME_ENABLED      : {resume_enabled}"
    )
    print(
        f"SKIP_COMPLETED      : {skip_completed}"
    )
    print(
        f"CHECKPOINT          : {checkpoint_each_scene}"
    )
    print(
        f"FAILURE_POLICY      : {failure_policy}"
    )
    print(
        f"MUSIC               : {music_enabled}"
    )
    print(
        f"SFX                 : {sfx_enabled}"
    )
    print(
        f"AMBIENT_SOUND       : {ambient_enabled}"
    )
    print(
        "=========================================="
    )

    # --------------------------------------------------------
    # EXISTING MANIFEST
    # --------------------------------------------------------

    existing_jobs = {}

    if (
        resume_enabled
        and MANIFEST.is_file()
    ):

        try:

            old_manifest = json.loads(
                MANIFEST.read_text(
                    encoding="utf-8"
                )
            )

            old_jobs = old_manifest.get(
                "jobs",
                [],
            )

            if isinstance(
                old_jobs,
                list,
            ):

                for job in old_jobs:

                    if not isinstance(
                        job,
                        dict,
                    ):
                        continue

                    key = scene_key(
                        job
                    )

                    if key is not None:
                        existing_jobs[key] = (
                            job
                        )

        except Exception as exc:

            print(
                f"WARNING: Existing TTS "
                f"manifest could not be read: "
                f"{exc}"
            )

    # --------------------------------------------------------
    # OUTPUT
    # --------------------------------------------------------

    OUT.mkdir(
        parents=True,
        exist_ok=True,
    )

    jobs = []
    failures = []

    # --------------------------------------------------------
    # PROCESS EVERY SCENE
    # --------------------------------------------------------

    for index, item in enumerate(
        scenes,
        start=1,
    ):

        part = int(
            item["part"]
        )

        scene = int(
            item["scene"]
        )

        key = (
            part,
            scene,
        )

        text = str(
            item.get(
                "text",
                "",
            )
        ).strip()

        # Scene-level speed from narration takes
        # priority, otherwise Input SPEED.
        scene_speed = item.get(
            "speed",
            configured_speed,
        )

        scene_speed = parse_rate(
            scene_speed
        )

        out_dir = (
            OUT
            / f"part_{part:02d}"
        )

        out_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        output = (
            out_dir
            / f"scene_{scene:02d}.mp3"
        )

        job = {
            "part": part,
            "scene": scene,
            "requested_voice": (
                requested_voice
            ),
            "configured_rate": (
                scene_speed
            ),
            "captions": captions,
            "format": video_format,
            "output": str(output),
            "status": "pending",
        }

        print()
        print(
            f"[{index}/{expected_total}] "
            f"Part {part} Scene {scene}"
        )

        # ----------------------------------------------------
        # RESUME
        # ----------------------------------------------------

        can_skip = (
            resume_enabled
            and skip_completed
            and valid_audio(output)
        )

        if can_skip:

            try:
                duration = get_duration(
                    output
                )

                old_job = existing_jobs.get(
                    key,
                    {},
                )

                job.update(
                    {
                        "status": "completed",
                        "duration": duration,
                        "voice": old_job.get(
                            "voice",
                            voices[0],
                        ),
                        "rate": old_job.get(
                            "rate",
                            scene_speed,
                        ),
                        "skipped": True,
                    }
                )

                jobs.append(
                    job
                )

                print(
                    "  SKIP: Existing valid "
                    "audio found."
                )

                if checkpoint_each_scene:
                    save_manifest(
                        {
                            "status": "in_progress",
                            "requested_voice": (
                                requested_voice
                            ),
                            "configured_rate": (
                                configured_speed
                            ),
                            "format": video_format,
                            "captions": captions,
                            "total": expected_total,
                            "completed": sum(
                                1
                                for j in jobs
                                if j["status"]
                                == "completed"
                            ),
                            "failed": len(
                                failures
                            ),
                            "jobs": jobs,
                        }
                    )

                continue

            except Exception:
                output.unlink(
                    missing_ok=True
                )

        # ----------------------------------------------------
        # EMPTY TEXT
        # ----------------------------------------------------

        if not text:

            job["status"] = "failed"

            job["error"] = (
                "Empty narration text."
            )

            failures.append(
                job
            )

            jobs.append(
                job
            )

            print(
                "  ERROR: Empty narration text."
            )

            if (
                failure_policy
                == "retry_then_checkpoint"
            ):
                break

            continue

        # ----------------------------------------------------
        # GENERATE
        # ----------------------------------------------------

        try:

            (
                used_voice,
                used_rate,
                attempts,
            ) = await synthesize_with_retry(
                text=text,
                voices=voices,
                rate=scene_speed,
                output=output,
                max_retries=max_retries,
            )

            duration = get_duration(
                output
            )

            job.update(
                {
                    "status": "completed",
                    "voice": used_voice,
                    "rate": used_rate,
                    "duration": duration,
                    "attempts": attempts,
                }
            )

            print(
                f"  OK: {duration}s"
            )

        except Exception as exc:

            output.unlink(
                missing_ok=True
            )

            job["status"] = "failed"

            job["error"] = str(
                exc
            )

            failures.append(
                job
            )

            print(
                f"  FAILED: {exc}"
            )

        jobs.append(
            job
        )

        # ----------------------------------------------------
        # CHECKPOINT
        # ----------------------------------------------------

        if checkpoint_each_scene:

            save_manifest(
                {
                    "status": (
                        "failed"
                        if failures
                        else "in_progress"
                    ),
                    "requested_voice": (
                        requested_voice
                    ),
                    "configured_rate": (
                        configured_speed
                    ),
                    "format": video_format,
                    "captions": captions,
                    "music": music_enabled,
                    "sfx": sfx_enabled,
                    "ambient_sound": (
                        ambient_enabled
                    ),
                    "total": expected_total,
                    "completed": sum(
                        1
                        for j in jobs
                        if j["status"]
                        == "completed"
                    ),
                    "failed": len(
                        failures
                    ),
                    "jobs": jobs,
                }
            )

        # ----------------------------------------------------
        # FAILURE POLICY
        # ----------------------------------------------------

        if failures:

            if (
                failure_policy
                == "retry_then_checkpoint"
            ):
                print(
                    "  FAILURE_POLICY: "
                    "retry_then_checkpoint"
                )
                break

    # --------------------------------------------------------
    # FINAL VALIDATION
    # --------------------------------------------------------

    completed = sum(
        1
        for job in jobs
        if job["status"] == "completed"
    )

    failed = len(
        failures
    )

    # Every expected scene must have valid audio.
    physical_audio = 0

    for item in scenes:

        part = int(
            item["part"]
        )

        scene = int(
            item["scene"]
        )

        path = (
            OUT
            / f"part_{part:02d}"
            / f"scene_{scene:02d}.mp3"
        )

        if valid_audio(path):
            physical_audio += 1

    if (
        completed == expected_total
        and failed == 0
        and physical_audio == expected_total
    ):
        final_status = "completed"

    else:
        final_status = "failed"

    # --------------------------------------------------------
    # FINAL MANIFEST
    # --------------------------------------------------------

    manifest = {
        "status": final_status,

        "requested_voice": (
            requested_voice
        ),

        "configured_rate": (
            configured_speed
        ),

        "format": video_format,

        "captions": captions,

        "music": music_enabled,

        "sfx": sfx_enabled,

        "ambient_sound": (
            ambient_enabled
        ),

        "parts": parts,

        "scenes_per_part": (
            scenes_per_part
        ),

        "total": expected_total,

        "completed": completed,

        "failed": failed,

        "physical_audio": (
            physical_audio
        ),

        "max_retries": max_retries,

        "resume_enabled": (
            resume_enabled
        ),

        "skip_completed_scenes": (
            skip_completed
        ),

        "failure_policy": (
            failure_policy
        ),

        "jobs": jobs,
    }

    save_manifest(
        manifest
    )

    # --------------------------------------------------------
    # SUMMARY
    # --------------------------------------------------------

    print()
    print(
        "=============================================="
    )
    print(
        "               TTS SUMMARY"
    )
    print(
        "=============================================="
    )

    print(
        f"Status          : {final_status}"
    )

    print(
        f"Expected        : {expected_total}"
    )

    print(
        f"Completed       : {completed}"
    )

    print(
        f"Failed          : {failed}"
    )

    print(
        f"Physical audio  : {physical_audio}"
    )

    print(
        f"Voice           : {requested_voice}"
    )

    print(
        f"Speed           : {configured_speed}"
    )

    print(
        f"Captions        : {captions}"
    )

    print(
        f"Manifest        : {MANIFEST}"
    )

    print(
        "=============================================="
    )

    return (
        0
        if final_status == "completed"
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(
        asyncio.run(
            main()
        )
    )
