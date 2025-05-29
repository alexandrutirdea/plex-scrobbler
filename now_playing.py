import requests
import hashlib
import time

# === CONFIGURATION ===
# Plex Settings
PLEX_SERVER_URL = "Your Server URL"
PLEX_TOKEN = "YOUR_TOKEN"

# Last.fm API Settings
LASTFM_API_KEY = "YOUR_API_KEY"
LASTFM_API_SECRET = "YOUR_API_SECRET"
LASTFM_SESSION_KEY = "YOUR_SESSION_KEY"

def get_currently_playing():
    """Fetch currently playing track from Plex."""
    url = f"{PLEX_SERVER_URL}/status/sessions"
    headers = {
        "X-Plex-Token": PLEX_TOKEN,
        "Accept": "application/json"
    }

    try:
        response = requests.get(url, headers=headers, timeout=5)
    except requests.exceptions.RequestException as e:
        print(f"[WARN] Network error contacting Plex: {e}")
        return None

    if response.status_code != 200:
        print(f"[INFO] Plex responded with status {response.status_code}. Possibly idle.")
        return None

    try:
        data = response.json()
    except ValueError:
        print("[WARN] Plex response not valid JSON")
        return None

    for media in data.get("MediaContainer", {}).get("Metadata", []):
        if media.get("type") == "track":
            album_artist = media.get("grandparentTitle") or "Various Artists"
            return {
                "artist": media.get("originalTitle") or media.get("grandparentTitle"),
                "album": media.get("parentTitle"),
                "track": media.get("title"),
                "albumArtist": album_artist
            }

    return None

def lastfm_now_playing(track, artist, album, album_artist):
    """Send now playing update to Last.fm."""
    url = "https://ws.audioscrobbler.com/2.0/"

    params = {
        "method": "track.updateNowPlaying",
        "api_key": LASTFM_API_KEY,
        "sk": LASTFM_SESSION_KEY,
        "artist": artist,
        "track": track,
        "album": album,
        "albumArtist": album_artist,  # This is to include album artist for compilations
        "format": "json"
    }

    # Generate API signature
    api_sig = generate_lastfm_signature(params)
    params["api_sig"] = api_sig

    response = requests.post(url, data=params)
    if response.status_code == 200:
        print(f"Updated now playing: {artist} - {track}")
    else:
        print("Error sending now playing update:", response.json())

def generate_lastfm_signature(params):
    """Generate Last.fm API signature for authentication."""
    # Remove 'format' before generating signature (not needed in sig calculation)
    params.pop("format", None)

    # Concatenate parameters in alphabetical order
    sorted_params = "".join(f"{key}{params[key]}" for key in sorted(params))

    # Append API secret and hash using MD5
    sig_string = sorted_params + LASTFM_API_SECRET
    return hashlib.md5(sig_string.encode()).hexdigest()

if __name__ == "__main__":
    while True:
        now_playing = get_currently_playing()
        if now_playing:
            lastfm_now_playing(now_playing["track"], now_playing["artist"], now_playing["album"], now_playing["albumArtist"])
        time.sleep(5)  # Check every 5 seconds
