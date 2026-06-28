# 主数据表测试 Excel

本目录存放用于「主数据表导入」功能测试的样例文件，文件名匹配 `field_mappings.json` 中的 `file_pattern`：

| 文件 | 说明 |
|------|------|
| `Application_sample.xlsx` | Application 主表，含全部已映射列 + 冗余列 |
| `候选人管理_sample.xlsx` | 候选人管理表，含已映射列 + 冗余列 |

**冗余列**（未在 `field_mappings.json` 配置）用于验证导入时按表头自动转拼音 `field_key` 入库、且网页默认不可见。

## 重新生成

```bash
python scripts/generate_test_excels.py
```

固定测试行（与冒烟测试兼容）：

- `RS2026001` / 主表新人 / `13790001001`
- `RS2026002` / 测试员 / `13911112222`
