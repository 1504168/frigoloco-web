"""Gap-free event-sync windows: start from sync_run history, chunking, outage recovery."""

from __future__ import annotations

import datetime

import pytest

from app.husky.sync import TRAILING_EVENT_WINDOW, JobOutcome

from cron import event_windows
from cron.event_windows import (
    MAX_WINDOW_SPAN,
    RESUME_OVERLAP,
    TimeWindow,
    resolve_window_start,
    run_event_sync,
    split_into_windows,
)

JOB = "sync_purchases"
# Fixed past instant so clamp_report_to (now - lag) never moves it.
NOW = datetime.datetime(2026, 10, 1, 12, 0, tzinfo=datetime.timezone.utc)
TRAILING_START = NOW - TRAILING_EVENT_WINDOW


class RecordingSync:
    """Stands in for a sync_*_window function and records the windows it was asked for."""

    def __init__(self, failing_call: int | None = None) -> None:
        self.windows: list[TimeWindow] = []
        self.failing_call = failing_call

    def __call__(
        self,
        window_from: datetime.datetime,
        window_to: datetime.datetime,
    ) -> JobOutcome:
        self.windows.append(TimeWindow(window_from, window_to))
        if len(self.windows) == self.failing_call:
            raise RuntimeError("husky timeout")
        return JobOutcome(fetched=10, upserted=10)


def test_window_start_is_trailing_start_when_job_never_ran():
    assert resolve_window_start(TRAILING_START, None) == TRAILING_START


def test_window_start_is_trailing_start_when_last_sync_is_recent():
    last_synced_until = NOW - datetime.timedelta(minutes=50)

    assert resolve_window_start(TRAILING_START, last_synced_until) == TRAILING_START


def test_window_start_reaches_back_to_last_sync_minus_overlap_after_outage():
    last_synced_until = NOW - datetime.timedelta(days=5)

    window_start = resolve_window_start(TRAILING_START, last_synced_until)

    assert window_start == last_synced_until - RESUME_OVERLAP


def test_split_into_windows_is_contiguous_and_capped():
    start = NOW - datetime.timedelta(days=16)

    windows = split_into_windows(start, NOW)

    assert len(windows) == 3
    assert windows[0].start == start
    assert windows[-1].end == NOW
    assert windows[0].end == windows[1].start
    assert windows[1].end == windows[2].start
    assert all(window.end - window.start <= MAX_WINDOW_SPAN for window in windows)


def test_five_day_outage_is_synced_without_gap(monkeypatch):
    last_synced_until = NOW - datetime.timedelta(days=5)
    monkeypatch.setattr(event_windows, "load_last_synced_by_job", lambda: {JOB: last_synced_until})
    recording_sync = RecordingSync()

    outcome = run_event_sync(JOB, recording_sync, TRAILING_EVENT_WINDOW, window_to=NOW)

    assert recording_sync.windows == [TimeWindow(last_synced_until - RESUME_OVERLAP, NOW)]
    assert outcome.upserted == 10


def test_twelve_day_outage_runs_in_oldest_first_chunks(monkeypatch):
    last_synced_until = NOW - datetime.timedelta(days=12)
    monkeypatch.setattr(event_windows, "load_last_synced_by_job", lambda: {JOB: last_synced_until})
    recording_sync = RecordingSync()

    outcome = run_event_sync(JOB, recording_sync, TRAILING_EVENT_WINDOW, window_to=NOW)

    first_window = recording_sync.windows[0]
    second_window = recording_sync.windows[1]
    assert first_window.start == last_synced_until - RESUME_OVERLAP
    assert first_window.end == second_window.start
    assert second_window.end == NOW
    assert outcome.upserted == 20


def test_failing_chunk_stops_the_run_so_later_chunks_are_not_synced(monkeypatch):
    last_synced_until = NOW - datetime.timedelta(days=12)
    monkeypatch.setattr(event_windows, "load_last_synced_by_job", lambda: {JOB: last_synced_until})
    recording_sync = RecordingSync(failing_call=1)

    with pytest.raises(RuntimeError):
        run_event_sync(JOB, recording_sync, TRAILING_EVENT_WINDOW, window_to=NOW)

    assert len(recording_sync.windows) == 1


def test_explicit_window_from_skips_history(monkeypatch):
    monkeypatch.setattr(event_windows, "load_last_synced_by_job", pytest.fail)
    window_from = NOW - datetime.timedelta(hours=3)
    recording_sync = RecordingSync()

    run_event_sync(JOB, recording_sync, TRAILING_EVENT_WINDOW, window_from, NOW)

    assert recording_sync.windows == [TimeWindow(window_from, NOW)]
