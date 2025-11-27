import os
import threading
import time

import uvicorn
import webview


def start_server():
    uvicorn.run("backend.server:app", host="127.0.0.1", port=8001, log_level="info")


if __name__ == "__main__":
    if not os.path.exists("data"):
        os.makedirs("data")

    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()

    # Wait a bit for the server to start
    time.sleep(1)

    webview.create_window("BiliMusic", "http://127.0.0.1:8001/", width=900,height=600)
    webview.start()
