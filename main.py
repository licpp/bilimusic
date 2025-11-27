import os
import sys
import threading
import time
import ctypes

import uvicorn
import webview

from backend.server import app 

def get_resource_path(relative_path):
    """
    获取资源文件的绝对路径。
    兼容开发环境（直接运行 Python）和 PyInstaller 打包后的环境。
    """
    if hasattr(sys, '_MEIPASS'):
        # PyInstaller 打包后，资源文件会被解压到 sys._MEIPASS 目录下
        base_path = sys._MEIPASS
    else:
        # 开发环境，使用当前脚本所在的目录
        base_path = os.path.dirname(os.path.abspath(__file__))
    
    return os.path.join(base_path, relative_path)

def start_server():
    # 启动 FastAPI 服务
    # host 设置为 127.0.0.1 仅供本地访问
    uvicorn.run(app, host="127.0.0.1", port=8001, log_level="error")

def set_app_user_model_id():
    """
    设置 Windows AppUserModelID。
    这能解决任务栏图标显示为空白或 Python 默认图标的问题。
    """
    if os.name == 'nt':
        try:
            # 这是一个任意的字符串，但必须唯一
            myappid = 'bilimusic.app.desktop.version1' 
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
        except Exception:
            print("Failed to set AppUserModelID")
            pass

if __name__ == "__main__":
    # 1. 设置 AppID (必须在创建窗口之前调用)
    set_app_user_model_id()

    # 2. 确保数据目录存在
    # 如果是打包环境，sys.executable 是 exe 的路径，数据应该存储在 exe 同级目录
    if hasattr(sys, '_MEIPASS'):
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        
    data_dir = os.path.join(base_dir, "data")
    if not os.path.exists(data_dir):
        os.makedirs(data_dir)

    # 3. 启动后端服务器线程
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()

    # 等待一秒确保服务器已准备好
    time.sleep(1)

    # 4. 获取图标路径 (用于窗口标题栏)
    # 这里的路径 "img/logo.ico" 对应你打包命令中的 --add-data "img;img"
    icon_path = get_resource_path(os.path.join("img", "logo.ico"))

    # 5. 创建窗口
    # 注意：create_window 不要传 icon 参数
    window = webview.create_window(
        "BiliMusic", 
        "http://127.0.0.1:8001/", 
        width=900, 
        height=600
    )

    # 6. 启动应用并传入图标
    # icon 参数必须放在这里，才能同时修复窗口标题栏图标
    webview.start(icon=icon_path)