import json
import os
import uuid
from datetime import datetime

DATA_FILE = os.path.join("data", "playlists.json")
FAVORITE_ID = "favorite"
FAVORITE_NAME = "My Favorite"

def _load_data():
    if not os.path.exists(DATA_FILE):
        data = []
    else:
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except:
            data = []

    # Ensure fixed "My Favorite" playlist exists and has stable id/name
    favorite = None
    for p in data:
        if p.get("id") == FAVORITE_ID or p.get("name") == FAVORITE_NAME:
            favorite = p
            break

    if favorite is None:
        favorite = {
            "id": FAVORITE_ID,
            "name": FAVORITE_NAME,
            "created_at": datetime.now().isoformat(),
            "songs": []
        }
        data.append(favorite)
    else:
        favorite["id"] = FAVORITE_ID
        favorite["name"] = FAVORITE_NAME

    _save_data(data)
    return data

def _save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_all_playlists():
    return _load_data()

def create_playlist(name):
    data = _load_data()
    new_playlist = {
        "id": str(uuid.uuid4()),
        "name": name,
        "created_at": datetime.now().isoformat(),
        "songs": []
    }
    data.append(new_playlist)
    _save_data(data)
    return new_playlist

def delete_playlist(playlist_id):
    if playlist_id == FAVORITE_ID:
        return True
    data = _load_data()
    data = [p for p in data if p["id"] != playlist_id]
    _save_data(data)
    return True

def rename_playlist(playlist_id, new_name):
    if playlist_id == FAVORITE_ID:
        return True
    data = _load_data()
    for p in data:
        if p["id"] == playlist_id:
            p["name"] = new_name
            break
    _save_data(data)
    return True

def add_song(playlist_id, song_info):
    """
    song_info: {
        "bvid": str,
        "cid": int,
        "title": str,
        "artist": str, # UP owner
        "duration": str,
        "cover": str
    }
    """
    data = _load_data()
    for p in data:
        if p["id"] == playlist_id:
            # Check for duplicates? Maybe not strictly required, but good practice.
            # For now, allow duplicates or just append.
            song_entry = song_info.copy()
            song_entry["added_at"] = datetime.now().isoformat()
            song_entry["uuid"] = str(uuid.uuid4()) # Unique ID for this instance in playlist
            p["songs"].append(song_entry)
            _save_data(data)
            return True
    return False

def remove_song(playlist_id, song_uuid):
    data = _load_data()
    for p in data:
        if p["id"] == playlist_id:
            p["songs"] = [s for s in p["songs"] if s.get("uuid") != song_uuid]
            _save_data(data)
            return True
    return False

def reorder_songs(playlist_id, song_uuids):
    data = _load_data()
    for p in data:
        if p["id"] == playlist_id:
            # Create a map for O(1) lookup
            song_map = {s["uuid"]: s for s in p["songs"]}
            new_list = []
            for uid in song_uuids:
                if uid in song_map:
                    new_list.append(song_map[uid])
            # Append any that might be missing from the input list (safety)
            existing_ids = set(song_uuids)
            for s in p["songs"]:
                if s["uuid"] not in existing_ids:
                    new_list.append(s)
            p["songs"] = new_list
            _save_data(data)
            return True
    return False
