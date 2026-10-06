"""Manual (A_manual) pipeline: clinical JSON -> prompt CSV -> CONCH embedding / baseline / HGCN clinic.

原独立子项目 ``A_pipeline``（gdc 线）已吸收进主项目：

* 编码内核          ``src/manual_pipeline/``（本包；相对 import 保持包内，对 ``common.*`` /
  ``greedy.*`` / ``discovery.*`` 的引用直接走 ``projects/src``，不再有 sys.path 注入）
* 方案模板          ``templates/manual_schemes/``（paper 方案 + Test_3_* 自定义方案 + L0-L5 冻结模板）
* gdc 词表          ``templates/manual_schemes/baseline_onehot_mapping_tables/gdc/``
* CLI 入口          ``scripts/run_a_manual.py``（``json2prompt / encode / pipeline / baseline /
  hgcn_clinic / cindex``）。

数据源只剩 gdc（``projects/datasets.json`` + ``ClinicDatasets/gdc_clinical``）；lizhe 数据源与
L0-L5/D0-D5 的 lizhe 运行配置属 PGC 线（``A_pipeline_pgc/``）。
"""

from __future__ import annotations
