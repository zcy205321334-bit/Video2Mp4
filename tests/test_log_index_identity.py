"""
test_log_index_identity.py - 验证 log_q 载荷用 src 路径，索引不漂移

Bug 复现（已修）：
  items = [bad.mov, good.mov]
  _start() 探测坏文件 → 不 append 进 prepared，但直接 set_status(bad, ✗)
  prepared = [good.mov]
  Worker.run 用 enumerate(prepared) → good 在 prepared 里 idx=0
  原代码：log_q.put((0, SUCCESS)) → _handle_log 收到 (0, SUCCESS) →
          self.items[0] = bad → 标 ✓ 到坏文件上
"""
from __future__ import annotations
import queue
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import core
import mov2mp4
# 注意：mov2mp4.py 用 `import core`，Worker 调的是模块对象 core.convert_one
# 直接 monkey-patch 模块属性（mov2mp4.core 不存在，那只是个 namespace）
_PATCH_MOD = sys.modules["core"]


def _stub_convert_one_factory(results):
    iter_results = iter(results)
    def stub(src, options, encoders, progress_cb, is_cancelled, summary=None,
             audio_strategy_override=None, encoder_override=None):
        r = next(iter_results)
        progress_cb(1.0, "end")
        return r
    return stub


def test_bad_first_then_good_keeps_separate_status():
    """坏文件在前、好文件在后 → 各自标各自的，不能错位。"""
    work = ROOT / "tests" / "out_logid"
    work.mkdir(parents=True, exist_ok=True)

    bad = work / "bad.mov"
    good = work / "good.mov"
    bad.write_bytes(b"not a video")
    good.write_bytes(b"placeholder")

    items = [(bad, None), (good, None)]
    results = [
        core.TaskResult(src=bad, dst=work / "bad.mp4",
                        status=core.Status.FAILED, message="bad"),
        core.TaskResult(src=good, dst=work / "good.mp4",
                        status=core.Status.SUCCESS, message="ok"),
    ]
    saved = _PATCH_MOD.convert_one
    _PATCH_MOD.convert_one = _stub_convert_one_factory(results)
    try:
        progress_q = queue.Queue(); log_q = queue.Queue(); done_q = queue.Queue()
        w = mov2mp4.Worker(items, core.ConvertOptions(mode="remux"),
                           {"hevc": [], "h264": []}, None,
                           progress_q, log_q, done_q)
        w.start()
        w.join(timeout=5)
        assert not w.is_alive(), "Worker 没退出"
    finally:
        _PATCH_MOD.convert_one = saved

    seen = []
    while not log_q.empty():
        seen.append(log_q.get_nowait())
    finals = [s for s in seen if s[1] in
              (core.Status.SUCCESS, core.Status.FAILED, "failed", "cancelled")]
    assert finals, f"没有任何状态条目：{seen}"

    by_src = {s[0]: s[1] for s in finals}
    assert by_src.get(bad) in (core.Status.FAILED, "failed"), (
        f"bad 文件状态错：{by_src}")
    assert by_src.get(good) == core.Status.SUCCESS, (
        f"good 文件状态错：{by_src}")
    print(f"✓ bad={by_src.get(bad)} good={by_src.get(good)}（各自独立）")


def test_probe_fail_does_not_leak_into_worker_log():
    """_start() 探测失败剔除的文件不应出现在 Worker 的 log_q 里。"""
    work = ROOT / "tests" / "out_logid2"
    work.mkdir(parents=True, exist_ok=True)

    bad = work / "bad2.mov"; bad.write_bytes(b"x")
    good = work / "good2.mov"; good.write_bytes(b"y")

    prepared = [(good, None)]
    results = [core.TaskResult(src=good, dst=work / "g.mp4",
                               status=core.Status.SUCCESS, message="ok")]
    saved = _PATCH_MOD.convert_one
    _PATCH_MOD.convert_one = _stub_convert_one_factory(results)
    try:
        progress_q = queue.Queue(); log_q = queue.Queue(); done_q = queue.Queue()
        w = mov2mp4.Worker(prepared, core.ConvertOptions(mode="remux"),
                           {"hevc": [], "h264": []}, None,
                           progress_q, log_q, done_q)
        w.start()
        w.join(timeout=5)
    finally:
        _PATCH_MOD.convert_one = saved

    drained = []
    while not log_q.empty():
        drained.append(log_q.get_nowait())
    bad_mentioned = any(s[0] == bad for s in drained)
    assert not bad_mentioned, f"bad 文件泄到 worker log_q：{drained}"
    print(f"✓ 探测失败文件未泄漏进 worker（drained {len(drained)} 条）")


if __name__ == "__main__":
    test_bad_first_then_good_keeps_separate_status()
    test_probe_fail_does_not_leak_into_worker_log()
