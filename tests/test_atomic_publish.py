"""
test_atomic_publish.py - 验证 atomic_publish 不会覆盖已存在的 final

Bug: plan_output 在调用时刻检查 final 是否存在，但 ffmpeg 编码期间（数秒到
数分钟）另一个进程/用户可能创建同名文件。atomic_publish 用 os.replace 永远
原子覆盖 → 用户已有数据被静默销毁。
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import core


def test_atomic_publish_does_not_overwrite_existing_final():
    """final 已存在 → atomic_publish 必须返回 False，不覆盖。"""
    work = ROOT / "tests" / "out_atomic"
    work.mkdir(parents=True, exist_ok=True)
    tmp = work / "movie.partial.mp4"
    final = work / "movie.mp4"

    existing = b"USER DATA WE MUST NOT DESTROY" * 100
    final.write_bytes(existing)

    tmp.write_bytes(b"new conversion output" * 1000)

    ok = core.atomic_publish(tmp, final)
    assert ok is False, "atomic_publish 返回 True 但 final 已被占用"
    assert final.read_bytes() == existing, "final 被覆盖，用户数据被销毁"
    assert not tmp.exists(), "tmp 在拒绝发布后未清理"
    print("✓ 拒绝覆盖已存在的 final")


def test_atomic_publish_succeeds_when_final_does_not_exist():
    """final 不存在 → atomic_publish 正常发布。"""
    work = ROOT / "tests" / "out_atomic2"
    if work.exists():
        import shutil
        shutil.rmtree(work)
    work.mkdir(parents=True, exist_ok=True)
    tmp = work / "x.partial.mp4"
    final = work / "x.mp4"
    tmp.write_bytes(b"converted bytes" * 100)

    ok = core.atomic_publish(tmp, final)
    assert ok is True, "final 不存在时应发布成功"
    assert final.exists(), "final 未生成"
    assert final.stat().st_size > 0, "final 是空文件"
    assert not tmp.exists(), "tmp 残留"
    print("✓ final 不存在时正常发布")


if __name__ == "__main__":
    test_atomic_publish_does_not_overwrite_existing_final()
    test_atomic_publish_succeeds_when_final_does_not_exist()
