"""A rendered policy whose template is gone must not survive the next render."""
from render_policy import stale_outputs


def test_leftover_policy_is_reported_as_stale(tmp_path):
    kept, left_over = tmp_path / "a_permit.cedar", tmp_path / "old_forbid.cedar"
    kept.write_text("x")
    left_over.write_text("x")
    (tmp_path / "a_permit.cedar.tmpl").write_text("x")
    assert stale_outputs(tmp_path, {kept}) == [left_over]


def test_nothing_is_stale_when_every_file_is_rendered(tmp_path):
    kept = tmp_path / "a_permit.cedar"
    kept.write_text("x")
    assert stale_outputs(tmp_path, {kept}) == []
