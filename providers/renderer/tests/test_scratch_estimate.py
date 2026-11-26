"""The scratch a render must find free before it draws (`_render.scratch_estimate`), at the shape of a 300 s post, with no render (PF-b1).

The recording bound is 300 s (VD7). Once ffmpeg is the default engine, a post of that length goes through the runtime with the default limits (scratch 2048 MiB,
`_docker.DEFAULT_SCRATCH_MB`), so the estimate must fit it: a live run of a 297.85 s input (7125 output frames, 7493 frame jobs) was refused `no_space output` while the
estimate counted 250000 bytes a frame. The guard itself stays: a render that cannot fit is still refused.
"""
from __future__ import annotations

import renderer_kit  # noqa: F401  (puts the renderer folder on the path)
import _docker as D
import _render
import _vocab

LIMITS = _vocab.load_data()["limits"]
MIB = 1024 * 1024
INSTAGRAM_BYTES = 300_000_000


def test_a_300_second_post_with_the_live_runs_frame_jobs_fits_the_default_scratch():
    jobs = 7493                                             # the live run: 7125 output frames, captions and beats counted as separate jobs
    assert _render.scratch_estimate(jobs, LIMITS, INSTAGRAM_BYTES) <= D.DEFAULT_SCRATCH_MB * MIB


def test_a_300_second_post_with_a_caption_on_every_frame_and_a_beat_on_a_fifth_fits_the_default_scratch():
    frames = 300 * 30
    jobs = frames + frames // 5
    assert _render.scratch_estimate(jobs, LIMITS, INSTAGRAM_BYTES) <= D.DEFAULT_SCRATCH_MB * MIB


def test_the_estimate_still_refuses_what_cannot_fit():
    jobs = 2 * 300 * 30 * 3                                  # three times the most two full tracks of a 300 s post can hold
    assert _render.scratch_estimate(jobs, LIMITS, INSTAGRAM_BYTES) > D.DEFAULT_SCRATCH_MB * MIB


def test_the_estimate_counts_the_frames_the_work_files_and_the_output():
    assert _render.scratch_estimate(0, LIMITS, 1000) == 64 * MIB + 1000
    assert _render.scratch_estimate(10, LIMITS, 0) - _render.scratch_estimate(0, LIMITS, 0) == 10 * LIMITS["frame_bytes_estimate"]


def test_the_estimate_is_the_one_the_render_uses():
    source = open(_render.__file__, encoding="utf-8").read()
    assert 'estimate = scratch_estimate(len(jobs_list), limits, plan["max_bytes"])' in source and 'free < estimate' in source      # the no_space guard is kept
