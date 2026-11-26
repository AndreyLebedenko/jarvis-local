import threading
from pathlib import Path
from unittest.mock import Mock

import pytest

from jarvis.core.brand_icon import BrandIconError
from jarvis.core.brand_render import GenerationOutcome
from jarvis.core.config import ConfigError
from jarvis.launcher.branding import (
    FAILED_STATUS,
    WORKING_STATUS,
    IconRegeneration,
    RegenerationJob,
    regenerate,
)


def outcome(message="Generated brand icons in X"):
    return GenerationOutcome(None, message)


@pytest.mark.parametrize(
    "error",
    [
        ConfigError("[brand].monogram must be one letter"),
        BrandIconError("bad"),
        OSError("denied"),
    ],
)
def test_expected_failures_keep_their_exact_message(tmp_path, error):
    def fail(home):
        raise error

    result = regenerate(tmp_path, fail)

    assert result.error is error
    assert result.message == str(error)


def test_an_unexpected_failure_is_wrapped_never_raised(tmp_path):
    def fail(home):
        raise KeyError("oops")

    result = regenerate(tmp_path, fail)

    assert isinstance(result.error, RuntimeError)
    assert "Icon generation failed" in str(result.error)
    assert "KeyError" in str(result.error)


def test_a_success_carries_the_generator_message(tmp_path):
    result = regenerate(
        tmp_path, lambda home: outcome("Default identity: nothing to generate")
    )

    assert (result.message, result.error) == (
        "Default identity: nothing to generate",
        None,
    )


def test_a_job_runs_off_the_calling_thread_and_delivers_one_result(tmp_path):
    release = threading.Event()
    seen = []

    def generate(home):
        seen.append((home, threading.current_thread() is not threading.main_thread()))
        release.wait(5)
        return outcome("done")

    job = RegenerationJob(tmp_path, generate)
    job.start()
    assert job.poll() is None
    release.set()
    job._thread.join(5)

    assert job.poll().message == "done"
    assert job.poll() is None
    assert seen == [(tmp_path, True)]


class FakeJob:
    def __init__(self, home):
        self.home = home
        self.started = False
        self.result = None

    def start(self):
        self.started = True

    def poll(self):
        return self.result


def make_regeneration(tmp_path):
    jobs, success, errors = [], Mock(), Mock()
    saved_home = {"value": tmp_path}

    def start_job(home):
        job = FakeJob(home)
        jobs.append(job)
        return job

    regeneration = IconRegeneration(
        lambda: saved_home["value"], success, errors, start_job
    )
    return regeneration, jobs, success, errors, saved_home


def test_a_click_starts_one_job_for_the_saved_home_and_shows_working(tmp_path):
    regeneration, jobs, *_ = make_regeneration(tmp_path)

    regeneration.click()

    assert regeneration.working
    assert regeneration.status == WORKING_STATUS == "Working..."
    assert jobs[0].home == tmp_path
    assert jobs[0].started


def test_clicks_while_working_start_nothing_more(tmp_path):
    regeneration, jobs, *_ = make_regeneration(tmp_path)

    regeneration.click()
    regeneration.click()

    assert len(jobs) == 1


def test_polling_before_the_result_changes_nothing(tmp_path):
    regeneration, _, success, errors, _ = make_regeneration(tmp_path)
    regeneration.click()

    regeneration.poll()

    assert regeneration.working
    success.assert_not_called()
    errors.assert_not_called()


def test_a_success_re_enables_shows_the_message_and_reloads_the_identity(tmp_path):
    regeneration, jobs, success, errors, _ = make_regeneration(tmp_path)
    regeneration.click()
    jobs[0].result = regenerate(
        tmp_path, lambda home: outcome("Generated brand icons in X")
    )

    regeneration.poll()

    assert not regeneration.working
    assert regeneration.status == "Generated brand icons in X"
    success.assert_called_once_with()
    errors.assert_not_called()
    regeneration.click()
    assert len(jobs) == 2


def test_the_default_identity_answer_is_shown_and_still_reloads(tmp_path):
    regeneration, jobs, success, _, _ = make_regeneration(tmp_path)
    regeneration.click()
    jobs[0].result = regenerate(
        tmp_path, lambda home: outcome("Default identity: nothing to generate")
    )

    regeneration.poll()

    assert regeneration.status == "Default identity: nothing to generate"
    success.assert_called_once_with()


def test_a_failure_hands_the_exact_error_to_the_dialog_and_re_enables(tmp_path):
    regeneration, jobs, success, errors, _ = make_regeneration(tmp_path)
    error = BrandIconError('[brand].icon "x.png": is not a PNG file (bad signature)')
    regeneration.click()
    jobs[0].result = regenerate(tmp_path, Mock(side_effect=error))

    regeneration.poll()

    assert not regeneration.working
    assert regeneration.status == FAILED_STATUS
    errors.assert_called_once_with(error)
    success.assert_not_called()


def test_clearing_resets_the_status_only_when_idle(tmp_path):
    regeneration, jobs, *_ = make_regeneration(tmp_path)
    regeneration.click()
    regeneration.clear()
    assert regeneration.status == WORKING_STATUS
    jobs[0].result = regenerate(tmp_path, lambda home: outcome("done"))
    regeneration.poll()

    regeneration.clear()

    assert regeneration.status == ""


def test_the_home_is_read_at_click_time(tmp_path):
    regeneration, jobs, _, _, saved_home = make_regeneration(tmp_path)
    saved_home["value"] = tmp_path / "other"

    regeneration.click()

    assert jobs[0].home == Path(tmp_path / "other")


def test_a_worker_that_cannot_start_does_not_leave_the_button_disabled(tmp_path):
    class UnstartableJob(FakeJob):
        def start(self):
            raise RuntimeError("can't start new thread")

    jobs = []
    errors = Mock()
    regeneration = IconRegeneration(
        lambda: tmp_path,
        Mock(),
        errors,
        lambda home: jobs.append(UnstartableJob(home)) or jobs[-1],
    )

    regeneration.click()

    assert not regeneration.working
    assert regeneration.status == FAILED_STATUS
    errors.assert_called_once()
    assert str(errors.call_args.args[0]) == "can't start new thread"
    regeneration.click()
    assert len(jobs) == 2
