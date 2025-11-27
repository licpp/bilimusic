import urllib3
import requests
import os
import sys
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import StreamingResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# 保持原来的相对导入不变
from . import api as bili_api
from . import store

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = FastAPI()

# --- 核心修复：资源路径处理逻辑 ---
def get_resource_path(relative_path):
    """
    获取资源文件的绝对路径。
    兼容开发环境和 PyInstaller 打包环境。
    """
    if hasattr(sys, '_MEIPASS'):
        # PyInstaller 打包后，web 文件夹会被解压到 sys._MEIPASS/web
        return os.path.join(sys._MEIPASS, relative_path)
    
    # 开发环境，假设 web 文件夹在项目根目录（即 backend 的上一级）
    # 或者直接使用相对路径，取决于你运行 main.py 的位置
    return os.path.join(os.path.abspath("."), relative_path)

# 获取 web 文件夹的真实路径
web_path = get_resource_path("web")

# 检查路径是否存在，方便调试
if not os.path.exists(web_path):
    print(f"Warning: Web directory not found at {web_path}")

# --- 这里的修改结束 ---

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

    # 注意：verify=False 可能有安全风险，但在代理流媒体时有时是必要的
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
    # --- 修复：使用动态计算的 web_path ---
    index_file = os.path.join(web_path, "index.html")
    with open(index_file, "r", encoding="utf-8") as f:
        return f.read()


# --- 修复：使用动态计算的 web_path ---
app.mount("/static", StaticFiles(directory=web_path), name="static")