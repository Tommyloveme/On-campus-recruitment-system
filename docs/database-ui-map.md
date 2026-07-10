# 数据库表关系、数据来源与 UI 对应说明

本文档描述校招全流程管理系统当前 SQLite 库（`data/candidates.db`）中各表之间的关联、数据按**大类**的来源划分，以及数据库表与前端 UI 界面的对应关系。

> 表结构权威定义见 `campus/db/schema.py`；列中文说明见 `config/db/table_registry.json`。  
> UI 模块注册见 `campus/core/modules.py`；左侧导航由 `/api/permissions/modules` 按权限动态渲染。

---

## 1. 表清单与关系总览

### 1.1 实体关系图

```mermaid
erDiagram
    users ||--o{ module_acl : "subject_id"
    users ||--o{ interviewer_availability : "user_id"
    users ||--o{ interview_bookings : "interviewer_id / booked_by"
    users ||--o{ feedback : "user_id"
    users ||--o{ logs : "user_name(逻辑关联)"

    candidates ||--|| candidate_pipeline : "candidate_id"
    candidates ||--o{ candidate_stage_history : "candidate_id"
    candidates ||--o{ interview_bookings : "candidate_id"
    candidates }o--|| candidates_raw_manual : "phone"
    candidates }o--|| candidates_raw_master : "phone"
    candidates ||--o{ data_hub : "resume_id(逻辑键)"
    candidates ||--o{ logs : "candidate_id"

    candidate_pipeline {
        int candidate_id PK
        text current_stage
        text manual_stage
    }

    users {
        int id PK
        text username UK
        text role
    }

    candidates {
        int id PK
        text phone UK
        text resume_id
        text data JSON
    }

    module_acl {
        int id PK
        text subject_type
        int subject_id
        text module_key
    }

    data_hub {
        int id PK
        text source
        text tab_key
        text resume_id
        text field_key
    }
```

### 1.2 表间关系说明

| 主表 | 从表 / 关联对象 | 关联方式 | 说明 |
|------|-----------------|----------|------|
| `users` | `module_acl` | `subject_type='user'` 且 `subject_id = users.id` | 用户模块权限（V/R/W/M + 细粒度 features） |
| `users` | `interviewer_availability` | `user_id → users.id` | 面试官可预约时段 |
| `users` | `interview_bookings` | `interviewer_id` / `booked_by → users.id` | 面试预约记录与预约操作人 |
| `users` | `feedback` | `user_id → users.id` | 问题反馈提交人 |
| `candidates` | `candidate_pipeline` | `candidate_id → candidates.id`（1:1，级联删除） | 流程阶段与手动流转覆盖，与 `data` JSON 解耦 |
| `candidates` | `candidate_stage_history` | `candidate_id → candidates.id`（级联删除） | 每次进入新阶段追加一条，供 SLA / 停留时长统计 |
| `candidates` | `interview_bookings` | `candidate_id → candidates.id` | 候选人面试预约 |
| `candidates` | `candidates_raw_manual` | `phone` 相同 | 手动录入/页面编辑的原始快照 |
| `candidates` | `candidates_raw_master` | `phone` 相同 | 主数据 Excel 导入的原始快照 |
| `candidates` | `data_hub` | `resume_id` 逻辑键（应聘档案编号 / 简历编号 / `无编号-<手机号>`） | 多来源字段汇总总表，非外键约束 |
| `candidates` | `logs` | `candidate_id` 可选 | 操作审计中涉及的候选人 |
| `logs` | `users` | `user_name` 文本 | 记录操作者姓名，非强外键 |
| `app_meta` | — | 独立键值 | 迁移标记、运行元数据，不关联业务表 |

**无库表但相关的存储：**

| 路径 | 说明 |
|------|------|
| `data/resumes/` | 简历附件文件；`candidates.resume_file` / `resume_name` 存路径与展示名 |
| `data/backups/` | 数据库备份 `.db` 文件；非独立业务表 |
| `config/*.json` | 角色、字段、阶段、导入映射等配置；部分在运行时写入库（如 `module_acl`） |

---

## 2. 各表数据来源（按大类）

数据来源仅按**大类**区分，不展开到具体 API 或按钮。

| 表名 | 中文名 | 数据来源大类 |
|------|--------|----------------|
| `users` | 用户表 | **系统初始化**（admin、guest 等内置账号）；**管理员操作**（权限管理新建/导入/编辑）；**用户自助**（「我的账户」修改个人资料） |
| `module_acl` | 模块权限表 | **配置文件**（`config/roles.json` 角色模板，创建用户或应用角色时写入）；**管理员操作**（权限矩阵内联勾选、批量授权） |
| `candidates` | 候选人主表 | **页面手工录入/编辑**（各阶段表格 CRUD）；**Excel 阶段导入**（按阶段模板导入）；**主数据导入**（登记主数据合并入候选人池）；**流程自动派生**（`current_stage` / `resume_id` 等索引列由 pipeline 与 field_store 同步） |
| `candidate_pipeline` | 流程状态表 | **页面手工录入/编辑**（阶段切换、Offer 策略手动流转）；**主数据导入**（按阶段规则判定初始阶段）；**流程自动派生**（字段组合规则自动推进 `current_stage`） |
| `candidate_stage_history` | 阶段流转历史 | **流程自动派生**（进入新阶段时由后端追加，供总览 SLA 统计） |
| `candidates_raw_manual` | 手动原始表 | **页面手工录入/编辑**（保存候选人时同步 UPSERT 原始快照） |
| `candidates_raw_master` | 主数据原始表 | **主数据导入**（Excel 主数据刷新时 UPSERT；含「字段键」「字段」双命名空间） |
| `data_hub` | 数据汇总总表 | **主数据导入**（`source=master_import`）；**页面手工录入/编辑**（`source=manual`）；**界面专属列**（`source=ui`，仅展示、不进 `candidates.data`） |
| `logs` | 操作日志表 | **审计自动记录**（登录用户在各模块的增删改、导入导出、权限变更等操作自动写入） |
| `feedback` | 问题反馈表 | **页面手工录入**（顶部「问题反馈」或问题反馈模块提交） |
| `interviewer_availability` | 面试官可用时段 | **页面手工录入**（各面试阶段「日历视图」中面试官维护空闲时段） |
| `interview_bookings` | 面试预约记录 | **页面手工录入**（日历视图中为候选人预约面试场次） |
| `app_meta` | 应用元数据 | **系统初始化 / 迁移**（启动时 `migrate()` 写入迁移完成标记等） |

### 2.1 `data_hub.source` 与来源大类对应

| `source` 值 | 对应大类 |
|-------------|----------|
| `master_import` | 主数据导入 |
| `manual` | 页面手工录入/编辑、Excel 阶段导入（合并后记入总表） |
| `ui` | 界面专属列（阶段页 UI 列，通过 `/api/data-hub/ui-values` 读写） |

### 2.2 配置文件与库表的关系（非表内数据，但驱动库表）

| 配置文件 | 影响的库表 / 行为 |
|----------|-------------------|
| `config/roles.json` | 驱动 `module_acl`（应用角色到用户时批量写入）；权限引擎运行时亦参考角色 `perms` |
| `config/user_fields.json` | 驱动 `users` 附属字段校验与 UI 表单；`users.extra` 存自定义字段 |
| `config/stages/*/fields.json` | 驱动各阶段 UI 列与 `candidates.data` 字段读写（经 field_store 转中文键） |
| `config/master_import/registration/*` | 驱动主数据导入写入 `candidates_raw_master`、`candidates`、`data_hub` |
| `config/db/field_registry.json` | 字段路径与中文 storage_key 映射，不直接落库，指导 JSON 读写 |
| `config/sla.json` | 不直接落库；全局总览读取 `candidate_stage_history` + 本配置计算 SLA |

---

## 3. 数据库表与 UI 界面对应关系

### 3.1 全局与公共 UI

| UI 入口 | 前端实现 | 主要读写的表 / 存储 | 说明 |
|---------|----------|---------------------|------|
| 登录页 | `static/index.html` + `core.js` | `users`（校验密码） | 访客快捷登录使用内置 `guest` 账号 |
| 我的账户 | `profile.js` 弹窗 | `users` | 修改姓名、附属信息、密码 |
| 顶部「问题反馈」 | `feedback.js` | `feedback` | 与侧栏「问题反馈」模块同一套 API |
| 左侧导航 | `main.js` `buildNavStructure()` | —（读 `/api/permissions/modules`） | 可见模块由 `module_acl` + `roles.json` 解析 |

### 3.2 业务模块（候选人全流程）

各**流程阶段**页统一由 `stage-view.js` 的 `renderStageView(stageKey)` 渲染（表格视图 + 部分阶段含日历视图）。阶段列表来自 `/api/config` 的 `stages`，与 `campus/core/modules.py` 中 `registration`、`recruit_flow` 子模块、`offer_strategy` 子模块一一对应。

| UI 模块（导航） | `module_key` / `stageKey` | 主要读写的表 | 次要 / 关联表 |
|-----------------|---------------------------|--------------|---------------|
| 候选人登记 | `registration` | `candidates`, `candidates_raw_manual`, `data_hub` | `candidate_pipeline`, `candidate_stage_history`, `data/resumes/` |
| 简历筛选 | `resume_screening` | 同上 | 同上 |
| 资格审查 | `qualification` | 同上 | 同上 |
| 商业秘密签署 | `commercial_secret` | 同上 | 同上 |
| 笔试 | `written_test` | 同上 | 同上 |
| 性格测评 | `personality_test` | 同上 | 同上 |
| 资格面试 | `qualification_interview` | 同上 + 日历：`interviewer_availability`, `interview_bookings` | `users`（面试官） |
| 技术面 | `tech_interview` | 同上 + 面试日历表 | 同上 |
| 主管面 | `manager_interview` | 同上 + 面试日历表 | 同上 |
| 报批 | `approval` | `candidates`, `data_hub` | `candidate_pipeline` |
| 谈薪 | `salary` | 同上 | 同上 |
| Offer 管理 | `offer` | 同上 | 同上 |
| 签约情况 | `contract_signing` | 同上 | 同上 |
| 入职管理 | `onboarding` | 同上 | 同上 |

**阶段页通用能力对应的表：**

| 能力 | 相关表 / 存储 |
|------|---------------|
| 表格 CRUD、筛选、排序、分页 | `candidates`, `candidate_pipeline` |
| 阶段 Excel 导入 / 导出 | `candidates`, `data_hub`, `candidates_raw_manual` |
| 主数据导入（登记） | `candidates_raw_master`, `candidates`, `data_hub`, `candidate_pipeline` |
| 简历上传 / 预览 / 下载 | `candidates` + `data/resumes/` |
| 流程终止 / 恢复 | `candidates`, `candidate_pipeline`, `candidate_stage_history` |
| Offer 策略手动流转 | `candidate_pipeline.manual_stage` |
| 面试日历（资格面试 / 技术面 / 主管面等） | `interview-calendar.js` → `interviewer_availability`, `interview_bookings`, `users` |
| UI 专属列（不进主 JSON） | `data_hub`（`source=ui`） |

### 3.3 数据看板

| UI 模块 | 前端 | 主要读写的表 | 说明 |
|---------|------|--------------|------|
| 全局总览 | `overview.js` | `candidates`, `candidate_pipeline`, `candidate_stage_history` | 按阶段统计人数、停留天数、SLA 预警；配置来自 `config/sla.json` |
| 数据图表 | `charts.js` | `candidates`（经 `/api/candidates` 聚合） | 透视、图表；只读候选人 `data` |

### 3.4 管理看板

| UI 模块 | 前端 | 主要读写的表 | 说明 |
|---------|------|--------------|------|
| 权限管理 | `permissions.js` | `users`, `module_acl` | 用户矩阵、角色矩阵、用户导入导出；配置展示 `user_fields.json`、`roles.json` |
| 操作日志 | `log-panel.js`（`op_logs` 或权限管理内嵌） | `logs` | 按模块、等级筛选；只读 |
| 数据备份 | `admin.js` `renderBackups()` | 整库文件 `data/backups/*.db` | 备份/恢复/下载为 SQLite 文件副本，非单表操作 |

权限管理页内「操作日志」子标签与侧栏「操作日志」共用 `log-panel.js`，均读 `logs`。

### 3.5 问题反馈

| UI 模块 | 前端 | 主要读写的表 |
|---------|------|--------------|
| 问题反馈 | `feedback.js` | `feedback`（读写）, `users`（展示提交人） |

---

## 4. UI 模块 → 表 速查矩阵

| 表 | 登录 | 我的账户 | 阶段页 | 面试日历 | 总览 | 图表 | 权限管理 | 操作日志 | 备份 | 反馈 |
|----|:----:|:--------:|:------:|:--------:|:----:|:----:|:--------:|:--------:|:----:|:----:|
| `users` | 读 | 读写 | 读（拓源人/接口人联想） | 读 | — | — | 读写 | — | — | 读 |
| `module_acl` | — | — | — | — | — | — | 读写 | — | — | — |
| `candidates` | — | — | 读写 | 读 | 读 | 读 | — | 读 | 备份\* | — |
| `candidate_pipeline` | — | — | 读写 | — | 读 | — | — | — | 备份\* | — |
| `candidate_stage_history` | — | — | 写 | — | 读 | — | — | — | 备份\* | — |
| `candidates_raw_manual` | — | — | 写 | — | — | — | — | — | 备份\* | — |
| `candidates_raw_master` | — | — | 读/写† | — | — | — | — | — | 备份\* | — |
| `data_hub` | — | — | 读写 | — | — | — | — | — | 备份\* | — |
| `interviewer_availability` | — | — | — | 读写 | — | — | — | — | 备份\* | — |
| `interview_bookings` | — | — | — | 读写 | — | — | — | — | 备份\* | — |
| `logs` | — | — | — | — | — | — | 读 | 读 | 备份\* | — |
| `feedback` | — | — | — | — | — | — | — | — | 备份\* | 读写 |
| `app_meta` | — | — | — | — | — | — | — | — | 备份\* | — |
| `data/resumes/` | — | — | 读写 | — | — | — | — | — | 备份\* | — |

\* **备份**：操作的是整个 `candidates.db` 文件副本，包含上表所有数据。  
† **主数据原始表**：主要在登记阶段「主数据导入」时写入；阶段页编辑合并结果时可能间接更新。

---

## 5. 数据流简图（候选人域）

```
                    ┌─────────────────┐
                    │  配置文件        │
                    │ roles / stages  │
                    │ master_import   │
                    └────────┬────────┘
                             │
     ┌───────────────────────┼───────────────────────┐
     │                       │                       │
     ▼                       ▼                       ▼
┌─────────┐          ┌──────────────┐        ┌─────────────┐
│ 页面编辑 │          │ Excel阶段导入 │        │ 主数据导入   │
│ 手工登记 │          │              │        │             │
└────┬────┘          └──────┬───────┘        └──────┬──────┘
     │                      │                       │
     ▼                      ▼                       ▼
candidates_raw_manual   candidates            candidates_raw_master
     │                      │                       │
     └──────────┬───────────┴───────────┬───────────┘
                ▼                       ▼
           candidates  ◄──────►  candidate_pipeline
                │                       │
                ├──────► candidate_stage_history
                ├──────► data_hub (manual / master_import / ui)
                ├──────► interview_bookings
                └──────► data/resumes/ (附件)
```

---

## 6. 相关文档

| 文档 | 内容 |
|------|------|
| [database.md](./database.md) | 字段中文键、field_store、data_hub 维度说明 |
| [维测指导手册.md](./维测指导手册.md) | API 列表、运维与配置说明 |
| `config/db/table_registry.json` | 表/列中文注册 |
| `GET /api/db/schema` | 运行时表结构 + field_registry 下发 |

---

*文档版本：与当前代码库同步（SQLite 表定义以 `campus/db/schema.py` 为准）。*
