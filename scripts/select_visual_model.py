#!/usr/bin/env python3

import json
import os
import sys
import time
from pathlib import Path

import requests

from input_config import (
    load_input_config,
    cfg_int,
    cfg_bool,
    normalize_format,
)


OUTPUT_FILE = Path(
    "output/config/selected_visual_model.json"
)

MODEL = "alibaba/wan-2.6-image"

API_BASE = (
    "https://api.cloudflare.com/client/v4/accounts/"
)

TEST_TIMEOUT = 120


def fail(message):
    print(f"ERROR: {message}")
    sys.exit(1)


def get_credentials():
    account_id = os.getenv(
        "CLOUDFLARE_ACCOUNT_ID",
        ""
    ).strip()

    api_token = os.getenv(
        "CLOUDFLARE_API_TOKEN",
        ""
    ).strip()

    if not account_id:
        fail("CLOUDFLARE_ACCOUNT_ID is not set.")

    if not api_token:
        fail("CLOUDFLARE_API_TOKEN is not set.")

    return account_id, api_token


def test_model(account_id, api_token):
    url = (
        f"{API_BASE}{account_id}"
        f"/ai/run/@{MODEL}"
    )

    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
    }

    # Minimal valid image-generation test payload.
    # The actual visual generator supplies the complete prompt
    # and dimensions later.
    payload = {
        "prompt": (
            "A photorealistic cinematic live-action "
            "environment test frame, natural lighting, "
            "real-world appearance"
        )
    }

    print()
    print(f"Testing visual model: {MODEL}")
    print(f"Endpoint: {url}")

    try:
        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=TEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        print(
            f"Model test request failed: {exc}"
        )
        return False, None

    print(
        f"HTTP status: {response.status_code}"
    )

    if response.status_code in (200, 201, 202):
        try:
            data = response.json()
        except Exception:
            data = {}

        if data.get("success") is False:
            print(
                "Cloudflare returned success=false."
            )
            print(
                json.dumps(
                    data,
                    ensure_ascii=False,
                    indent=2,
                )[:3000]
            )
            return False, data

        return True, data

    if response.status_code in (
        401,
        403,
    ):
        print(
            "Cloudflare authentication/permission "
            "error."
        )

    elif response.status_code == 404:
        print(
            "Cloudflare model endpoint was not found."
        )

    elif response.status_code == 429:
        print(
            "Cloudflare rate limit received."
        )

    elif response.status_code >= 500:
        print(
            "Cloudflare server-side error."
        )

    try:
        data = response.json()
    except Exception:
        data = {
            "raw": response.text[:3000]
        }

    print(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2,
        )[:3000]
    )

    return False, data


def save_selection(
    model,
    status,
):
    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    data = {
        "status": status,
        "model": model,
        "provider": "cloudflare",
        "selected_by": "select_visual_model.py",
        "timestamp": int(time.time()),
    }

    tmp = OUTPUT_FILE.with_suffix(
        OUTPUT_FILE.suffix + ".tmp"
    )

    with tmp.open(
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2,
        )

    tmp.replace(OUTPUT_FILE)

    return data


def main():
    print("=" * 60)
    print("        SELECTING VISUAL GENERATION MODEL")
    print("=" * 60)

    try:
        config = load_input_config()
    except Exception as exc:
        fail(
            f"Failed to load Input configuration: {exc}"
        )

    format_name = normalize_format(config)

    max_retries = cfg_int(
        config,
        "MAX_RETRIES",
        3,
    )

    resume_enabled = cfg_bool(
        config,
        "RESUME_ENABLED",
        True,
    )

    print(f"FORMAT        : {format_name}")
    print(f"MAX_RETRIES   : {max_retries}")
    print(f"RESUME        : {resume_enabled}")
    print(f"MODEL         : {MODEL}")

    account_id, api_token = get_credentials()

    # ---------------------------------------------------------
    # TEST THE EXACT MODEL USED BY generate_visuals.py
    # ---------------------------------------------------------

    success = False
    result = None

    attempts = max(
        1,
        max_retries,
    )

    for attempt in range(
        1,
        attempts + 1,
    ):
        print()
        print(
            f"Model test attempt "
            f"{attempt}/{attempts}"
        )

        success, result = test_model(
            account_id,
            api_token,
        )

        if success:
            break

        if attempt < attempts:
            wait_seconds = min(
                10 * attempt,
                60,
            )

            print(
                f"Retrying in "
                f"{wait_seconds} seconds..."
            )

            time.sleep(
                wait_seconds
            )

    if not success:
        save_selection(
            MODEL,
            "failed",
        )

        fail(
            f"Visual model test failed: {MODEL}"
        )

    # ---------------------------------------------------------
    # SAVE SELECTED MODEL
    # ---------------------------------------------------------

    selection = save_selection(
        MODEL,
        "selected",
    )

    print()
    print("=" * 60)
    print("        VISUAL MODEL SELECTED")
    print("=" * 60)

    print(
        f"Selected model : {selection['model']}"
    )

    print(
        f"Provider       : {selection['provider']}"
    )

    print(
        f"Saved to       : {OUTPUT_FILE}"
    )

    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
