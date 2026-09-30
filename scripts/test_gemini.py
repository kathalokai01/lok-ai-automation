import os
import urllib.request
import json

api_key = os.environ.get("GEMINI_API_KEY")

if not api_key:
    raise SystemExit("ERROR: GEMINI_API_KEY is not set")

url = (
    "https://generativelanguage.googleapis.com/v1beta/"
    "models/gemini-2.5-flash:generateContent"
    f"?key={api_key}"
)

payload = {
    "contents": [
        {
            "parts": [
                {
                    "text": "Reply with exactly: GEMINI_OK"
                }
            ]
        }
    ]
}

request = urllib.request.Request(
    url,
    data=json.dumps(payload).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST"
)

try:
    with urllib.request.urlopen(request, timeout=60) as response:
        result = json.loads(response.read().decode("utf-8"))

    text = (
        result["candidates"][0]["content"]["parts"][0]["text"]
        .strip()
    )

    print(f"Gemini response: {text}")

except Exception as e:
    raise SystemExit(f"Gemini API test failed: {e}")
