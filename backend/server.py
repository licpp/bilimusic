import urllib3
import requests
import base64
import os
import uuid
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import List, Optional, Dict

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import StreamingResponse, HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from bilibili_api import login_v2
from bilibili_api.utils.geetest import Geetest, GeetestType

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


@dataclass
class SmsLoginSession:
    geetest: Geetest
    phone: Optional[login_v2.PhoneNumber] = None
    captcha_id: Optional[str] = None
    login_check: Optional[login_v2.LoginCheck] = None
    verify_geetest: Optional[Geetest] = None
    done: bool = False


qr_sessions: Dict[str, login_v2.QrCodeLogin] = {}
sms_sessions: Dict[str, SmsLoginSession] = {}


class SmsSendCodeRequest(BaseModel):
    session_id: str
    phone: str


class SmsVerifyCodeRequest(BaseModel):
    session_id: str
    code: str


class SmsCheckCompleteRequest(BaseModel):
    session_id: str
    code: str


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


@app.get("/api/login/status")
def login_status():
    return bili_api.get_login_status()


@app.get("/api/login/info")
async def login_info():
    return await bili_api.get_login_info()


@app.post("/api/logout")
def logout():
    bili_api.logout()
    return {"success": True}


@app.post("/api/login/qrcode/start")
async def login_qrcode_start():
    qr = login_v2.QrCodeLogin(platform=login_v2.QrCodeLoginChannel.WEB)
    await qr.generate_qrcode()
    picture = qr.get_qrcode_picture()
    img_b64 = base64.b64encode(picture.content).decode("ascii")
    session_id = uuid.uuid4().hex
    qr_sessions[session_id] = qr
    return {"session_id": session_id, "qrcode_image": f"data:image/png;base64,{img_b64}"}


@app.get("/api/login/qrcode/status")
async def login_qrcode_status(session_id: str = Query(...)):
    qr = qr_sessions.get(session_id)
    if not qr:
        raise HTTPException(status_code=404, detail="Session not found")

    if qr.has_done():
        cred = qr.get_credential()
        bili_api.save_credential_to_file(cred)
        qr_sessions.pop(session_id, None)
        return {"status": "done"}

    event = await qr.check_state()
    if event == login_v2.QrCodeLoginEvents.SCAN:
        status = "scan"
    elif event == login_v2.QrCodeLoginEvents.CONF:
        status = "confirm"
    elif event == login_v2.QrCodeLoginEvents.TIMEOUT:
        status = "timeout"
        qr_sessions.pop(session_id, None)
    else:
        status = "unknown"
    return {"status": status}


@app.post("/api/login/sms/geetest/start")
async def sms_geetest_start():
    gee = Geetest()
    await gee.generate_test(GeetestType.LOGIN)
    gee.start_geetest_server()
    session_id = uuid.uuid4().hex
    sms_sessions[session_id] = SmsLoginSession(geetest=gee)
    return {"session_id": session_id, "geetest_url": gee.get_geetest_server_url()}


@app.get("/api/login/sms/geetest/status")
def sms_geetest_status(session_id: str = Query(...)):
    session = sms_sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"done": session.geetest.has_done()}


@app.post("/api/login/sms/send_code")
async def sms_send_code(body: SmsSendCodeRequest):
    session = sms_sessions.get(body.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if not session.geetest.has_done():
        raise HTTPException(status_code=400, detail="Geetest not completed")

    phone = login_v2.PhoneNumber(body.phone, "+86")
    captcha_id = await login_v2.send_sms(phonenumber=phone, geetest=session.geetest)
    try:
        session.geetest.close_geetest_server()
    except Exception:
        pass
    session.phone = phone
    session.captcha_id = captcha_id
    return {"status": "sms_sent"}


@app.post("/api/login/sms/verify")
async def sms_verify(body: SmsVerifyCodeRequest):
    session = sms_sessions.get(body.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if not session.phone or not session.captcha_id:
        raise HTTPException(status_code=400, detail="SMS not sent")

    cred_or_check = await login_v2.login_with_sms(
        phonenumber=session.phone,
        code=body.code,
        captcha_id=session.captcha_id,
    )

    if isinstance(cred_or_check, login_v2.LoginCheck):
        gee = Geetest()
        await gee.generate_test(type_=GeetestType.VERIFY)
        gee.start_geetest_server()
        session.login_check = cred_or_check
        session.verify_geetest = gee
        return {"status": "need_verify", "geetest_url": gee.get_geetest_server_url()}

    cred = cred_or_check
    bili_api.save_credential_to_file(cred)
    session.done = True
    return {"status": "done"}


@app.post("/api/login/sms/verify_complete")
async def sms_verify_complete(body: SmsCheckCompleteRequest):
    session = sms_sessions.get(body.session_id)
    if not session or not session.login_check or not session.verify_geetest:
        raise HTTPException(status_code=404, detail="Session not found")
    if not session.verify_geetest.has_done():
        raise HTTPException(status_code=400, detail="Geetest not completed")

    await session.login_check.send_sms(session.verify_geetest)
    try:
        session.verify_geetest.close_geetest_server()
    except Exception:
        pass
    cred = await session.login_check.complete_check(body.code)
    bili_api.save_credential_to_file(cred)
    session.done = True
    return {"status": "done"}


@app.get("/", response_class=HTMLResponse)
def index():
    # --- 修复：使用动态计算的 web_path ---
    index_file = os.path.join(web_path, "index.html")
    with open(index_file, "r", encoding="utf-8") as f:
        return f.read()


# --- 修复：使用动态计算的 web_path ---
app.mount("/static", StaticFiles(directory=web_path), name="static")