import urllib3
import requests
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import StreamingResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import api as bili_api
from . import store

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = FastAPI()


class PlaylistCreate(BaseModel):
    name: str


class PlaylistRename(BaseModel):
    name: str


class SongInfo(BaseModel):
    bvid: str
    cid: int
    title: str
    artist: str
    duration: str
    cover: str


class ReorderSongsRequest(BaseModel):
    song_uuids: List[str]


@app.get("/api/playlists")
def get_all_playlists():
    return store.get_all_playlists()


@app.post("/api/playlists")
def create_playlist(payload: PlaylistCreate):
    return store.create_playlist(payload.name)


@app.delete("/api/playlists/{playlist_id}")
def delete_playlist(playlist_id: str):
    store.delete_playlist(playlist_id)
    return {"success": True}


@app.put("/api/playlists/{playlist_id}")
def rename_playlist(playlist_id: str, payload: PlaylistRename):
    store.rename_playlist(playlist_id, payload.name)
    return {"success": True}


@app.post("/api/playlists/{playlist_id}/songs")
def add_song(playlist_id: str, song: SongInfo):
    ok = store.add_song(playlist_id, song.dict())
    if not ok:
        raise HTTPException(status_code=404, detail="Playlist not found")
    return {"success": True}


@app.delete("/api/playlists/{playlist_id}/songs/{song_uuid}")
def remove_song(playlist_id: str, song_uuid: str):
    ok = store.remove_song(playlist_id, song_uuid)
    if not ok:
        raise HTTPException(status_code=404, detail="Playlist or song not found")
    return {"success": True}


@app.post("/api/playlists/{playlist_id}/songs/reorder")
def reorder_songs(playlist_id: str, body: ReorderSongsRequest):
    ok = store.reorder_songs(playlist_id, body.song_uuids)
    if not ok:
        raise HTTPException(status_code=404, detail="Playlist not found")
    return {"success": True}


@app.get("/api/search")
async def search_videos(keyword: str = Query(...), page: int = Query(1, ge=1)):
    return await bili_api.search_videos(keyword, page)


@app.get("/api/videos/{bvid}")
async def get_video_details(bvid: str):
    return await bili_api.get_video_details(bvid)


@app.get("/api/audio_url")
async def get_audio_url(bvid: str, cid: Optional[int] = None):
    return await bili_api.get_audio_stream_url(bvid, cid)


@app.get("/stream")
def stream_audio(request: Request, url: str = Query(...)):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Referer": "https://www.bilibili.com/",
    }

    range_header = request.headers.get("range") or request.headers.get("Range")
    if range_header:
        headers["Range"] = range_header

    resp = requests.get(url, headers=headers, stream=True, verify=False)

    def iter_stream():
        for chunk in resp.iter_content(chunk_size=1024 * 1024):
            if chunk:
                yield chunk

    response_headers = {}
    content_type = resp.headers.get("Content-Type", "audio/mp4")
    response_headers["Content-Type"] = content_type

    for h in ["Content-Length", "Content-Range", "Accept-Ranges"]:
        if h in resp.headers:
            response_headers[h] = resp.headers[h]

    if "Accept-Ranges" not in response_headers:
        response_headers["Accept-Ranges"] = "bytes"

    return StreamingResponse(
        iter_stream(),
        status_code=resp.status_code,
        headers=response_headers,
    )


@app.get("/", response_class=HTMLResponse)
def index():
    index_path = Path("web") / "index.html"
    return index_path.read_text(encoding="utf-8")


app.mount("/static", StaticFiles(directory="web"), name="static")
