import json

import pytest

from lapicero.library import Library, LibraryFormatError, PAGE_HEIGHT, PAGE_WIDTH, IMPORT_MARGIN
from lapicero.model import Note, PlacedImage, Stroke


def make_page():
    library = Library()
    subject = library.create_subject("Physics")
    section = library.create_section(subject.id, "Dynamics")
    page = library.create_page(section.id, "Page 1")
    return library, subject, section, page


def test_order_ids_lookups_rename_and_validation():
    library, subject, section, page = make_page()
    other = library.create_subject("Calculus")
    next_section = library.create_section(subject.id, "Statics")
    next_page = library.create_page(section.id, "Page 2")
    assert [s.name for s in library.subjects] == ["Physics", "Calculus"]
    assert [s.name for s in subject.sections] == ["Dynamics", "Statics"]
    assert [p.name for p in section.pages] == ["Page 1", "Page 2"]
    assert len({subject.id, other.id, section.id, next_section.id, page.id, next_page.id}) == 6
    assert library.subject(subject.id) is subject
    assert library.section(section.id) is section
    assert library.page(page.id) is page
    library.rename_subject(subject.id, " Mechanics ")
    library.rename_section(section.id, "Motion")
    library.rename_page(page.id, "Sheet 1")
    assert (subject.name, section.name, page.name) == ("Mechanics", "Motion", "Sheet 1")
    for action in (lambda: library.create_subject(" \t "),
                   lambda: library.create_section(subject.id, ""),
                   lambda: library.create_page(section.id, None),
                   lambda: library.rename_subject(subject.id, ""),
                   lambda: library.rename_section(section.id, 14),
                   lambda: library.rename_page(page.id, "  ")):
        with pytest.raises(ValueError):
            action()
    with pytest.raises(KeyError):
        library.create_page("missing", "Page")
    assert len(section.pages) == 2 and page.name == "Sheet 1"


def test_page_notes_are_independent_and_saved_with_hierarchy(tmp_path):
    library, subject, section, first = make_page()
    second = library.create_page(section.id, "Page 2")
    ink = Stroke(((10, 20), (100, 110)), "#abcdef", 5)
    first.note.add_stroke(ink)
    assert second.note.strokes == [] and library.dirty
    path = tmp_path / "library.json"
    library.save(path)
    assert not library.dirty and not first.note.dirty and library.path == path
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == 1
    reopened = Library.load(path)
    assert not reopened.dirty
    loaded_subject = reopened.subject(subject.id)
    loaded_section = reopened.section(section.id)
    assert loaded_subject.sections[0] is loaded_section
    assert [p.id for p in loaded_section.pages] == [first.id, second.id]
    assert reopened.page(first.id).note.strokes == [ink]
    assert reopened.page(second.id).note.strokes == []
    reopened.page(second.id).note.add_stroke(Stroke(((50, 60),)))
    assert reopened.dirty and reopened.page(second.id).note.dirty
    reopened.save()
    assert not reopened.dirty
    assert Library.load(path).page(second.id).note.strokes == [Stroke(((50, 60),))]
    assert Library.load(path).page(first.id).note.strokes == [ink]
    assert PAGE_WIDTH / PAGE_HEIGHT == pytest.approx(210 / 297, abs=.002)


@pytest.mark.parametrize("payload", [
    "not json", "[]", '{"version":true,"subjects":[]}',
    '{"version":2,"subjects":[]}', '{"version":1,"subjects":{}}',
    '{"version":1,"subjects":[],"extra":0}',
    '{"version":1,"subjects":[{"id":"s","name":" ","sections":[]}]}',
    '{"version":1,"subjects":[{"id":"s","name":" Trim ","sections":[]}]}',
    '{"version":1,"subjects":[{"id":"s","name":"OK","sections":{} }]}',
    '{"version":1,"subjects":[{"id":"s","name":"OK","sections":[]},'
    '{"id":"s","name":"Duplicate","sections":[]}]}',
    '{"version":1,"subjects":[{"id":"s","name":"OK","sections":['
    '{"id":"s","name":"Duplicate across levels","pages":[]}]}]}',
    '{"version":1,"subjects":[{"id":"s","name":"OK","sections":['
    '{"id":"t","name":"Section","pages":[{"id":"p","name":"Page","strokes":{}}]}]}]}',
    '{"version":1,"subjects":[{"id":"s","name":"OK","sections":['
    '{"id":"t","name":"Section","pages":[{"id":"p","name":"Page","strokes":['
    '{"points":[[NaN,0]],"color":"#000000","width":3}]}]}]}]}',
])
def test_reject_malformed_tree(tmp_path, payload):
    path = tmp_path / "invalid.json"
    path.write_text(payload, encoding="utf-8")
    with pytest.raises(LibraryFormatError):
        Library.load(path)


def test_failed_replace_keeps_previous_file_dirty_state_and_removes_temp(tmp_path, monkeypatch):
    library, _, _, page = make_page()
    path = tmp_path / "library.json"
    library.save(path)
    previous = path.read_bytes()
    page.note.add_stroke(Stroke(((1, 2),)))

    def fail_replace(source, target):
        assert target == path and source.exists()
        raise OSError("disk unavailable")

    monkeypatch.setattr("lapicero.library.os.replace", fail_replace)
    with pytest.raises(OSError, match="disk unavailable"):
        library.save()
    assert path.read_bytes() == previous
    assert library.path == path and library.dirty and page.note.dirty
    assert list(tmp_path.iterdir()) == [path]


def test_failed_save_as_keeps_path_and_dirty_state(tmp_path, monkeypatch):
    library, _, _, _ = make_page()
    target = tmp_path / "target.json"
    monkeypatch.setattr("lapicero.library.os.replace", lambda *_: (_ for _ in ()).throw(OSError("fail")))
    with pytest.raises(OSError):
        library.save(target)
    assert not target.exists() and list(tmp_path.iterdir()) == []
    assert library.path is None and library.dirty


@pytest.mark.parametrize("contents", [
    b"unrelated plain text", b'{"version":', b'{"version":2,"subjects":[]}',
    b'{"version":1,"subjects":[]}',
])
def test_new_library_refuses_any_existing_target(tmp_path, contents):
    target = tmp_path / "existing.json"
    target.write_bytes(contents)
    library, _, _, page = make_page()
    with pytest.raises(ValueError, match="overwrite"):
        library.save(target)
    assert target.read_bytes() == contents
    assert library.path is None and library.dirty and page.note.dirty is False
    assert list(tmp_path.iterdir()) == [target]


def test_loaded_and_successfully_saved_library_owns_only_its_target(tmp_path):
    path = tmp_path / "library.json"
    library, _, _, page = make_page()
    library.save(path)
    page.note.add_stroke(Stroke(((1, 2),)))
    library.save()
    assert not library.dirty and Library.load(path).page(page.id).note.strokes == [Stroke(((1, 2),))]
    other = Library.load(path)
    other_target = tmp_path / "other.json"
    other_target.write_bytes(path.read_bytes())
    other.create_subject("Math")
    with pytest.raises(ValueError, match="overwrite"):
        other.save(other_target)
    assert other_target.read_bytes() == path.read_bytes()
    assert other.path == path and other.dirty
    other.save()
    assert not other.dirty and Library.load(path).subjects[-1].name == "Math"


@pytest.mark.parametrize("change", [b"external text", b'{"version":1,"subjects":[]}\n'])
def test_owned_target_modified_externally_is_refused(tmp_path, change):
    path = tmp_path / "library.json"
    library, _, _, page = make_page()
    library.save(path)
    page.note.add_stroke(Stroke(((1, 2),)))
    path.write_bytes(change)
    with pytest.raises(ValueError, match="changed"):
        library.save()
    assert path.read_bytes() == change and library.path == path
    assert library.dirty and page.note.dirty
    assert list(tmp_path.iterdir()) == [path]


def test_import_legacy_copies_ink_and_preserves_original(tmp_path):
    legacy = tmp_path / "old-note.json"
    note = Note()
    stroke = Stroke(((30, 40), (150, 200)), "#123456", 4)
    note.add_stroke(stroke)
    note.save(legacy)
    before = legacy.read_bytes()
    library, _, section, previous = make_page()
    imported = library.import_legacy_note(section.id, legacy)
    assert imported.name == "old-note" and imported.id != previous.id
    assert imported.note.strokes == [stroke]
    assert imported.note.path is None
    assert previous.note.strokes == [] and section.pages == [previous, imported]
    assert legacy.read_bytes() == before
    with pytest.raises(ValueError, match="standalone"):
        library.save(legacy)
    assert legacy.read_bytes() == before and library.dirty and library.path is None
    library.save(tmp_path / "collection.json")
    assert Library.load(library.path).page(imported.id).note.strokes == [stroke]
    assert legacy.read_bytes() == before


def test_oversized_legacy_ink_scaled_uniformly_with_margin_and_no_clipping(tmp_path):
    legacy = tmp_path / "oversized.json"
    original = [Stroke(((-900, -500), (9000, 5000)), "#123abc", 12),
                Stroke(((1500, 1600),), "#abcdef", 6)]
    note = Note()
    for stroke in original:
        note.add_stroke(stroke)
    note.save(legacy)
    before = legacy.read_bytes()
    library, _, section, _ = make_page()
    imported = library.import_legacy_note(section.id, legacy, "Oversized")
    ink = imported.note.strokes
    scale = ink[0].width / original[0].width
    assert 0 < scale < 1
    assert ink[1].width == pytest.approx(original[1].width * scale)
    for source, transformed in zip(original, ink):
        assert transformed.color == source.color and len(transformed.points) == len(source.points)
        offsets = [(x2 - scale * x1, y2 - scale * y1)
                   for (x1, y1), (x2, y2) in zip(source.points, transformed.points)]
        assert all(x == pytest.approx(offsets[0][0]) and y == pytest.approx(offsets[0][1])
                   for x, y in offsets)
        for x, y in transformed.points:
            assert IMPORT_MARGIN <= x - transformed.width / 2
            assert x + transformed.width / 2 <= PAGE_WIDTH - IMPORT_MARGIN
            assert IMPORT_MARGIN <= y - transformed.width / 2
            assert y + transformed.width / 2 <= PAGE_HEIGHT - IMPORT_MARGIN
    assert legacy.read_bytes() == before
    library.save(tmp_path / "collection.json")
    assert Library.load(library.path).page(imported.id).note.strokes == ink


def test_failed_import_does_not_create_page(tmp_path):
    library, _, section, _ = make_page()
    bad = tmp_path / "bad.json"
    bad.write_text("not json", encoding="utf-8")
    with pytest.raises(ValueError):
        library.import_legacy_note(section.id, bad)
    assert len(section.pages) == 1


def test_page_paper_defaults_persists_and_legacy_pages_load(tmp_path):
    library = Library(path=tmp_path / "library.json")
    subject = library.create_subject("Math")
    section = library.create_section(subject.id, "Algebra")
    page = library.create_page(section.id, "Grid")
    assert page.paper == "grid"
    plain = library.create_page(section.id, "Plain")
    library.set_paper(plain.id, "plain")
    assert library.dirty
    library.save()
    reopened = Library.load(library.path)
    papers = [p.paper for p in reopened.subjects[0].sections[0].pages]
    assert papers == ["grid", "plain"]
    with pytest.raises(ValueError):
        library.set_paper(page.id, "dotted")
    legacy = tmp_path / "legacy.json"
    legacy.write_text('{"version":1,"subjects":[{"id":"s","name":"S","sections":[{"id":"t","name":"T",'
                      '"pages":[{"id":"p","name":"P","strokes":[]}]}]}]}', encoding="utf-8")
    assert Library.load(legacy).page("p").paper == "plain"
    bad = tmp_path / "bad.json"
    bad.write_text('{"version":1,"subjects":[{"id":"s","name":"S","sections":[{"id":"t","name":"T",'
                   '"pages":[{"id":"p","name":"P","strokes":[],"paper":"dots"}]}]}]}', encoding="utf-8")
    with pytest.raises(LibraryFormatError):
        Library.load(bad)


def test_store_image_is_content_addressed_next_to_library(tmp_path):
    import hashlib
    library = Library(path=tmp_path / "lib" / "library.json")
    data = b"\x89PNG fake bytes"
    key = library.store_image(data)
    assert key == hashlib.sha256(data).hexdigest() + ".png"
    assert library.image_path(key) == tmp_path / "lib" / "images" / key
    assert library.image_path(key).read_bytes() == data
    assert library.store_image(data) == key
    library.image_path(key).write_bytes(b"tampered")
    with pytest.raises(ValueError):
        library.store_image(data)
    assert library.image_path(key).read_bytes() == b"tampered"
    with pytest.raises(ValueError):
        library.image_path("../library.json")


def test_page_images_persist_and_legacy_pages_have_none(tmp_path):
    library = Library(path=tmp_path / "library.json")
    subject = library.create_subject("Physics")
    section = library.create_section(subject.id, "Optics")
    page = library.create_page(section.id, "Lens")
    key = library.store_image(b"png")
    page.note.add_image(PlacedImage(key, 10, 20, 300, 200))
    assert library.dirty
    library.save()
    assert not library.dirty and not page.note.dirty
    reopened = Library.load(library.path).page(page.id).note
    assert reopened.images == [PlacedImage(key, 10, 20, 300, 200)] and not reopened.dirty
    legacy = tmp_path / "legacy.json"
    legacy.write_text('{"version":1,"subjects":[{"id":"s","name":"S","sections":[{"id":"t","name":"T",'
                      '"pages":[{"id":"p","name":"P","strokes":[]}]}]}]}', encoding="utf-8")
    assert Library.load(legacy).page("p").note.images == []
    for images in ('[{"key":"../x.png","x":0,"y":0,"width":1,"height":1}]', '{}',
                   '[{"key":"%s","x":0,"y":0,"width":1}]' % key):
        bad = tmp_path / "bad.json"
        bad.write_text('{"version":1,"subjects":[{"id":"s","name":"S","sections":[{"id":"t","name":"T",'
                       '"pages":[{"id":"p","name":"P","strokes":[],"paper":"grid","images":%s}]}]}]}' % images,
                       encoding="utf-8")
        with pytest.raises(LibraryFormatError):
            Library.load(bad)


def test_picture_angle_persists_and_is_optional(tmp_path):
    library = Library(path=tmp_path / "library.json")
    subject = library.create_subject("S")
    section = library.create_section(subject.id, "T")
    page = library.create_page(section.id, "P")
    key = library.store_image(b"png")
    page.note.add_image(PlacedImage(key, 0, 0, 10, 20, 90))
    page.note.add_image(PlacedImage(key, 5, 5, 10, 20))
    library.save()
    raw = json.loads(library.path.read_text(encoding="utf-8"))
    entries = raw["subjects"][0]["sections"][0]["pages"][0]["images"]
    assert entries[0]["angle"] == 90 and "angle" not in entries[1]
    assert [i.angle for i in Library.load(library.path).page(page.id).note.images] == [90, 0]


def test_stroke_pressures_round_trip_and_stay_optional(tmp_path):
    library = Library(path=tmp_path / "library.json")
    subject = library.create_subject("S")
    section = library.create_section(subject.id, "T")
    page = library.create_page(section.id, "P")
    page.note.add_stroke(Stroke(((0, 0), (5, 5)), "#202020", 3, (0.25, 0.75)))
    page.note.add_stroke(Stroke(((9, 9), (5, 5))))
    library.save()
    raw = json.loads(library.path.read_text(encoding="utf-8"))
    entries = raw["subjects"][0]["sections"][0]["pages"][0]["strokes"]
    assert entries[0]["pressures"] == [0.25, 0.75] and "pressures" not in entries[1]
    strokes = Library.load(library.path).page(page.id).note.strokes
    assert [s.pressures for s in strokes] == [(0.25, 0.75), None]
    bad = tmp_path / "bad.json"
    bad.write_text('{"version":1,"subjects":[{"id":"s","name":"S","sections":[{"id":"t","name":"T",'
                   '"pages":[{"id":"p","name":"P","strokes":[{"points":[[0,0],[1,1]],"color":"#000000",'
                   '"width":3,"pressures":[0.5]}]}]}]}]}', encoding="utf-8")
    with pytest.raises(LibraryFormatError):
        Library.load(bad)


def test_nested_sections_lookup_save_and_reload(tmp_path):
    library, subject, section, page = make_page()
    child = library.create_subsection(section.id, "Kinematics")
    grandchild = library.create_subsection(child.id, "Projectiles")
    deep_page = library.create_page(grandchild.id, "Deep")
    assert section.sections == [child] and child.sections == [grandchild]
    assert library.section(grandchild.id) is grandchild
    assert library.page(deep_page.id) is deep_page
    library.rename_section(grandchild.id, "Ballistics")
    library.save(tmp_path / "library.json")
    reopened = Library.load(tmp_path / "library.json")
    loaded = reopened.subjects[0].sections[0].sections[0].sections[0]
    assert (loaded.id, loaded.name, loaded.pages[0].id) == (grandchild.id, "Ballistics", deep_page.id)
    assert not reopened.dirty
    with pytest.raises(KeyError):
        library.create_subsection("missing", "X")


def test_sections_without_children_keep_the_previous_file_format(tmp_path):
    library, subject, section, page = make_page()
    library.save(tmp_path / "library.json")
    raw = json.loads((tmp_path / "library.json").read_text())
    assert set(raw["subjects"][0]["sections"][0]) == {"id", "name", "pages"}
    bad = tmp_path / "bad.json"
    bad.write_text('{"version":1,"subjects":[{"id":"s","name":"S","sections":[{"id":"t","name":"T",'
                   '"pages":[],"sections":{}}]}]}')
    with pytest.raises(LibraryFormatError):
        Library.load(bad)


def test_delete_section_removes_its_pages_and_subsections():
    library, subject, section, page = make_page()
    sibling = library.create_section(subject.id, "Statics")
    child = library.create_subsection(section.id, "Kinematics")
    nested_page = library.create_page(child.id, "Nested")
    removed = library.delete_section(child.id)
    assert removed is child and section.sections == []
    with pytest.raises(KeyError):
        library.page(nested_page.id)
    library.delete_section(section.id)
    assert subject.sections == [sibling]
    with pytest.raises(KeyError):
        library.page(page.id)
    with pytest.raises(KeyError):
        library.delete_section(section.id)


def test_delete_subject_removes_it_with_everything_inside():
    library = Library()
    keep = library.create_subject("Keep")
    subject = library.create_subject("Physics")
    section = library.create_section(subject.id, "Mechanics")
    library.create_page(section.id, "Week 1")
    assert library.delete_subject(subject.id) is subject
    assert library.subjects == [keep]
    with pytest.raises(KeyError):
        library.section(section.id)
    with pytest.raises(KeyError):
        library.delete_subject(subject.id)
