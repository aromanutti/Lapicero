import json

import pytest

from lapicero.model import Note, NoteFormatError, PlacedImage, Stroke


def test_save_reopen_and_path_association(tmp_path):
    note = Note()
    note.add_stroke(Stroke(((1, 2), (20, 30)), "#123abc", 4))
    assert note.dirty
    path = tmp_path / "first.json"
    note.save(path)
    assert note.path == path
    assert not note.dirty
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == 1
    reopened = Note.load(path)
    assert reopened.path == path
    assert reopened.strokes == note.strokes
    assert not reopened.dirty
    reopened.add_stroke(Stroke(((4, 5),)))
    reopened.save()
    assert len(Note.load(path).strokes) == 2


def test_undo_redo_erase_whole_stroke_and_saved_state(tmp_path):
    note = Note()
    a = Stroke(((0, 0), (100, 0)))
    b = Stroke(((0, 50),))
    note.add_stroke(a)
    note.save(tmp_path / "note.json")
    note.add_stroke(b)
    assert note.erase_at(50, 4, radius=3)
    assert note.strokes == [b]
    assert note.undo() and note.strokes == [a, b]
    assert note.undo() and note.strokes == [a] and not note.dirty
    assert note.redo() and note.strokes == [a, b]
    assert note.redo() and note.strokes == [b]
    assert not note.redo()
    note.undo()
    note.add_stroke(Stroke(((12, 15),)))
    assert not note.redo()
    assert not note.erase_at(200, 200)


def test_eraser_drag_is_one_history_entry_with_live_changes_and_dirty_state(tmp_path):
    note = Note()
    first = Stroke(((0, 0),))
    second = Stroke(((60, 0),))
    note.add_stroke(first)
    note.add_stroke(second)
    note.save(tmp_path / "note.json")

    note.begin_erase()
    assert note.erase_at(0, 0)
    assert note.strokes == [second] and note.dirty
    assert not note.erase_at(30, 30)
    assert note.erase_at(60, 0)
    assert not note.strokes
    note.end_erase()

    assert note.undo() and note.strokes == [first, second] and not note.dirty
    assert note.redo() and not note.strokes and note.dirty
    assert note.undo() and not note.dirty
    assert not note.erase_at(200, 200)
    assert note.redo() and not note.strokes


def test_predicate_erase_groups_history_and_preserves_no_op_redo():
    first = Stroke(((0, 0),))
    second = Stroke(((60, 0),))
    note = Note(strokes=[first, second])
    note.begin_erase()
    assert note.erase_where(lambda stroke: stroke is first)
    assert note.strokes == [second]
    assert note.erase_where(lambda stroke: stroke is second)
    note.end_erase()
    assert note.undo() and note.strokes == [first, second]
    assert not note.undo()
    note.begin_erase()
    assert not note.erase_where(lambda stroke: False)
    note.end_erase()
    assert note.redo() and note.strokes == []


def test_no_op_eraser_drag_does_not_add_history_or_clear_redo():
    note = Note()
    stroke = Stroke(((0, 0),))
    note.add_stroke(stroke)
    assert note.undo()
    note.begin_erase()
    assert not note.erase_at(100, 100)
    note.end_erase()
    assert note.redo() and note.strokes == [stroke]
    note.begin_erase()
    assert note.erase_at(0, 0)
    note.end_erase()
    assert note.undo() and note.strokes == [stroke]
    note.begin_erase()
    assert note.erase_at(0, 0)
    note.end_erase()
    assert not note.redo()  # A changed drag invalidates the redo branch.


@pytest.mark.parametrize("payload", [
    "not json", "[]", '{"version":2,"strokes":[]}',
    '{"version":true,"strokes":[]}', '{"version":1,"strokes":{}}',
    '{"version":1,"strokes":[{"points":[],"color":"#000000","width":3}]}',
    '{"version":1,"strokes":[{"points":[[NaN,0]],"color":"#000000","width":3}]}',
    '{"version":1,"strokes":[{"points":[[1,2]],"color":"red","width":3}]}',
    '{"version":1,"strokes":[{"points":[[1,2]],"color":"#000000","width":0}]}',
    '{"version":1,"strokes":[],"extra":1}',
])
def test_reject_malformed_notes(tmp_path, payload):
    path = tmp_path / "bad.json"
    path.write_text(payload, encoding="utf-8")
    with pytest.raises(NoteFormatError):
        Note.load(path)


def test_failed_atomic_replace_preserves_old_content_and_document_state(tmp_path, monkeypatch):
    path = tmp_path / "note.json"
    note = Note()
    note.add_stroke(Stroke(((1, 2),)))
    note.save(path)
    old_content = path.read_bytes()
    note.add_stroke(Stroke(((3, 4),)))

    def fail_replace(source, target):
        assert target == path
        assert source.exists()
        raise OSError("disk unavailable")

    monkeypatch.setattr("lapicero.model.os.replace", fail_replace)
    with pytest.raises(OSError, match="disk unavailable"):
        note.save(path)
    assert path.read_bytes() == old_content
    assert note.path == path and note.dirty
    assert list(tmp_path.iterdir()) == [path]


def test_failed_save_as_does_not_claim_new_path(tmp_path, monkeypatch):
    note = Note()
    note.add_stroke(Stroke(((1, 2),)))
    existing = tmp_path / "existing.json"
    existing.write_text("original", encoding="utf-8")
    monkeypatch.setattr("lapicero.model.os.replace", lambda *_: (_ for _ in ()).throw(OSError("failed")))
    with pytest.raises(OSError):
        note.save(existing)
    assert existing.read_text(encoding="utf-8") == "original"
    assert note.path is None and note.dirty


def test_translucent_color_accepted_and_bad_alpha_rejected():
    assert Stroke(((0, 0),), "#ffe60080", 12).to_data()["color"] == "#ffe60080"
    for color in ("#ffe600zz", "#ffe6008", "#ffe6008000"):
        with pytest.raises(NoteFormatError):
            Stroke(((0, 0),), color, 3)


def test_replace_is_one_undo_step_and_noop_preserves_redo():
    note = Note()
    first = Stroke(((0, 0), (10, 0)))
    note.add_stroke(first)
    moved = Stroke(((5, 5), (15, 5)))
    assert note.replace([moved])
    assert note.strokes == [moved]
    assert note.undo() and note.strokes == [first]
    assert note.redo() and note.strokes == [moved]
    note.undo()
    assert not note.replace([first])
    assert note.redo()


KEY = "a" * 64 + ".png"


def test_placed_image_validation():
    image = PlacedImage(KEY, 1, 2, 30, 40)
    assert image.to_data() == {"key": KEY, "x": 1.0, "y": 2.0, "width": 30.0, "height": 40.0}
    for args in (("../evil.png", 0, 0, 1, 1), ("A" * 64 + ".png", 0, 0, 1, 1), (KEY, 0, 0, 0, 1),
                 (KEY, float("nan"), 0, 1, 1), (KEY, 0, 0, 1, -2)):
        with pytest.raises(NoteFormatError):
            PlacedImage(*args)


def test_images_share_undo_history_and_eraser_ignores_them():
    note = Note()
    stroke = Stroke(((10, 10), (20, 20)))
    image = PlacedImage(KEY, 0, 0, 100, 100)
    note.add_stroke(stroke)
    assert note.add_image(image) and note.images == [image] and note.dirty
    moved = PlacedImage(KEY, 50, 50, 100, 100)
    assert note.replace([stroke], [moved]) and note.images == [moved]
    assert note.erase_at(15, 15) and note.strokes == [] and note.images == [moved]
    assert note.undo() and note.strokes == [stroke] and note.images == [moved]
    assert note.undo() and note.images == [image]
    assert note.undo() and note.images == []
    assert note.redo() and note.images == [image]


def test_placed_image_angle_is_normalized_and_validated():
    assert PlacedImage(KEY, 0, 0, 1, 1, 270).angle == -90
    assert PlacedImage(KEY, 0, 0, 1, 1, 90).to_data()["angle"] == 90
    with pytest.raises(NoteFormatError):
        PlacedImage(KEY, 0, 0, 1, 1, float("inf"))
