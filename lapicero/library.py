"""GUI-independent Subjects -> Sections -> Pages library.

Sections nest: a section may hold subsections as well as pages.

Pages are unbounded canvases in logical units; ink is stored as original point
geometry. PAGE_WIDTH/PAGE_HEIGHT (approximately A4 at 96 dpi) only frame the
area that imported standalone notes are fitted into.
"""

from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import tempfile
from uuid import uuid4

from .model import IMAGE_KEY, Note, NoteFormatError, PlacedImage, Stroke


PAGE_WIDTH = 794.0
PAGE_HEIGHT = 1123.0
IMPORT_MARGIN = 32.0
LIBRARY_VERSION = 1
PAPERS = ("plain", "grid")
# Pasted pictures live beside the library as content-addressed PNG files.
IMAGE_DIR = "images"


class LibraryFormatError(ValueError):
    """The file does not describe a supported library tree."""


@dataclass
class Page:
    id: str
    name: str
    note: Note = field(default_factory=Note)
    paper: str = "grid"


@dataclass
class Section:
    id: str
    name: str
    pages: list[Page] = field(default_factory=list)
    sections: list["Section"] = field(default_factory=list)


@dataclass
class Subject:
    id: str
    name: str
    sections: list[Section] = field(default_factory=list)


def _name(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Name must be non-empty text")
    return value.strip()


def _fields(value, keys):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise LibraryFormatError("Invalid library structure")


def _identity(data, seen):
    identifier = data["id"]
    if not isinstance(identifier, str) or not identifier or identifier in seen:
        raise LibraryFormatError("Invalid or duplicate library ID")
    seen.add(identifier)
    try:
        name = _name(data["name"])
    except ValueError as exc:
        raise LibraryFormatError(str(exc)) from exc
    if name != data["name"]:
        raise LibraryFormatError("Names must not have surrounding whitespace")
    return identifier, name


def _strokes(entries):
    if not isinstance(entries, list):
        raise LibraryFormatError("Strokes must be a list")
    strokes = []
    for entry in entries:
        if isinstance(entry, dict) and "pressures" not in entry:
            entry = {**entry, "pressures": None}
        _fields(entry, ("points", "color", "width", "pressures"))
        if not isinstance(entry["points"], list) or entry["pressures"] is not None and not isinstance(
                entry["pressures"], list):
            raise LibraryFormatError("Stroke points and pressures must be lists")
        try:
            strokes.append(Stroke(entry["points"], entry["color"], entry["width"], entry["pressures"]))
        except NoteFormatError as exc:
            raise LibraryFormatError(str(exc)) from exc
    return strokes


def _images(entries):
    if not isinstance(entries, list):
        raise LibraryFormatError("Images must be a list")
    images = []
    for entry in entries:
        if isinstance(entry, dict) and "angle" not in entry:
            entry = {**entry, "angle": 0}
        _fields(entry, ("key", "x", "y", "width", "height", "angle"))
        try:
            images.append(PlacedImage(entry["key"], entry["x"], entry["y"], entry["width"],
                                      entry["height"], entry["angle"]))
        except NoteFormatError as exc:
            raise LibraryFormatError(str(exc)) from exc
    return images


def _section(child, seen):
    # Sections saved before nesting existed have no "sections" key.
    if isinstance(child, dict) and "sections" not in child:
        child = {**child, "sections": []}
    _fields(child, ("id", "name", "pages", "sections"))
    cid, cname = _identity(child, seen)
    if not isinstance(child["pages"], list):
        raise LibraryFormatError("Pages must be a list")
    if not isinstance(child["sections"], list):
        raise LibraryFormatError("Sections must be a list")
    pages = []
    for leaf in child["pages"]:
        # Pages saved before paper choice existed were plain white.
        if isinstance(leaf, dict) and "paper" not in leaf:
            leaf = {**leaf, "paper": "plain"}
        if isinstance(leaf, dict) and "images" not in leaf:
            leaf = {**leaf, "images": []}
        _fields(leaf, ("id", "name", "strokes", "paper", "images"))
        if leaf["paper"] not in PAPERS:
            raise LibraryFormatError("Unknown paper type")
        pid, pname = _identity(leaf, seen)
        strokes = _strokes(leaf["strokes"])
        images = _images(leaf["images"])
        note = Note(strokes=strokes, images=images)
        note.mark_saved()
        pages.append(Page(pid, pname, note, leaf["paper"]))
    return Section(cid, cname, pages, [_section(nested, seen) for nested in child["sections"]])


def _section_data(section):
    data = {"id": section.id, "name": section.name, "pages": [
        {"id": page.id, "name": page.name,
         "strokes": [stroke.to_data() for stroke in page.note.strokes],
         "paper": page.paper,
         "images": [image.to_data() for image in page.note.images]}
        for page in section.pages]}
    # Only write the key when needed, so libraries without nesting keep their old format.
    if section.sections:
        data["sections"] = [_section_data(child) for child in section.sections]
    return data


def _walk(sections):
    """Yield every section in the tree, parents before their subsections."""
    for section in sections:
        yield section
        yield from _walk(section.sections)


def _parse(data):
    _fields(data, ("version", "subjects"))
    if type(data["version"]) is not int or data["version"] != LIBRARY_VERSION:
        raise LibraryFormatError("Unsupported library version")
    if not isinstance(data["subjects"], list):
        raise LibraryFormatError("Subjects must be a list")
    seen = set()
    subjects = []
    for item in data["subjects"]:
        _fields(item, ("id", "name", "sections"))
        sid, name = _identity(item, seen)
        if not isinstance(item["sections"], list):
            raise LibraryFormatError("Sections must be a list")
        sections = [_section(child, seen) for child in item["sections"]]
        subjects.append(Subject(sid, name, sections))
    return subjects


class Library:
    """Ordered local hierarchy; edits to each page's Note remain page-local.

    Save writes a complete snapshot atomically. No page Note has a standalone
    path: persist edits with Library.save, not Note.save.
    """

    def __init__(self, subjects=None, path=None):
        self.subjects = list(subjects) if subjects is not None else []
        self.path = Path(path) if path is not None else None
        self._saved = None if subjects is None else self._data()
        self._owned_path = None
        self._owned_bytes = None

    def _data(self):
        return {"version": LIBRARY_VERSION, "subjects": [
            {"id": subject.id, "name": subject.name,
             "sections": [_section_data(section) for section in subject.sections]}
            for subject in self.subjects]}

    @property
    def dirty(self):
        return self._data() != (self._saved if self._saved is not None else
                                {"version": LIBRARY_VERSION, "subjects": []})

    def subject(self, identifier):
        for subject in self.subjects:
            if subject.id == identifier:
                return subject
        raise KeyError(identifier)

    def all_sections(self):
        """Every section at any depth, in tree order."""
        for subject in self.subjects:
            yield from _walk(subject.sections)

    def section(self, identifier):
        for section in self.all_sections():
            if section.id == identifier:
                return section
        raise KeyError(identifier)

    def page(self, identifier):
        for section in self.all_sections():
            for page in section.pages:
                if page.id == identifier:
                    return page
        raise KeyError(identifier)

    def create_subject(self, name):
        subject = Subject(uuid4().hex, _name(name))
        self.subjects.append(subject)
        return subject

    def delete_subject(self, identifier):
        """Remove a subject with all of its sections and pages; return it."""
        subject = self.subject(identifier)
        self.subjects.remove(subject)
        return subject

    def create_section(self, subject_id, name):
        subject = self.subject(subject_id)
        section = Section(uuid4().hex, _name(name))
        subject.sections.append(section)
        return section

    def create_subsection(self, section_id, name):
        parent = self.section(section_id)
        section = Section(uuid4().hex, _name(name))
        parent.sections.append(section)
        return section

    def delete_section(self, identifier):
        """Remove a section with all of its pages and subsections; return it."""
        containers = [subject.sections for subject in self.subjects]
        containers += [section.sections for section in self.all_sections()]
        for container in containers:
            for index, section in enumerate(container):
                if section.id == identifier:
                    return container.pop(index)
        raise KeyError(identifier)

    def create_page(self, section_id, name):
        section = self.section(section_id)
        page = Page(uuid4().hex, _name(name))
        section.pages.append(page)
        return page

    def rename_subject(self, identifier, name):
        self.subject(identifier).name = _name(name)

    def rename_section(self, identifier, name):
        self.section(identifier).name = _name(name)

    def rename_page(self, identifier, name):
        self.page(identifier).name = _name(name)

    def image_path(self, key):
        if not isinstance(key, str) or not IMAGE_KEY.fullmatch(key):
            raise ValueError("Invalid image key")
        if self.path is None:
            raise ValueError("Choose a library path first")
        return self.path.parent / IMAGE_DIR / key

    def store_image(self, data):
        """Write PNG bytes once under their SHA-256 name and return that key.

        An existing file with the same name must hold the same bytes; anything
        else is left untouched and refused.
        """
        key = hashlib.sha256(data).hexdigest() + ".png"
        target = self.image_path(key)
        if os.path.lexists(target):
            if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() + ".png" != key:
                raise ValueError("Existing image file does not match its name")
            return key
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="wb", dir=target.parent, prefix=f".{key}.",
                                             suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return key

    def set_paper(self, identifier, paper):
        if paper not in PAPERS:
            raise ValueError(f"Paper must be one of {PAPERS}")
        self.page(identifier).paper = paper

    def import_legacy_note(self, section_id, source, name=None):
        """Copy a standalone v1 Note to a new page; never change its file.

        Ink already fitting the page stays unchanged. Otherwise, scale all
        coordinates AND widths by one factor <= 1, and center their combined
        stroke-width-inclusive bounds inside a 32-unit margin. No clipping.
        """
        section = self.section(section_id)
        source = Path(source)
        page_name = _name(source.stem if name is None else name)
        strokes = Note.load(source).strokes
        if strokes:
            left = min(x - s.width / 2 for s in strokes for x, _ in s.points)
            right = max(x + s.width / 2 for s in strokes for x, _ in s.points)
            top = min(y - s.width / 2 for s in strokes for _, y in s.points)
            bottom = max(y + s.width / 2 for s in strokes for _, y in s.points)
            if left < 0 or top < 0 or right > PAGE_WIDTH or bottom > PAGE_HEIGHT:
                scale = min(1.0, (PAGE_WIDTH - 2 * IMPORT_MARGIN) / (right - left),
                            (PAGE_HEIGHT - 2 * IMPORT_MARGIN) / (bottom - top))
                # Center the bounds, including the physical pen width.
                dx = (PAGE_WIDTH - (right - left) * scale) / 2 - left * scale
                dy = (PAGE_HEIGHT - (bottom - top) * scale) / 2 - top * scale
                strokes = [Stroke(tuple((x * scale + dx, y * scale + dy) for x, y in s.points),
                                  s.color, s.width * scale) for s in strokes]
        page = Page(uuid4().hex, page_name, Note())
        for stroke in strokes:
            page.note.add_stroke(stroke)
        section.pages.append(page)
        return page

    @classmethod
    def load(cls, path):
        path = Path(path)
        contents = path.read_bytes()
        try:
            data = json.loads(contents.decode("utf-8"))
        except (ValueError, UnicodeError) as exc:
            raise LibraryFormatError(f"Invalid library JSON: {exc}") from exc
        library = cls(_parse(data), path)
        library._owned_path = path.absolute()
        library._owned_bytes = contents
        return library

    def _validate(self):
        """Check the live tree without re-creating every stroke.

        Strokes and pictures validate themselves when constructed and are
        immutable, so only their types need checking here; this keeps the
        autosave cost low for large libraries.
        """
        seen = set()

        def identity(item):
            if not isinstance(item.id, str) or not item.id or item.id in seen:
                raise LibraryFormatError("Invalid or duplicate library ID")
            seen.add(item.id)
            if not isinstance(item.name, str) or not item.name.strip() or item.name != item.name.strip():
                raise LibraryFormatError("Names must be non-empty text without surrounding whitespace")

        for subject in self.subjects:
            identity(subject)
            for section in _walk(subject.sections):
                identity(section)
                if not isinstance(section.sections, list):
                    raise LibraryFormatError("Sections must be a list")
                for page in section.pages:
                    identity(page)
                    if page.paper not in PAPERS:
                        raise LibraryFormatError("Unknown paper type")
                    if not all(isinstance(stroke, Stroke) for stroke in page.note.strokes):
                        raise LibraryFormatError("Invalid stroke in page")
                    if not all(isinstance(image, PlacedImage) for image in page.note.images):
                        raise LibraryFormatError("Invalid image in page")

    def _check_target(self, target):
        if self._owned_path == target.absolute() and self._owned_bytes is not None:
            try:
                contents = target.read_bytes()
            except FileNotFoundError as exc:
                raise ValueError("Owned library target changed externally") from exc
            if contents != self._owned_bytes:
                raise ValueError("Owned library target changed externally")
            return
        if os.path.lexists(target):
            # Retain a specific error for standalone notes; all other existing
            # targets are equally protected, regardless of format or version.
            try:
                existing = json.loads(target.read_bytes().decode("utf-8"))
            except (ValueError, UnicodeError):
                existing = None
            if (isinstance(existing, dict) and set(existing) == {"version", "strokes"}
                    and existing["version"] == 1):
                raise ValueError("Cannot overwrite a standalone v1 note")
            raise ValueError("Cannot overwrite an unowned existing file")

    def save(self, path=None):
        target = Path(path) if path is not None else self.path
        if target is None:
            raise ValueError("Choose a library path first")
        self._validate()  # Reject invalid direct mutations before writing anything.
        data = self._data()
        contents = json.dumps(data, allow_nan=False).encode("utf-8")
        self._check_target(target)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="wb", dir=target.parent,
                                             prefix=f".{target.name}.", suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(contents)
                stream.flush()
                os.fsync(stream.fileno())
            self._check_target(target)
            os.replace(temporary, target)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        self.path = target
        self._owned_path = target.absolute()
        self._owned_bytes = contents
        self._saved = data
        for section in self.all_sections():
            for page in section.pages:
                page.note.mark_saved()
