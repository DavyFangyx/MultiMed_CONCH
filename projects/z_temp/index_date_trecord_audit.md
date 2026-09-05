# index_date 与 t_record 零点核对

对照 [TIME_CRITERIA.md](../rawdata_stats/TIME_CRITERIA.md) 和 [raw_json](../ClinicDatasets/gdc_clinical/raw_json)。
问题不是 CHOL 里有没有写成 Diagnosis，而是 landmark 的第 0 天对每个 case 是否真是同一件事。当前实现没有读 index_date，CHOL 的数据巧合不能当默认。

## 结论

1. 词典把 index_date 钉成 case 级锚点，合法取值 7 个：Diagnosis / First Patient Visit / First Treatment / Initial Genomic Sequencing / Recurrence / Sample Procurement / Study Enrollment。所有 days_to_*（诊断、治疗、随访、死亡）都相对这个锚点，不是相对各自事件日。
2. 当前 33 份 TCGA JSON、11428 例里，有值的 index_date **全部是 Diagnosis**（11293）。没有任何一例写成另外 6 个枚举。项目内部也没有混用。字段只出现在 case 顶层，诊断对象上没有。
3. 因此“同一批 landmark 队列里 index_date 取值不一致”这件事，**在现有 TCGA 文件里没有发生**。但缺字段发生了：135 例没有 index_date 键。其中 127 例是空壳（无 diagnoses / demographic），8 例仍有临床内容。
4. 真正被 CHOL 掩盖的，不是“取值不是 Diagnosis”，而是 **Diagnosis 这个词也不等于原发诊断日**。SKCM 470 例全部 index_date=Diagnosis，但 diagnosis_is_primary_disease=true 的对象只有 118 例 days_to_diagnosis=0；其余 338 例的“研究疾病”钉在 Progression / metastasis 上，原发皮肤病灶反而在第 0 天。t_record 按 days_to_* 原样使用时，第 0 天对 SKCM 多数患者是转移/进展诊断，不是初诊。
5. 如果 landmark 概念原点必须是原发诊断日，不能假定 index_date=Diagnosis 已经够了，更不能假定 days_to_diagnosis=0 的那个对象就是 diagnosis_is_primary_disease。需要显式选锚点对象，再用该对象的 days_to_diagnosis 做一次整轴平移。当前 33 份文件里，这个平移量几乎只在 SKCM 非零。
6. [time_stats.py](../src/time_stats.py) 完全不读 index_date，直接把各对象自己的 days_to_* 当 t_record。在现有 TCGA 数据上，这等价于“信任 GDC 已经把轴挂在 Diagnosis 上”，但没有校验，也没有记录。换癌种或换 GDC 导出后会静默错位。

## 词典

来源：[gdc_clinical_dictionary.csv](../ClinicDatasets/gdc_clinical/field_tables/gdc_clinical_dictionary.csv)。

| 字段 | 实体 | 含义 |
| --- | --- | --- |
| index_date | case，enum，非必填 | date obfuscation 的参考/锚点日 |
| days_to_diagnosis | diagnosis | index 日到该恶性疾病诊断日 |
| days_to_treatment_start 等 | 各临床实体 | 都相对同一个 index 日 |
| age_at_index | demographic | 患者在锚点日的年龄 |
| days_to_last_follow_up | diagnosis | 词典写的是相对 initial pathologic diagnosis，和其他 days_to_* 的口径不一致 |

下载端 [gdc_clinical_batch.py](../ClinicDatasets/gdc_clinical_batch.py) 已经把 index_date 放进 clinical JSON 字段列表，缺值不是下载漏字段，是 GDC 该 case 没给。

Field Bank 的 R1 会丢掉 index_date，所以它不能靠筛后字段表回溯，必须在 raw JSON / time_stats 阶段核。

## 全库计数

扫描 ClinicDatasets/gdc_clinical/raw_json 全部 33 个文件。

| 项 | 计数 |
| --- | --- |
| case 总数 | 11428 |
| index_date=Diagnosis | 11293 |
| 无 index_date 键 | 135 |
| 其它 6 个枚举 | 0 |
| 项目内混合取值 | 0 |
| 诊断对象上也有 index_date | 0 |
| 有 diagnoses[] 且存在 days_to_diagnosis=0 | 11168 |
| 同一 case 多个对象 days_to_diagnosis=0 | 73，多为 Synchronous / Prior primary 与当前 primary 同日 |
| index_date=Diagnosis 但所有诊断都缺 days_to_diagnosis | 103 |
| 有非空 days_to_diagnosis 但没有任何一个是 0 | 26 |
| diagnosis_is_primary_disease=true 且 days_to_diagnosis=0 | 10820 |
| 同上但天数非 0 | 338，全部在 SKCM |
| 同上但缺天数 | 135 |
| 有 diagnoses 却没有任何 diagnosis_is_primary_disease=true | 8，正好是那 8 例“有临床、无 index_date” |

按项目：

| 项目 | n | Diagnosis | 缺键 | 空壳 | 有临床仍缺 | primary 在 0 | primary 非 0 | primary 缺天数 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ACC | 92 | 92 | 0 | 0 | 0 | 92 | 0 | 0 |
| BLCA | 412 | 411 | 1 | 0 | 1 | 411 | 0 | 0 |
| BRCA | 1098 | 1096 | 2 | 1 | 1 | 1096 | 0 | 0 |
| CESC | 307 | 307 | 0 | 0 | 0 | 307 | 0 | 0 |
| CHOL | 51 | 48 | 3 | 3 | 0 | 48 | 0 | 0 |
| COAD | 461 | 460 | 1 | 0 | 1 | 458 | 0 | 2 |
| DLBC | 58 | 48 | 10 | 10 | 0 | 48 | 0 | 0 |
| ESCA | 185 | 185 | 0 | 0 | 0 | 185 | 0 | 0 |
| GBM | 617 | 596 | 21 | 17 | 4 | 595 | 0 | 1 |
| HNSC | 528 | 528 | 0 | 0 | 0 | 527 | 0 | 1 |
| KICH | 113 | 113 | 0 | 0 | 0 | 113 | 0 | 0 |
| KIRC | 537 | 537 | 0 | 0 | 0 | 537 | 0 | 0 |
| KIRP | 291 | 291 | 0 | 0 | 0 | 266 | 0 | 25 |
| LAML | 200 | 200 | 0 | 0 | 0 | 200 | 0 | 0 |
| LGG | 516 | 516 | 0 | 0 | 0 | 515 | 0 | 1 |
| LIHC | 377 | 377 | 0 | 0 | 0 | 376 | 0 | 1 |
| LUAD | 585 | 522 | 63 | 63 | 0 | 503 | 0 | 19 |
| LUSC | 504 | 504 | 0 | 0 | 0 | 479 | 0 | 25 |
| MESO | 87 | 87 | 0 | 0 | 0 | 87 | 0 | 0 |
| OV | 608 | 587 | 21 | 21 | 0 | 587 | 0 | 0 |
| PAAD | 185 | 185 | 0 | 0 | 0 | 184 | 0 | 1 |
| PCPG | 179 | 179 | 0 | 0 | 0 | 179 | 0 | 0 |
| PRAD | 500 | 500 | 0 | 0 | 0 | 469 | 0 | 31 |
| READ | 172 | 171 | 1 | 0 | 1 | 170 | 0 | 1 |
| SARC | 261 | 261 | 0 | 0 | 0 | 261 | 0 | 0 |
| SKCM | 470 | 470 | 0 | 0 | 0 | 118 | 338 | 14 |
| STAD | 443 | 443 | 0 | 0 | 0 | 437 | 0 | 6 |
| TGCT | 263 | 263 | 0 | 0 | 0 | 263 | 0 | 0 |
| THCA | 507 | 507 | 0 | 0 | 0 | 507 | 0 | 0 |
| THYM | 124 | 124 | 0 | 0 | 0 | 123 | 0 | 1 |
| UCEC | 560 | 548 | 12 | 12 | 0 | 542 | 0 | 6 |
| UCS | 57 | 57 | 0 | 0 | 0 | 57 | 0 | 0 |
| UVM | 80 | 80 | 0 | 0 | 0 | 80 | 0 | 0 |

CHOL 没有“取值不是 Diagnosis”的问题。3 例缺键全是空壳：TCGA-5A-A8ZF / TCGA-5A-A8ZG / TCGA-ZK-AAYZ，只有 case_id / disease_type / primary_site / project / state / submitter_id / updated_datetime。其余 48 例全部 Diagnosis，且研究疾病诊断都在第 0 天。多诊断时 Prior primary 可以是负数（TCGA-4G-AAZG 的 -6101），recurrence 是正数（TCGA-3X-AAV9 的 216）。这正好说明：轴已经挂在当前 CHOL 诊断上，历史病灶不是零点。

## 两种风险在数据里怎么落地

### 1. 同一 landmark 队列里 index_date 取值不一致

现有 33 个 TCGA 项目里没有。每个有值的 case 都是 Diagnosis。不能据此把校验拿掉：词典允许另外 6 个值，GDC 换项目或换导出后随时可能出现。

缺键不是混合取值，但进队列前仍要分流：

- 127 例空壳：本来就没有 t_record 可算，时间统计会自然排除。
- 8 例有 diagnoses / demographic 却没有 index_date：TCGA-BL-A0C8（BLCA）、TCGA-A7-A0DC（BRCA）、TCGA-A6-2670（COAD）、TCGA-12-1601 / 06-0131 / 32-2498 / 12-0653（GBM）、TCGA-AF-3912（READ）。其中 4 例仍有 days_to_diagnosis=0，看起来轴仍像诊断日，但没有官方锚点声明。这 8 例也都没有 diagnosis_is_primary_disease=true。

建议：有临床内容却缺 index_date 的 case 单独打标，不要静默当成 Diagnosis。

### 2. index_date 不是 Diagnosis 时，把轴重挂到诊断日

原理成立，而且只需要一次减法：所有 days_to_* 已经在同一条轴上。若概念原点必须是某个诊断对象 D，则

    t_prime = t - D.days_to_diagnosis

治疗、病理、随访、死亡一起平移。缺 days_to_diagnosis 就不能重挂。

当前文件用不上这条，因为没有非 Diagnosis 的 index_date。真正要用减法的是下节：锚点词是 Diagnosis，但 Diagnosis 指的不是原发灶。

## Diagnosis 也不等于原发诊断日

GDC 的 Diagnosis 是“本 case 选来当 index 的那次诊断”，不一定是 classification_of_tumor=primary，也不一定是 diagnosis_is_primary_disease=true。

SKCM 把这件事暴露出来。470 例全部 index_date=Diagnosis。age_at_index 对得上第 0 天那个诊断对象的年龄，对不上多数 diagnosis_is_primary_disease=true 对象——那些对象中位 days_to_diagnosis 约 760 天（-2 到 10847）。

典型结构（TCGA-FS-A4FC）：

- classification=primary, is_primary_disease=false, days_to_diagnosis=0：原发皮肤黑色素瘤，在第 0 天
- classification=Progression, is_primary_disease=true, days_to_diagnosis=1309：研究收录的那次进展，在 +1309

常见 day-0 模式：

- 166 例：day 0 是 not reported / false，研究疾病是 Progression 且不在 0
- 91 例：day 0 是 primary / false，研究疾病是 Progression 且不在 0
- 84 例：day 0 就是 primary / true（这时两套定义重合）
- 28 例：day 0 直接是 Progression 且 is_primary_disease=true

所以对 SKCM：

- 若 landmark 原点 = GDC index（当前 t_record 的做法）：第 0 天是“本 case 被选作 Diagnosis 的那次诊断”，常常是转移/进展。
- 若 landmark 原点 = 原发皮肤诊断：必须找到那个原发对象，用它的 days_to_diagnosis 做平移。不能用 is_primary_disease=true，那会把进展日当成原发日。classification_of_tumor=primary 且天数为 0 的对象更接近原发灶，但 252/470 例找不到带数字的 classification=primary，不能硬平移。

其它癌种里，is_primary_disease=true 与 day 0 基本重合。CHOL、LAML、KIRC 这类项目可以暂时把两套定义当成同一件事，但代码仍应核，不要写死。

另外 26 例 index_date=Diagnosis、轴上有天数却没有任何一个诊断是 0。全部是“研究疾病缺 days_to_diagnosis，其它病史/复发/转移有天数”。分布：KIRP 9、LUSC 7、LUAD 6、UCEC 3、PAAD 1。例如 TCGA-HE-7129：primary 缺天数，另一个 not reported = 2399。这时没有可减的诊断日，不能重挂。

## 和当前 t_record 实现的关系

TIME_CRITERIA.md 写的是：单元格是相对 index 的天数，归一化 days / last_time_days，不再减日历 t0。src/time_stats.py 的 _record_days_* 直接读各对象 days_to_*，不看 index_date，也不选诊断对象做平移。

这在数学上就是“GDC 给什么轴就用什么轴”。现有 TCGA 上几乎都是 Diagnosis 轴，所以 CHOL / BRCA / LAML 看起来正常。它没有做的事：

- 断言本数据集 index_date 唯一且等于 Diagnosis
- 把缺 index_date 的有临床 case 打出来
- 检查 diagnosis_is_primary_disease=true 是否在 0 附近
- 在概念原点改成原发诊断时做平移

生存终点同样相对 index：Dead 用 demographic.days_to_death，存活用 days_to_last_follow_up / days_to_follow_up。如果以后把特征轴平移到原发诊断日，终点必须一起平移，否则 L 和死亡日不在同一原点。词典还警告 days_to_last_follow_up 可能相对 initial pathologic diagnosis；CHOL/PCPG/ACC 上它与同对象 days_to_diagnosis 不冲突，SKCM 上也基本是 last_fu >= dtd，只有 TCGA-EB-A430 的 last_fu=-2。这不是这次的主问题，但如果做平移，终点字段要单独再核一次。

## 建议接到实现上的检查

不改口径公式，先加数据集级断言，写进 time_stats 的自检或每套 time_record/ 旁的小表。

1. 枚举分布：每个数据集输出 index_date 取值计数。出现非 Diagnosis、或同一数据集多个非缺失取值，直接失败或标 mixed_index_date。
2. 缺键：空壳忽略；有 diagnoses/demographic 仍缺键的 8 类 case 标 index_date_missing，不假装 Diagnosis。
3. 零点一致性：对 index_date=Diagnosis 的 case，统计 is_primary_disease=true 的 days_to_diagnosis。若一个数据集里非 0 比例高（SKCM 338/470），在日志里写明：本数据集第 0 天是 GDC Diagnosis，不是原发灶。
4. 只有确认概念原点必须是原发诊断、并且该 case 找得到带数字的原发对象时，才做 t_prime = t - dtd_primary。候选对象建议优先 classification_of_tumor=primary 且天数最接近 0 的那个，而不是 diagnosis_is_primary_disease。找不到就保持原轴并标缺失，不要用 0 填。
5. 换非 TCGA 项目时先跑这张表，再跑 landmark。当前 33 份文件不能外推。

CHOL 可以继续当 Diagnosis 轴的干净例子。SKCM 是反例，必须进回归，不能只用 CHOL 锁规则。
