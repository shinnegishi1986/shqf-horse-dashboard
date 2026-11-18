#!/usr/bin/env python3
# scripts/make-video-playable-in-ipad.py
#
# Run:
#   python scripts/make-video-playable-in-ipad.py app.py
#   python scripts/make-video-playable-in-ipad.py app.py --dry-run
#
# Prerequisite:
#   scripts/implement-video-feature.py
#
# Features:
#   - Explicit touch-friendly Play button.
#   - Inline playback on iPad/iPhone.
#   - Native playback controls.
#   - Optional server-side H.264/AAC MP4 conversion using FFmpeg.
#   - Applies wherever media_play_blob_video() is used:
#     timer videos, journal videos, editing previews, and shared pages.
#   - Prevents the known public timer's 15-second fragment refresh from
#     repeatedly replacing the player.
#
# Storage:
#   Original SQLite video BLOBs are NOT modified.
#   Conversion uses temporary server files, removed after conversion.
#   Converted bytes are cached in server memory for up to one hour.
#
# FFmpeg:
#   Install FFmpeg on the machine running Streamlit, not on the iPad.
#   Ensure "ffmpeg" is available on that machine's PATH, then restart Streamlit.
#   Without FFmpeg, original video bytes are played and codec compatibility
#   depends on the device.
#
# To disable automatic conversion:
#   Set TIMER_VIDEO_TRANSCODE=0 in the Streamlit server environment.
#
# Privacy:
#   No new public routes or download buttons are added.
#   Existing authentication and share-token checks remain unchanged.
#   Download controls are hidden where supported; this is not DRM.
#
# This patch validates Python syntax, not actual device playback.

import argparse
import ast
import difflib
import shutil
import sys
from datetime import datetime
from pathlib import Path


MARKER = "# IPAD_TOUCH_VIDEO_SUPPORT_V1"

REPLACEMENT = r'''
# IPAD_TOUCH_VIDEO_SUPPORT_V1

@st.cache_data(ttl=3600, max_entries=4, show_spinner=False)
def ipad_prepare_video(content, mime_type):
    """Return playback bytes, MIME type, and an optional diagnostic."""
    import os
    import shutil
    import subprocess
    import tempfile
    from pathlib import Path

    original = bytes(content)
    enabled = os.environ.get("TIMER_VIDEO_TRANSCODE", "1").lower()
    if enabled in {"0", "false", "no", "off"}:
        return original, mime_type, ""

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return original, mime_type, (
            "FFmpeg is not installed on the app server. "
            "If playback fails, upload H.264/AAC MP4 or install FFmpeg. "
            "再生できない場合はH.264/AAC形式のMP4を使用してください。"
        )

    suffix = ".webm" if mime_type == "video/webm" else ".mp4"
    try:
        with tempfile.TemporaryDirectory(prefix="timer-ipad-video-") as folder:
            source = Path(folder) / ("input" + suffix)
            output = Path(folder) / "playback.mp4"
            source.write_bytes(original)

            result = subprocess.run(
                [
                    ffmpeg,
                    "-nostdin", "-hide_banner", "-loglevel", "error",
                    "-y", "-i", str(source),
                    "-map", "0:v:0",
                    "-map", "0:a:0?",
                    "-map_metadata", "-1",
                    "-c:v", "libx264",
                    "-preset", "veryfast",
                    "-crf", "23",
                    "-pix_fmt", "yuv420p",
                    "-vf",
                    "scale=1280:1280:force_original_aspect_ratio=decrease:"
                    "force_divisible_by=2,setsar=1",
                    "-c:a", "aac",
                    "-b:a", "128k",
                    "-ac", "2",
                    "-movflags", "+faststart",
                    str(output),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=180,
                check=False,
            )

            if (
                result.returncode == 0
                and output.exists()
                and output.stat().st_size > 0
            ):
                return output.read_bytes(), "video/mp4", ""

            return original, mime_type, (
                "Compatibility conversion failed; trying the original video. "
                "The server needs FFmpeg with libx264 and AAC support."
            )

    except subprocess.TimeoutExpired:
        return original, mime_type, (
            "Compatibility conversion timed out; trying the original video. "
            "Try a shorter H.264/AAC MP4."
        )
    except OSError:
        return original, mime_type, (
            "Compatibility conversion is unavailable; "
            "trying the original video."
        )


def media_play_blob_video(content, mime_type):
    """Touch-friendly playback of an authorized SQLite video BLOB."""
    import base64
    import json
    import streamlit.components.v1 as components

    if mime_type not in {"video/mp4", "video/webm"}:
        st.error("Unsupported video format / 未対応の動画形式です。")
        return
    if not content:
        st.info("Video is empty / 動画データがありません。")
        return

    with st.spinner("Preparing video / 動画を準備しています…"):
        playback, playback_mime, notice = ipad_prepare_video(
            bytes(content), mime_type
        )

    if notice:
        st.caption(notice)

    payload = json.dumps({
        "mime": playback_mime,
        "data": base64.b64encode(playback).decode("ascii"),
    })

    document = r"""
<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
html,body {
    margin:0; padding:0; background:transparent;
    font-family:system-ui,sans-serif;
}
video {
    display:block; width:100%; height:310px;
    object-fit:contain; background:#080b10; border-radius:12px;
}
.actions { display:flex; gap:10px; margin-top:10px; }
button {
    min-height:48px; padding:10px 22px;
    border:0; border-radius:10px;
    background:#2563eb; color:white; font-size:16px;
    cursor:pointer; touch-action:manipulation;
}
button:disabled { opacity:.55; cursor:default; }
#message {
    font-size:13px; line-height:1.5; margin:10px 0;
    color:#64748b;
}
@media(prefers-color-scheme:dark) {
    #message { color:#cbd5e1; }
}
</style>
</head>
<body>
<video id="video"
    controls
    playsinline
    webkit-playsinline
    preload="metadata"
    controlslist="nodownload noremoteplayback"
    disablepictureinpicture
    disableremoteplayback
    aria-label="Video player">
</video>
<div class="actions">
    <button id="play" type="button" disabled>Play / 再生</button>
    <button id="pause" type="button" disabled>Pause / 一時停止</button>
</div>
<p id="message" role="status">Preparing / 準備中…</p>
<script>
"use strict";
const payload = __PAYLOAD__;
const video = document.getElementById("video");
const playButton = document.getElementById("play");
const pauseButton = document.getElementById("pause");
const message = document.getElementById("message");
let objectUrl = null;

video.playsInline = true;

video.addEventListener("contextmenu", function(event) {
    event.preventDefault();
});

function reportPlayFailure(error) {
    if (error && error.name === "NotAllowedError") {
        message.textContent =
            "Tap the video's native Play control. "
            + "動画内の再生ボタンをタップしてください。";
    } else {
        message.textContent =
            "Cannot play this video. Try H.264/AAC MP4. "
            + "H.264/AAC形式のMP4を使用してください。";
    }
}

playButton.addEventListener("click", function() {
    // Call play directly within the trusted tap/click handler.
    // Do not await metadata, conversion, or network work first.
    try {
        const promise = video.play();
        if (promise && typeof promise.catch === "function") {
            promise.catch(reportPlayFailure);
        }
    } catch (error) {
        reportPlayFailure(error);
    }
});

pauseButton.addEventListener("click", function() {
    video.pause();
});

video.addEventListener("playing", function() {
    message.textContent = "";
});
video.addEventListener("waiting", function() {
    message.textContent = "Loading / 読み込み中…";
});
video.addEventListener("canplay", function() {
    message.textContent = video.paused
        ? "Tap Play / 再生をタップしてください。" : "";
});
video.addEventListener("error", function() {
    const code = video.error ? video.error.code : "unknown";
    message.textContent =
        "Playback error (" + code + "). Use H.264/AAC MP4 "
        + "or enable FFmpeg on the app server. "
        + "対応形式への変換が必要な可能性があります。";
});

try {
    const binary = atob(payload.data);
    const chunks = [];
    const chunkSize = 1024 * 1024;
    for (let offset = 0; offset < binary.length; offset += chunkSize) {
        const size = Math.min(chunkSize, binary.length - offset);
        const bytes = new Uint8Array(size);
        for (let index = 0; index < size; index++) {
            bytes[index] = binary.charCodeAt(offset + index);
        }
        chunks.push(bytes);
    }

    const blob = new Blob(chunks, {type:payload.mime});
    objectUrl = URL.createObjectURL(blob);
    video.src = objectUrl;
    payload.data = "";
    video.load();

    // Enable immediately: some mobile browsers defer metadata until a tap.
    playButton.disabled = false;
    pauseButton.disabled = false;
    message.textContent = "Tap Play / 再生をタップしてください。";
} catch (error) {
    message.textContent =
        "Cannot prepare video. Try a smaller MP4. "
        + "より小さいMP4ファイルを使用してください。";
}

window.addEventListener("pagehide", function(event) {
    // Keep the URL alive when the page enters the browser's back/forward cache.
    if (!event.persisted && objectUrl !== null) {
        video.pause();
        video.removeAttribute("src");
        video.load();
        URL.revokeObjectURL(objectUrl);
        objectUrl = null;
    }
});
</script>
</body>
</html>
"""
    components.html(
        document.replace("__PAYLOAD__", payload),
        height=470,
        scrolling=False,
    )

'''


def find_function(source, name, required=True):
    matches = [
        node
        for node in ast.parse(source).body
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    if not matches and not required:
        return None
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one {name}() function.")
    return matches[0]


def offsets(source, node):
    lines = source.splitlines(keepends=True)
    first_line = min(
        [node.lineno] + [item.lineno for item in node.decorator_list]
    )
    return (
        sum(map(len, lines[:first_line - 1])),
        sum(map(len, lines[:node.end_lineno])),
    )


def patch_source(source):
    if MARKER in source:
        raise ValueError("iPad/touch video support is already installed.")

    player = find_function(source, "media_play_blob_video")
    start, end = offsets(source, player)
    updated = source[:start] + REPLACEMENT + source[end:]

    refresh_changed = False
    public_renderer = find_function(
        updated, "render_public_shared_timer", required=False
    )

    if public_renderer:
        lines = updated.splitlines(keepends=True)
        changes = []

        for node in ast.walk(public_renderer):
            if not isinstance(node, ast.FunctionDef):
                continue
            for decorator in node.decorator_list:
                if not (
                    isinstance(decorator, ast.Call)
                    and isinstance(decorator.func, ast.Attribute)
                    and isinstance(decorator.func.value, ast.Name)
                    and decorator.func.value.id == "st"
                    and decorator.func.attr == "fragment"
                ):
                    continue

                interval = next(
                    (
                        item.value
                        for item in decorator.keywords
                        if item.arg == "run_every"
                    ),
                    None,
                )
                if not (
                    isinstance(interval, ast.Constant)
                    and interval.value == "15s"
                ):
                    continue

                # Replace only the exact known public refresh decorator.
                # Leave unrelated fragments untouched.
                if decorator.lineno != decorator.end_lineno:
                    continue
                line = lines[decorator.lineno - 1]
                indent = line[:len(line) - len(line.lstrip())]
                changes.append((
                    decorator.lineno - 1,
                    indent + "@st.fragment\n",
                ))

        for index, replacement in changes:
            lines[index] = replacement
            refresh_changed = True
        updated = "".join(lines)

    ast.parse(updated)
    compile(updated, "<ipad-touch-video-patch>", "exec")
    return updated, refresh_changed


def main():
    parser = argparse.ArgumentParser(
        description="Add iPad/touch-friendly BLOB video playback."
    )
    parser.add_argument(
        "app", nargs="?", type=Path, default=Path("app.py")
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    app = args.app.expanduser().resolve()

    try:
        if not app.is_file():
            raise ValueError(f"Application not found: {app}")

        original = app.read_text(encoding="utf-8")
        updated, refresh_changed = patch_source(original)

        if args.dry_run:
            sys.stdout.writelines(difflib.unified_diff(
                original.splitlines(keepends=True),
                updated.splitlines(keepends=True),
                fromfile=str(app),
                tofile=f"{app} (iPad/touch video)",
            ))
            return 0

        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        backup = app.with_name(f"{app.name}.backup-{stamp}")
        temporary = app.with_name(f".{app.name}.{stamp}.tmp")

        shutil.copy2(app, backup)
        try:
            temporary.write_text(updated, encoding="utf-8")
            shutil.copymode(app, temporary)
            temporary.replace(app)
        finally:
            if temporary.exists():
                temporary.unlink()

        print(f"Updated: {app}")
        print(f"Backup:  {backup}")
        print("Original SQLite video BLOBs were not modified.")
        if refresh_changed:
            print(
                "Disabled the public timer's 15-second fragment refresh "
                "to avoid interrupting playback."
            )
            print("Public statistics now update on page reload/interaction.")
        print("Restart Streamlit, refresh the iPad page, then tap Play.")
        print(
            "For incompatible codecs, install FFmpeg on the app server "
            "and restart Streamlit."
        )
        print("Device playback still requires testing on your iPad.")
        return 0

    except (OSError, ValueError, SyntaxError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())