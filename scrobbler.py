# --- BEGIN SCRIPT ---

import requests
import hashlib
import time
import json
import os
import logging
import sys
from datetime import datetime
from pathlib import Path

# === CONFIGURATION ===
SCRIPT_DIR = os.environ.get("SCRIPT_DIR", os.path.dirname(os.path.abspath(__file__)))
if not SCRIPT_DIR:
    SCRIPT_DIR = "/app"

PLEX_SERVER_URL = os.environ.get("PLEX_SERVER_URL", "http://ip:32400")
PLEX_TOKEN = os.environ.get("PLEX_TOKEN", "YOUR_TOKEN")

LASTFM_API_KEY = os.environ.get("LASTFM_API_KEY", "YOUR_KEY")
LASTFM_API_SECRET = os.environ.get("LASTFM_API_SECRET", "YOURAPISECRET")
LASTFM_SESSION_KEY = os.environ.get("LASTFM_SESSION_KEY", "YOUR SESSION KEY")

CACHE_FILE = os.path.join(SCRIPT_DIR, "scrobble_cache.json")
TRACK_HISTORY_FILE = os.path.join(SCRIPT_DIR, "track_history.json")
HISTORY_FILE = os.path.join(SCRIPT_DIR, "scrobble_history.json")
LOG_FILE = os.path.join(SCRIPT_DIR, "plex_scrobbler.log")
MAX_RETRY_ATTEMPTS = 5
RETRY_INTERVAL = 60
SCROBBLE_FALLBACK_TIMEOUT = None

os.makedirs(SCRIPT_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("PlexScrobbler")

scrobbled_tracks = []
replay_counter = {}

def scrobble_if_ready(track_info):
    track_id = track_info["ratingKey"]
    for track_session in scrobbled_tracks:
        if (track_session["ratingKey"] == track_id and not track_session["scrobble_submitted"]
                and not any(ts for ts in scrobbled_tracks if ts != track_session and ts["ratingKey"] == track_id and ts.get("scrobble_submitted"))):
            playback_state = track_info.get("playbackState", "stopped")

            if track_session.get("ready_to_scrobble"):
                if playback_state in ["paused", "stopped"] and not track_session.get("ended_timestamp"):
                    track_session["ended_timestamp"] = time.time()

                if track_session.get("ended_timestamp") and (
                    track_info["ratingKey"] != track_session["ratingKey"]
                    or SCROBBLE_FALLBACK_TIMEOUT == 0
                    or time.time() - track_session["ended_timestamp"] >= SCROBBLE_FALLBACK_TIMEOUT):

                    timestamp = int(track_session.get("ready_timestamp", time.time()))
                    success = scrobble_track(
                        track_session["track"],
                        track_session["artist"],
                        track_session["album"],
                        track_session["albumArtist"],
                        timestamp
                    )

                    if success:
                        track_session["scrobble_submitted"] = True
                        track_session["scrobble_timestamp"] = time.time()
                        key = f"{track_session['artist']} - {track_session['track']}"
                        replay_counter[key] = replay_counter.get(key, 0) + 1
                        logger.info(f"📤 Scrobbled: {key} (Play #{replay_counter[key]})")

                        scrobble_entry = {
                            "artist": track_session["artist"],
                            "track": track_session["track"],
                            "album": track_session["album"],
                            "albumArtist": track_session["albumArtist"],
                            "timestamp": timestamp
                        }
                        try:
                            if os.path.exists(HISTORY_FILE):
                                with open(HISTORY_FILE, "r") as f:
                                    history = json.load(f)
                            else:
                                history = []
                            history.append(scrobble_entry)
                            with open(HISTORY_FILE, "w") as f:
                                json.dump(history, f, indent=2)
                        except Exception as e:
                            logger.warning(f"Could not write scrobble history: {e}")

                        queued = [s for s in scrobbled_tracks if s.get("ready_to_scrobble") and not s.get("scrobble_submitted")]
                        if queued:
                            logger.info("📋 Queued scrobbles:")
                            for q in queued:
                                logger.info(f" - {q['artist']} - {q['track']}")
                    break


def add_or_update_play_session(track_info, start_time):
    track_id = track_info["ratingKey"]
    duration = track_info["duration"]
    current_position = track_info["viewOffset"]

    # Check for a true repeat only if viewOffset has reset significantly
    if scrobbled_tracks:
        last_session = scrobbled_tracks[-1]
        if last_session["ratingKey"] == track_id:
            previous_position = last_session.get("last_position", 0)
            if previous_position >= duration * 0.9 and current_position < 5:
                logger.info(f"🔁 Detected repeat: {track_info['artist']} - {track_info['track']}")
                # Create a new session for true repeat
                new_session = {
                    "ratingKey": track_id,
                    "track": track_info.get("track"),
                    "artist": track_info.get("artist"),
                    "album": track_info.get("album"),
                    "albumArtist": track_info.get("albumArtist"),
                    "start_time": start_time,
                    "last_position": current_position,
                    "ready_to_scrobble": False,
                    "ready_timestamp": None,
                    "ended_timestamp": None,
                    "scrobble_submitted": False
                }
                scrobbled_tracks.append(new_session)
                logger.info(f"🎧 Tracking new session for: {track_info['artist']} - {track_info['track']}")

    # Otherwise update the most recent session if still active and same track
    if scrobbled_tracks:
        last_session = scrobbled_tracks[-1]
        if last_session["ratingKey"] == track_id and not last_session["scrobble_submitted"]:
            last_session["last_position"] = current_position
            elapsed_time = time.time() - last_session["start_time"]
            min_play_time = max(0.5, min(duration * 0.5, 240))
            if elapsed_time >= min_play_time and not last_session["ready_to_scrobble"]:
                last_session["ready_to_scrobble"] = True
                last_session["ready_timestamp"] = time.time()
                logger.info(f"✅ Marked track ready to scrobble: {track_info['artist']} - {track_info['track']}")
            return

    # Prevent repeated fallback sessions if viewOffset isn't progressing
    if scrobbled_tracks:
        last_session = scrobbled_tracks[-1]
        if last_session["ratingKey"] == track_id:
            if last_session.get("scrobble_submitted") and time.time() - last_session.get("scrobble_timestamp", 0) < 300:
                logger.debug("🚫 Skipping fallback: track already scrobbled and session is lingering.")
                return
    if scrobbled_tracks:
        last_session = scrobbled_tracks[-1]
        if last_session["ratingKey"] == track_id and current_position < 5:
            logger.debug(f"⏸️ Ignoring fallback tracking: stale session detected at offset {current_position}s")
            return

    # Fallback: new session if nothing to update
    logger.info(f"🎧 Tracking fallback session for: {track_info['artist']} - {track_info['track']}")
    new_session = {
        "ratingKey": track_id,
        "track": track_info.get("track"),
        "artist": track_info.get("artist"),
        "album": track_info.get("album"),
        "albumArtist": track_info.get("albumArtist"),
        "start_time": start_time,
        "last_position": current_position,
        "ready_to_scrobble": False,
        "ready_timestamp": None,
        "ended_timestamp": None,
        "scrobble_submitted": False
    }
    scrobbled_tracks.append(new_session)
    logger.info(f"🎧 Tracking new session for: {track_info['artist']} - {track_info['track']}")

    


def scrobble_track(track, artist, album, album_artist, timestamp):
    url = "https://ws.audioscrobbler.com/2.0/"
    params = {
        "method": "track.scrobble",
        "api_key": LASTFM_API_KEY,
        "sk": LASTFM_SESSION_KEY,
        "artist": artist,
        "track": track,
        "album": album,
        "albumArtist": album_artist,
        "timestamp": timestamp,
        "format": "json"
    }
    sig = hashlib.md5(("".join(f"{k}{v}" for k, v in sorted(params.items()) if k != "format") + LASTFM_API_SECRET).encode()).hexdigest()
    params["api_sig"] = sig

    try:
        r = requests.post(url, data=params, timeout=15)
        return r.status_code == 200
    except requests.exceptions.RequestException as e:
        logger.error(f"Network error while scrobbling: {e}")
        return False


def get_currently_playing():
    url = f"{PLEX_SERVER_URL}/status/sessions"
    headers = {"X-Plex-Token": PLEX_TOKEN, "Accept": "application/json"}

    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            logger.error(f"Error: Unable to reach Plex API. Status code: {response.status_code}")
            return None

        try:
            data = response.json()
        except requests.exceptions.JSONDecodeError:
            logger.error(f"Error: Invalid JSON. Response: {response.text[:500]}")
            return None

        for media in data.get("MediaContainer", {}).get("Metadata", []):
            if media.get("type") == "track":
                track_artist = media.get("originalTitle") or media.get("grandparentTitle")
                album_artist = media.get("grandparentTitle") or "Various Artists"
                playback_state = media.get("Player", {}).get("state", "stopped")
                viewOffset = media.get("viewOffset", 0)

                return {
                    "artist": track_artist,
                    "album": media.get("parentTitle"),
                    "track": media.get("title"),
                    "albumArtist": album_artist,
                    "duration": media.get("duration", 0) // 1000,
                    "ratingKey": media.get("ratingKey"),
                    "playbackState": playback_state,
                    "viewOffset": viewOffset // 1000
                }

        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"Network error: {e}")
        return None


if __name__ == "__main__":
    current_track = None
    track_start_time = None

    while True:
        try:
            now_playing = get_currently_playing()

            if now_playing:
                track_id = now_playing["ratingKey"]

                if current_track != track_id:
                    # Finalize any unsubmitted ready track session before switching
                    for session in scrobbled_tracks:
                        if (
                            session["ratingKey"] == current_track
                            and session.get("ready_to_scrobble")
                            and not session.get("ended_timestamp")
                            and not session.get("scrobble_submitted")
                        ):
                            session["ended_timestamp"] = time.time()
                            logger.debug(f"💡 Marked previous track ended due to new playback: {session['artist']} - {session['track']}")

                    current_track = track_id
                    SCROBBLE_FALLBACK_TIMEOUT = max(1, now_playing["duration"] // 2)
                    logger.info(f"⏳ Fallback timeout set to {SCROBBLE_FALLBACK_TIMEOUT} seconds for this track")
                    track_start_time = time.time() - now_playing["viewOffset"]
                    logger.info(f"▶️ Now playing: {now_playing['artist']} - {now_playing['track']}")

                add_or_update_play_session(now_playing, track_start_time)
                scrobble_if_ready(now_playing)

            for track_session in scrobbled_tracks:
                if track_session.get("ready_to_scrobble") and not track_session.get("scrobble_submitted"):
                    fake_track_info = {
                        "ratingKey": track_session["ratingKey"],
                        "playbackState": "stopped",
                        "track": track_session.get("track", "Unknown"),
                        "artist": track_session.get("artist", "Unknown"),
                        "album": track_session.get("album", ""),
                        "albumArtist": track_session.get("albumArtist", "")
                    }
                    scrobble_if_ready(fake_track_info)

            time.sleep(0.5)
        except Exception as e:
            logger.error(f"Main loop error: {e}", exc_info=True)
            time.sleep(5)
