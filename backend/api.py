import asyncio
import json
import os
from bilibili_api import search, video, sync, Credential, user as bili_user
import httpx
import base64

CREDENTIAL_FILE = os.path.join("data", "credential.json")

# Initialize Credential (empty for now, or load from env/config if needed)
# For public videos, empty credential usually works for 360p/480p and basic audio.
# High quality audio might need SESSDATA.
credential = Credential()


def load_credential_from_file():
    global credential
    if not os.path.exists(CREDENTIAL_FILE):
        return
    try:
        with open(CREDENTIAL_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        credential_local = Credential(
            sessdata=data.get("sessdata", ""),
            bili_jct=data.get("bili_jct", ""),
            dedeuserid=data.get("dedeuserid", ""),
            ac_time_value=data.get("ac_time_value", ""),
        )
        credential = credential_local
    except Exception as e:
        print(f"Load credential error: {e}")


def save_credential_to_file(cred: Credential):
    global credential
    credential = cred
    os.makedirs(os.path.dirname(CREDENTIAL_FILE), exist_ok=True)
    data = {
        "sessdata": getattr(cred, "sessdata", ""),
        "bili_jct": getattr(cred, "bili_jct", ""),
        "dedeuserid": getattr(cred, "dedeuserid", ""),
        "ac_time_value": getattr(cred, "ac_time_value", ""),
    }
    try:
        with open(CREDENTIAL_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Save credential error: {e}")


def get_login_status():
    return {
        "logged_in": bool(getattr(credential, "sessdata", "")),
        "dedeuserid": getattr(credential, "dedeuserid", None),
    }


async def get_login_info():
    base = get_login_status()
    info = None
    if base["logged_in"] and base.get("dedeuserid"):
        try:
            uid = int(base["dedeuserid"])
            u = bili_user.User(uid=uid, credential=credential)
            data = await u.get_user_info()
            face_url = data.get("face")
            face_data_uri = None
            if face_url:
                if face_url.startswith("//"):
                    face_url = "https:" + face_url
                face_data_uri = await fetch_image_as_data_uri(face_url)

            vip_data = data.get("vip") or {}
            level_info = data.get("level_info") or {}

            info = {
                "mid": data.get("mid"),
                "name": data.get("name") or data.get("uname"),
                "face": face_data_uri,
                "sign": data.get("sign"),
                "sex": data.get("sex"),
                "level": level_info.get("current_level") or data.get("level"),
                "vip_type": vip_data.get("type"),
                "vip_label": (vip_data.get("label") or {}).get("text"),
            }
        except Exception as e:
            print(f"Get user info error: {e}")
    base["user"] = info
    return base


def logout():
    global credential
    credential = Credential()
    try:
        if os.path.exists(CREDENTIAL_FILE):
            os.remove(CREDENTIAL_FILE)
    except Exception as e:
        print(f"Remove credential file error: {e}")


load_credential_from_file()


async def fetch_image_as_data_uri(url, client=None):
    if not url:
        return None

    close_client = False
    if client is None:
        client = httpx.AsyncClient(timeout=10)
        close_client = True

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Referer": "https://www.bilibili.com/",
        }
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "image/jpeg")
        b64 = base64.b64encode(resp.content).decode("ascii")
        return f"data:{content_type};base64,{b64}"
    except Exception as e:
        print(f"Fetch image error: {e}")
        return None
    finally:
        if close_client:
            await client.aclose()

async def search_videos(keyword, page=1):
    try:
        # search_type=video
        res = await search.search_by_type(
            keyword,
            search_type=search.SearchObjectType.VIDEO,
            page=page,
            page_size=20,
        )
        # Format results
        items = []
        if 'result' in res and res['result']:
            async with httpx.AsyncClient(timeout=10) as client:
                # 先为所有结果构建图片 URL 列表
                pic_urls = []
                for item in res['result']:
                    raw_pic = item.get("pic")
                    if not raw_pic:
                        pic_urls.append(None)
                        continue
                    pic_url = "https:" + raw_pic if raw_pic.startswith("//") else raw_pic
                    pic_urls.append(pic_url)

                # 并发请求所有封面图片
                tasks = [
                    fetch_image_as_data_uri(url, client=client) if url else asyncio.sleep(0, result=None)
                    for url in pic_urls
                ]
                pic_data_list = await asyncio.gather(*tasks)

                # 组装返回结果
                for item, pic_data_uri in zip(res['result'], pic_data_list):
                    items.append({
                        "bvid": item.get("bvid"),
                        "title": item.get("title").replace("<em class=\"keyword\">", "").replace("</em>", ""),
                        "author": item.get("author"),
                        "pic": pic_data_uri,
                        "duration": item.get("duration"),
                        "play": item.get("play")
                    })
        return {"items": items, "page": page, "has_more": res.get("numPages", 0) > page}
    except Exception as e:
        print(f"Search error: {e}")
        return {"error": str(e)}

async def get_video_details(bvid):
    try:
        v = video.Video(bvid=bvid, credential=credential)
        info = await v.get_info()
        
        pic_data_uri = None
        pic_url = info.get("pic")
        if pic_url:
            if pic_url.startswith("//"):
                pic_url = "https:" + pic_url
            pic_data_uri = await fetch_image_as_data_uri(pic_url)

        # Extract pages (P)
        pages = []
        if "pages" in info:
            for p in info["pages"]:
                pages.append({
                    "cid": p["cid"],
                    "page": p["page"],
                    "part": p["part"],
                    "duration": p.get("duration") # seconds
                })
        
        return {
            "bvid": bvid,
            "title": info.get("title"),
            "pic": pic_data_uri,
            "desc": info.get("desc"),
            "owner": info.get("owner", {}).get("name"),
            "pages": pages
        }
    except Exception as e:
        print(f"Get info error: {e}")
        return {"error": str(e)}

async def get_audio_stream_url(bvid, cid=None):
    try:
        v = video.Video(bvid=bvid, credential=credential)
        
        # If cid is not provided, get the first page's cid
        if not cid:
            info = await v.get_info()
            cid = info["pages"][0]["cid"]
            
        # Get download url
        # fnval=16 (DASH format) is usually better for separate audio/video streams
        download_url_data = await v.get_download_url(cid=cid)
        
        detecter = video.VideoDownloadURLDataDetecter(data=download_url_data)
        streams = detecter.detect_best_streams()
        
        # We prefer audio stream. 
        # detect_best_streams() returns a list of streams.
        # If DASH is available, we look for audio only stream.
        
        target_url = None
        
        # Check if we have dash audio
        if 'dash' in download_url_data:
            # In DASH, audio is usually separate.
            # Accessing raw dash audio streams
            if 'audio' in download_url_data['dash']:
                audios = download_url_data['dash']['audio']
                if audios:
                    # Sort by bandwidth/quality?
                    # Usually the first one is good enough or best.
                    target_url = audios[0]['base_url']
                    # Backup url? audios[0]['backup_url']
        
        if not target_url:
            # Fallback to FLV/MP4 (might be full video file, bandwidth heavy but works)
            if streams:
                target_url = streams[0].url

        return {
            "url": target_url,
            "user_agent": "Mozilla/5.0",
            "referer": "https://www.bilibili.com" 
        }
    except Exception as e:
        print(f"Get audio error: {e}")
        return {"error": str(e)}
