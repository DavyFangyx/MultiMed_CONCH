# Codex 5：Field Bank convert / unit / template

A 通路已删。Field Bank 长表在 `templates/field_bank/{dataset}/FIELD_BANK.csv`。
本任务只填 convert / unit / template，不碰 greedy、onehot、Analyzer、R0–R6、rawdata_stats。

## 要做的事

1. 新建 `templates/field_bank/_shared/field_prompt_spec.csv`，列 `field,convert,unit,template,note`，覆盖 33 份表的全部 field path。
2. 规则代码放 `src/discovery/field_bank_spec.py`；回填脚本放 `scripts/fill_field_bank_templates.py`。
3. 回填 33 份 `FIELD_BANK.csv`：
   - convert/unit 用共享表覆盖，全库同一 field 必须相同。
   - template 只填空单元格；LIHC 已有 39 句逐字保留。
   - example 一律不动。
4. `write_field_bank_template_skeleton` 对空 convert/unit/template 从共享表补，已填值不覆盖。
5. `converters.py` 仍只有 `days_to_years` 和 `int`，不要新增函数，不要读 sibling 单位字段。

## Convert / unit

- `days_to_years` + `years`：仅 `diagnoses[].age_at_diagnosis`
- `int`：年份、整数计数、ECOG/KPS、身高体重
- 不 convert：BMI、剂量、化验值、肿瘤尺寸、`number_of_cycles`、酒精天数/支数、pack-years
- unit 只填能从官方 description 钉死的；剂量/化验 unit 留空

## Template

一句、一个 `{}`、英文、句号结尾。LIHC 句式是同名字段标准。
有 unit 的写成 `Height is {} cm.`，不要把 unit 再塞进 `{}`。

## 不要做

不要改路径 helper、`--encoding`、greedy 搜索、Analyzer、R0–R6。
不要重跑 33 个 JSON，不要跑 CONCH。

## 验收

```bash
python projects/scripts/fill_field_bank_templates.py --rewrite-spec
python projects/tests/test_common_and_filter.py
python projects/tests/test_field_presence.py
python projects/tests/test_field_bank_spec.py
```

共享表 194 行；空 template 为 0；LIHC 39 句不变；convert 只能是空 / `days_to_years` / `int`。
