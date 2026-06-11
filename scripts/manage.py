# -*- coding: utf-8 -*-
"""维测管理脚本（跨平台，仅依赖标准库）。

用法: python scripts/manage.py <status|start|stop|force_stop|restart>

  status      查看服务是否运行、监听端口与进程 PID
  start       后台启动服务（输出追加到 data/server.log）
  stop        停止占用服务端口的进程（Linux 先发 SIGTERM 优雅退出）
  force_stop  强制停止：杀掉端口进程 + 所有运行 app.py 的 python 残留进程
  restart     stop 后等待端口释放再 start

端口读取 config/app_config.json 的 server.port（环境变量 PORT 优先）。
数据库为 SQLite WAL 模式，强制停止不会损坏数据。
"""
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IS_WIN = os.name == "nt"
LOG_PATH = os.path.join(BASE_DIR, "data", "server.log")


def get_port():
    if os.environ.get("PORT"):
        return int(os.environ["PORT"])
    with open(os.path.join(BASE_DIR, "config", "app_config.json"), encoding="utf-8") as f:
        return int(json.load(f).get("server", {}).get("port", 8000))


def port_open(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex(("127.0.0.1", port)) == 0


def listening_pids(port):
    """返回监听指定端口的进程 PID 列表。"""
    pids = set()
    if IS_WIN:
        out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True).stdout
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 5 and parts[0] == "TCP" and parts[3] == "LISTENING" \
                    and parts[1].endswith(f":{port}"):
                pids.add(int(parts[4]))
    else:
        out = subprocess.run(["ss", "-lntp"], capture_output=True, text=True).stdout
        for line in out.splitlines():
            if f":{port} " in line:
                pids.update(int(m) for m in re.findall(r"pid=(\d+)", line))
    return sorted(pids)


def app_py_pids():
    """返回所有命令行包含 app.py 的 python 进程 PID（用于清理残留实例）。"""
    pids = set()
    me = os.getpid()
    if IS_WIN:
        cmd = ["powershell", "-NoProfile", "-Command",
               "Get-CimInstance Win32_Process -Filter \"Name like 'python%'\" | "
               "Where-Object { $_.CommandLine -match 'app\\.py' } | "
               "Select-Object -ExpandProperty ProcessId"]
        out = subprocess.run(cmd, capture_output=True, text=True).stdout
        pids.update(int(p) for p in out.split() if p.isdigit())
    else:
        out = subprocess.run(["pgrep", "-f", "app.py"], capture_output=True, text=True).stdout
        pids.update(int(p) for p in out.split() if p.isdigit())
    pids.discard(me)
    return sorted(pids)


def parent_pids(pids):
    """返回各 PID 的父进程号（Windows venv 的 python.exe 是启动器，父子进程命令行相同）。"""
    parents = set()
    for pid in pids:
        if IS_WIN:
            cmd = ["powershell", "-NoProfile", "-Command",
                   f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}').ParentProcessId"]
        else:
            cmd = ["ps", "-o", "ppid=", "-p", str(pid)]
        out = subprocess.run(cmd, capture_output=True, text=True).stdout.strip()
        if out.isdigit():
            parents.add(int(out))
    return parents


def kill(pid, force=False):
    try:
        if IS_WIN:
            # Windows 控制台进程不支持优雅退出，统一带 /F；/T 连带子进程
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                           capture_output=True, text=True)
        else:
            os.kill(pid, signal.SIGKILL if force else signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass


def venv_python():
    p = os.path.join(BASE_DIR, "venv", "Scripts" if IS_WIN else "bin",
                     "python.exe" if IS_WIN else "python")
    return p if os.path.exists(p) else sys.executable


def cmd_status():
    port = get_port()
    pids = listening_pids(port)
    if pids:
        print(f"运行中：端口 {port}，PID {', '.join(map(str, pids))}")
    else:
        print(f"未运行：端口 {port} 无监听进程")
    # venv 启动器父进程与监听进程命令行相同，不算残留
    known = set(pids) | parent_pids(pids)
    stray = [p for p in app_py_pids() if p not in known]
    if stray:
        print(f"警告：发现 {len(stray)} 个未监听端口的 app.py 残留进程（PID {', '.join(map(str, stray))}），"
              f"建议执行 force_stop 清理")
    return 0 if pids else 1


def cmd_stop(quiet=False):
    port = get_port()
    pids = listening_pids(port)
    if not pids:
        if not quiet:
            print(f"服务未在运行（端口 {port} 无监听进程）")
        return 0
    for pid in pids:
        kill(pid)
    # 等待端口释放（Linux SIGTERM 需要时间优雅退出）
    for _ in range(10):
        if not port_open(port):
            print(f"已停止服务（PID {', '.join(map(str, pids))}）")
            return 0
        time.sleep(0.5)
    print("停止超时，进程可能未退出，请执行 force_stop")
    return 1


def cmd_force_stop():
    port = get_port()
    targets = set(listening_pids(port)) | set(app_py_pids())
    if not targets:
        print("没有需要清理的进程")
        return 0
    for pid in sorted(targets):
        kill(pid, force=True)
    time.sleep(1)
    remain = set(listening_pids(port)) | set(app_py_pids())
    if remain:
        print(f"仍有进程未退出：PID {', '.join(map(str, remain))}（请检查权限）")
        return 1
    print(f"已强制停止 {len(targets)} 个进程，端口 {port} 已释放")
    return 0


def cmd_start():
    port = get_port()
    if port_open(port):
        print(f"服务已在运行（端口 {port}），如需重启请用 restart")
        return 1
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    log = open(LOG_PATH, "a", encoding="utf-8")
    log.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} 启动 =====\n")
    log.flush()
    kwargs = dict(cwd=BASE_DIR, stdout=log, stderr=subprocess.STDOUT,
                  stdin=subprocess.DEVNULL)
    if IS_WIN:
        # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP：脱离当前控制台，关窗口不影响服务
        kwargs["creationflags"] = 0x00000008 | 0x00000200
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen([venv_python(), os.path.join(BASE_DIR, "app.py")], **kwargs)
    for _ in range(20):
        if port_open(port):
            print(f"服务已启动：http://127.0.0.1:{port} （PID {proc.pid}，日志 data/server.log）")
            return 0
        if proc.poll() is not None:
            break
        time.sleep(0.5)
    print("启动失败，请查看 data/server.log")
    return 1


def cmd_restart():
    if cmd_stop(quiet=True) != 0:
        print("优雅停止失败，改用强制停止")
        if cmd_force_stop() != 0:
            return 1
    return cmd_start()


COMMANDS = {"status": cmd_status, "start": cmd_start, "stop": cmd_stop,
            "force_stop": cmd_force_stop, "restart": cmd_restart}

if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in COMMANDS:
        print(__doc__.strip())
        sys.exit(2)
    sys.exit(COMMANDS[sys.argv[1]]() or 0)
