# -*- coding: utf-8 -*-
"""一次性冒烟测试脚本：覆盖登录/权限/CRUD/Excel导入/简历/分组配置/并发/日志/总览。"""
import io
import json
import os
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


def sample_reg_data(name, phone=None, **extra):
    d = {
        "name": name,
        "phone": phone or f"139{uuid.uuid4().int % 100000000:08d}",
        "sourcer": "hr01", "interface_person": "招聘专员小王",
        "education": "本科", "school": "测试大学", "major": "计算机",
        "registration_source": "校园宣讲",
    }
    d.update(extra)
    return d


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

call("POST", "/api/login", {"username": "admin", "password": "admin123"})

# 1b. 用户注册与个人资料
req = urllib.request.Request(BASE + "/api/register/options")
with opener.open(req) as r:
    reg_opts = json.loads(r.read().decode())
check("注册可选业务角色", "拓源人" in reg_opts["job_roles"] and "接口人" in reg_opts["default_job_roles"])
check("注册下发部门配置", "存储部" in reg_opts.get("dept_level2_options", []))
s, _ = call("POST", "/api/register", {
    "employee_id": "abc12345", "display_name": "注册测试", "supervisor": "张主管",
    "dept_level2": "存储部", "password": "123456", "job_roles": ["拓源人"],
}, expect_error=True)
check("工号须8位数字", s == 400)
s, _ = call("POST", "/api/register", {
    "employee_id": "12345678", "display_name": "Test", "supervisor": "张主管",
    "dept_level2": "存储部", "password": "123456", "job_roles": ["拓源人"],
}, expect_error=True)
check("姓名须中文", s == 400)
s, _ = call("POST", "/api/register", {
    "employee_id": "admin", "display_name": "假管理员", "supervisor": "张主管",
    "dept_level2": "存储部", "password": "123456", "job_roles": ["拓源人"],
}, expect_error=True)
check("固定管理员账号不可注册", s == 403)
test_emp = f"{uuid.uuid4().int % 100000000:08d}"
s, reg_r = call("POST", "/api/register", {
    "employee_id": test_emp, "display_name": "注册测试", "supervisor": "张主管",
    "dept_level2": "存储部", "password": "123456", "job_roles": ["拓源人", "接口人"],
})
check("用户自助注册成功", s == 200 and reg_r.get("ok"))
s, me_reg = call("POST", "/api/login", {"username": test_emp, "password": "123456"})
check("注册用户可登录", s == 200 and me_reg["display_name"] == "注册测试")
s, me_up = call("PUT", "/api/profile", {
    "display_name": "注册测试改", "supervisor": "王主管", "dept_level2": "存储部",
    "job_roles": ["拓源人", "HR"],
})
check("用户可更新个人资料", me_up["display_name"] == "注册测试改")
check("普通用户不可在账户页改业务角色", "HR" not in me_up.get("job_roles", []))
call("POST", "/api/login", {"username": "admin", "password": "admin123"})

# 2. 配置与分组
s, cfg = call("GET", "/api/config")
check("读取10个流程阶段", len(cfg["stages"]) == 10)
check("界面配置下发(每页15条)", cfg["app"]["page_size"] == 15)
check("含登记与入职阶段", "registration" in cfg["stage_fields"] and "onboarding" in cfg["stage_fields"])
reg_fields = cfg["stage_fields"]["registration"]
reg_keys = [f["key"] for f in reg_fields if f["visible"]]
check("登记阶段不含三层部门", "dept_level3" not in reg_keys)
check("登记阶段列顺序正确",
      reg_keys[:11] == ["resume_id", "name", "phone", "sourcer", "sourcer_dept", "interface_person",
                        "interface_dept", "education", "school", "major",
                        "registration_source"] and reg_keys[11] == "registration_status")
onb_fields = cfg["stage_fields"]["onboarding"]
check("入职阶段含三层部门", any(f["key"] == "dept_level3" and f["visible"] for f in onb_fields))
from openpyxl import load_workbook
req = urllib.request.Request(BASE + "/api/import/template?stage=registration")
with opener.open(req) as r:
    tpl_headers = [c.value for c in load_workbook(io.BytesIO(r.read())).active[1]]
check("登记导入模板首列为简历编号", tpl_headers[0] == "简历编号" and "三层部门" not in tpl_headers)

# 3. 候选人 CRUD（清理可能残留的测试数据）
for n in ("测试员", "导入甲", "导入乙", "三层部门测试"):
    s, old = call("GET", f"/api/candidates?q={quote(n)}")
    for c in old:
        call("DELETE", f"/api/candidates/{c['id']}")

# 3. 候选人 CRUD
s, r = call("POST", "/api/candidates", {
    "stage": "registration",
    "data": {
        "name": "测试员", "phone": "13911112222",
        "sourcer": "hr01", "interface_person": "招聘专员小王",
        "education": "本科", "school": "测试大学", "major": "计算机",
        "registration_source": "校园宣讲",
    },
})
cid = r["id"]
check("新增候选人(登记阶段)", s == 200 and not r.get("merged"))
# hr01 登记自动带入拓源人/部门（无需手填分组）
s, users = call("GET", "/api/users")
hr01 = next((u for u in users if u["username"] == "hr01"), None)
if hr01:
    call("PUT", f"/api/users/{hr01['id']}", {
        "display_name": "招聘专员小王", "role": hr01["role"],
        "supervisor": "李主管", "dept_level2": "存储部", "job_roles": ["拓源人", "接口人"],
    })
call("POST", "/api/login", {"username": "hr01", "password": "123456"})
s, r_auto = call("POST", "/api/candidates", {
    "stage": "registration",
    "data": {
        "name": "自动带入测试", "phone": "13922223333",
        "sourcer": "hr01", "interface_person": "招聘专员小王",
        "education": "硕士", "school": "测试大学", "major": "软件工程",
        "registration_source": "内推",
    },
})
auto_id = r_auto["id"]
s, auto_cands = call("GET", "/api/candidates?q=" + quote("自动带入测试"))
auto_data = auto_cands[0]["data"]
check("登记自动带入拓源人部门", auto_data.get("sourcer_dept") == "存储部")
check("登记保存拓源人工号", auto_data.get("sourcer") == "hr01")
check("登记不手填简历编号", not auto_data.get("resume_id"))
call("POST", "/api/login", {"username": "admin", "password": "admin123"})
call("DELETE", f"/api/candidates/{auto_id}")
call("POST", "/api/login", {"username": "admin", "password": "admin123"})
s, cands = call("GET", "/api/candidates?q=" + quote("测试员"))
check("手动登记默认待投递", cands[0]["data"]["registration_status"] == "待投递"
      and cands[0]["data"].get("registration_time"))
# 电话重复须确认后覆盖
dup_status, dup_body = call("POST", "/api/candidates", {
    "stage": "registration",
    "data": {
        "name": "测试员", "phone": "13911112222", "sourcer": "hr01",
        "interface_person": "招聘专员小王", "education": "本科",
        "school": "测试大学", "major": "计算机", "registration_source": "校园宣讲",
    },
}, expect_error=True)
check("同手机号未确认返回409", dup_status == 409 and dup_body.get("code") == "phone_duplicate")
s, r2 = call("POST", "/api/candidates", {
    "stage": "registration",
    "confirm_overwrite": True,
    "data": {
        "name": "测试员", "phone": "13911112222", "sourcer": "hr01",
        "interface_person": "招聘专员小王", "education": "本科",
        "school": "测试大学", "major": "计算机", "registration_source": "校园宣讲",
    },
})
check("确认后覆盖同手机号候选人", r2.get("overwritten") and r2["id"] == cid)
s, cands = call("GET", "/api/candidates?q=" + quote("测试员"))
check("合并后保留拓源人", cands[0]["data"].get("sourcer") == "hr01")
s, r = call("PUT", f"/api/candidates/{cid}", {
    "stage": "onboarding",
    "data": {"sign_status": "已签约", "onboard_risk": "高"},
})
check("修改候选人(2项变更)", r["changed"] == 2)
s, cands = call("GET", "/api/candidates?q=" + quote("测试员"))
check("搜索候选人", len(cands) == 1 and cands[0]["data"]["sign_status"] == "已签约")

# 4. 日志
s, logs = call("GET", "/api/logs")
msg = logs["items"][0]["message"]
check("修改日志简洁呈现", "修改了「" in msg and "签约状态" in msg and "→" in msg)
print("   日志示例:", msg)

# 5. Excel 导入（登记阶段）
wb = Workbook()
ws = wb.active
ws.append(["候选人", "电话", "来源渠道", "登记状态", "拟录取工作地"])
ws.append(["导入甲", "13700001111", "校园宣讲", "已登记", "北京"])
ws.append(["导入乙", "13700002222", "内推", "已登记", "成都"])
ws.append(["测试员", "13911112222", "线上投递", "已登记", "西安"])  # 应匹配并更新
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
part("stage", "registration")
part("file", filename="t.xlsx", content=buf.getvalue())
body.write(f"--{boundary}--\r\n".encode())
s, r = call("POST", "/api/import", raw=body.getvalue(), ctype=f"multipart/form-data; boundary={boundary}")
check("Excel导入(新增2 更新1)", r["created"] == 2 and r["updated"] == 1)

# 5a. 入职阶段导入仍兼容旧表头「入职三层」
wb_ob = Workbook()
ws_ob = wb_ob.active
ws_ob.append(["入职三层", "候选人", "签约状态"])
ws_ob.append(["网络部", "三层部门测试", "已签约"])
buf_legacy = io.BytesIO()
wb_ob.save(buf_legacy)
boundary_l = uuid.uuid4().hex
body_l = io.BytesIO()
def part_l(name, value=None, filename=None, content=None):
    body_l.write(f"--{boundary_l}\r\n".encode())
    if filename:
        body_l.write(f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode())
        body_l.write(b"Content-Type: application/octet-stream\r\n\r\n")
        body_l.write(content)
        body_l.write(b"\r\n")
    else:
        body_l.write(f'Content-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
part_l("stage", "onboarding")
part_l("file", filename="legacy.xlsx", content=buf_legacy.getvalue())
body_l.write(f"--{boundary_l}--\r\n".encode())
s, r = call("POST", "/api/import", raw=body_l.getvalue(), ctype=f"multipart/form-data; boundary={boundary_l}")
check("入职阶段旧表头入职三层兼容导入", r["created"] == 1)
s, found = call("GET", "/api/candidates?q=" + quote("三层部门测试"))
check("入职导入写入三层部门", found[0]["data"].get("dept_level3") == "网络部")

# 5a-master. 主数据表双文件导入（Application*.xlsx + 候选人管理*.xlsx）
_fix_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tests", "fixtures", "master_import")
with open(os.path.join(_fix_dir, "Application_test.xlsx"), "rb") as _f:
    _app_xlsx = _f.read()
with open(os.path.join(_fix_dir, "候选人管理_test.xlsx"), "rb") as _f:
    _mgmt_xlsx = _f.read()
boundary_m = uuid.uuid4().hex
body_m = io.BytesIO()
def part_m(name, value=None, filename=None, content=None):
    body_m.write(f"--{boundary_m}\r\n".encode())
    if filename:
        body_m.write(f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode())
        body_m.write(b"Content-Type: application/octet-stream\r\n\r\n")
        body_m.write(content)
        body_m.write(b"\r\n")
    else:
        body_m.write(f'Content-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
part_m("page", "registration")
part_m("application", filename="Application_test.xlsx", content=_app_xlsx)
part_m("candidate_mgmt", filename="候选人管理_test.xlsx", content=_mgmt_xlsx)
body_m.write(f"--{boundary_m}--\r\n".encode())
s, r = call("POST", "/api/master-import/upload", raw=body_m.getvalue(),
             ctype=f"multipart/form-data; boundary={boundary_m}")
check("主数据表双文件上传成功", s == 200 and r.get("both_ready"))
s, cfg_mi = call("GET", "/api/master-import/config?page=registration")
check("主数据表配置含双数据源", len(cfg_mi.get("sources", [])) == 2 and cfg_mi.get("join_key") == "resume_id")
check("主数据匹配键为手机号", cfg_mi.get("match_keys") == ["phone"])
boundary_r = uuid.uuid4().hex
body_r = io.BytesIO()
body_r.write(f"--{boundary_r}\r\n".encode())
body_r.write(b'Content-Disposition: form-data; name="page"\r\n\r\nregistration\r\n')
body_r.write(f"--{boundary_r}--\r\n".encode())
s, r = call("POST", "/api/master-import/refresh", raw=body_r.getvalue(),
             ctype=f"multipart/form-data; boundary={boundary_r}")
check("主数据表刷新成功", s == 200 and (r.get("created", 0) + r.get("updated", 0)) >= 1)
s, c_new = call("GET", "/api/candidates?q=" + quote("主表新人"))
check("主表新人已导入且含简历编号", len(c_new) == 1 and c_new[0]["data"].get("resume_id") == "RS2026001")
check("主表导入锁定登记字段", "name" in c_new[0]["data"].get("_master_locked_fields", []))
s, _ = call("PUT", f"/api/candidates/{c_new[0]['id']}", {
    "stage": "registration", "data": {"name": "改名测试"},
}, expect_error=True)
check("主表锁定字段不可编辑", s == 400)
check("候选人管理表字段已合并(当前进展)", "0619" in (c_new[0]["data"].get("progress") or ""))
s, c_upd = call("GET", "/api/candidates?q=" + quote("测试员"))
check("测试员经手机号更新", len(c_upd) == 1 and c_upd[0]["data"].get("onboard_risk") == "高")

# 5b. 批量导入 120 名候选人（登记阶段）
s, bulk_old = call("GET", "/api/candidates?q=" + quote("压测"))
for c in bulk_old:
    call("DELETE", f"/api/candidates/{c['id']}")
wb = Workbook()
ws = wb.active
ws.append(["候选人", "电话", "学历", "毕业院校", "专业", "登记状态", "毕业时间"])
for i in range(1, 121):
    ws.append([f"压测{i:03d}", f"139{i:08d}", ["本科", "硕士", "博士"][i % 3],
               f"测试大学{i % 10}", "计算机科学", "已登记",
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
part2("stage", "registration")
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
                               raw=json.dumps({"ids": exp_ids, "stage": "registration"}).encode(),
                               ctype="application/json")
check("选中数据导出Excel", s == 200 and content[:2] == b"PK" and headers.get("X-Export-Count") == "6")
exp_headers = [c.value for c in load_workbook(io.BytesIO(content)).active[1]]
check("导出Excel首列为简历编号", exp_headers[0] == "简历编号")

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
check("组成员可见全部候选人", len(cands) >= 1)
s, r = call("PUT", f"/api/candidates/{cid}", {"stage": "registration", "data": {"sourcer": "hr02"}})
check("组成员可修改候选人", s == 200 and r.get("changed") == 1)
s, _ = call("GET", "/api/overview", expect_error=True)
check("组成员无法访问管理员总览", s == 403)

# 9. 细化权限：组管理员（增删改查+添加成员）/ 组成员（无删除权）
call("POST", "/api/login", {"username": "admin", "password": "admin123"})
s, users = call("GET", "/api/users")
for u in users:
    if u["username"] in ("t_lead", "t_member", "t_admin2"):
        call("DELETE", f"/api/users/{u['id']}")
s, _ = call("POST", "/api/users", {"username": "t_lead", "display_name": "测试组管",
                                   "password": "pw123", "role": "group_admin",
                                   "supervisor": "张主管", "dept_level2": "存储部"})
check("管理员创建组管理员", s == 200)

call("POST", "/api/login", {"username": "t_lead", "password": "pw123"})
s, r = call("POST", "/api/candidates", {"stage": "registration", "data": sample_reg_data("组管新增")})
check("组管理员新增候选人", s == 200)
lead_cid = r["id"]
s, _ = call("POST", "/api/users", {"username": "t_member", "display_name": "测试组员",
                                   "role": "editor", "supervisor": "张主管", "dept_level2": "存储部"})
check("组管理员添加成员", s == 200)
s, _ = call("POST", "/api/users", {"username": "t_admin2", "password": "pw123", "role": "admin",
            "supervisor": "张主管", "dept_level2": "存储部"},
            expect_error=True)
check("组管理员不能创建管理员", s == 403)
s, members = call("GET", "/api/users")
check("组管理员可见用户列表", len(members) >= 1)

call("POST", "/api/login", {"username": "t_member", "password": "123456"})
s, me2 = call("GET", "/api/me")
check("默认密码123456登录成功", s == 200 and me2["username"] == "t_member")
s, _ = call("PUT", f"/api/candidates/{lead_cid}", {
    "stage": "registration", "data": {"phone": "13099998888"},
})
check("组成员可编辑候选人", s == 200)
s, _ = call("DELETE", f"/api/candidates/{lead_cid}", expect_error=True)
check("组成员无删除权限", s == 403)
s, _ = call("GET", "/api/users", expect_error=True)
check("组成员无用户管理权限", s == 403)

call("POST", "/api/login", {"username": "t_lead", "password": "pw123"})
s, _ = call("DELETE", f"/api/candidates/{lead_cid}")
check("组管理员可删除候选人", s == 200)

# 9b. 全局查看员：只读、无系统管理
call("POST", "/api/login", {"username": "admin", "password": "admin123"})
s, users = call("GET", "/api/users")
for u in users:
    if u["username"] == "t_gv":
        call("DELETE", f"/api/users/{u['id']}")
s, _ = call("POST", "/api/users", {"username": "t_gv", "display_name": "测试查看员",
                                   "role": "global_viewer", "supervisor": "张主管", "dept_level2": "存储部"})
check("管理员创建全局查看员", s == 200)

call("POST", "/api/login", {"username": "t_gv", "password": "123456"})
s, cands = call("GET", "/api/candidates")
check("全局查看员可见候选人数据", len(cands) >= 1)
s, ov = call("GET", "/api/overview")
check("全局查看员可看全局总览", s == 200 and len(ov) >= 1)
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

# 9d. 数据备份与恢复（仅管理员）
call("POST", "/api/login", {"username": "hr01", "password": "123456"})
s, _ = call("GET", "/api/backups", expect_error=True)
check("非管理员无备份权限", s == 403)

call("POST", "/api/login", {"username": "admin", "password": "admin123"})
s, r = call("POST", "/api/backups", {})
check("管理员手动创建备份", s == 200 and r.get("ok"))
backup_name = r["name"]
s, backups = call("GET", "/api/backups")
check("备份列表包含新备份", s == 200 and any(b["name"] == backup_name for b in backups))

# 备份后新增一名候选人，恢复备份后应消失
s, c_tmp = call("POST", "/api/candidates", {
    "stage": "registration",
    "data": sample_reg_data("恢复测试甲"),
})
s, found = call("GET", "/api/candidates?q=" + quote("恢复测试甲"))
check("恢复前能查到新候选人", len(found) == 1)
s, r = call("POST", "/api/backups/restore", {"name": backup_name})
check("管理员恢复指定备份", s == 200 and r.get("ok"))
s, found = call("GET", "/api/candidates?q=" + quote("恢复测试甲"))
check("恢复后新候选人已消失", len(found) == 0)
s, _ = call("POST", "/api/backups/restore", {"name": "../etc/passwd"}, expect_error=True)
check("非法备份名被拒绝", s == 400)

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
    if u["username"] in ("t_lead", "t_member", "t_gv") or u["username"].startswith("emp"):
        call("DELETE", f"/api/users/{u['id']}")
s, cands = call("GET", "/api/candidates?q=" + quote("压测"))
for c in cands:
    call("DELETE", f"/api/candidates/{c['id']}")
for n in ("测试员", "导入甲", "导入乙", "三层部门测试", "自动带入测试"):
    s, cands = call("GET", f"/api/candidates?q={quote(n)}")
    for c in cands:
        call("DELETE", f"/api/candidates/{c['id']}")

print("\n全部冒烟测试通过。")
