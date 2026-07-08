# 校招全流程管理系统

跨平台（Windows / SUSE Linux）的校招全流程管理系统，覆盖候选人从**登记、简历筛选、资审、笔试、面试、报批、谈薪、Offer 到入职**的全流程跟踪，支持 Excel 导入、主数据表双表刷新、字段配置、模块级权限管理与完整的操作日志。

## 功能特性

- **全流程阶段管理**：流程阶段与各阶段字段全部由 `config/stages.json` 与 `config/stages/<stage>/fields.json` 配置驱动，加字段/加阶段无需改代码或数据库。
- **主数据表导入**：上传 applicationProcessList 主表与候选人面试安排管理列表双 Excel，按应聘档案编号关联、按 应聘档案编号→简历编号→手机号 唯一化合并，`current_stage` 按 `stage_rules.json` 规则自动判定。
- **Excel 批量导入/导出**：各阶段支持模板下载、按电话去重导入、勾选导出。
- **面试管理**：面试官自助设置可约时段，接口人按日历预约技术面/主管面，岗位方向自动匹配。
- **简历管理**：上传（.pdf/.docx）、在线预览（PDF 内嵌、DOCX 转网页）、下载、批量打包 zip。
- **模块级权限**：`用户 × 模块` 的可见/读/写/管理四勾选（`module_acl`），子模块继承父模块；角色为权限模板（`config/roles.json`），支持自定义角色与批量应用；系统管理员（或 bypass 角色）绕过全部检查。
- **问题反馈**：全员可提交带图反馈，管理员设优先级并回复。
- **数据备份**：自动定时快照 + 手动备份/一键恢复。
- **高并发**：waitress 多线程 + SQLite WAL 模式，支撑 500+ 人同时在线。
- **修改留痕**：新增、修改、删除、导入、权限变更均自动记录操作日志。

## 快速开始

依赖：Python 3.9+（Windows 与 SUSE Linux 均可）。

**Windows：**

```bat
start.bat
```

**SUSE Linux / 其他 Linux：**

```bash
chmod +x start.sh
./start.sh
```

脚本会自动创建虚拟环境、安装依赖并启动服务，随后浏览器访问 `http://127.0.0.1:8000`。

- 默认管理员账号：`admin / admin123`（请登录后及时新建账号并修改）
- 如需写入演示数据：`start.bat --demo` 或 `./start.sh --demo`，演示账号 `hr01`、`hr02`，密码均为 `123456`
- 端口可通过环境变量 `PORT` 修改。

## 项目结构

```
├── app.py                  # 薄入口：建应用、初始化数据库、启动 waitress
├── campus/                 # 后端包（五层架构，详见维测手册 §1.2）
│   ├── core/               # L0 基础层：settings/modules/roles_store/stage_config/…
│   ├── domain/             # L1 领域规则层：stage_routing/interview_slots/employees
│   ├── db/                 # L2 数据访问层：connection/schema
│   ├── services/           # L3 业务服务层：acl/users/candidates/interviews/…
│   └── web/                # L4 HTTP 接口层：Blueprint 路由 + guards 鉴权装饰器
├── config/                 # JSON 业务配置（阶段/字段/角色/主数据导入/运行配置）
├── static/                 # 前端 SPA（原生 HTML/CSS/JS，无构建依赖）
├── scripts/                # 维测脚本（status/stop/restart + 演示数据生成）
├── tools/gen_manual.py     # 操作手册 PDF 生成脚本（输出 static/manual.pdf）
├── docs/维测指导手册.md     # 架构、配置、接口、数据库、排障与测试指导
├── smoke_test.py           # 全量冒烟测试
├── data/                   # 运行时数据（数据库/简历/备份/日志，自动创建）
├── start.bat / start.sh    # 双平台启动脚本
└── requirements.txt
```

## 权限模型（简述）

- 系统仅区分**系统管理员**（admin 或 bypass 角色）与**普通用户**；普通用户的能力完全由「用户 × 模块」的四项勾选决定。
- 角色是权限模板：对用户应用角色会把模板写入其模块权限；新建用户自动获得 `user` 角色的基线权限。
- 详细模型与接口清单见 `docs/维测指导手册.md` 第 5、6 节。

## 维测脚本（scripts/）

| 命令 | Windows | Linux | 说明 |
| --- | --- | --- | --- |
| 状态 | `scripts\status.bat` | `./scripts/status.sh` | 端口/PID/残留进程检测 |
| 停止 | `scripts\stop.bat` | `./scripts/stop.sh` | 按端口定位并停止服务 |
| 强制停止 | `scripts\force_stop.bat` | `./scripts/force_stop.sh` | 杀掉端口进程+所有 app.py 残留进程 |
| 重启 | `scripts\restart.bat` | `./scripts/restart.sh` | 停止后后台启动（日志写 `data/server.log`） |

## 测试

```bash
python app.py --demo     # 终端1：带演示数据启动
python smoke_test.py     # 终端2：全量冒烟（130+ 断言，全部 PASS 即可发布）
```
