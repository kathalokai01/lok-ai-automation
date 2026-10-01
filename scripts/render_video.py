#!/usr/bin/env python3

import json
import os
import subprocess
from pathlib import Path


INPUT = Path("Input/topic.txt")
NARRATION = Path("output/narration/audio_jobs.json")
VISUALS = Path("output/visuals/visual_jobs.json")

SCENES_OUT = Path("output/scenes")
PARTS_OUT = Path("output/parts")
MANIFEST_OUT = Path("output/video_render_manifest.json")


def load_json(path: Path):
    if not path.exists():
        raise SystemExit(f"ERROR: Required file not found: {path}")

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"ERROR: Invalid JSON in {path}: {exc}")


def read_config(key: str, default: str = "") -> str:
    if not INPUT.exists():
        return default

    for raw in INPUT.read_text(encoding="utf-8").splitlines():
        line = raw.strip()

        if not line:
            continue

        if line.startswith("#"):
            continue

        if "=" not in line:
            continue

        k, value = line.split("=", 1)

        if k.strip() != key:
            continue

        value = value.split("#", 1)[0].strip()

        if (
            len(value) >= 2
            and value[0] == value[-1]
            and value[0] in ('"', "'")
        ):
            value = value[1:-1]

        return value.strip()

    return default


def run_command(command):
    print()
    print("RUN:")
    print(" ".join(str(x) for x in command))
    print()

    subprocess.run(command, check=True)


def probe_duration(path: Path) -> float:
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

    value = result.stdout.strip()

    if not value:
        raise RuntimeError(f"Could not determine duration: {path}")

    return round(float(value), 3)


def valid_video(path: Path) -> bool:
    if not path.exists():
        return False

    if path.stat().st_size < 1000:
        return False

    try:
        duration = probe_duration(path)
        return duration > 0.01
    except Exception:
        return False


def get_output_geometry(video_format: str):
    video_format = video_format.strip().lower()

    if video_format in {
        "short",
        "shorts",
        "vertical",
        "9:16",
    }:
        return 720, 1280

    if video_format in {
        "square",
        "1:1",
    }:
        return 1080, 1080

    return 1920, 1080


def build_video_filter(video_format: str, fps: int) -> str:
    width, height = get_output_geometry(video_format)

    return (
        f"scale={width}:{height}:"
        f"force_original_aspect_ratio=increase,"
        f"crop={width}:{height},"
        f"fps={fps}"
    )


def normalize_jobs(manifest, kind):
    jobs = manifest.get("jobs", [])

    result = {}

    for job in jobs:
        try:
            part = int(job.get("part"))
            scene = int(job.get("scene"))
        except (TypeError, ValueError):
            continue

        status = str(job.get("status", "")).lower()

        if kind == "audio":
            is_complete = status in {
                "completed",
                "complete",
                "success",
                "generated",
            }
        else:
            is_complete = status in {
                "completed",
                "complete",
                "success",
                "generated",
            }

        if is_complete:
            result[(part, scene)] = job

    return result


def resolve_audio(job, part, scene):
    candidates = [
        job.get("output"),
        job.get("output_path"),
        job.get("audio"),
        job.get("audio_path"),
        f"output/narration/audio/part_{part:02d}/scene_{scene:02d}.mp3",
    ]

    for candidate in candidates:
        if not candidate:
            continue

        path = Path(str(candidate))

        if path.exists():
            return path

    return Path(
        f"output/narration/audio/part_{part:02d}/scene_{scene:02d}.mp3"
    )


def resolve_visual(job, part, scene):
    candidates = [
        job.get("asset_path"),
        job.get("output"),
        job.get("output_path"),
        job.get("visual"),
        job.get("visual_path"),
        f"output/visuals/part_{part:02d}/scene_{scene:02d}.png",
    ]

    for candidate in candidates:
        if not candidate:
            continue

        path = Path(str(candidate))

        if path.exists():
            return path

    return Path(
        f"output/visuals/part_{part:02d}/scene_{scene:02d}.png"
    )


def render_scene(
    visual: Path,
    audio: Path,
    output: Path,
    fps: int,
    video_format: str,
):
    output.parent.mkdir(parents=True, exist_ok=True)

    temp_output = output.with_suffix(".tmp.mp4")

    if temp_output.exists():
        temp_output.unlink()

    video_filter = build_video_filter(video_format, fps)

    run_command(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",

            "-loop",
            "1",
            "-i",
            str(visual),

            "-i",
            str(audio),

            "-map",
            "0:v:0",
            "-map",
            "1:a:0",

            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-tune",
            "stillimage",

            "-pix_fmt",
            "yuv420p",

            "-vf",
            video_filter,

            "-c:a",
            "aac",
            "-b:a",
            "128k",

            "-shortest",

            "-movflags",
            "+faststart",

            str(temp_output),
        ]
    )

    if not temp_output.exists():
        raise RuntimeError(
            f"FFmpeg did not create expected output: {temp_output}"
        )

    if temp_output.stat().st_size < 1000:
        raise RuntimeError(
            f"Generated video is unexpectedly small: {temp_output}"
        )

    os.replace(temp_output, output)


def create_part_video(part: int, scene_records):
    scene_records = sorted(
        scene_records,
        key=lambda item: item["scene"],
    )

    concat_file = PARTS_OUT / f"part_{part:02d}_concat.txt"
    output = PARTS_OUT / f"part_{part:02d}.mp4"
    temp_output = output.with_suffix(".tmp.mp4")

    lines = []

    for record in scene_records:
        scene_path = Path(record["video"]).resolve()

        if not valid_video(scene_path):
            raise SystemExit(
                f"ERROR: Invalid scene video for Part {part}: "
                f"{scene_path}"
            )

        escaped = str(scene_path).replace("'", "'\\''")
        lines.append(f"file '{escaped}'")

    concat_file.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )

    if temp_output.exists():
        temp_output.unlink()

    run_command(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_file),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(temp_output),
        ]
    )

    if not temp_output.exists():
        raise RuntimeError(
            f"Part video was not created: {temp_output}"
        )

    os.replace(temp_output, output)

    if not valid_video(output):
        raise RuntimeError(
            f"Part video validation failed: {output}"
        )

    print(
        f"PART COMPLETE: Part {part} -> "
        f"{output} "
        f"({probe_duration(output)} sec)"
    )

    return output


def main():
    print("==============================================")
    print("        LOK AI VIDEO RENDERER")
    print("==============================================")

    fps_raw = read_config("FPS", "24")

    try:
        fps = int(fps_raw)
    except ValueError:
        fps = 24

    if fps <= 0:
        fps = 24

    video_format = read_config("FORMAT", "short")

    print(f"FORMAT : {video_format}")
    print(f"FPS    : {fps}")

    width, height = get_output_geometry(video_format)

    print(f"OUTPUT : {width}x{height}")

    narration = load_json(NARRATION)
    visuals = load_json(VISUALS)

    narration_status = str(
        narration.get("status", "")
    ).lower()

    if narration_status not in {
        "completed",
        "complete",
        "success",
    }:
        raise SystemExit(
            "ERROR: Narration/TTS manifest is not completed."
        )

    failed_visuals = int(
        visuals.get("failed_jobs", 0) or 0
    )

    if failed_visuals > 0:
        raise SystemExit(
            f"ERROR: Visual manifest contains "
            f"{failed_visuals} failed jobs."
        )

    audio_jobs = normalize_jobs(
        narration,
        "audio",
    )

    visual_jobs = normalize_jobs(
        visuals,
        "visual",
    )

    if not audio_jobs:
        raise SystemExit(
            "ERROR: No completed audio jobs found."
        )

    if not visual_jobs:
        raise SystemExit(
            "ERROR: No completed visual jobs found."
        )

    SCENES_OUT.mkdir(
        parents=True,
        exist_ok=True,
    )

    PARTS_OUT.mkdir(
        parents=True,
        exist_ok=True,
    )

    all_keys = sorted(audio_jobs.keys())

    print()
    print(f"Audio scenes  : {len(audio_jobs)}")
    print(f"Visual scenes : {len(visual_jobs)}")
    print()

    scene_records = []

    for part, scene in all_keys:
        key = (part, scene)

        if key not in visual_jobs:
            raise SystemExit(
                f"ERROR: Missing visual for "
                f"Part {part} Scene {scene}"
            )

        audio = resolve_audio(
            audio_jobs[key],
            part,
            scene,
        )

        visual = resolve_visual(
            visual_jobs[key],
            part,
            scene,
        )

        if not audio.exists():
            raise SystemExit(
                f"ERROR: Audio missing: {audio}"
            )

        if not visual.exists():
            raise SystemExit(
                f"ERROR: Visual missing: {visual}"
            )

        output = (
            SCENES_OUT
            / f"part_{part:02d}"
            / f"scene_{scene:02d}.mp4"
        )

        output.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        print(
            f"SCENE Part {part} "
            f"Scene {scene}"
        )

        if valid_video(output):
            print(
                f"SKIP: Existing valid video -> "
                f"{output}"
            )
        else:
            print(
                f"RENDER: {visual} + {audio}"
            )

            render_scene(
                visual=visual,
                audio=audio,
                output=output,
                fps=fps,
                video_format=video_format,
            )

        duration = probe_duration(output)

        scene_records.append(
            {
                "part": part,
                "scene": scene,
                "video": str(output),
                "audio": str(audio),
                "visual": str(visual),
                "duration": duration,
            }
        )

    parts = sorted(
        {
            record["part"]
            for record in scene_records
        }
    )

    part_outputs = []

    for part in parts:
        records = [
            record
            for record in scene_records
            if record["part"] == part
        ]

        part_output = create_part_video(
            part,
            records,
        )

        part_outputs.append(
            {
                "part": part,
                "output": str(part_output),
                "duration": probe_duration(
                    part_output
                ),
                "scenes": len(records),
            }
        )

    manifest = {
        "status": "completed",
        "format": video_format,
        "width": width,
        "height": height,
        "fps": fps,
        "total_scenes": len(scene_records),
        "total_parts": len(part_outputs),
        "parts": part_outputs,
        "scenes": scene_records,
    }

    MANIFEST_OUT.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    MANIFEST_OUT.write_text(
        json.dumps(
            manifest,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print()
    print("==============================================")
    print(
        f"VIDEO RENDERING COMPLETED: "
        f"{len(scene_records)} scenes"
    )
    print(
        f"PART VIDEOS CREATED: "
        f"{len(part_outputs)}"
    )
    print(
        f"MANIFEST: {MANIFEST_OUT}"
    )
    print("==============================================")


if __name__ == "__main__":
    main()
