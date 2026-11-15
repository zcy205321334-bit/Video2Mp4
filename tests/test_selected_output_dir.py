"""Regression for converting directly into the folder selected in the GUI."""
from pathlib import Path
import queue
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core
from mov2mp4 import Worker


def test_worker_converts_directly_into_selected_folder():
    with TemporaryDirectory() as root:
        source_dir = Path(root) / "source"
        output_dir = Path(root) / "output"
        source_dir.mkdir()
        output_dir.mkdir()
        source = source_dir / "sample.mov"
        subprocess.run(
            [core.get_ffmpeg(), "-v", "error", "-f", "lavfi", "-i",
             "color=s=64x64:r=10:d=1", "-c:v", "libx264", str(source)],
            check=True,
            capture_output=True,
            timeout=20,
        )
        original_source = source.read_bytes()
        existing = output_dir / "sample.mp4"
        existing.write_bytes(b"existing file")
        logs = queue.Queue()
        done = queue.Queue()
        worker = Worker(
            [(source, None)], core.ConvertOptions(mode="remux"), {},
            output_dir, queue.Queue(), logs, done,
        )
        with patch.object(core, "run_ffmpeg_with_progress",
                          wraps=core.run_ffmpeg_with_progress) as run_ffmpeg:
            worker.run()

        assert done.get_nowait() == "done"
        assert logs.get_nowait()[0] == source
        log_source, status, message = logs.get_nowait()
        assert log_source == source and status == core.Status.SUCCESS, message
        conversion = run_ffmpeg.call_args.kwargs
        assert Path(conversion["cmd"][-1]).parent == output_dir, conversion["cmd"][-1]
        assert conversion["log_path"].parent == output_dir
        assert list(source_dir.iterdir()) == [source]
        assert source.read_bytes() == original_source
        assert existing.read_bytes() == b"existing file"
        output = output_dir / "sample (1).mp4"
        assert set(output_dir.iterdir()) == {existing, output}
        assert core.summarize_streams(core.probe_streams(output)).video_codecs == ["h264"]

        output.unlink()
        run_conversion = core.run_ffmpeg_with_progress

        def add_existing_target(**kwargs):
            result = run_conversion(**kwargs)
            output.write_bytes(b"arrived during conversion")
            return result

        with patch.object(core, "run_ffmpeg_with_progress", side_effect=add_existing_target):
            result = core.convert_one(
                source, core.ConvertOptions(mode="remux"), {},
                lambda *_: None, lambda: False, output_dir=output_dir,
            )
        assert result.status == core.Status.FAILED
        assert "未覆盖" in result.message
        assert output.read_bytes() == b"arrived during conversion"
        assert not list(output_dir.glob("*.partial.mp4"))


def test_planning_same_output_reserves_distinct_temporary_files():
    with TemporaryDirectory() as root:
        source = Path(root) / "sample.mov"
        final_a, temp_a = core.plan_output(source, Path(root), "remux")
        final_b, temp_b = core.plan_output(source, Path(root), "remux")
        assert final_a == final_b
        assert temp_a != temp_b and temp_a.is_file() and temp_b.is_file()


if __name__ == "__main__":
    test_worker_converts_directly_into_selected_folder()
    test_planning_same_output_reserves_distinct_temporary_files()
    print("PASS: Worker uses selected output folder")
