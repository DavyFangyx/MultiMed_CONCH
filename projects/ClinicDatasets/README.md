# GDC 临床数据下载

脚本：[gdc_clinical_batch.py](gdc_clinical_batch.py)。只下 clinic，不碰组学文件。全部 open access，不需要 token / dbGaP。

GDC 是两级目录，不是“一个癌种一个数据集”：

```
GDC
└── program          研究计划，例如 TCGA、TARGET、CPTAC、MMRF
    └── project_id   具体队列，例如 TCGA-LIHC、TARGET-AML、CPTAC-3、MMRF-COMMPASS
```

`--program` 选的是上一层，`--projects` 选的是下一层。`--dry-run` 不会改范围，只是按当前选中的 project 报病例数和 biotab 体积。不带 `--skip-*` 时 A、B 会一起跑；要单独跑某一支，用下面的示例。

下面的清单来自 `POST https://api.gdc.cancer.gov/projects`，快照日期 2026-08-27：27 个 program、93 个 project、50571 例。`n_clinical_file_cases` 只统计 GDC 文件目录里 `data_category=Clinical` 的病例；为 0 不代表门户 clinical JSON / `/cases` 也没有，CPTAC / MMRF 就是这种。

## 怎么选范围

| 开关 | 层级 | 写法 | 作用 |
|---|---|---|---|
| `--program` | program，也接受 project_id | 逗号分隔，默认 `TCGA` | 把点名的 program 下全部 project 放进本次名单 |
| `--projects` | project | 空格分隔 | 只跑这些 project，给出后不再看 `--program` |
| `--dry-run` | 不改范围 | 可和上面两个一起用 | 只报计数，不下载 |
| `--program all` | 全库 | 替代已删除的 `--all-gdc` | 27 个 program 全部扫一遍 |

`--program CPTAC-3,TARGET` 能用，是因为脚本同时认 program 名和 project_id：`TARGET` 是 program，会带上 9 个 TARGET project；`CPTAC-3` 是 project，只带这一个。真正的 program 名是 `CPTAC`，下面才是 `CPTAC-2` / `CPTAC-3`。

单独运行 dry-run，只统计，不下载：

```bash
python ClinicDatasets/gdc_clinical_batch.py --dry-run
python ClinicDatasets/gdc_clinical_batch.py --program TARGET,CPTAC --dry-run
python ClinicDatasets/gdc_clinical_batch.py --program CPTAC-3,TARGET --dry-run
python ClinicDatasets/gdc_clinical_batch.py --projects TCGA-LIHC TCGA-LUAD --dry-run
python ClinicDatasets/gdc_clinical_batch.py --program all --dry-run
```

单独运行 A 分支，下载门户 clinical JSON：

```bash
python ClinicDatasets/gdc_clinical_batch.py --skip-biotab
python ClinicDatasets/gdc_clinical_batch.py --projects TCGA-KIRP --skip-biotab
python ClinicDatasets/gdc_clinical_batch.py --program TARGET --skip-biotab
python ClinicDatasets/gdc_clinical_batch.py --projects MMRF-COMMPASS CPTAC-3 --skip-biotab --page-size 100
```

CPTAC / MMRF 没有 BCR Biotab（`n_clinical_file_cases=0`），只能走 A 分支 JSON。它们的 clinical 嵌套比 TCGA 大，默认一次拉 10000 例会把 GDC 附件截断，这两个队列用 `--page-size 100`。

单独运行 B 分支，下载 BCR Biotab：

```bash
python ClinicDatasets/gdc_clinical_batch.py --skip-indexed
python ClinicDatasets/gdc_clinical_batch.py --projects TCGA-KIRP --skip-indexed
python ClinicDatasets/gdc_clinical_batch.py --projects TCGA-KIRP --skip-indexed --manifest-only
python ClinicDatasets/gdc_clinical_batch.py --projects TCGA-KIRP --skip-indexed --raw-only
```

默认 `--program TCGA`，所以只写 `--dry-run` 会扫 33 个 TCGA project，不会自动扩到 TARGET / CPTAC。

## `--cdr` 已停用

A 现在只下载 GDC 门户同款 JSON，落到 `ClinicDatasets/gdc_clinical/raw_json/<PROJECT>.json`，不再生成 `clinical_indexed.csv`，所以 `--cdr` 也不会再并进拉平表。生存终点如果要用 TCGA-CDR Table S1，请自己按 `submitter_id` / `bcr_patient_barcode` 去并。

## program 清单

| program | n_projects | n_cases | n_clinical_file_cases | projects |
|---|---:|---:|---:|---|
| `ALCHEMIST` | 1 | 1176 | 1176 | `ALCHEMIST-ALCH` |
| `APOLLO` | 3 | 225 | 0 | `APOLLO-BRCA-1`, `APOLLO-LUAD`, `APOLLO-OV` |
| `BEATAML1.0` | 2 | 882 | 0 | `BEATAML1.0-COHORT`, `BEATAML1.0-CRENOLANIB` |
| `CCDI` | 1 | 3076 | 0 | `CCDI-MCI` |
| `CCG` | 1 | 272 | 272 | `CCG-CUPP` |
| `CDDP_EAGLE` | 1 | 50 | 50 | `CDDP_EAGLE-1` |
| `CGCI` | 4 | 645 | 596 | `CGCI-BLGSP`, `CGCI-HTMCP-CC`, `CGCI-HTMCP-DLBCL`, `CGCI-HTMCP-LC` |
| `CMI` | 3 | 299 | 36 | `CMI-ASC`, `CMI-MBC`, `CMI-MPC` |
| `CPTAC` | 2 | 2208 | 0 | `CPTAC-2`, `CPTAC-3` |
| `CTSP` | 1 | 45 | 37 | `CTSP-DLBCL1` |
| `EXCEPTIONAL_RESPONDERS` | 1 | 84 | 84 | `EXCEPTIONAL_RESPONDERS-ER` |
| `FM` | 1 | 18004 | 18004 | `FM-AD` |
| `HCMI` | 1 | 805 | 805 | `HCMI-CMDC` |
| `MATCH` | 17 | 516 | 516 | `MATCH-B`, `MATCH-C1`, `MATCH-H`, `MATCH-I`, `MATCH-N`, `MATCH-P`, `MATCH-Q`, `MATCH-R`, `MATCH-S1`, `MATCH-S2`, `MATCH-U`, `MATCH-W`, `MATCH-Y`, `MATCH-Z1A`, `MATCH-Z1B`, `MATCH-Z1D`, `MATCH-Z1I` |
| `MMRF` | 1 | 995 | 0 | `MMRF-COMMPASS` |
| `MP2PRT` | 2 | 1562 | 1562 | `MP2PRT-ALL`, `MP2PRT-WT` |
| `NCICCR` | 1 | 489 | 0 | `NCICCR-DLBCL` |
| `OHSU` | 1 | 176 | 0 | `OHSU-CNL` |
| `ORGANOID` | 1 | 70 | 0 | `ORGANOID-PANCREATIC` |
| `PECGS` | 1 | 67 | 67 | `PECGS-COPECC` |
| `RC` | 1 | 58 | 58 | `RC-PTCL` |
| `REBC` | 1 | 449 | 0 | `REBC-THYR` |
| `TARGET` | 9 | 6543 | 5220 | `TARGET-ALL-P1`, `TARGET-ALL-P2`, `TARGET-ALL-P3`, `TARGET-AML`, `TARGET-CCSK`, `TARGET-NBL`, `TARGET-OS`, `TARGET-RT`, `TARGET-WT` |
| `TCGA` | 33 | 11428 | 11428 | `TCGA-ACC`, `TCGA-BLCA`, `TCGA-BRCA`, `TCGA-CESC`, `TCGA-CHOL`, `TCGA-COAD`, `TCGA-DLBC`, `TCGA-ESCA`, `TCGA-GBM`, `TCGA-HNSC`, `TCGA-KICH`, `TCGA-KIRC`, `TCGA-KIRP`, `TCGA-LAML`, `TCGA-LGG`, `TCGA-LIHC`, `TCGA-LUAD`, `TCGA-LUSC`, `TCGA-MESO`, `TCGA-OV`, `TCGA-PAAD`, `TCGA-PCPG`, `TCGA-PRAD`, `TCGA-READ`, `TCGA-SARC`, `TCGA-SKCM`, `TCGA-STAD`, `TCGA-TGCT`, `TCGA-THCA`, `TCGA-THYM`, `TCGA-UCEC`, `TCGA-UCS`, `TCGA-UVM` |
| `TRIO` | 1 | 339 | 0 | `TRIO-CRU` |
| `VAREPOP` | 1 | 7 | 0 | `VAREPOP-APOLLO` |
| `WCDT` | 1 | 101 | 0 | `WCDT-MCRPC` |

合计 27 个 program，93 个 project，50571 例；其中 GDC Clinical 文件目录覆盖 39911 例。

## project 清单

| program | project_id | name | n_cases | n_clinical_file_cases | n_clinical_files | primary_site |
|---|---|---|---:|---:|---:|---|
| `ALCHEMIST` | `ALCHEMIST-ALCH` | Adjuvant Lung Cancer Enrichment Marker Identification and Sequencing Trial | 1176 | 1176 | 1176 | Not Reported |
| `APOLLO` | `APOLLO-BRCA-1` | Proteogenomic analysis of tumors from young women with breast cancer | 68 | 0 | 0 | Breast |
| `APOLLO` | `APOLLO-LUAD` | APOLLO1: Proteogenomic characterization of lung adenocarcinoma | 87 | 0 | 0 | Bronchus and lung |
| `APOLLO` | `APOLLO-OV` | APOLLO2: Proteogenomic characterization of ovarian serous cystadenocarcinoma | 70 | 0 | 0 | Ovary; Retroperitoneum and peritoneum |
| `BEATAML1.0` | `BEATAML1.0-COHORT` | Functional Genomic Landscape of Acute Myeloid Leukemia | 826 | 0 | 0 | Hematopoietic and reticuloendothelial systems |
| `BEATAML1.0` | `BEATAML1.0-CRENOLANIB` | Clinical Resistance to Crenolanib in Acute Myeloid Leukemia Due to Diverse Molecular Mechanisms | 56 | 0 | 0 | Hematopoietic and reticuloendothelial systems |
| `CCDI` | `CCDI-MCI` | Molecular Characterization Initiative (MCI) | 3076 | 0 | 0 | Other and unspecified parts of mouth; Rectosigmoid junction … |
| `CCG` | `CCG-CUPP` | Center for Cancer Genomics (CCG) Cancers of Unknown Primary Project (CUPP) | 272 | 272 | 272 | Unknown |
| `CDDP_EAGLE` | `CDDP_EAGLE-1` | CDDP Integrative Analysis of Lung Adenocarcinoma (Phase 2) | 50 | 50 | 101 | Bronchus and lung |
| `CGCI` | `CGCI-BLGSP` | Burkitt Lymphoma Genome Sequencing Project | 324 | 291 | 296 | Hematopoietic and reticuloendothelial systems |
| `CGCI` | `CGCI-HTMCP-CC` | HIV+ Tumor Molecular Characterization Project - Cervical Cancer | 212 | 212 | 216 | Cervix uteri |
| `CGCI` | `CGCI-HTMCP-DLBCL` | HIV+ Tumor Molecular Characterization Project - Diffuse Large B-Cell Lymphoma | 70 | 57 | 62 | Hematopoietic and reticuloendothelial systems |
| `CGCI` | `CGCI-HTMCP-LC` | HIV+ Tumor Molecular Characterization Project - Lung Cancer | 39 | 36 | 41 | Bronchus and lung |
| `CMI` | `CMI-ASC` | Count Me In (CMI): The Angiosarcoma (ASC) Project | 36 | 36 | 1 | Bronchus and lung; Breast … |
| `CMI` | `CMI-MBC` | Count Me In (CMI): The Metastatic Breast Cancer (MBC) Project | 200 | 0 | 0 | Breast |
| `CMI` | `CMI-MPC` | Count Me In (CMI): The Metastatic Prostate Cancer (MPC) Project | 63 | 0 | 0 | Prostate gland; Lymph nodes |
| `CPTAC` | `CPTAC-2` | CPTAC-Breast, Colon, Ovary | 342 | 0 | 0 | Other and unspecified female genital organs; Colon … |
| `CPTAC` | `CPTAC-3` | CPTAC-Brain, Head and Neck, Kidney, Lung, Pancreas, Uterus | 1866 | 0 | 0 | Stomach; Other and ill-defined sites in lip, oral cavity and pharynx … |
| `CTSP` | `CTSP-DLBCL1` | CTSP Diffuse Large B-Cell Lymphoma (DLBCL) CALGB 50303 | 45 | 37 | 37 | Unknown; Lymph nodes |
| `EXCEPTIONAL_RESPONDERS` | `EXCEPTIONAL_RESPONDERS-ER` | Exceptional Responders | 84 | 84 | 151 | Esophagus; Stomach … |
| `FM` | `FM-AD` | Foundation Medicine Adult Cancer Clinical Dataset (FM-AD) | 18004 | 18004 | 42 | Not Reported; Esophagus … |
| `HCMI` | `HCMI-CMDC` | NCI Cancer Model Development for the Human Cancer Model Initiative | 805 | 805 | 805 | Other and unspecified parts of tongue; Stomach … |
| `MATCH` | `MATCH-B` | Genomic Characterization CS-MATCH-0007 Arm B | 33 | 33 | 33 | Cervix uteri; Other and unspecified female genital organs … |
| `MATCH` | `MATCH-C1` | Genomic Characterization CS-MATCH-0007 Arm C1 | 11 | 11 | 11 | Esophagus; Bronchus and lung … |
| `MATCH` | `MATCH-H` | Genomic Characterization CS-MATCH-0007 Arm H | 21 | 21 | 21 | Other and unspecified female genital organs; Bronchus and lung … |
| `MATCH` | `MATCH-I` | Genomic Characterization CS-MATCH-0007 Arm I | 60 | 60 | 60 | Esophagus; Skin … |
| `MATCH` | `MATCH-N` | Genomic Characterization CS-MATCH-0007 Arm N | 21 | 21 | 21 | Cervix uteri; Bronchus and lung … |
| `MATCH` | `MATCH-P` | Genomic Characterization CS-MATCH-0007 Arm P | 28 | 28 | 28 | Cervix uteri; Bronchus and lung … |
| `MATCH` | `MATCH-Q` | Genomic Characterization CS-MATCH-0007 Arm Q | 35 | 35 | 35 | Other and unspecified female genital organs; Bronchus and lung … |
| `MATCH` | `MATCH-R` | Genomic Characterization CS-MATCH-0007 Arm R | 28 | 28 | 28 | Vulva; Bronchus and lung … |
| `MATCH` | `MATCH-S1` | Genomic Characterization CS-MATCH-0007 Arm S1 | 41 | 41 | 41 | Other and unspecified female genital organs; Bronchus and lung … |
| `MATCH` | `MATCH-S2` | Genomic Characterization CS-MATCH-0007 Arm S2 | 3 | 3 | 3 | Skin; Unknown |
| `MATCH` | `MATCH-U` | Genomic Characterization CS-MATCH-0007 Arm U | 23 | 23 | 23 | Other and unspecified female genital organs; Bronchus and lung … |
| `MATCH` | `MATCH-W` | Genomic Characterization CS-MATCH-0007 Arm W | 45 | 45 | 45 | Other and unspecified female genital organs; Bronchus and lung … |
| `MATCH` | `MATCH-Y` | Genomic Characterization CS-MATCH-0007 Arm Y | 31 | 31 | 31 | Cervix uteri; Bronchus and lung … |
| `MATCH` | `MATCH-Z1A` | Genomic Characterization CS-MATCH-0007 Arm Z1A | 45 | 45 | 45 | Colon; Connective, subcutaneous and other soft tissues … |
| `MATCH` | `MATCH-Z1B` | Genomic Characterization CS-MATCH-0007 Arm Z1B | 29 | 29 | 29 | Esophagus; Vulva … |
| `MATCH` | `MATCH-Z1D` | Genomic Characterization CS-MATCH-0007 Arm Z1D | 36 | 36 | 36 | Esophagus; Other and unspecified female genital organs … |
| `MATCH` | `MATCH-Z1I` | Genomic Characterization CS-MATCH-0007 Arm Z1I | 26 | 26 | 26 | Other and unspecified female genital organs; Bronchus and lung … |
| `MMRF` | `MMRF-COMMPASS` | Multiple Myeloma CoMMpass Study | 995 | 0 | 0 | Hematopoietic and reticuloendothelial systems |
| `MP2PRT` | `MP2PRT-ALL` | Molecular Profiling to Predict Response to Treatment for Acute Lymphoblastic Leukemia | 1510 | 1510 | 3 | Hematopoietic and reticuloendothelial systems |
| `MP2PRT` | `MP2PRT-WT` | Molecular Profiling to Predict Response to Treatment - Wilms Tumor | 52 | 52 | 52 | Kidney |
| `NCICCR` | `NCICCR-DLBCL` | Genomic Variation in Diffuse Large B Cell Lymphomas | 489 | 0 | 0 | Lymph nodes |
| `OHSU` | `OHSU-CNL` | Philadelphia-Negative Neutrophilic Leukemias (CNL/aCML/MDS/MPNu) | 176 | 0 | 0 | Hematopoietic and reticuloendothelial systems |
| `ORGANOID` | `ORGANOID-PANCREATIC` | Pancreas Cancer Organoid Profiling | 70 | 0 | 0 | Pancreas |
| `PECGS` | `PECGS-COPECC` | USC PE-CGS: Optimizing Engagement of Hispanic Colorectal Cancer Patients in Cancer Genomic Characterization Studies | 67 | 67 | 1 | Rectosigmoid junction; Colon … |
| `RC` | `RC-PTCL` | Refractory Cancers (RC) - Peripheral T-Cell Lymphoma (PTCL) | 58 | 58 | 58 | Connective, subcutaneous and other soft tissues; Liver and intrahepatic bile ducts … |
| `REBC` | `REBC-THYR` | Comprehensive genomic characterization of radiation-related papillary thyroid cancer in the Ukraine | 449 | 0 | 0 | Thyroid gland |
| `TARGET` | `TARGET-ALL-P1` | Acute Lymphoblastic Leukemia - Phase I | 24 | 24 | 4 | Hematopoietic and reticuloendothelial systems |
| `TARGET` | `TARGET-ALL-P2` | Acute Lymphoblastic Leukemia - Phase II | 1587 | 1034 | 9 | Hematopoietic and reticuloendothelial systems |
| `TARGET` | `TARGET-ALL-P3` | Acute Lymphoblastic Leukemia - Phase III | 191 | 112 | 2 | Unknown; Hematopoietic and reticuloendothelial systems |
| `TARGET` | `TARGET-AML` | Acute Myeloid Leukemia | 2492 | 2181 | 7 | Unknown; Hematopoietic and reticuloendothelial systems |
| `TARGET` | `TARGET-CCSK` | Clear Cell Sarcoma of the Kidney | 13 | 13 | 3 | Kidney |
| `TARGET` | `TARGET-NBL` | Neuroblastoma | 1132 | 842 | 3 | Other endocrine glands and related structures; Stomach … |
| `TARGET` | `TARGET-OS` | Osteosarcoma | 383 | 293 | 4 | Not Reported; Bones, joints and articular cartilage of other and unspecified sites … |
| `TARGET` | `TARGET-RT` | Rhabdoid Tumor | 69 | 69 | 5 | Liver and intrahepatic bile ducts; Lip … |
| `TARGET` | `TARGET-WT` | High-Risk Wilms Tumor | 652 | 652 | 4 | Kidney |
| `TCGA` | `TCGA-ACC` | Adrenocortical Carcinoma | 92 | 92 | 197 | Adrenal gland |
| `TCGA` | `TCGA-BLCA` | Bladder Urothelial Carcinoma | 412 | 412 | 994 | Bladder |
| `TCGA` | `TCGA-BRCA` | Breast Invasive Carcinoma | 1098 | 1098 | 2288 | Breast |
| `TCGA` | `TCGA-CESC` | Cervical Squamous Cell Carcinoma and Endocervical Adenocarcinoma | 307 | 307 | 632 | Ovary; Cervix uteri |
| `TCGA` | `TCGA-CHOL` | Cholangiocarcinoma | 51 | 51 | 116 | Liver and intrahepatic bile ducts; Pancreas … |
| `TCGA` | `TCGA-COAD` | Colon Adenocarcinoma | 461 | 461 | 995 | Rectosigmoid junction; Colon |
| `TCGA` | `TCGA-DLBC` | Lymphoid Neoplasm Diffuse Large B-cell Lymphoma | 58 | 58 | 102 | Colon; Stomach … |
| `TCGA` | `TCGA-ESCA` | Esophageal Carcinoma | 185 | 185 | 393 | Esophagus; Stomach |
| `TCGA` | `TCGA-GBM` | Glioblastoma Multiforme | 617 | 617 | 1219 | Brain |
| `TCGA` | `TCGA-HNSC` | Head and Neck Squamous Cell Carcinoma | 528 | 528 | 1103 | Base of tongue; Lip … |
| `TCGA` | `TCGA-KICH` | Kidney Chromophobe | 113 | 113 | 248 | Kidney |
| `TCGA` | `TCGA-KIRC` | Kidney Renal Clear Cell Carcinoma | 537 | 537 | 1165 | Kidney |
| `TCGA` | `TCGA-KIRP` | Kidney Renal Papillary Cell Carcinoma | 291 | 291 | 647 | Kidney |
| `TCGA` | `TCGA-LAML` | Acute Myeloid Leukemia | 200 | 200 | 201 | Hematopoietic and reticuloendothelial systems |
| `TCGA` | `TCGA-LGG` | Brain Lower Grade Glioma | 516 | 516 | 1064 | Brain |
| `TCGA` | `TCGA-LIHC` | Liver Hepatocellular Carcinoma | 377 | 377 | 803 | Liver and intrahepatic bile ducts |
| `TCGA` | `TCGA-LUAD` | Lung Adenocarcinoma | 585 | 585 | 1146 | Bronchus and lung |
| `TCGA` | `TCGA-LUSC` | Lung Squamous Cell Carcinoma | 504 | 504 | 1081 | Bronchus and lung |
| `TCGA` | `TCGA-MESO` | Mesothelioma | 87 | 87 | 190 | Heart, mediastinum, and pleura; Bronchus and lung |
| `TCGA` | `TCGA-OV` | Ovarian Serous Cystadenocarcinoma | 608 | 608 | 1204 | Ovary; Retroperitoneum and peritoneum |
| `TCGA` | `TCGA-PAAD` | Pancreatic Adenocarcinoma | 185 | 185 | 396 | Pancreas |
| `TCGA` | `TCGA-PCPG` | Pheochromocytoma and Paraganglioma | 179 | 179 | 401 | Other endocrine glands and related structures; Adrenal gland … |
| `TCGA` | `TCGA-PRAD` | Prostate Adenocarcinoma | 500 | 500 | 1038 | Prostate gland |
| `TCGA` | `TCGA-READ` | Rectum Adenocarcinoma | 172 | 172 | 364 | Colon; Unknown … |
| `TCGA` | `TCGA-SARC` | Sarcoma | 261 | 261 | 576 | Colon; Stomach … |
| `TCGA` | `TCGA-SKCM` | Skin Cutaneous Melanoma | 470 | 470 | 973 | Skin; Connective, subcutaneous and other soft tissues … |
| `TCGA` | `TCGA-STAD` | Stomach Adenocarcinoma | 443 | 443 | 906 | Stomach |
| `TCGA` | `TCGA-TGCT` | Testicular Germ Cell Tumors | 263 | 263 | 677 | Testis |
| `TCGA` | `TCGA-THCA` | Thyroid Carcinoma | 507 | 507 | 1064 | Thyroid gland |
| `TCGA` | `TCGA-THYM` | Thymoma | 124 | 124 | 266 | Heart, mediastinum, and pleura; Other and ill-defined sites … |
| `TCGA` | `TCGA-UCEC` | Uterine Corpus Endometrial Carcinoma | 560 | 560 | 1166 | Corpus uteri; Uterus, NOS |
| `TCGA` | `TCGA-UCS` | Uterine Carcinosarcoma | 57 | 57 | 129 | Corpus uteri; Uterus, NOS |
| `TCGA` | `TCGA-UVM` | Uveal Melanoma | 80 | 80 | 172 | Eye and adnexa |
| `TRIO` | `TRIO-CRU` | Ukrainian National Research Center for Radiation Medicine Trio Study | 339 | 0 | 0 |  |
| `VAREPOP` | `VAREPOP-APOLLO` | VA Research Precision Oncology Program | 7 | 0 | 0 | Bronchus and lung |
| `WCDT` | `WCDT-MCRPC` | Genomic Characterization of Metastatic Castration Resistant Prostate Cancer | 101 | 0 | 0 | Prostate gland |


# 将数据进行下载与处理：

A 下载的是 GDC 门户同一份临床 JSON，不是自己 `POST /cases + expand` 再拼出来的肥对象。
每个 project 一份附件，落到 `ClinicDatasets/gdc_clinical/raw_json/<PROJECT>.json`。
这份 JSON 是病例级临床实体（demographic / diagnoses / treatments / follow_ups 等），
没有 `sample_ids` / `aliquot_ids`，也不会再压成 `clinical_indexed.csv`。

B 更接近原文件下载。它查 Files API，把 BCR Biotab TSV 原样落到 `ClinicDatasets/gdc_clinical/biotab/<PROJECT>/`。
多张 clinic 表不会合成一张，也不会并进 A 的 JSON。额外只写 manifest 和字段清单。
表头解析、`read_biotab()` 是给后面用的辅助，主产物仍是原始 TSV。

可以这么记：

- A：按 project 直接下载门户 clinical JSON。
- B：TCGA 原始 BCR 表，drug / radiation / follow-up / nte / omf 都还在；代价是要自己按 `bcr_patient_barcode` 拼表。

`--dry-run` 数到的“多个 clinic 文件”只描述 B。A 每个癌种一份 JSON，文件名是 `<PROJECT>.json`。

A / B 实际下载完成后，每个落盘文件的 md5、下载日期、GDC data release 会写到 `ClinicDatasets/gdc_download_detail.json`。分两次跑 A、B 时，按文件覆盖，其余记录保留。

单独运行 dry-run，只统计，不下载：

```bash
python ClinicDatasets/gdc_clinical_batch.py --dry-run
python ClinicDatasets/gdc_clinical_batch.py --projects TCGA-KIRP --dry-run
```

单独运行 A 分支，下载门户 clinical JSON：

```bash
python ClinicDatasets/gdc_clinical_batch.py --skip-biotab
python ClinicDatasets/gdc_clinical_batch.py --projects TCGA-KIRP --skip-biotab
```

单独运行 B 分支，下载 BCR Biotab：

```bash
python ClinicDatasets/gdc_clinical_batch.py --skip-indexed
python ClinicDatasets/gdc_clinical_batch.py --projects TCGA-KIRP --skip-indexed
```


## 导出 clinic 字段表

脚本：[gdc_field_tables.py](gdc_field_tables.py)。只拉 schema，不下病例。对应已经落在 `gdc_clinical/raw_json/` 里的门户 clinical JSON。

两张表：

1. Data Dictionary，Clinical 类别下的实体（case / demographic / diagnosis / treatment / exposure / follow_up / family_history / pathology_detail / molecular_test，以及 category=clinical 的其它实体）
   `GET /v0/submission/_dictionary/_all`
   -> `gdc_clinical/field_tables/gdc_clinical_dictionary.csv`
2. `/cases/_mapping` 里 clinical JSON 用得到的字段（field / type / description）
   `GET /cases/_mapping`
   -> `gdc_clinical/field_tables/gdc_cases_mapping.csv`

```bash
python ClinicDatasets/gdc_field_tables.py
python ClinicDatasets/gdc_field_tables.py --timeout 180
python ClinicDatasets/gdc_field_tables.py --include-nonclinical-mapping
```

`--include-nonclinical-mapping` 会把 `/cases` 全部可查询字段都留下，默认只留 demographic / diagnoses / exposures / family_histories / follow_ups 和病例根字段。
