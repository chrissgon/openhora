"""The host rebuilds a result from a closed schema: the render's summary carries the two hashes of each block of the second contract, the storyboard's names
the blocks it drew with no pixel gate, and nothing else a container writes there survives."""
from __future__ import annotations

import renderer_kit  # noqa: F401  (puts the renderer's modules on the path)
import _docker as D

PROOF = {"served_sha256": "a" * 64, "runtime_sha256": "b" * 64}


def test_the_render_summary_keeps_the_hf_proofs_and_only_their_two_fields():
    schema = D.RESULT_SCHEMAS["render"][1]["hf_proofs"]
    kept = D.sanitise({"hf:demo-pop": dict(PROOF, extra="x")}, schema, "render")
    assert kept == {"hf:demo-pop": PROOF}
    assert D.sanitise(None, schema, "render") is None


def test_the_storyboard_summary_may_name_the_blocks_it_drew_without_the_gates():
    schema = D.RESULT_SCHEMAS["storyboard"][1]["advisory"]
    assert D.sanitise(["hf:demo-pop"], schema, "storyboard") == ["hf:demo-pop"] and D.sanitise(None, schema, "storyboard") is None
