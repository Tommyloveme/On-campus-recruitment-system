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
        "sourcer": "hr01", "interface_person": "hr02",
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

# 1b. 账户选项与个人资料（不提供自助注册，账号由管理员统一创建）
req = urllib.request.Request(BASE + "/api/account/options")
with opener.open(req) as r:
    acct_opts = json.loads(r.read().decode())
check("账户选项下发用户字段配置", "user_fields" in acct_opts and len(acct_opts["user_fields"]) >= 4)
check("账户选项不再下发业务角色", "job_roles" not in acct_opts)
check("用户字段含工号唯一性与附属信息", any(f["key"] == "display_name" for f in acct_opts["user_fields"])
      and any(f["key"] == "dept_level2" and f.get("type") == "select" for f in acct_opts["user_fields"]))

# 自助注册接口已移除
req = urllib.request.Request(BASE + "/api/register", data=b"{}",
                             headers={"Content-Type": "application/json"}, method="POST")
try:
    with opener.open(req) as r:
        s = r.status
except urllib.error.HTTPError as e:
    s = e.code
check("自助注册接口已关闭(404)", s == 404)

# 管理员统一创建测试用户（角色仅 admin/user；新建用户无任何模块权限，由管理员在权限矩阵授予）
test_emp = f"{uuid.uuid4().int % 100000000:08d}"
s, _ = call("POST", "/api/users", {
    "username": test_emp, "display_name": "Test", "supervisor": "张主管",
    "dept_level2": "软件部", "password": "123456", "role": "user",
}, expect_error=True)
check("管理员创建用户姓名须中文", s == 400)
s, _ = call("POST", "/api/users", {
    "username": "admin", "display_name": "假管理员", "supervisor": "张主管",
    "dept_level2": "软件部", "password": "123456", "role": "user",
}, expect_error=True)
check("重复账号创建被拒", s == 400)
s, crt = call("POST", "/api/users", {
    "username": test_emp, "display_name": "管理员创建", "supervisor": "张主管",
    "dept_level2": "软件部", "dept_level3": "块存储",
    "password": "123456", "role": "user",
})
check("管理员创建用户成功(含自定义附属字段)", s == 200 and crt.get("ok"))
s, me_reg = call("POST", "/api/login", {"username": test_emp, "password": "123456"})
check("管理员创建的用户可登录", s == 200 and me_reg["display_name"] == "管理员创建")
check("新建用户角色为user", me_reg["role"] == "user")
# 新建 user 角色用户默认应用角色权限模板（角色与权限捆绑），故可见登记模块
s, mods_new = call("GET", "/api/permissions/modules")
def find_mod(mods_resp, key):
    for sec in mods_resp["modules"]:
        if sec["key"] == key:
            return sec
        for it in sec.get("items", []):
            if it["key"] == key:
                return it
    return None
check("新建user角色用户默认获登记模块权限", find_mod(mods_new, "registration")["visible"] is True)
s, me_up = call("PUT", "/api/profile", {
    "display_name": "管理员创建改", "supervisor": "王主管", "dept_level2": "软件部",
})
check("用户可更新个人资料", me_up["display_name"] == "管理员创建改")
# 清理本节创建的临时用户（需管理员权限）
call("POST", "/api/login", {"username": "admin", "password": "admin123"})
call("DELETE", f"/api/users/{crt['id']}")

# 2. 配置与分组
s, cfg = call("GET", "/api/config")
check("读取13个流程阶段", len(cfg["stages"]) == 13)
check("含新增流程阶段", {"personality_test", "qualification_interview", "contract_signing"} <= {s["key"] for s in cfg["stages"]})
check("界面配置下发(每页15条)", cfg["app"]["page_size"] == 15)
check("含登记与入职阶段", "registration" in cfg["stage_fields"] and "onboarding" in cfg["stage_fields"])
reg_fields = cfg["stage_fields"]["registration"]
# 数据库键已中文化：字段 key 为中文 storage_key，legacy_key 保留英文
check("登记阶段默认按登记时间倒序", cfg.get("stage_table", {}).get("registration", {}).get("default_sort")
      == {"key": "登记时间", "dir": -1})
reg_keys = [f["key"] for f in reg_fields if f["visible"]]
reg_leg_keys = [f.get("legacy_key") or f["key"] for f in reg_fields if f["visible"]]
check("登记阶段不含三层部门至入职风险", "三层部门" not in reg_keys and "入职风险" not in reg_keys
      and "dept_level3" not in reg_leg_keys and "onboard_risk" not in reg_leg_keys
      and "work_location" not in reg_leg_keys and "offer_status" not in reg_leg_keys)
check("登记阶段表格列顺序配置",
      cfg.get("stage_table", {}).get("registration", {}).get("column_order")[:2]
      == ["登记时间", "投递时间"])
check("登记阶段默认冻结列数可配置",
      cfg.get("stage_table", {}).get("registration", {}).get("frozen_column_count") == 5)
onb_fields = cfg["stage_fields"]["onboarding"]
check("入职阶段含三层部门", any((f.get("legacy_key") or f["key"]) == "dept_level3" and f["visible"] for f in onb_fields))
from openpyxl import load_workbook
req = urllib.request.Request(BASE + "/api/import/template?stage=registration")
with opener.open(req) as r:
    tpl_headers = [c.value for c in load_workbook(io.BytesIO(r.read())).active[1]]
check("登记导入模板不含简历编号", tpl_headers[0] == "候选人" and "简历编号" not in tpl_headers and "三层部门" not in tpl_headers)

# 3. 候选人 CRUD（清理可能残留的测试数据）
for n in ("测试员", "导入甲", "导入乙", "三层部门测试", "自动带入测试", "无效接口人"):
    s, old = call("GET", f"/api/candidates?q={quote(n)}")
    for c in old:
        call("DELETE", f"/api/candidates/{c['id']}")

# 3. 候选人 CRUD
s, r = call("POST", "/api/candidates", {
    "stage": "registration",
    "data": {
        "name": "测试员", "phone": "13911112222",
        "sourcer": "hr01", "interface_person": "hr02",
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
        "supervisor": "李主管", "dept_level2": "软件部",
    })
hr02 = next((u for u in users if u["username"] == "hr02"), None)
if hr02:
    call("PUT", f"/api/users/{hr02['id']}", {
        "display_name": "招聘专员小李", "role": hr02["role"],
        "supervisor": "王主管", "dept_level2": "软件部",
    })
call("POST", "/api/login", {"username": "hr01", "password": "123456"})
s, r_auto = call("POST", "/api/candidates", {
    "stage": "registration",
    "data": {
        "name": "自动带入测试", "phone": "13922223333",
        "sourcer": "hr01", "interface_person": "hr02",
        "education": "硕士", "school": "测试大学", "major": "软件工程",
        "registration_source": "内推",
    },
})
auto_id = r_auto["id"]
s, auto_cands = call("GET", "/api/candidates?q=" + quote("自动带入测试"))
auto_data = auto_cands[0]["data"]
check("登记自动带入拓源人部门", auto_data.get("sourcer_dept") == "软件部")
check("登记保存拓源人工号", auto_data.get("sourcer") == "hr01")
check("登记保存接口人工号", auto_data.get("interface_person") == "hr02")
check("登记接口人部门由工号解析", auto_data.get("interface_dept") == "软件部")
s, lookup = call("GET", "/api/users/lookup-employee?username=hr02")
check("工号查询接口人部门", lookup.get("found") and lookup.get("department") == "软件部")
s, sug = call("GET", "/api/users/suggest-employee?q=hr")
check("拓源人/接口人联想匹配", sug.get("items") and any(x["username"] == "hr02" for x in sug["items"]))
s, sug_many = call("GET", "/api/users/suggest-employee?q=")
check("空关键词不返回联想", not sug_many.get("items"))
s, bad_iface = call("POST", "/api/candidates", {
    "stage": "registration",
    "data": sample_reg_data("无效接口人", interface_person="notexist99"),
}, expect_error=True)
check("未注册接口人工号拒绝保存", s == 400 and bad_iface.get("code") == "user_not_registered")
check("登记不手填简历编号", not auto_data.get("resume_id"))
call("POST", "/api/login", {"username": "admin", "password": "admin123"})
call("DELETE", f"/api/candidates/{auto_id}")
call("POST", "/api/login", {"username": "admin", "password": "admin123"})
s, cands = call("GET", "/api/candidates?q=" + quote("测试员"))
check("手动登记默认待投递", cands[0]["data"]["registration_status"] == "待投递"
      and cands[0]["data"].get("registration_time"))
# 电话重复须拒绝录入
dup_status, dup_body = call("POST", "/api/candidates", {
    "stage": "registration",
    "data": {
        "name": "重复测试", "phone": "13911112222", "sourcer": "hr01",
        "interface_person": "hr02", "education": "本科",
        "school": "测试大学", "major": "计算机", "registration_source": "校园宣讲",
    },
}, expect_error=True)
check("同手机号拒绝新增", dup_status == 409 and dup_body.get("code") == "phone_duplicate")
s, r_other = call("POST", "/api/candidates", {
    "stage": "registration",
    "data": {
        "name": "电话冲突乙", "phone": "13933334444", "sourcer": "hr01",
        "interface_person": "hr02", "education": "本科",
        "school": "测试大学", "major": "计算机", "registration_source": "校园宣讲",
    },
})
other_id = r_other["id"]
dup_edit_status, dup_edit_body = call("PUT", f"/api/candidates/{cid}", {
    "stage": "registration",
    "data": {"phone": "13933334444"},
}, expect_error=True)
check("编辑改为已占用电话拒绝", dup_edit_status == 409 and dup_edit_body.get("code") == "phone_duplicate")
call("DELETE", f"/api/candidates/{other_id}")
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
ws_ob.append(["入职三层", "候选人", "电话", "签约状态"])
ws_ob.append(["网络部", "三层部门测试", "13700003333", "已签约"])
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

# 5a-master. 主数据表双文件导入（applicationProcessList 风格主表 + 候选人面试安排管理列表）
_fix_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tests", "fixtures", "master_import")
with open(os.path.join(_fix_dir, "Application_test.xlsx"), "rb") as _f:
    _app_xlsx = _f.read()
with open(os.path.join(_fix_dir, "候选人面试安排管理列表_test.xlsx"), "rb") as _f:
    _iv_xlsx = _f.read()
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
part_m("interview_mgmt", filename="候选人面试安排管理列表_test.xlsx", content=_iv_xlsx)
body_m.write(f"--{boundary_m}--\r\n".encode())
s, r = call("POST", "/api/master-import/upload", raw=body_m.getvalue(),
             ctype=f"multipart/form-data; boundary={boundary_m}")
check("主数据表双文件上传成功", s == 200 and r.get("both_ready"))
s, cfg_mi = call("GET", "/api/master-import/config?page=registration")
check("主数据表配置含双数据源", len(cfg_mi.get("sources", [])) == 2
      and cfg_mi.get("join_key") == "application_archive_id")
check("主数据匹配键为档案编号→手机号",
      cfg_mi.get("match_keys") == ["application_archive_id", "phone"])
boundary_r = uuid.uuid4().hex
body_r = io.BytesIO()
body_r.write(f"--{boundary_r}\r\n".encode())
body_r.write(b'Content-Disposition: form-data; name="page"\r\n\r\nregistration\r\n')
body_r.write(f"--{boundary_r}--\r\n".encode())
s, r = call("POST", "/api/master-import/refresh", raw=body_r.getvalue(),
             ctype=f"multipart/form-data; boundary={boundary_r}")
check("主数据表刷新成功", s == 200 and (r.get("created", 0) + r.get("updated", 0)) >= 1)
s, c_new = call("GET", "/api/candidates?q=" + quote("主表新人"))
check("主表新人已导入且含SR格式应聘档案编号",
      len(c_new) == 1 and c_new[0]["data"].get("application_archive_id") == "SR2026010100001")
check("主表新人含应聘档案编号", c_new[0]["data"].get("application_archive_id") == "SR2026010100001")
check("应聘档案编号日期段解析为投递时间", c_new[0]["data"].get("delivery_time") == "2026-01-01")
_locked = c_new[0]["data"].get("_master_locked_fields", [])
check("主表导入锁定登记字段", "候选人" in _locked or "name" in _locked)
s, _ = call("PUT", f"/api/candidates/{c_new[0]['id']}", {
    "stage": "registration", "data": {"name": "改名测试"},
}, expect_error=True)
check("主表锁定字段不可编辑", s == 400)
check("主表冗余列自动入库(当前进展)", "0619" in (c_new[0]["data"].get("progress") or ""))
check("面试安排表字段已按档案编号合并(面试进展)",
      "专业面试" in (c_new[0]["data"].get("面试进展") or ""))
check("流程状态列已生成", bool((c_new[0]["data"].get("流程状态") or "").strip()))
s, c_upd = call("GET", "/api/candidates?q=" + quote("测试员"))
check("测试员经档案编号更新", len(c_upd) == 1 and c_upd[0]["data"].get("onboard_risk") == "高")

# 5a2. 流程终止 / 恢复（冻结当前阶段，可还原到终止前状态）
cid_t = c_new[0]["id"]
stage_before_term = c_new[0].get("current_stage")
s, r = call("POST", f"/api/candidates/{cid_t}/terminate", {"action": "terminate"})
check("流程终止成功", s == 200 and r.get("terminated"))
s, ct = call("GET", "/api/candidates?q=" + quote("主表新人"))
check("终止后流程状态为流程终止",
      ct[0]["data"].get("流程状态") == "流程终止" and ct[0]["data"].get("流程终止") == "是")
check("终止后阶段冻结", ct[0].get("current_stage") == stage_before_term)
s, _ = call("POST", f"/api/candidates/{cid_t}/stage-transition",
            {"direction": "next"}, expect_error=True)
check("终止后禁止手动流转", s == 400)
s, _ = call("POST", f"/api/candidates/{cid_t}/terminate", {"action": "terminate"}, expect_error=True)
check("重复终止被拒", s == 400)
s, r = call("POST", f"/api/candidates/{cid_t}/terminate", {"action": "restore"})
check("流程恢复成功", s == 200 and not r.get("terminated"))
s, ct = call("GET", "/api/candidates?q=" + quote("主表新人"))
check("恢复到终止前阶段", ct[0].get("current_stage") == stage_before_term
      and ct[0]["data"].get("流程状态") != "流程终止")

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
s, r = call("POST", f"/api/candidates/{cid}/resume", raw=raw, ctype=ct)
check("任意格式简历可上传(txt)", s == 200 and r["resume_name"] == "resume.txt")

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
check("导出Excel首列为应聘档案编号且无简历编号",
      exp_headers[0] == "应聘档案编号" and "简历编号" not in exp_headers)

s, _ = call("DELETE", f"/api/candidates/{cid}/resume")
check("删除简历", s == 200)
s, _ = call("POST", "/api/resumes/export", {"ids": [cid]}, expect_error=True)
check("无简历时导出报错", s == 400)

s, logs = call("GET", "/api/logs")
resume_logs = [l["message"] for l in logs["items"][:6]]
check("简历操作已记录日志", any("简历" in m for m in resume_logs))

# 8. 普通用户权限（基线模块授权用户：共享池可读写、无管理员模块）
# 重置 hr02 的非基线模块授权（避免手动 UI 测试残留的 data_board/overview 等影响断言）
call("POST", "/api/login", {"username": "admin", "password": "admin123"})
s, _users8 = call("GET", "/api/users")
_hr02 = next((u for u in _users8 if u["username"] == "hr02"), None)
if _hr02:
    for _mk in ("data_board", "overview", "charts"):
        try:
            call("DELETE", "/api/module-acl", {"subject_type": "user", "subject_id": _hr02["id"], "module_key": _mk})
        except Exception:
            pass
call("POST", "/api/login", {"username": "hr02", "password": "123456"})
s, cands = call("GET", "/api/candidates")
check("普通用户可见共享池候选人", len(cands) >= 1)
s, r = call("PUT", f"/api/candidates/{cid}", {"stage": "registration", "data": {"sourcer": "hr02"}})
check("普通用户可修改共享池候选人", s == 200 and r.get("changed") == 1)
s, _ = call("GET", "/api/overview", expect_error=True)
check("普通用户无全局总览模块权限", s == 403)
s, _ = call("GET", "/api/logs", expect_error=True)
check("普通用户无操作日志权限(仅管理员)", s == 403)
s, _ = call("GET", "/api/users", expect_error=True)
check("普通用户无用户管理权限", s == 403)

# 9. 纯模块授权：无任何模块授权的用户无权限；按用户授予模块权限
call("POST", "/api/login", {"username": "admin", "password": "admin123"})
s, users = call("GET", "/api/users")
for u in users:
    if u["username"] in ("t_user", "t_isolated"):
        call("DELETE", f"/api/users/{u['id']}")
# 创建一个隔离用户（显式不应用角色权限，故无任何模块权限）
s, r_iso = call("POST", "/api/users", {"username": "t_isolated", "display_name": "隔离用户",
                                       "password": "pw123", "role": "user",
                                       "supervisor": "张主管", "dept_level2": "软件部",
                                       "apply_role": False})
check("创建隔离用户", s == 200 and r_iso.get("ok"))
iso_id = r_iso["id"]

call("POST", "/api/login", {"username": "t_isolated", "password": "pw123"})
s, mods_iso = call("GET", "/api/permissions/modules")
check("隔离用户无登记模块权限", find_mod(mods_iso, "registration")["visible"] is False)
s, _ = call("POST", "/api/candidates", {"stage": "registration", "data": sample_reg_data("隔离新增")}, expect_error=True)
check("隔离用户不可新增候选人(无模块写)", s == 403)

# 管理员可创建系统管理员
call("POST", "/api/login", {"username": "admin", "password": "admin123"})
s, users = call("GET", "/api/users")
for u in users:
    if u["username"] == "t_admin2":
        call("DELETE", f"/api/users/{u['id']}")
s, _ = call("POST", "/api/users", {"username": "t_admin2", "display_name": "测试管理员",
                                   "password": "pw123", "role": "admin",
                                   "supervisor": "张主管", "dept_level2": "软件部"})
check("系统管理员可创建管理员", s == 200)

# 9b. 按用户授予模块读权限：授予 hr02 overview 读 → hr02 可访问总览
call("POST", "/api/login", {"username": "admin", "password": "admin123"})
s, users = call("GET", "/api/users")
hr02 = next((u for u in users if u["username"] == "hr02"), None)
s, _ = call("PUT", "/api/module-acl", {
    "subject_type": "user", "subject_id": hr02["id"], "module_key": "overview",
    "perm_visibility": 1, "perm_read": 1, "perm_write": 0, "perm_manage": 0,
})
check("授予 hr02 overview 读权限", s == 200)
call("POST", "/api/login", {"username": "hr02", "password": "123456"})
s, ov = call("GET", "/api/overview")
check("hr02 获 overview 读后可访问总览", s == 200 and len(ov) >= 1)
# 撤销 overview 权限
call("POST", "/api/login", {"username": "admin", "password": "admin123"})
call("DELETE", "/api/module-acl", {
    "subject_type": "user", "subject_id": hr02["id"], "module_key": "overview",
})
call("POST", "/api/login", {"username": "hr02", "password": "123456"})
s, _ = call("GET", "/api/overview", expect_error=True)
check("撤销 overview 后 hr02 被拒(403)", s == 403)

# 9c. 批量删除：普通用户被拒，仅系统管理员可用
call("POST", "/api/login", {"username": "admin", "password": "admin123"})
s, any_cands = call("GET", "/api/candidates")
any_cid = any_cands[0]["id"]
call("POST", "/api/login", {"username": "hr01", "password": "123456"})
s, _ = call("POST", "/api/candidates/batch_delete", {"ids": [any_cid]}, expect_error=True)
check("普通用户不能批量删除", s == 403)

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

# 11. 权限管理（合并页）：扁平 用户×模块 权限矩阵 + 批量填充 + 附属信息字段配置
call("POST", "/api/login", {"username": "admin", "password": "admin123"})

# 11a0. 预清理残留测试数据
s, cands = call("GET", "/api/candidates?q=" + quote("模块权限甲"))
for c in cands:
    call("DELETE", f"/api/candidates/{c['id']}")
s, users0 = call("GET", "/api/users")
for u in users0:
    if u["username"] in ("perm_a", "perm_b"):
        call("DELETE", f"/api/users/{u['id']}")

# 11a. 权限选项下发（扁平模型：仅 users/user_fields/modules，无分组/模板/资源分组）
s, perm_opts = call("GET", "/api/permissions/options")
check("权限选项下发", s == 200 and "settings" in perm_opts)
check("权限选项含用户与模块矩阵", "users" in perm_opts and "modules" in perm_opts and "user_fields" in perm_opts)
check("已取消用户分组/资源分组/模板概念",
      "user_groups" not in perm_opts and "resource_groups" not in perm_opts
      and "permission_templates" not in perm_opts and "user_group_templates" not in perm_opts)
check("附属信息字段由配置下发", any(f["key"] == "dept_level2" and f.get("type") == "select" for f in perm_opts["user_fields"]))

# 11b. 准备测试用户 perm_a（显式不应用角色权限，保持无任何模块权限，用于后续逐项授权测试）
call("POST", "/api/users", {"username": "perm_a", "display_name": "权限甲", "role": "user",
                            "supervisor": "张主管", "dept_level2": "软件部", "password": "123456",
                            "apply_role": False})
s, users = call("GET", "/api/users")
perm_a = next(u for u in users if u["username"] == "perm_a")
check("perm_a 创建成功且自带附属字段默认空", perm_a.get("dept_level3") == "")

# 12. 模块级 ACL：用户 × 模块 的 V/R/W/M（恒门禁，纯用户主体授权）
call("POST", "/api/login", {"username": "admin", "password": "admin123"})

# 12a. 模块注册表下发（含板块与子模块；不含 enabled 开关）
s, mods = call("GET", "/api/permissions/modules")
check("模块注册表下发", s == 200 and len(mods["modules"]) >= 6)
mk_keys = set()
for sec in mods["modules"]:
    mk_keys.add(sec["key"])
    for it in sec.get("items", []):
        mk_keys.add(it["key"])
check("模块含板块与子模块", {"recruit_flow", "tech_interview", "manager_interview", "admin_board"} <= mk_keys)
check("模块元数据不含 enabled 开关", "enabled" not in mods["modules"][0])
ab = find_mod(mods, "admin_board")
ab_keys = {it["key"] for it in (ab or {}).get("items", [])} if ab else set()
check("管理看板含权限管理/操作日志/数据备份",
      {"permissions", "op_logs", "backups"} <= ab_keys)
check("问题反馈为独立顶级模块", "feedback" in mk_keys and "feedback" not in ab_keys)
s, fb = call("POST", "/api/feedback", {"title": "冒烟测试反馈", "content_html": "<p>冒烟测试反馈</p>"})
check("用户可提交问题反馈", s == 200 and fb.get("ok"))
s, fb_list = call("GET", "/api/feedback?all=1")
check("登录用户可查看问题反馈列表", s == 200 and fb_list.get("total", 0) >= 1)
check("字段配置已合并进权限管理", "field_config" not in ab_keys)

# 12b. 授予 perm_a tech_interview 可见+读+写
s, _ = call("PUT", "/api/module-acl", {
    "subject_type": "user", "subject_id": perm_a["id"], "module_key": "tech_interview",
    "perm_visibility": 1, "perm_read": 1, "perm_write": 1, "perm_manage": 0,
})
check("模块ACL单条授权", s == 200)
s, rows = call("GET", "/api/module-acl?module_key=tech_interview")
check("模块ACL查询", any(r["subject_id"] == perm_a["id"] and r["perm_write"] for r in rows))

# admin 建一个候选人并推进到技术面
s, r = call("POST", "/api/candidates", {
    "stage": "registration",
    "data": {"name": "模块权限甲", "phone": "13900001111",
             "sourcer": "hr01", "interface_person": "hr02",
             "education": "本科", "school": "模块大学", "major": "计算机",
             "registration_source": "校园宣讲"},
})
mod_cid = r["id"]
s, _ = call("PUT", f"/api/candidates/{mod_cid}",
            {"stage": "tech_interview", "data": {"tech_interview_time": "2026-07-01 10:00"}})
check("admin 推进候选人到技术面", s == 200)

# perm_a 视角：tech_interview 可见可写 → 可更新
call("POST", "/api/login", {"username": "perm_a", "password": "123456"})
s, mods_a = call("GET", "/api/permissions/modules")
ti = find_mod(mods_a, "tech_interview")
check("perm_a 可见可写 tech_interview", ti["visible"] is True and ti["writable"] is True)
s, _ = call("PUT", f"/api/candidates/{mod_cid}",
            {"stage": "tech_interview", "data": {"tech_interview_time": "2026-07-02 14:00"}})
check("perm_a 有模块写权限可更新技术面", s == 200)

# 12c. 未授权 manager_interview → perm_a 不可见且不可写
call("POST", "/api/login", {"username": "admin", "password": "admin123"})
s, _ = call("PUT", f"/api/candidates/{mod_cid}",
            {"stage": "manager_interview", "data": {"manager_interview_time": "2026-07-03 10:00"}})
check("admin 推进到主管面", s == 200)
call("POST", "/api/login", {"username": "perm_a", "password": "123456"})
s, _ = call("PUT", f"/api/candidates/{mod_cid}",
            {"stage": "manager_interview", "data": {"manager_interview_time": "2026-07-04 10:00"}},
            expect_error=True)
check("perm_a 无主管面模块写权限被拒(403)", s == 403)
s, mods_a2 = call("GET", "/api/permissions/modules")
mi = find_mod(mods_a2, "manager_interview")
check("perm_a 主管面模块不可见", mi["visible"] is False)

# 12d. 板块继承：授予板块 recruit_flow 读 → 子模块 qualification 继承读
call("POST", "/api/login", {"username": "admin", "password": "admin123"})
call("PUT", "/api/module-acl", {
    "subject_type": "user", "subject_id": perm_a["id"], "module_key": "recruit_flow",
    "perm_visibility": 1, "perm_read": 1, "perm_write": 0, "perm_manage": 0,
})
call("POST", "/api/login", {"username": "perm_a", "password": "123456"})
s, mods_a3 = call("GET", "/api/permissions/modules")
qual = find_mod(mods_a3, "qualification")
check("子模块继承板块读权限", qual["visible"] is True and qual["readable"] is True and qual["writable"] is False)

# 12e. 批量填充模块权限（Excel 式）：对 perm_a 批量授予 onboarding V/R/W，manage 需二次确认
call("POST", "/api/login", {"username": "admin", "password": "admin123"})
entries_set = [{"subject_type": "user", "subject_id": perm_a["id"], "module_key": "onboarding",
                "perm_visibility": 1, "perm_read": 1, "perm_write": 1, "perm_manage": 1}]
s, prev = call("POST", "/api/module-acl/batch", {"mode": "set", "entries": entries_set, "dry_run": True})
check("模块批量填充预览", s == 200 and prev["dry_run"] and prev["preview"]["entry_count"] == 1)
s, _ = call("POST", "/api/module-acl/batch", {"mode": "set", "entries": entries_set}, expect_error=True)
check("批量授 manage 需二次确认", s == 400)
s, bset = call("POST", "/api/module-acl/batch", {"mode": "set", "entries": entries_set, "confirm": True})
check("模块批量填充执行成功", s == 200 and bset["affected"] == 1)
call("POST", "/api/login", {"username": "perm_a", "password": "123456"})
s, mods_a4 = call("GET", "/api/permissions/modules")
ob = find_mod(mods_a4, "onboarding")
check("perm_a 批量获 onboarding 写+管理", ob["writable"] is True)

# 12f. 批量撤销模块权限（dry_run 预览 + 执行）
call("POST", "/api/login", {"username": "admin", "password": "admin123"})
entries_rev = [
    {"subject_type": "user", "subject_id": perm_a["id"], "module_key": "recruit_flow"},
    {"subject_type": "user", "subject_id": perm_a["id"], "module_key": "tech_interview"},
    {"subject_type": "user", "subject_id": perm_a["id"], "module_key": "onboarding"},
]
s, prev = call("POST", "/api/module-acl/batch", {"mode": "revoke", "entries": entries_rev, "dry_run": True})
check("模块批量撤销预览", s == 200 and prev["dry_run"] and prev["preview"]["entry_count"] == 3)
s, bres = call("POST", "/api/module-acl/batch", {"mode": "revoke", "entries": entries_rev, "dry_run": False})
check("模块批量撤销执行", s == 200 and bres["affected"] == 3)
call("POST", "/api/login", {"username": "perm_a", "password": "123456"})
s, mods_a5 = call("GET", "/api/permissions/modules")
check("perm_a 撤销后无任何模块可见", find_mod(mods_a5, "registration")["visible"] is False
      and find_mod(mods_a5, "tech_interview")["visible"] is False)

# 12g. 模块矩阵 Excel 导出
call("POST", "/api/login", {"username": "admin", "password": "admin123"})
req = urllib.request.Request(BASE + "/api/module-acl/export")
with opener.open(req) as r:
    mod_xlsx = r.read()
check("导出模块权限矩阵Excel", mod_xlsx[:2] == b"PK")

# 12h. 批量修改用户附属信息（Excel 式批量）
call("POST", "/api/login", {"username": "admin", "password": "admin123"})
s, r = call("PUT", "/api/users/batch", {"ids": [perm_a["id"]], "patch": {"dept_level3": "研发三组"}})
check("批量修改用户附属信息", s == 200 and r["updated"] == 1)
s, users = call("GET", "/api/users")
perm_a2 = next(u for u in users if u["username"] == "perm_a")
check("附属字段已批量写入", perm_a2.get("dept_level3") == "研发三组")

# 13. 角色管理（角色=权限模板，持久化到 config/roles.json）
call("POST", "/api/login", {"username": "admin", "password": "admin123"})
s, roles_resp = call("GET", "/api/roles")
role_keys_list = [r["key"] for r in roles_resp["roles"]]
check("角色列表含4个默认角色", {"admin", "user", "interviewer", "manager"} <= set(role_keys_list))
check("admin角色标记bypass", any(r["key"] == "admin" and r["bypass"] for r in roles_resp["roles"]))
check("interviewer角色含技术面写权限",
      (roles_resp["roles"][[r["key"] for r in roles_resp["roles"]].index("interviewer")]["perms"]
       .get("tech_interview", {}).get("w") == 1))
# 新增自定义角色
s, rrole = call("POST", "/api/roles", {"key": "test_role", "label": "测试角色",
    "perms": {"tech_interview": {"v": 1, "r": 1, "w": 1, "m": 0}}})
check("新增自定义角色", s == 200 and rrole["role"]["key"] == "test_role")
s, roles_resp2 = call("GET", "/api/roles")
check("新角色已持久化", any(r["key"] == "test_role" for r in roles_resp2["roles"]))
# 重复 key 被拒
s, _ = call("POST", "/api/roles", {"key": "test_role", "label": "重复", "perms": {}}, expect_error=True)
check("重复角色key被拒", s == 400)
# 编辑角色
s, _ = call("PUT", "/api/roles/test_role", {"label": "测试角色改", "perms": {"manager_interview": {"v": 1, "r": 1, "w": 1, "m": 0}}})
check("编辑角色成功", s == 200)
s, roles_resp3 = call("GET", "/api/roles")
_tr = next(r for r in roles_resp3["roles"] if r["key"] == "test_role")
check("角色编辑已持久化", _tr["label"] == "测试角色改" and _tr["perms"]["manager_interview"]["w"] == 1)
# 应用角色权限到用户：把 perm_a 的角色改为 test_role 并应用其权限模板（覆盖原有模块权限）
s, r_ap = call("PUT", f"/api/users/{perm_a['id']}", {"role": "test_role", "apply_role": True})
check("切换用户角色并应用权限", s == 200)
call("POST", "/api/login", {"username": "perm_a", "password": "123456"})
s, mods_ap = call("GET", "/api/permissions/modules")
check("perm_a 应用测试角色后可见主管面写",
      find_mod(mods_ap, "manager_interview")["writable"] is True)
call("POST", "/api/login", {"username": "admin", "password": "admin123"})
# 删除内置角色被拒
s, _ = call("DELETE", "/api/roles/user", expect_error=True)
check("内置角色不可删除", s == 400)
# 删除自定义角色
s, _ = call("DELETE", "/api/roles/test_role")
check("删除自定义角色", s == 200)
s, roles_resp4 = call("GET", "/api/roles")
check("自定义角色已删除", not any(r["key"] == "test_role" for r in roles_resp4["roles"]))

# 清理模块 ACL 与权限测试数据
call("POST", "/api/login", {"username": "admin", "password": "admin123"})
for mk in ("tech_interview", "manager_interview", "recruit_flow", "qualification", "onboarding", "overview"):
    call("DELETE", "/api/module-acl",
         {"subject_type": "user", "subject_id": perm_a["id"], "module_key": mk})
s, cands = call("GET", "/api/candidates?q=" + quote("模块权限甲"))
for c in cands:
    call("DELETE", f"/api/candidates/{c['id']}")
s, users = call("GET", "/api/users")
for u in users:
    if u["username"] in ("perm_a", "perm_b"):
        call("DELETE", f"/api/users/{u['id']}")

# 清理测试数据
call("POST", "/api/login", {"username": "admin", "password": "admin123"})
s, users = call("GET", "/api/users")
for u in users:
    if u["username"] in ("t_isolated", "t_admin2", "t_user") or u["username"].startswith("emp"):
        call("DELETE", f"/api/users/{u['id']}")
s, cands = call("GET", "/api/candidates?q=" + quote("压测"))
for c in cands:
    call("DELETE", f"/api/candidates/{c['id']}")
for n in ("测试员", "导入甲", "导入乙", "三层部门测试", "自动带入测试"):
    s, cands = call("GET", f"/api/candidates?q={quote(n)}")
    for c in cands:
        call("DELETE", f"/api/candidates/{c['id']}")

print("\n全部冒烟测试通过。")
