"""cmd_run 补位式调度的回归测试(2026-10-14)。

旧实现 = 整批等待:认领 n_conf 个 → 等全部完成 → 再认领。慢 conf 拖住整批,
running/ 掉到个位数、队列看着像卡死。新实现 = 补位式:完成一个立即认领下一个,
在飞数保持在 n_conf。

本测试用真实 queue_core(原子认领/状态迁移)+ stub 执行器,验证调度语义:
  1. 在飞数上限 = WORKERS(每卡 conf 数);
  2. 补位成立:一个慢 conf 不会挡住后续认领——它完成时,其余 conf 早已跑完;
  3. 全部跑完后正常收工,退出码 0。
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for item in (ROOT, ROOT / "src", ROOT / "scripts"):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

import exp_queue as EQ  # noqa: E402


def _fake_conf(root: Path, name: str) -> None:
    (root / "queue").mkdir(parents=True, exist_ok=True)
    (root / "queue" / name).write_text(
        json.dumps({"job_key": name, "dataset": "TCGA-XX", "kind": "bogus"}) + "\n",
        encoding="utf-8")


def _opts(root: Path, workers: int, interval: float = 1) -> argparse.Namespace:
    return argparse.Namespace(queue_root=str(root), workers=workers, interval=interval)


def test_refill_not_batch_wait(tmp_path, monkeypatch):
    """慢 conf 不挡补位:conf_0 睡 0.8s,其余 7 个睡 0.05s,WORKERS=3。

    旧整批逻辑:第一批 = conf_0,1,2 → 等 0.8s 才认领 3,4,5。
    新补位逻辑:1,2 完成即认领 3,4,…,conf_0 完成时其余 7 个全跑完。
    """
    events: list[tuple[float, str]] = []
    inflight = 0
    max_inflight = 0
    lock = threading.Lock()

    def stub_run(path, field_workers):
        nonlocal inflight, max_inflight
        with lock:
            inflight += 1
            max_inflight = max(max_inflight, inflight)
        name = path.name
        # 慢 conf 3.5s >> 轮询 1s,快 conf 0.05s(与生产比例一致:分钟级 vs 秒级轮询)
        sleep = 3.5 if name.startswith("conf_0_") else 0.05
        time.sleep(sleep)
        with lock:
            inflight -= 1
            events.append((time.monotonic(), name))
        from queue_core import mark_done
        mark_done(path)

    monkeypatch.setattr(EQ, "_run_conf", stub_run)
    for i in range(8):
        _fake_conf(tmp_path / "cfg", f"conf_{i}_x.conf")

    start = time.monotonic()
    rc = EQ.cmd_run(_opts(tmp_path / "cfg", workers=3))
    elapsed = time.monotonic() - start

    assert rc == 0
    assert max_inflight == 3, f"在飞数上限应为 3,实际 {max_inflight}"
    # 补位判据:慢 conf(3.5s)完成时,至少 4 个快 conf 已完成。
    # (整批逻辑 = 只完成第一批的 2 个;补位受 1 秒轮询节流,实测 5-7 个。
    #   生产里 conf 分钟级、轮询秒级,节流无感——这里只要求显著区别于整批。)
    slow_done = next(t for t, n in events if n.startswith("conf_0_"))
    finished_before_slow = [n for t, n in events if t <= slow_done and not n.startswith("conf_0_")]
    assert len(finished_before_slow) >= 4, \
        f"补位失效:conf_0 完成时只有 {len(finished_before_slow)} 个完成(应 >= 4)"
    assert elapsed < 8.0, f"总时长异常 {elapsed:.2f}s"
    assert len(events) == 8


def test_workers_equals_conf_concurrency(tmp_path, monkeypatch):
    """WORKERS=4 → 每卡在飞 4 个 conf(用户口径:WORKERS = conf 数,不是进程数)。"""
    inflight = 0
    max_inflight = 0
    lock = threading.Lock()

    def stub_run(path, field_workers):
        nonlocal inflight, max_inflight
        with lock:
            inflight += 1
            max_inflight = max(max_inflight, inflight)
        time.sleep(0.05)
        with lock:
            inflight -= 1
        from queue_core import mark_done
        mark_done(path)

    monkeypatch.setattr(EQ, "_run_conf", stub_run)
    for i in range(6):
        _fake_conf(tmp_path / "cfg", f"c{i}.conf")

    rc = EQ.cmd_run(_opts(tmp_path / "cfg", workers=4))
    assert rc == 0
    assert max_inflight == 4, f"WORKERS=4 应在飞 4 个 conf,实际 {max_inflight}"


def test_refill_fills_slots_while_all_long(tmp_path, monkeypatch):
    """全部 conf 都长时,补位不能饿死:第一个完成时其余空位应已全部被认领。

    旧 bug 现场:剩余 conf 全是很长的 univariate,run 阻塞在等完成,
    空位空转数小时、队列纹丝不动(2026-10-14 过夜实锤)。
    """
    import exp_queue as EQ2
    inflight = 0
    max_inflight = 0
    lock = threading.Lock()

    def stub_run(path, field_workers):
        nonlocal inflight, max_inflight
        with lock:
            inflight += 1
            max_inflight = max(max_inflight, inflight)
        time.sleep(0.6)   # 全部 0.6s,远大于 interval=0.1 的轮询
        with lock:
            inflight -= 1
        from queue_core import mark_done
        mark_done(path)

    monkeypatch.setattr(EQ2, "_run_conf", stub_run)
    for i in range(6):
        _fake_conf(tmp_path / "cfg2", f"c{i}.conf")

    rc = EQ2.cmd_run(_opts(tmp_path / "cfg2", workers=3, interval=0.1))
    assert rc == 0
    # 若补位被阻塞等待饿死,峰值在飞数会掉到 1;正确行为 = 一直 3
    assert max_inflight == 3, f"补位饿死:峰值在飞 {max_inflight},应保持 3"
