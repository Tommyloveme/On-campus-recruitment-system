# -*- coding: utf-8 -*-
"""一次性冒烟测试脚本：覆盖登录/权限/CRUD/Excel导入/简历/分组配置/并发/日志/总览。"""
import io
import json
import threading
import urllib.request
from urllib.parse import quote
import http.cookiejar
import uuid
import zipfile

from openpyxl import Workbook

BASE = "http://127.0.0.1:8000"
cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))


def call(method, path, payload=None, raw=None, ctype="application/json", expect_error=False):
    data = json.dumps(payload).encode() if payload is not None else raw
    req = urllib.request.Request(BASE + path, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", ctype)
    try:
        with opener.open(req) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        if not expect_error:
            raise
        return e.code, json.loads(e.read().decode())


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    assert cond, name


# 1. 登录
s, me = call("POST", "/api/login", {"username": "admin", "password": "admin123"})
check("管理员登录", s == 200 and me["role"] == "admin")

s, _ = call("POST", "/api/login", {"username": "admin", "password": "wrong"}, expect_error=True)
check("错误密码被拒绝", s == 401)
call("POST", "/api/login", {"username": "admin", "password": "admin123"})

# 2. 配置与分组
s, cfg = call("GET", "/api/config")
check("读取字段配置(19个字段)", len(cfg["fields"]) == 19)
check("界面配置下发(每页15条)", cfg["app"]["page_size"] == 15)
keys = [f["key"] for f in cfg["fields"]]
check("已移除入职二层/接口人经理", "dept_level2" not in keys and "interface_manager" not in keys)
check("含当前进展列", "progress" in keys)
hidden = [f["key"] for f in cfg["fields"] if not f["visible"]]
check("学历/院校/专业/电话/Offer状态默认隐藏",
      set(hidden) >= {"education", "school", "major", "phone", "offer_status"})
s, groups = call("GET", "/api/groups")
check("读取分组(demo含2组)", len(groups) >= 2)
g1 = groups[0]["id"]

# 3. 候选人 CRUD
s, r = call("POST", "/api/candidates", {"group_id": g1, "data": {"name": "测试员", "phone": "13911112222", "offer_status": "已发放"}})
cid = r["id"]
check("新增候选人", s == 200)
s, r = call("PUT", f"/api/candidates/{cid}", {"data": {"sign_status": "已签约", "onboard_risk": "高"}})
check("修改候选人(2项变更)", r["changed"] == 2)
s, cands = call("GET", "/api/candidates?q=" + quote("测试员"))
check("搜索候选人", len(cands) == 1 and cands[0]["data"]["sign_status"] == "已签约")

# 4. 日志
s, logs = call("GET", "/api/logs")
msg = logs["items"][0]["message"]
check("修改日志简洁呈现", "修改了「测试员」" in msg and "未签约" not in msg.split("：")[0] and "→" in msg)
print("   日志示例:", msg)

# 5. Excel 导入
wb = Workbook()
ws = wb.active
ws.append(["候选人", "电话", "Offer状态", "拟录取工作地", "入职风险"])
ws.append(["导入甲", "13700001111", "已接受", "北京", "低"])
ws.append(["导入乙", "13700002222", "已发放", "成都", "中"])
ws.append(["测试员", "13911112222", "已接受", "西安", ""])  # 应匹配并更新
buf = io.BytesIO()
wb.save(buf)
boundary = uuid.uuid4().hex
body = io.BytesIO()
def part(name, value=None, filename=None, content=None):
    body.write(f"--{boundary}\r\n".encode())
    if filename:
        body.write(f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode())
        body.write(b"Content-Type: application/octet-stream\r\n\r\n")
        body.write(content)
        body.write(b"\r\n")
    else:
        body.write(f'Content-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
part("group_id", str(g1))
part("file", filename="t.xlsx", content=buf.getvalue())
body.write(f"--{boundary}--\r\n".encode())
s, r = call("POST", "/api/import", raw=body.getvalue(), ctype=f"multipart/form-data; boundary={boundary}")
check("Excel导入(新增2 更新1)", r["created"] == 2 and r["updated"] == 1)

# 5b. 批量导入 120 名候选人
wb = Workbook()
ws = wb.active
ws.append(["候选人", "电话", "学历", "毕业院校", "专业", "Offer状态", "毕业时间"])
for i in range(1, 121):
    ws.append([f"压测{i:03d}", f"139{i:08d}", ["本科", "硕士", "博士"][i % 3],
               f"测试大学{i % 10}", "计算机科学", ["未发放", "已发放", "已接受"][i % 3],
               f"2026-{(i % 12) + 1:02d}-15"])
buf2 = io.BytesIO()
wb.save(buf2)
boundary2 = uuid.uuid4().hex
body2 = io.BytesIO()
def part2(name, value=None, filename=None, content=None):
    body2.write(f"--{boundary2}\r\n".encode())
    if filename:
        body2.write(f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode())
        body2.write(b"Content-Type: application/octet-stream\r\n\r\n")
        body2.write(content)
        body2.write(b"\r\n")
    else:
        body2.write(f'Content-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
part2("group_id", str(g1))
part2("file", filename="bulk.xlsx", content=buf2.getvalue())
body2.write(f"--{boundary2}--\r\n".encode())
s, r = call("POST", "/api/import", raw=body2.getvalue(), ctype=f"multipart/form-data; boundary={boundary2}")
check("批量导入120名候选人", r["created"] == 120)
s, cands = call("GET", "/api/candidates?q=" + quote("压测"))
check("批量导入数据可查询(含新字段)", len(cands) == 120 and cands[0]["data"].get("education") in ("本科", "硕士", "博士"))

# 6. 总览
s, ov = call("GET", "/api/overview")
check("管理员总览含最新进展", any(c.get("latest_log") for grp in ov for c in grp["candidates"]))


def call_raw(method, path, raw=None, ctype=None):
    req = urllib.request.Request(BASE + path, data=raw, method=method)
    if ctype:
        req.add_header("Content-Type", ctype)
    with opener.open(req) as r:
        return r.status, r.read(), dict(r.headers)


def multipart(parts):
    boundary = uuid.uuid4().hex
    body = io.BytesIO()
    for name, value, filename in parts:
        body.write(f"--{boundary}\r\n".encode())
        if filename:
            body.write(f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode())
            body.write(b"Content-Type: application/octet-stream\r\n\r\n")
            body.write(value)
            body.write(b"\r\n")
        else:
            body.write(f'Content-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    body.write(f"--{boundary}--\r\n".encode())
    return body.getvalue(), f"multipart/form-data; boundary={boundary}"

def make_docx(text):
    """构造最小可解析的 docx 文件。"""
    b = io.BytesIO()
    ns = "http://schemas.openxmlformats.org/"
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("[Content_Types].xml",
                   f'<?xml version="1.0"?><Types xmlns="{ns}package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        z.writestr("_rels/.rels",
                   f'<?xml version="1.0"?><Relationships xmlns="{ns}package/2006/relationships">'
                   f'<Relationship Id="rId1" Type="{ns}officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        z.writestr("word/document.xml",
                   f'<?xml version="1.0"?><w:document xmlns:w="{ns}wordprocessingml/2006/main">'
                   f'<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>')
    return b.getvalue()


# 7. 简历上传 / 在线预览 / 更换 / 下载 / 删除 / 批量导出
raw, ct = multipart([("file", make_docx("简历正文ABC"), "resume.docx")])
s, r = call("POST", f"/api/candidates/{cid}/resume", raw=raw, ctype=ct)
check("上传docx简历", s == 200 and r["resume_name"] == "resume.docx")

s, content, headers = call_raw("GET", f"/api/candidates/{cid}/resume/preview")
check("docx在线预览(转HTML)", s == 200 and "简历正文ABC".encode() in content
      and "text/html" in headers.get("Content-Type", ""))

raw, ct = multipart([("file", b"fake txt", "resume.txt")])
s, r = call("POST", f"/api/candidates/{cid}/resume", raw=raw, ctype=ct, expect_error=True)
check("非法格式被拒绝", s == 400)

raw, ct = multipart([("file", b"%PDF-fake", "new_resume.pdf")])
s, r = call("POST", f"/api/candidates/{cid}/resume", raw=raw, ctype=ct)
check("更换为pdf简历", s == 200 and r["resume_name"] == "new_resume.pdf")

s, content, headers = call_raw("GET", f"/api/candidates/{cid}/resume/preview")
check("pdf在线预览(浏览器内嵌)", s == 200 and content.startswith(b"%PDF")
      and "application/pdf" in headers.get("Content-Type", ""))

s, content, _ = call_raw("GET", f"/api/candidates/{cid}/resume")
check("下载简历内容一致", s == 200 and content == b"%PDF-fake")

s, content, headers = call_raw("POST", "/api/resumes/export",
                               raw=json.dumps({"ids": [cid]}).encode(), ctype="application/json")
check("批量导出zip(含1份)", s == 200 and content[:2] == b"PK" and headers.get("X-Export-Count") == "1")

# 7b. 选中数据导出Excel
s, cands = call("GET", "/api/candidates?q=" + quote("压测"))
exp_ids = [c["id"] for c in cands[:5]] + [cid]
s, content, headers = call_raw("POST", "/api/candidates/export",
                               raw=json.dumps({"ids": exp_ids}).encode(), ctype="application/json")
check("选中数据导出Excel", s == 200 and content[:2] == b"PK" and headers.get("X-Export-Count") == "6")

s, _ = call("DELETE", f"/api/candidates/{cid}/resume")
check("删除简历", s == 200)
s, _ = call("POST", "/api/resumes/export", {"ids": [cid]}, expect_error=True)
check("无简历时导出报错", s == 400)

s, logs = call("GET", "/api/logs")
resume_logs = [l["message"] for l in logs["items"][:6]]
check("简历操作已记录日志", any("简历" in m for m in resume_logs))

# 8. 普通用户权限
call("POST", "/api/login", {"username": "hr02", "password": "123456"})
s, cands = call("GET", "/api/candidates")
check("hr02只能看到本组数据", all(c["group_name"] == "研发二组" for c in cands) and len(cands) >= 1)
s, _ = call("PUT", f"/api/candidates/{cid}", {"data": {"name": "越权"}}, expect_error=True)
check("hr02无法修改他组候选人", s == 403)
s, _ = call("GET", "/api/overview", expect_error=True)
check("hr02无法访问管理员总览", s == 403)

# 9. 细化权限：组管理员（增删改查+添加成员）/ 组成员（无删除权）
call("POST", "/api/login", {"username": "admin", "password": "admin123"})
s, users = call("GET", "/api/users")
for u in users:
    if u["username"] in ("t_lead", "t_member"):
        call("DELETE", f"/api/users/{u['id']}")
g2 = groups[1]["id"]
s, _ = call("POST", "/api/users", {"username": "t_lead", "display_name": "测试组管",
                                   "password": "pw123", "role": "group_admin", "group_id": g2})
check("管理员创建组管理员", s == 200)

call("POST", "/api/login", {"username": "t_lead", "password": "pw123"})
s, r = call("POST", "/api/candidates", {"data": {"name": "组管新增"}})
check("组管理员新增本组候选人", s == 200)
lead_cid = r["id"]
s, _ = call("POST", "/api/users", {"username": "t_member", "display_name": "测试组员",
                                   "role": "editor"})  # 不传密码 -> 默认123456
check("组管理员添加本组成员", s == 200)

# 组管理员配置本组字段显示（独立配置文件）
s, _ = call("PUT", "/api/config", {"fields": [{"key": "phone", "visible": False}]})
check("组管理员配置本组字段", s == 200)
s, cfg2 = call("GET", "/api/config")
phone2 = next(f for f in cfg2["fields"] if f["key"] == "phone")
check("本组配置生效(电话列隐藏)", phone2["visible"] is False)
s, _ = call("POST", "/api/users", {"username": "t_admin2", "password": "pw123", "role": "admin"},
            expect_error=True)
check("组管理员不能创建管理员", s == 403)
s, members = call("GET", "/api/users")
check("组管理员仅见本组成员", all(u["group_id"] == g2 for u in members))

call("POST", "/api/login", {"username": "t_member", "password": "123456"})
s, me2 = call("GET", "/api/me")
check("默认密码123456登录成功", s == 200 and me2["username"] == "t_member")
s, cfg3 = call("GET", "/api/config")
check("组成员看到的也是本组配置", next(f for f in cfg3["fields"] if f["key"] == "phone")["visible"] is False)
s, _ = call("PUT", f"/api/candidates/{lead_cid}", {"data": {"phone": "13099998888"}})
check("组成员可编辑本组候选人", s == 200)
s, _ = call("DELETE", f"/api/candidates/{lead_cid}", expect_error=True)
check("组成员无删除权限", s == 403)
s, _ = call("GET", "/api/users", expect_error=True)
check("组成员无用户管理权限", s == 403)

call("POST", "/api/login", {"username": "t_lead", "password": "pw123"})
s, _ = call("DELETE", f"/api/candidates/{lead_cid}")
check("组管理员可删除本组候选人", s == 200)
# 恢复本组字段配置，避免影响后续使用
call("PUT", "/api/config", {"fields": [{"key": "phone", "visible": True}]})

# 9b. 全局查看员：界面同管理员（全分组/总览/图表数据），但只读、无系统管理
call("POST", "/api/login", {"username": "admin", "password": "admin123"})
s, users = call("GET", "/api/users")
for u in users:
    if u["username"] == "t_gv":
        call("DELETE", f"/api/users/{u['id']}")
s, _ = call("POST", "/api/users", {"username": "t_gv", "display_name": "测试查看员",
                                   "role": "global_viewer"})
check("管理员创建全局查看员", s == 200)

call("POST", "/api/login", {"username": "t_gv", "password": "123456"})
s, cands = call("GET", "/api/candidates")
check("全局查看员可见所有分组数据", len({c["group_id"] for c in cands}) >= 2)
s, ov = call("GET", "/api/overview")
check("全局查看员可看全局总览", s == 200 and len(ov) >= 2)
s, logs = call("GET", "/api/logs")
check("全局查看员可看全部日志", s == 200)
any_cid = cands[0]["id"]
s, _ = call("PUT", f"/api/candidates/{any_cid}", {"data": {"name": "越权改名"}}, expect_error=True)
check("全局查看员不能修改数据", s == 403)
s, _ = call("POST", "/api/candidates/batch_delete", {"ids": [any_cid]}, expect_error=True)
check("全局查看员不能批量删除", s == 403)
s, _ = call("GET", "/api/users", expect_error=True)
check("全局查看员无用户管理权限", s == 403)

# 9c. 批量删除：组成员被拒，组管理员/管理员可用
call("POST", "/api/login", {"username": "hr01", "password": "123456"})
s, _ = call("POST", "/api/candidates/batch_delete", {"ids": [any_cid]}, expect_error=True)
check("组成员不能批量删除", s == 403)

call("POST", "/api/login", {"username": "admin", "password": "admin123"})
s, batch = call("GET", "/api/candidates?q=" + quote("压测"))
batch_ids = [c["id"] for c in batch[:10]]
s, r = call("POST", "/api/candidates/batch_delete", {"ids": batch_ids})
check("管理员批量删除10名候选人", r["deleted"] == 10)

# 10. 并发场景：60个并发会话同时登录+查询
call("POST", "/api/login", {"username": "admin", "password": "admin123"})
conc_results = []
def one_session():
    try:
        cj2 = http.cookiejar.CookieJar()
        op2 = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj2))
        req = urllib.request.Request(BASE + "/api/login",
                                     data=json.dumps({"username": "admin", "password": "admin123"}).encode(),
                                     method="POST")
        req.add_header("Content-Type", "application/json")
        with op2.open(req, timeout=30) as r1:
            ok1 = r1.status == 200
        with op2.open(BASE + "/api/candidates", timeout=30) as r2:
            ok2 = r2.status == 200 and len(json.loads(r2.read().decode())) > 0
        conc_results.append(ok1 and ok2)
    except Exception:
        conc_results.append(False)

threads = [threading.Thread(target=one_session) for _ in range(60)]
import time
t0 = time.time()
for t in threads:
    t.start()
for t in threads:
    t.join()
elapsed = time.time() - t0
check(f"并发60会话全部成功(耗时{elapsed:.1f}s)", len(conc_results) == 60 and all(conc_results))

# 清理测试数据
call("POST", "/api/login", {"username": "admin", "password": "admin123"})
s, users = call("GET", "/api/users")
for u in users:
    if u["username"] in ("t_lead", "t_member", "t_gv"):
        call("DELETE", f"/api/users/{u['id']}")
s, cands = call("GET", "/api/candidates?q=" + quote("压测"))
for c in cands:
    call("DELETE", f"/api/candidates/{c['id']}")
for n in ("测试员", "导入甲", "导入乙"):
    s, cands = call("GET", f"/api/candidates?q={quote(n)}")
    for c in cands:
        call("DELETE", f"/api/candidates/{c['id']}")

print("\n全部冒烟测试通过。")
