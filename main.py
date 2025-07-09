import json
import re
from tarfile import CONTTYPE
import asyncio
import logging
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
import httpx
import urllib.parse

# 配置日志
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = FastAPI()

config = json.load(open("config.json"))

url_api_map = {
    "douyin": config["douyin"],
    "other": config["other"],
}


@app.post("/download")
async def download_video(request: Request, message: str):
    """专门用于下载视频的端点，直接返回文件流"""
    url_list = re.findall('http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', message)
    
    if not url_list:
        return JSONResponse({"error": "Invalid URL"}, status_code=400)
    
    # 只处理第一个URL
    url = url_list[0]
    
    if "douyin" in url:
        url_api = url_api_map["douyin"]
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                resp = await client.get(url_api, params={"url": url})
                # 如果抖音API返回的是文件内容，直接返回
                if resp.headers.get("content-type", "").startswith("video/"):
                    filename = resp.headers.get('Content-Disposition').split('filename=')[1].replace('"', '').replace("'", '')
                    # 使用安全的文件名
                    quoted_filename = urllib.parse.quote(filename)
                    return Response(
                        content=resp.content,
                        media_type=resp.headers.get("content-type", "video/mp4"),
                        headers={
                            "Content-Disposition": f"attachment; filename*=UTF-8''{quoted_filename}"
                        }
                    )
                else:
                    # 如果返回的是JSON信息，包含下载链接
                    return JSONResponse(content=resp.json(), status_code=resp.status_code)
            except httpx.RequestError as e:
                return JSONResponse({"error": str(e)}, status_code=502)
    else:
        url_api = url_api_map["other"]
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                # 1. add
                add_resp = await client.post(url_api + "/add", json={"url": url, "quality": "1080p", "format": "mp4"})

                if add_resp.status_code != 200:
                    return JSONResponse({"error": add_resp.json()}, status_code=add_resp.status_code)
                
                if add_resp.json()["status"] != "ok":
                    return JSONResponse({"error": add_resp.json()}, status_code=400)
                
                # 2. wait and poll
                max_attempts = 60
                attempts = 0

                while attempts < max_attempts:
                    history_resp = await client.get(url_api + "/history")
                    history_data = history_resp.json()
                    logger.info(f"history_data: {history_data}")
                    
                    for item in history_data.get("done", []):
                        if item.get("id") in url:
                            filename = item.get("filename")
                            if filename:
                                # 3. download and return file
                                download_resp = await client.get(url_api + "/download/" + filename)
                                # 正确处理中文文件名
                                quoted_filename = urllib.parse.quote(filename)
                                return Response(
                                    content=download_resp.content,
                                    media_type=download_resp.headers.get("content-type", "video/mp4"),
                                    headers={
                                        "Content-Disposition": f"attachment; filename*=UTF-8''{quoted_filename}"
                                    }
                                )
                    attempts += 1
                    await asyncio.sleep(5)
                
                return JSONResponse({"error": "Download timeout"}, status_code=408)
            except httpx.RequestError as e:
                return JSONResponse({"error": str(e)}, status_code=502) 