# -*- coding: utf-8 -*-
"""本机网络探测与 Windows waitress 兼容补丁。"""
import errno
import os
import socket
import time


def _primary_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    finally:
        s.close()


def _loopback_connect_ok(timeout=1):
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.settimeout(timeout)
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        probe.connect(srv.getsockname())
        return True
    except OSError:
        return False
    finally:
        probe.close()
        srv.close()


def resolve_loopback_host():
    """返回本机可用于内部 TCP 绑定的地址。

    部分 Windows 环境（VPN/TUN/安全软件）会导致 127.0.0.1 回环 connect 超时，
    waitress 触发器因此无法初始化。此时回退到本机局域网 IP。
    """
    env = os.environ.get("SERVER_BIND_HOST", "").strip()
    if env:
        return env
    if os.name != "nt":
        return "127.0.0.1"

    for _ in range(3):
        if _loopback_connect_ok():
            return "127.0.0.1"
        time.sleep(0.2)
    return _primary_local_ip()


def resolve_access_url(port):
    """返回浏览器/客户端应使用的访问地址。"""
    host = resolve_loopback_host()
    if host == "127.0.0.1":
        return f"http://127.0.0.1:{port}"
    return f"http://{host}:{port}"


def port_is_open(port, timeout=1):
    """探测端口是否已有服务在监听。"""
    hosts = []
    for host in (resolve_loopback_host(), "127.0.0.1"):
        if host not in hosts:
            hosts.append(host)
    for host in hosts:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            if s.connect_ex((host, port)) == 0:
                return True
    return False


def patch_waitress_trigger(bind_host=None):
    """Windows 下将 waitress 内部触发器绑定到可用地址。"""
    if os.name != "nt":
        return
    bind_host = bind_host or resolve_loopback_host()
    if bind_host == "127.0.0.1":
        return

    import waitress.trigger as trig
    import waitress.wasyncore

    if getattr(trig.trigger, "_campus_bind_host", None) == bind_host:
        return

    class trigger(trig._triggerbase, waitress.wasyncore.dispatcher):
        kind = "loopback"
        _campus_bind_host = bind_host

        def __init__(self, map):
            trig._triggerbase.__init__(self)
            w = socket.socket()
            w.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            count = 0
            while True:
                count += 1
                a = socket.socket()
                a.bind((bind_host, 0))
                connect_address = a.getsockname()
                a.listen(1)
                try:
                    w.connect(connect_address)
                    break
                except OSError as detail:
                    if getattr(detail, "winerror", None) != errno.WSAEADDRINUSE:
                        raise
                    if count >= 10:
                        a.close()
                        w.close()
                        raise RuntimeError("Cannot bind trigger!")
                    a.close()
            r, _addr = a.accept()
            a.close()
            self.trigger = w
            waitress.wasyncore.dispatcher.__init__(self, r, map=map)

        def _close(self):
            self.socket.close()
            self.trigger.close()

        def _physical_pull(self):
            self.trigger.send(b"x")

    trig.trigger = trigger


def serve_waitress(app, **kwargs):
    """启动 waitress；Windows 回环异常时自动改用局域网 IP 触发器。"""
    from waitress import serve

    bind_hosts = []
    for host in (resolve_loopback_host(), _primary_local_ip()):
        if host not in bind_hosts:
            bind_hosts.append(host)

    last_err = None
    for bind_host in bind_hosts:
        patch_waitress_trigger(bind_host)
        try:
            serve(app, **kwargs)
            return
        except TimeoutError as err:
            if os.name != "nt" or getattr(err, "winerror", None) != 10060:
                raise
            last_err = err
            continue
    if last_err is not None:
        raise last_err
