"""Saved tests are deleted after the retention period (worker/retention.py), and a whole test is recorded."""
import asyncio
import json
import time
import wave

import pytest

import worker.retention as retention
import worker.session as sess
from worker.session import ExamSession

NOW = time.mktime(time.strptime("20261201_120000", "%Y%m%d_%H%M%S"))


def make_files(folder, *names):
    for name in names:
        (folder / name).write_bytes(b"x")


def left(folder):
    return sorted(p.name for p in folder.iterdir())


def test_only_saved_tests_older_than_the_period_are_deleted(tmp_path):
    old = ["run_20261031_115959_11111111.json", "run_20261031_115959_11111111.wav", "run_20260101_000000.json"]
    keep = ["run_20261101_120001_22222222.json", "run_20261101_120001_22222222.wav", "run_20261201_100000_33333333.json",
            "notes.txt", "run_20200101_000000_44444444.log", "run_20200101.json", "copy of run_20200101_000000_5.json",
            "run_99999999_999999_6.json"]
    make_files(tmp_path, *old, *keep)
    sub = tmp_path / "gpu_session"
    sub.mkdir()
    make_files(sub, "run_20200101_000000_77777777.json")              # a folder someone made: never entered
    (tmp_path / "run_20200101_000000_88888888.json").mkdir()          # a folder with a run's name: not a file, left alone
    assert sorted(retention.purge(tmp_path, 30, now=NOW)) == sorted(old)
    assert left(tmp_path) == sorted(keep + ["gpu_session", "run_20200101_000000_88888888.json"])
    assert left(sub) == ["run_20200101_000000_77777777.json"]


def test_zero_days_keeps_everything_and_a_missing_folder_is_fine(tmp_path):
    make_files(tmp_path, "run_20200101_000000_1.json")
    assert retention.purge(tmp_path, 0, now=NOW) == []
    assert retention.purge(tmp_path / "nothing", 30, now=NOW) == []
    assert left(tmp_path) == ["run_20200101_000000_1.json"]


@pytest.mark.parametrize("value, days", [(None, 30), ("", 30), ("7", 7), ("0.5", 0.5), ("0", 0), ("-1", 0), ("a month", 0), ("nan", 0)])
def test_the_period_comes_from_the_setting_and_a_bad_one_deletes_nothing(monkeypatch, value, days):
    monkeypatch.delenv("RETENTION_DAYS", raising=False)
    if value is not None:
        monkeypatch.setenv("RETENTION_DAYS", value)
    assert retention.retention_days() == days


def record_a_test(tmp_path, monkeypatch, seconds):
    monkeypatch.setattr(sess, "RUNS", tmp_path)

    class Task:
        async def queue_frames(self, frames):
            pass

    async def go():
        async def send(event):
            pass

        s = ExamSession(send, seed=3)
        s.task = Task()
        await s.handle_control({"action": "start"})
        s._ticker.cancel()
        second = (1000).to_bytes(2, "little") * 16000
        for _ in range(seconds):
            s.note_audio(second)
        return await s.finish()

    path = asyncio.run(go())
    with wave.open(str(path.with_suffix(".wav"))) as w:
        recorded = w.getnframes() / w.getframerate()
    return json.loads(path.read_text(encoding="utf-8")), recorded


def test_a_test_longer_than_ten_minutes_is_recorded_whole(tmp_path, monkeypatch):
    monkeypatch.delenv("MAX_RECORDING_S", raising=False)
    record, recorded = record_a_test(tmp_path, monkeypatch, 16 * 60)
    assert recorded == record["mic_seconds"] == 16 * 60 and record["recording_truncated"] is False
    assert record["mic_peak"] == record["mic_rms"] == round(1000 / 32768, 4)


def test_a_recording_that_reaches_the_limit_says_so(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_RECORDING_S", "5")
    record, recorded = record_a_test(tmp_path, monkeypatch, 8)
    assert recorded == 5 and record["recording_truncated"] is True
