# 清理记录 2026-10-05:gt≤0 患者口径漏洞的旧搜索运行产物(用户指令)

## 删除路径
12G	results/greedy/prompt
25M	results/Test_3_greedy_vs_works/search
6.4M	results/Test_3_greedy_vs_works/archive_sigstop_20261004
104K	results/Test_3_greedy_vs_works/compare
4.1M	results/Test_3_greedy_vs_works/logs
12K	results/Test_3_greedy_vs_works/missed_fields.csv
8.0K	results/Test_3_greedy_vs_works/three_arm.csv

## 进程(已 SIGTERM)
124535 run_e2_selection_queue.py --dataset TCGA-BRCA
124805 run_e2_selection.py --dataset TCGA-BRCA
3327026 evaluate.py G9_acb452fac3 (TCGA-BRCA 贪婪内部评估)
