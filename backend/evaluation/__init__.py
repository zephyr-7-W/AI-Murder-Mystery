# evaluation/__init__.py
# 离线评估子系统（开发 / 论文用），**不参与游戏运行时**。
#
# 边界（重要，改动前先读）：
#   1. 本包只在离线批量评估时被导入；游戏侧代码（main.py / dialogue.py / oracle.py /
#      coach.py / judge.py / role_skeleton/*）永远不导入本包，也永远不导入 ragas；
#   2. Ragas 打分本身要再调一次大模型，延迟与成本都不适合实时交互，因此绝不挂在
#      WebSocket 动作路径上（游玩时不在线跑 Ragas）；
#   3. 本包产出的报告 / 样本文件属于“可对外”的评估产物，因此绝不写入真凶身份、
#      murder_process、骨架 secrets / private_facts 与未放行的揭示原文；
#      写入前统一过 report.scan_and_redact() 兜底。
#
# 这里刻意不做任何 import：保持“导入即零成本”，也避免把 ragas 拖进运行时的模块图。

__all__: list[str] = []
