#!/usr/bin/env python3

import asyncio
import json
import re
import subprocess
from pathlib import Path

INPUT = Path("Input/topic.txt")
NARRATION = Path("output/narration/narration.json")
OUT = Path("output/narration/audio")
MANIFEST = Path("output/narration/audio_jobs.json")

# Ordered fallback list.
# Hindi voices first; if one fails, try the next one.
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


def cfg_value(key, default=""):
    if not INPUT.exists():
        return default

    for raw in INPUT.read_text(encoding="utf-8").splitlines():
        line = raw.strip()

        if not line or line.startswith("#") or "=" not in line:
            continue

        k, v = line.split("=", 1)

        if k.strip() == key:
            v = v.strip()

            if "#" in v:
                v = v.split("#", 1)[0].strip()

            return v.strip().strip('"').strip("'")

    return default


def parse_rate(value):
    match = re.search(
        r"([+-]?\d+(?:\.\d+)?)\s*%",
        value or ""
    )

    if not match:
        return "+0%"

    number = float(match.group(1))

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

    return round(float(result.stdout.strip()), 3)


async def synthesize(text, voice, rate, output):
    import edge_tts

    communicate = edge_tts.Communicate(
        text=text,
        voice=voice,
        rate=rate,
    )

    await communicate.save(str(output))


async def synthesize_with_fallback(
    text,
    voices,
    configured_rate,
    output,
):
    """
    Try each Hindi voice with the configured rate first.
    If Edge TTS returns no usable audio, retry that voice
    without an explicit rate.
    """

    attempts = []

    for voice in voices:

        # Attempt 1: configured rate
        attempts.append(
            {
                "voice": voice,
                "rate": configured_rate,
            }
        )

        output.unlink(missing_ok=True)

        try:
            print(
                f"  TRY  {voice} | rate={configured_rate}"
            )

            await synthesize(
                text,
                voice,
                configured_rate,
                output,
            )

            if (
                output.exists()
                and output.stat().st_size > 1000
            ):
                return voice, configured_rate, attempts

            print(
                f"  RETRY {voice} | "
                "default rate"
            )

        except Exception as exc:
            print(
                f"  RETRY {voice} | "
                f"default rate | first error: {exc}"
            )

        # Attempt 2: let Edge TTS use its default rate.
        attempts.append(
            {
                "voice": voice,
                "rate": None,
            }
        )

        output.unlink(missing_ok=True)

        try:
            print(
                f"  TRY  {voice} | rate=default"
            )

            await synthesize(
                text,
                voice,
                None,
                output,
            )

            if (
                output.exists()
                and output.stat().st_size > 1000
            ):
                return voice, None, attempts

        except Exception as exc:
            print(
                f"  FAIL {voice} | "
                f"rate=default | {exc}"
            )

        output.unlink(missing_ok=True)

    raise RuntimeError(
        "All configured Hindi Edge TTS voices failed. "
        f"Attempts: {json.dumps(attempts, ensure_ascii=False)}"
    )


async def main():
    if not NARRATION.exists():
        print("ERROR: narration.json not found")
        return 1

    OUT.mkdir(
        parents=True,
        exist_ok=True,
    )

    data = json.loads(
        NARRATION.read_text(
            encoding="utf-8"
        )
    )

    scenes = data.get("scenes", [])

    if not scenes:
        print("ERROR: No narration scenes found")
        return 1

    configured_voice = cfg_value(
        "VOICE",
        "male",
    ).lower()

    configured_speed = parse_rate(
        cfg_value(
            "SPEED",
            "+0%",
        )
    )

    voices = VOICE_MAP.get(
        configured_voice,
        VOICE_MAP["male"],
    )

    print("")
    print("===== TTS CONFIGURATION =====")
    print(f"Requested voice: {configured_voice}")
    print(f"Voice fallback: {', '.join(voices)}")
    print(f"Configured rate: {configured_speed}")
    print(f"Scenes: {len(scenes)}")
    print("==============================")
    print("")

    jobs = []
    failures = []

    for item in scenes:
        part = int(item["part"])
        scene = int(item["scene"])

        text = str(
            item.get("text", "")
        ).strip()

        raw_scene_speed = item.get(
            "speed",
            "",
        )

        if raw_scene_speed:
            scene_rate = parse_rate(
                str(raw_scene_speed)
            )
        else:
            scene_rate = configured_speed

        out_dir = OUT / f"part_{part:02d}"

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
            "requested_voice": configured_voice,
            "configured_rate": scene_rate,
            "output": str(output),
            "status": "pending",
        }

        # Resume support.
        if (
            output.exists()
            and output.stat().st_size > 1000
        ):
            try:
                job["duration"] = get_duration(
                    output
                )

                job["status"] = "completed"
                job["skipped"] = True

                jobs.append(job)

                print(
                    f"SKIP part {part:02d} "
                    f"scene {scene:02d}: "
                    "audio exists"
                )

                continue

            except Exception:
                output.unlink(
                    missing_ok=True
                )

        if not text:
            job["status"] = "failed"
            job["error"] = "Empty narration text"

            failures.append(job)
            jobs.append(job)

            continue

        print(
            f"GENERATE part {part:02d} "
            f"scene {scene:02d}"
        )
        print(
            f"  Requested voice: "
            f"{configured_voice}"
        )
        print(
            f"  Rate: {scene_rate}"
        )

        try:
            (
                used_voice,
                used_rate,
                attempts,
            ) = await synthesize_with_fallback(
                text,
                voices,
                scene_rate,
                output,
            )

            job["voice"] = used_voice
            job["rate"] = (
                used_rate
                if used_rate is not None
                else "default"
            )
            job["attempts"] = attempts

            job["duration"] = get_duration(
                output
            )

            job["status"] = "completed"

            print(
                f"OK part {part:02d} "
                f"scene {scene:02d}: "
                f"{job['duration']}s | "
                f"voice={used_voice} | "
                f"rate={job['rate']}"
            )

        except Exception as exc:
            job["status"] = "failed"
            job["error"] = str(exc)

            failures.append(job)
            jobs.append(job)

            print(
                f"FAILED part {part:02d} "
                f"scene {scene:02d}: {exc}"
            )

        # Save checkpoint after every scene.
        MANIFEST.write_text(
            json.dumps(
                {
                    "status": (
                        "failed"
                        if failures
                        else "completed"
                    ),
                    "requested_voice": configured_voice,
                    "configured_rate": configured_speed,
                    "total": len(jobs),
                    "completed": sum(
                        1
                        for j in jobs
                        if j["status"] == "completed"
                    ),
                    "failed": len(failures),
                    "jobs": jobs,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        # Stop after the first failed scene.
        if failures:
            break

    completed = sum(
        1
        for j in jobs
        if j["status"] == "completed"
    )

    failed = len(failures)

    final_status = (
        "completed"
        if failed == 0
        and completed == len(scenes)
        else "failed"
    )

    manifest = {
        "status": final_status,
        "requested_voice": configured_voice,
        "configured_rate": configured_speed,
        "total": len(scenes),
        "completed": completed,
        "failed": failed,
        "jobs": jobs,
    }

    MANIFEST.write_text(
        json.dumps(
            manifest,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print("")
    print("===== TTS SUMMARY =====")
    print(f"Total: {len(scenes)}")
    print(f"Completed: {completed}")
    print(f"Failed: {failed}")
    print(f"Requested voice: {configured_voice}")
    print(f"Configured rate: {configured_speed}")
    print("=======================")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(
        asyncio.run(main())
    )
