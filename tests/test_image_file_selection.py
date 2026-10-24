import re
from types import SimpleNamespace

import pytest

from dioptas_batch_gui.file_watcher import FileWatcher, LambdaFileHandler
from dioptas_batch_gui.supported_formats import (
    DIFFRACTION_IMAGE_EXTENSIONS,
    has_hdf5_extension,
    has_supported_image_extension,
    image_file_regex,
    qt_image_file_filter,
)
from test_batch_processor_metadata import _processor


def test_only_listed_extensions_are_selected():
    assert set(DIFFRACTION_IMAGE_EXTENSIONS) == {
        ".tif", ".tiff", ".edf", ".cbf", ".h5", ".hdf", ".hdf5", ".nxs",
        ".img", ".sfrm", ".dm3", ".xml", ".kccd", ".msk",
        ".spr", ".mccd", ".mar3450", ".pnm",
    }
    pattern = re.compile(image_file_regex(), re.IGNORECASE)
    for extension in DIFFRACTION_IMAGE_EXTENSIONS:
        assert has_supported_image_extension(f"scan_0001{extension}")
        assert pattern.match(f"scan_0001{extension}")
        assert f"*{extension}" in qt_image_file_filter()

    for name in (
        "scan_0001.int.cake.npy",
        "scan_0001.tth.cake.npy",
        "scan_0001.azi.cake.npy",
        "SCAN_0001.INT.CAKE.NPY",
        "raw_image.npy",
        "raw_image.npz",
        "scan_0001.kcd",
        "scan_0001.png",
    ):
        assert not has_supported_image_extension(name)
        assert not pattern.match(name)

    assert "All Files" not in qt_image_file_filter()
    assert has_hdf5_extension("scan_0001.h5")
    assert has_hdf5_extension("scan_0001.hdf")


def test_watcher_ignores_generated_cake_events(tmp_path):
    handler = LambdaFileHandler(file_queue=None)
    source = tmp_path / "scan_0001.h5"
    cake = tmp_path / "scan_0001.int.cake.npy"
    source.touch()
    cake.touch()

    for event_method in (handler.on_created, handler.on_modified):
        event_method(SimpleNamespace(is_directory=False, src_path=str(cake)))
    handler.on_moved(SimpleNamespace(is_directory=False, dest_path=str(cake)))

    assert handler.pending_files == {}
    handler.on_created(SimpleNamespace(is_directory=False, src_path=str(source)))
    assert str(source) in handler.pending_files


def test_watcher_tracks_only_listed_extensions(tmp_path):
    handler = LambdaFileHandler(file_queue=None)
    accepted = [tmp_path / f"scan_0001{extension}" for extension in DIFFRACTION_IMAGE_EXTENSIONS]
    rejected = [
        tmp_path / name
        for name in ("scan_0001.npy", "scan_0001.npz", "scan_0001.png")
    ]

    for path in accepted + rejected:
        path.touch()
        handler.on_created(SimpleNamespace(is_directory=False, src_path=str(path)))

    assert set(handler.pending_files) == {str(path) for path in accepted}


def test_watcher_scans_and_observes_only_root_files(tmp_path, monkeypatch):
    root_image = tmp_path / "scan_0001.h5"
    nested_dir = tmp_path / "processed"
    nested_dir.mkdir()
    nested_image = nested_dir / "scan_0002.h5"
    cake = tmp_path / "scan_0001.int.cake.npy"
    excluded = tmp_path / "scan_0001.png"
    for path in (root_image, nested_image, cake, excluded):
        path.touch()

    class FakeObserver:
        def schedule(self, _handler, path, recursive):
            self.path = path
            self.recursive = recursive

        def start(self):
            pass

    monkeypatch.setattr("dioptas_batch_gui.file_watcher.Observer", FakeObserver)
    watcher = FileWatcher(str(tmp_path))

    assert watcher.get_existing_files() == [str(root_image)]
    watcher.start()
    assert watcher.observer.path == str(tmp_path)
    assert watcher.observer.recursive is False


def test_processor_groups_only_source_images(tmp_path, monkeypatch):
    processor = _processor(tmp_path, monkeypatch)
    source = tmp_path / "scan_0001.h5"
    cake = tmp_path / "scan_0001.int.cake.npy"
    source.touch()
    cake.touch()

    assert processor.group_lambda_files([str(source), str(cake)]) == [[str(source)]]
    with pytest.raises(ValueError, match="supported diffraction image"):
        processor.process_file_set([str(cake)])
