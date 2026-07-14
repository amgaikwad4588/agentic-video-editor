"""Seed a demo project through the public API (used for docs screenshots).

Usage: python scripts/seed_demo.py [base_url]
Prints the created project id on the last line.
"""

import json
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.services.ffmpeg import resolve_ffmpeg  # noqa: E402

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"

# lavfi generators available in ffmpeg 4.2 (the imageio-ffmpeg bundle);
# `gradients` only exists in 4.3+. Infinite sources are capped with -t.
SOURCES = {
    "coastline.mp4": "life=size=1280x720:mold=10:ratio=0.08:rate=30:life_color=#F9F8F6:death_color=#1A2A3A",
    "night-market.mp4": "mandelbrot=size=1280x720",
    "studio-b-roll.mp4": "testsrc2=size=1280x720:rate=30",
}


def req(method: str, path: str, data: bytes | None = None, ctype: str | None = None):
    r = urllib.request.Request(BASE + path, method=method, data=data)
    if ctype:
        r.add_header("Content-Type", ctype)
    with urllib.request.urlopen(r, timeout=60) as resp:
        return json.loads(resp.read() or b"null")


def make_clip(dest: Path, source: str) -> None:
    args = [resolve_ffmpeg(), "-y", "-f", "lavfi", "-i", source,
            "-f", "lavfi", "-i", "sine=frequency=330:duration=6",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            "-shortest", "-t", "6", str(dest)]
    subprocess.run(args, capture_output=True, check=True, timeout=180)


def upload(path: Path) -> dict:
    boundary = "XSEEDX"
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
        f"filename=\"{path.name}\"\r\nContent-Type: video/mp4\r\n\r\n"
    ).encode() + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    return req("POST", "/api/media", body, f"multipart/form-data; boundary={boundary}")


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="seed-"))
    assets = []
    for name, source in SOURCES.items():
        f = tmp / name
        make_clip(f, source)
        assets.append(upload(f))
        print("uploaded", name, flush=True)

    project = req("POST", "/api/projects", json.dumps({"name": "Coastal Diary — Cut 03"}).encode(),
                  "application/json")

    timeline = {"clips": [
        {"asset_id": assets[0]["id"], "start": 0.5, "end": 4.5, "speed": 1.0, "volume": 1.0,
         "overlays": [{"text": "The Coast, 6:14 am", "x": "(w-text_w)/2", "y": "h-th-40",
                       "font_size": 44, "color": "white", "start": 0.4, "end": None}]},
        {"asset_id": assets[1]["id"], "start": 1.0, "end": 5.0, "speed": 2.0, "volume": 0.6,
         "overlays": []},
        {"asset_id": assets[2]["id"], "start": 0.0, "end": 3.0, "speed": 1.0, "volume": 0.0,
         "overlays": [{"text": "Fig. 03 — Studio", "x": "(w-text_w)/2", "y": "40",
                       "font_size": 36, "color": "white", "start": 0.0, "end": None}]},
    ]}
    req("PUT", f"/api/projects/{project['id']}/timeline", json.dumps(timeline).encode(),
        "application/json")
    print("project ready", flush=True)
    print(project["id"])


if __name__ == "__main__":
    main()
