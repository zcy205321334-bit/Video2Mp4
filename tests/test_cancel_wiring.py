"""
test_cancel_wiring.py - 验证 Worker.cancel() 真正传到 convert_one.is_cancelled()

Bug: Worker._cancel_flag 和 cancel_token 是两套互不相通的机制。
点取消 → set Worker._cancel_flag → engine 看到的是另一个 CancelToken.is_cancelled()。
"""
from __future__ import annotations
import queue
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import core
import mov2mp4


def test_cancel_propagates_through_worker():
    """Worker.cancel() → convert_one.is_cancelled() 应在 2 秒内返回 True。"""
    src = ROOT / "_test" / "sample.mov"
    assert src.exists(), f"缺少测试样本：{src}"

    # 用 stub 替换 convert_one：它在每次 is_cancelled() 时记录时间，
    # cancel 后应立即看到 True。
    poll_log = []

    def slow_one(src, options, encoders, progress_cb, is_cancelled, summary=None,
                 audio_strategy_override=None, encoder_override=None):
        t0 = time.time()
        while time.time() - t0 < 5.0:
            if is_cancelled():
                poll_log.append(("cancelled_seen", time.time() - t0))
                return core.TaskResult(src=src, dst=Path(),
                                       status=core.Status.CANCELLED,
                                       message="stub cancelled")
            time.sleep(0.05)
        poll_log.append(("timeout", time.time() - t0))
        return core.TaskResult(src=src, dst=Path(),
                               status=core.Status.SUCCESS,
                               message="stub success")

    original = mov2mp4.core.convert_one
    mov2mp4.core.convert_one = slow_one
    try:
        items = [(src, None)]
        opts = core.ConvertOptions(mode="remux")
        encs = core.detect_encoders_full(lambda m: None)

        progress_q = queue.Queue()
        log_q = queue.Queue()
        done_q = queue.Queue()

        w = mov2mp4.Worker(items, opts, encs, None, progress_q, log_q, done_q)
        t0 = time.time()
        w.start()
        time.sleep(0.3)  # 让 convert_one stub 进入轮询
        w.cancel()
        w.join(timeout=8)
        elapsed = time.time() - t0
        assert not w.is_alive(), f"worker {elapsed:.1f}s 后仍未退出"
    finally:
        mov2mp4.core.convert_one = original

    assert poll_log, "convert_one stub 从未被调用"
    kind, delay = poll_log[0]
    assert kind == "cancelled_seen", (
        f"convert_one 轮询 is_cancelled 但始终看到 False（log={poll_log}）"
    )
    assert delay < 2.0, f"cancel 传播耗时 {delay:.2f}s，要求 < 2s"
    print(f"✓ cancel 传播耗时 {delay:.3f}s")


if __name__ == "__main__":
    test_cancel_propagates_through_worker()
