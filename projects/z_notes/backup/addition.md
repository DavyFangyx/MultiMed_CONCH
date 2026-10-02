
1、timepoint_category 调查情况：

  词典里 5 个实体共用同一套 enum（36 个值，非必填）：follow_up、
  molecular_test、other_clinical_attribute、treatment、pathology_detail。
  diagnoses 上没有这个字段。

  全库 33 个 TCGA JSON 里，字段出现 70805 次，没有空值。按父项目：

   父项目                                     对象总数    有该字段    覆盖率
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  ━━━━━━━━━━  ━━━━━━━━━━  ━━━━━━━━
   follow_ups[]                               72435       43187       59.6%
  ─────────────────────────────────────────  ──────────  ──────────  ────────
   follow_ups[].molecular_tests[]             20754       14643       70.6%
  ─────────────────────────────────────────  ──────────  ──────────  ────────
   follow_ups[].other_clinical_attributes[    8321        8229        98.9%
   ]
  ─────────────────────────────────────────  ──────────  ──────────  ────────
   diagnoses[].treatments[]                   54945       4497        8.2%
  ─────────────────────────────────────────  ──────────  ──────────  ────────
   diagnoses[].pathology_details[]            14366       249         1.7%
  ─────────────────────────────────────────  ──────────  ──────────  ────────
   diagnoses[]                                18839       0           0%

  嵌套化验/属性上的 14643 + 8229 条，父 follow-up 全是壳：父对象既没有
  timepoint_category，也没有 days_to_follow_up。所以它不能拿来当父随访的时
  间。

  全库取值分布（n=70805）
- Follow-up：20117
- Initial Diagnosis：11943
- Last Contact：11223
- Preoperative：6506
- Post Initial Treatment：5191
- Prior to Diagnosis：4982
- Sample Procurement：3781
- Not Reported：1628
- Prior to Procurement：1480
- Postoperative：1283
- Within 3 Months of Surgery：575
- Post Adjuvant Therapy：489
- Prior to Adjuvant Therapy：455
- Other：377
- First Treatment：264
- Unknown：234
- Prior to Treatment：82
- Within 2 Months After Completion of First-Course Treatment：46
- Recurrence/Progression：38
- Adjuvant Therapy：31
- Adulthood：27
- Recurrence：21
- Childhood：16
- Progression：8
- Adolescence：8
  
  词典里另外 11 个 enum 在这批 TCGA 原始 JSON 中一次都没出现：After
  Chemotherapy、After Study Registration、End of Consolidation Therapy、End
  of Treatment Course、End of Treatment Course 1、End of Treatment Course 2、
  First Complete Response、Post Hormone Therapy、Post Secondary Therapy、
  Prior to Chemotherapy、Prior to Study Registration。
  
  分父项目看，取值完全不是同一套。
  
  follow_ups[]（43187）：Follow-up 20117，Last Contact 11223，Post Initial
  Treatment 5191，Preoperative 1950，Not Reported 1192，Initial Diagnosis
  1043，Within 3 Months of Surgery 575，Post Adjuvant Therapy 468，Prior to
  Adjuvant Therapy 445，Other 377，Unknown 234，Prior to Diagnosis 218，其余
  均 <50。这 43187 条里 37837 条同时有 days_to_follow_up。
  
  follow_ups[].molecular_tests[]（14643）：Initial Diagnosis 6655，Sample
  Procurement 3781，Preoperative 3583，Postoperative 564，Prior to Treatment
  60。其中只有 1638 条有 days_to_test。
  
  follow_ups[].other_clinical_attributes[]（8229）：Initial Diagnosis 4245，
  Prior to Diagnosis 3497，Not Reported 436，Adulthood 27，Childhood 16，
  Adolescence 8。有天数的只有 24 条。
  
  diagnoses[].treatments[]（4497）：Prior to Procurement 1480，Prior to
  Diagnosis 1267，Preoperative 973，Postoperative 484，First Treatment 264，
  Recurrence 21，Progression 8。这 4497 条全部没有 days_to_treatment_start/
  end。
  
  diagnoses[].pathology_details[]（249，全部在 TGCT）：Postoperative 218，
  Post Adjuvant Therapy 21，Prior to Adjuvant Therapy 10。
  days_to_pathology_detail 全空。


diagnoses  全库取值分布
• diagnoses 对象自己没有 timepoint_category。18839 条诊断上这个字段是 0。
  它只出现在诊断下面的嵌套对象里，一共 4746 次：treatments 4497，
  pathology_details 249。treatments 写成 c 的那 2 条没有这个字段。
  diagnoses[].treatments[]（4497）
- Prior to Procurement：1480
- Prior to Diagnosis：1267
- Preoperative：973
- Postoperative：484
- First Treatment：264
- Recurrence：21
- Progression：8
diagnoses[].pathology_details[]（249，全在 TGCT）
- Postoperative：218
- Post Adjuvant Therapy：21
- Prior to Adjuvant Therapy：10



• 结论先说：这三类里，没有一个精确 days_to_* 能当全库记录钟。唯一接近“几乎每
  条都有”的，只有 other_clinical_attributes.timepoint_category。
  created_datetime / updated_datetime 三类都是 100%，但按你们的定义那是
  t_write，不是 t_record。

  全库 33 份 raw_json 扫完的覆盖如下。

  diagnoses[].pathology_details[]（14366 条）

  设计上的记录日是 days_to_pathology_detail（词典：index 日到这次病理阅片
  日）。实际 0 条有值，对象上也没有任何其它 days_to_*。

  timepoint_category 只有 249 条（1.73%），而且全在 TGCT：Postoperative 218、
  Post Adjuvant Therapy 21、Prior to Adjuvant Therapy 10。

  父诊断 days_to_diagnosis 有 13867 条（96.53%），这是病理对象旁边最近的“几乎
  全有”天数；缺的 499 条里 367 条在 SKCM。但这是父诊断的钟，当前规则不允许
  nested 自动继承。

  典型空钟对象：ACC TCGA-OR-A5KB 的 pathology 只有淋巴结数字和
  consistent_pathology_review，没有任何时间字段。

  follow_ups[].molecular_tests[]（20754 条）

  设计字段是 days_to_test（index 日到化验日）。实际只有 1638 条（7.89%），而
  且只在 TGCT 1199 + PRAD 439。有天数的 1638 条同时都有
  timepoint_category（Preoperative / Postoperative）。

  更常见的是类别，不是天数：timepoint_category 14643 条（70.56%）。分布是
  Initial Diagnosis 6655、Sample Procurement 3781、Preoperative 3583、
  Postoperative 564、Prior to Treatment 60。仍有 6111 条（29.4%）天数和类别都
  没有，主要是 BRCA 的 ERBB2/ESR1/PGR IHC。

  父 follow-up 全部是壳：20754 条的父对象都只有 follow_up_id +
  molecular_tests，days_to_follow_up 为 0。CHOL TCGA-4G-AAZG 那种术前 CA19-9/
  白蛋白就是这种，自身只有 timepoint_category=Preoperative。

  follow_ups[].other_clinical_attributes[]（8321 条）

  精确天数几乎没有：days_to_comorbidity 和 days_to_risk_factor 各 24 条
  （0.29%），而且是同一 24 条 PAAD 记录、两值始终相等。

  真正接近全覆盖的是 timepoint_category：8229 条（98.89%）。常见值是 Initial
  Diagnosis 4245、Prior to Diagnosis 3497；其余是 Not Reported 436，以及少量
  Adulthood / Childhood / Adolescence。缺类别的 92 条全在 UVM（80 条只有
  eye_color）。

  父 follow-up 同样全是壳：8321 条父对象只有 follow_up_id +
  other_clinical_attributes，没有 days_to_follow_up。

  对应关系可以收成这样：

   父字段              设计上的记录日           实际覆盖    几乎全有的时间表
                                                            征
  ━━━━━━━━━━━━━━━━━━  ━━━━━━━━━━━━━━━━━━━━━━━  ━━━━━━━━━━  ━━━━━━━━━━━━━━━━━━
   diagnoses.pathol    days_to_pathology_det    0%          没有。最近的是父
   ogy_details         ail                                  诊断
                                                            days_to_diagnosi
                                                            s（96.5%），但不
                                                            是本对象字段
  ──────────────────  ───────────────────────  ──────────  ──────────────────
   follow_ups.molec    days_to_test             7.9%        没有。最多的是自
   ular_tests                                               身
                                                            timepoint_catego
                                                            ry（70.6%）
  ──────────────────  ───────────────────────  ──────────  ──────────────────
   follow_ups.other    days_to_comorbidity /    0.29%       自身
   _clinical_attrib    days_to_risk_factor                  timepoint_catego
   utes                                                     ry（98.9%）

  所以：病理明细没有本记录时间；化验没有全库天数，多数只有类别；OCA 也没有全
  库天数，但 timepoint_category 基本每条都有。这三类都不能靠父 follow-up / 父
  诊断的天数直接当 t_record。



 diagnoses[].pathology_details[]  ：
  在这 11558 个有病理的诊断里：

- 正好 1 条：9824（85.00%）
- 2 条：795（6.88%）
- 3 条：861（7.45%）
- 4–6 条：78（0.67%）
  
  所以「有 pathology 的父诊断，下面基本上只有一个对象」大体对，但仍有 1734 个
  诊断（15%）下面是 2 到 6 条。这些多条几乎全挤在少数癌种：HNSC、UCEC、SARC、
  TGCT、CESC、UCS、UVM、DLBC。ACC/BRCA/KIRC 这类项目里，只要该诊断有
  pathology，就都是 1 条。

其中对 diagnoses 下有多条 pathology_details 进行统计：
  2 条
  ClinicDatasets/gdc_clinical/raw_json/TCGA-CESC.json:1141 的 TCGA-DS-A1OC，
  诊断对象在第 1139 行，pathology_details 数组是第 1141–1160 行。
  一条是淋巴结计数（positive 2 / tested 19），另一条只有
  lymph_node_involved_site=Pelvis, NOS。

  3 条
  同一个文件里的 TCGA-C5-A3HF：ClinicDatasets/gdc_clinical/raw_json/TCGA-
  CESC.json:9509，数组第 9509–9536 行。
  一条是淋巴结计数（11/32），另外两条分别是 Paraaortic 和 Pelvis, NOS。

  4–6 条
  4 条：还是 CESC 的 TCGA-C5-A1MP，ClinicDatasets/gdc_clinical/raw_json/TCGA-
  CESC.json:9999，第 9999–10035 行。一条淋巴结计数+淋巴管侵犯，另外三条是不同
  SARC.json:2124，第 2124–2178 行。放射学尺寸、病理学尺寸、margin/necrosis 被
  拆开。
  6 条是全库仅有的一条：SARC 的 TCGA-DX-A48R，ClinicDatasets/gdc_clinical/
  raw_json/TCGA-SARC.json:35492，第 35492–35556 行，全是同一诊断下的不同测量/
  切缘对象。


• 对，父对象是同一次诊断。1734 个「一条诊断下挂了 2–6 条 pathology」的例子，
  全部都挂在同一个 diagnoses[] 对象上，不是另一次诊断。
  但不能再往前推一步，说它们一定是同一次阅片、同一个时间点。
  CESC / HNSC / UCEC 那种，看起来就是同一份病理被拆字段：一条记淋巴结计数，其
  余几条各记一个 lymph_node_involved_site。SARC 也像同一肿瘤的放射学尺寸、病
  理学尺寸、切缘被拆开。这类基本可以当成同一次诊断病理的碎片。
  反例在 TGCT。245 个多条 pathology 的诊断里，timepoint_category 是混的。例如
  ClinicDatasets/gdc_clinical/raw_json/TCGA-TGCT.json:133 的 TCGA-2G-AAFY：一
  条是原发灶脉管侵犯，没有时间类别；另一条是腹膜后淋巴结，标了
  Postoperative。再如第 496 行的 TCGA-2G-AAGC，第二条直接是 Prior to Adjuvant
  Therapy 的淋巴结清扫。这两条仍属于同一次诊断，但临床动作不是同一时刻。
  
所以准确说法是：它们都来自同一个诊断对象，多数是同一次病理被拆开；只有 TGCT
  这类明确带了不同 timepoint_category 的，才不能当成同一个记录时间。


diagnoses[].treatments[]  ：
• diagnoses[].treatments[] 全库 54947 条。能表征记录/事件时间的，主要就这几个：

- days_to_treatment_start：index 日到治疗开始
- days_to_treatment_end：index 日到治疗结束
- timepoint_category：相对事件的时间类别，不是精确天数
  
  created_datetime / updated_datetime 几乎都有，但按你们的定义是 t_write，不是
  t_record。treatment_duration（49 条）和 treatment_outcome_duration（4 条）基本
  可以忽略。
  
  精确天数的覆盖率：
  
  字段                       非空条数    覆盖率
  ━━━━━━━━━━━━━━━━━━━━━━━━━  ━━━━━━━━━━  ━━━━━━━━
  days_to_treatment_start    17831       32.45%
  ─────────────────────────  ──────────  ────────
  days_to_treatment_end      14457       26.31%
  ─────────────────────────  ──────────  ────────
  起止都有                   14059       25.59%
  ─────────────────────────  ──────────  ────────
  只有 start                 3772        6.86%
  ─────────────────────────  ──────────  ────────
  只有 end                   398         0.72%
  ─────────────────────────  ──────────  ────────
  start / end 都没有         36718       66.82%


  timepoint_category 另有 4497 条（8.18%），而且在这批 TCGA 里和 start/end 互斥：
  有天数的对象都没有类别，有类别的都没有天数。常见值是 Prior to Procurement、
  Prior to Diagnosis、Preoperative。


  患者层：至少一个治疗有明确起止
  全库 11428 例里，10557 例（92.38%）至少有一条 diagnoses[].treatments[]。在这些
  有治疗的患者中：

- 至少一条有 start 或 end：5819（55.12%）
- 一条都没有：4738（44.88%）
- 同一患者有的有天数、有的没有：5459（51.71%）
  
  绝大多数患者本来就不止一条治疗（10557 里 10395 例有 ≥2 条）。限制到「一个患者有
  多条 treatments」时，数字几乎不变：5800 / 10395（55.80%）至少有一条起止明确，
  4595（44.20%）全部缺失。

treatment_or_therapy字段，其中该治疗到底有没有执行？
如果是no大概率是该治疗考虑了，但是实际上没有执行。
treatment,clinical,Treatment,treatment_or_therapy,enum,no,no,An indicator related to the administration of the treatment specified in the treatment_type field.,yes | no | unknown | not reported,4,,,,,,,



Followup情况：

  Follow_ups 带孩子时全是空壳
  follow_ups 实际分成两群，不会混在同一条记录里：

   类型        条数      父级内容            子级
  ━━━━━━━━━━  ━━━━━━━━  ━━━━━━━━━━━━━━━━━━  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   真正随访    43,360    有                  无
                         days_to_follow_u
                         p、
                         timepoint_catego
                         ry、
                         disease_response
                         等
  ──────────  ────────  ──────────────────  ─────────────────────────────────
   空壳随访    29,075    只有                molecular_tests 或
                         follow_up_id        other_clinical_attributes

  7,458 例同时有这两类。空壳父级没有 days_to_follow_up，也没有
  created_datetime。
  子级自己可以带时间：molecular_tests.days_to_test 1,638 条，
  other_clinical_attributes.days_to_comorbidity 24 条。这是“父没有时间、子有
  时间”，不是父子时间不一致。

    follow_ups 这边每个空壳最多挂 1 个子对象，但一个病例可以有很多个空壳：最多
  47 个 molecular_test、9 个 other_clinical_attribute。例如 BRCA 的 ER/PR/
  HER2 IHC+FISH 就是 4 个空壳 follow_up 各挂 1 个 molecular_test。

    一句话：diagnoses 是真父记录，时间和治疗/病理都挂在它下面；follow_ups 里真
  正随访和分子/其他临床属性是拆开的，后者只是 GDC 模型要求的空壳包装。

在这批 TCGA JSON 里，它们实际上是三条平行记录，不是真嵌套。
  GDC 模型上 molecular_test / other_clinical_attribute 必须挂在 follow_up 下
  面，所以 JSON 看起来像父子。但这 72,435 条 follow_ups 里，一条 follow_up 永
  远只装一类有效数据：

   这条 follow_up 实际      条数    父级有没有临床字    子级
   是什么                           段
  ━━━━━━━━━━━━━━━━━━━━━  ━━━━━━━━  ━━━━━━━━━━━━━━━━━━  ━━━━━━━━━━━━━━━━━━━━━━
   真正随访               43,360    有                  无
                                    days_to_follow_u
                                    p、
                                    timepoint_catego
                                    ry、
                                    disease_response
                                    等
  ─────────────────────  ────────  ──────────────────  ──────────────────────
   分子检测的空壳包装     20,754    只有                恰好 1 条
                                    follow_up_id        molecular_tests
  ─────────────────────  ────────  ──────────────────  ──────────────────────
   其他临床属性的空壳      8,321    只有                恰好 1 条
   包装                             follow_up_id        other_clinical_attri
                                                        butes

  没有例外：
- 真正随访从不挂 molecular_tests / other_clinical_attributes
- 同一条 follow_up 从不同时挂 mol 和 oca
- 一个空壳最多只包 1 个子对象
- 空壳自己没有 submitter_id、created_datetime、days_to_follow_up
  
  所以从病例视角，应看成三个平行集合：
- follow_ups：真正随访事件
- molecular_tests：分子检测
- other_clinical_attributes：BMI、月经、合并症等

这是followup的情况：
  follow_ups[].other_clinical_attributes[]
  8321 条对象里 8229 条有 timepoint_category，没有空值。
- Initial Diagnosis：4245
- Prior to Diagnosis：3497
- Not Reported：436
- Adulthood：27
- Childhood：16
- Adolescence：8
  有明确天数的只有 Prior to Diagnosis 里的 24 条（days_to_comorbidity /
  days_to_risk_factor）。其余全靠类别。Adulthood/Childhood/Adolescence 是生命
  阶段，不是相对诊断的时点。
  
  follow_ups[].molecular_tests[]
  20754 条对象里 14643 条有 timepoint_category，没有空值。
- Initial Diagnosis：6655
- Sample Procurement：3781
- Preoperative：3583
- Postoperative：564
- Prior to Treatment：60



Q1：为什么 diagnosis_is_primary_disease = false 归入既往史、定点 (0, 0]
逻辑链是这样的：
- false 意味着这条诊断不是本次入组的主病——它是患者过去得过的另一种癌（比如你 JSON 里 TCGA-DK-A3IS 的皮肤基底细胞癌、TCGA-XF-AAN8 的乳腺癌）。
- 这些既往癌的信息是怎么进入数据库的？不是当年治那个癌时实时录的，而是本次入组做基线问诊时，医生问"你以前得过什么病"，患者口述，然后填进 CRF 表。
- 所以定位的对象不是"那个癌什么时候发生"（那个时间点往往根本不可知，age_at_diagnosis 经常是 null），而是"这条记录什么时候被写下来"——答案就是基线问诊那一刻，即第 0 天。

Q2：不可选的治疗方式为什么还要记录
这是 TCGA CRF 表单的设计方式：表单上预置了固定的几个治疗类别（手术、化疗、放疗），每个格子都必须填 yes 或 no，不管该方式对这个病种有没有临床意义。
所以结肠癌患者的表单上也有"放疗"这一行，填了 no——这不是医生评估后决定不做放疗，而是表单强制填写产生的结构性噪声。

