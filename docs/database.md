# 数据库设计说明

本文档描述校招候选人跟踪系统的 SQLite 数据库结构、字段中文键规范、解耦分层与外部嵌套配置方式。

## 设计原则

1. **SQL 表/列名保持英文**：兼容 SQLite 工具链与 ORM 习惯；中文含义见 `config/db/table_registry.json`。
2. **业务 JSON 使用中文键**：`candidates.data`、原始表 `data` 列中以 **storage_key**（中文）为 canonical 形式。
3. **未映射的导入列直接用中文表头作键**：主数据导入的未映射 Excel 列以表头原文入库（不再转拼音）；历史拼音键由启动迁移自动改回中文；英文表头保持英文。
4. **流程状态与业务字段解耦**：`candidate_pipeline` 独立存储阶段；`candidates` 上提取 `phone` / `resume_id` / `current_stage` 索引列。
5. **统一读写入口**：`campus.db.field_store`（嵌套路径、legacy 英文键、中文键三者互通）。

## 分层架构

```
┌─────────────────────────────────────────────────────────────┐
│  外部配置 / API                                              │
│  config/db/field_registry.json  ·  GET /api/db/schema       │
└───────────────────────────┬─────────────────────────────────┘
                            │ 嵌套路径 候选人.基本信息.姓名
┌───────────────────────────▼─────────────────────────────────┐
│  field_store（campus/db/field_store.py）                     │
│  normalize · field_get/set · nested_view · resolve_path      │
└───────────────────────────┬─────────────────────────────────┘
                            │
     ┌──────────────────────┼──────────────────────┐
     ▼                      ▼                      ▼
 candidates          candidate_pipeline      data_hub
 (身份+JSON)          (流程状态)              (汇总总表)
     │                      │
     ├─ candidates_raw_manual（手动原始）
     └─ candidates_raw_master（主数据原始，双命名空间）
```

## 核心表

### candidates（候选人主表）

| 列名 | 中文 | 说明 |
|------|------|------|
| id | 编号 | 自增主键 |
| phone | 电话 | 唯一标识，与原始表主键一致 |
| resume_id | 简历编号 | 从 data 提取的索引列 |
| current_stage | 当前流程阶段 | 与 pipeline 同步的索引列 |
| data | 业务数据 | **中文键 JSON** |
| resume_file / resume_name | 简历文件 | 附件路径与展示名 |
| created_at / updated_at | 时间戳 | |

### candidate_pipeline（流程状态表，解耦）

| 列名 | 中文 | 说明 |
|------|------|------|
| candidate_id | 候选人编号 | PK，FK → candidates.id |
| current_stage | 当前阶段 | 有效阶段 key（registration / offer …） |
| manual_stage | 手动指定阶段 | Offer 策略页手动流转写入，优先于规则 |
| updated_at | 更新时间 | |

### candidate_stage_history（阶段流转历史，SLA 依据）

| 列名 | 中文 | 说明 |
|------|------|------|
| id | 编号 | 自增主键 |
| candidate_id | 候选人编号 | FK → candidates.id |
| stage | 阶段 | 每次进入新阶段追加一条 |
| entered_at | 进入时间 | 停留时长 = 当前时间 − 最近一条当前阶段的进入时间 |

SLA 目标配置：`config/sla.json`（各阶段 `warn_days` 预警 / `max_days` 超期）；
全局总览页据此展示各流程平均/最长停留天数与超期人数。

### candidates_raw_manual / candidates_raw_master（原始快照）

按 **电话** 主键 UPSERT，保存合并前的原始数据。

- **手动原始表**：中文键扁平 JSON。
- **主数据原始表** 双命名空间：
  - `字段键`：中文 storage_key 扁平 dict（合并用）
  - `字段`：Excel 中文列名 dict（规则引擎按中文名取值）

### data_hub（数据汇总总表）

维度：`source` × `tab_key` × `resume_id` × `field_key`（中文）。

`resume_id` 列存放候选人**唯一化关联键**，优先级：应聘档案编号 → 简历编号 →
`无编号-<手机号>`（主数据导入补齐编号后自然并轨）。主数据导入的候选人匹配
（`config/master_import/registration/index.json` 的 `match_keys`）与各表导出
（`config/export_profiles.json`）均按同一优先级唯一化。

| source | 含义 |
|--------|------|
| master_import | 主数据导入 |
| manual | 页面编辑/手动录入 |
| ui | 界面专属列（不进 candidates.data） |

## 字段注册表（嵌套配置）

**文件**：`config/db/field_registry.json`（可由 `build_field_registry()` 从阶段/主数据配置自动生成）

每条字段记录：

```json
{
  "name": {
    "legacy_key": "name",
    "storage_key": "候选人",
    "label": "候选人",
    "path": ["候选人", "基本信息", "候选人"],
    "stages": ["registration", "..."]
  }
}
```

- **legacy_key**：历史英文配置键（`config/stages/*/fields.json` 中仍可使用）
- **storage_key**：数据库 JSON 中的中文键
- **path**：嵌套配置路径，层数不限，用 `.` 连接

### 外部读写示例（Python）

```python
from campus.db.field_store import field_get, field_set, resolve_path, nested_view

data = {}
field_set(data, "候选人.基本信息.电话", "13800000000")
field_set(data, "phone", "13800000001")  # legacy 英文键同样有效

phone = field_get(data, "电话")
tree = nested_view(data)  # 嵌套视图供前端/报表使用
```

### HTTP API

- `GET /api/db/schema` — 表结构说明 + 完整 field_registry + 嵌套示例
- `GET /api/field-dictionary` — 各阶段字段列表（key 已为中文 storage_key，含 path / legacy_key）

## 内部簿记键

| legacy | storage（中文） |
|--------|----------------|
| _master_imported | _主数据已导入 |
| _master_locked_fields | _主数据锁定字段 |
| manual_stage | _手动流程阶段 |

## 其他系统表

| 表 | 用途 |
|----|------|
| users | 登录账号与附属信息 |
| module_acl | 用户×模块权限 v/r/w/m + perm_features |
| logs | 操作审计 |
| feedback | 问题反馈 |
| interview_bookings / interviewer_availability | 面试预约 |
| groups | 历史分组（现共享池，group_id 多为 NULL） |

完整列说明见 `config/db/table_registry.json`。

## 数据迁移

启动时 `campus.db.schema.migrate()` 自动执行：

1. 已知英文字段键 → 中文 storage_key（`candidates` / raw 表 / data_hub）
2. 回填 `resume_id`、`current_stage` 索引列
3. 同步 `candidate_pipeline` 表

未在注册表中的英文键（如 Excel 拼音自动列）**不做修改**。

## 相关配置文件

| 文件 | 作用 |
|------|------|
| `config/db/field_registry.json` | 字段中文键 + 嵌套路径 |
| `config/db/table_registry.json` | 表/列中文说明 |
| `config/master_import/registration/field_mappings.json` | Excel → field_key 映射 |
| `config/master_import/registration/stage_rules.json` | 字段组合 → 流程阶段 |
| `config/stages/*/fields.json` | 各阶段字段（legacy 英文 key，运行时转中文） |
