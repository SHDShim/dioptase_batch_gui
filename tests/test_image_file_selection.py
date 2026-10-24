from types import SimpleNamespace

import pytest

from dioptas_batch_gui.file_watcher import FileWatcher, LambdaFileHandler
from dioptas_batch_gui.supported_formats import has_supported_image_extension
from test_batch_processor_metadata import _processor


def test_generated_cake_arrays_are_not_source_images():
    for name in (
        "scan_0001.int.cake.npy",
        "scan_0001.tth.cake.npy",
        "scan_0001.azi.cake.npy",
        "SCAN_0001.INT.CAKE.NPY",
    ):
        assert not has_supported_image_extension(name)

    for name in ("scan_0001.h5", "scan_0001.nxs", "scan_0001.tiff", "raw_image.npy"):
        assert has_supported_image_extension(name)


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


def test_watcher_scans_and_observes_only_root_files(tmp_path, monkeypatch):
    root_image = tmp_path / "scan_0001.h5"
    nested_dir = tmp_path / "processed"
    nested_dir.mkdir()
    nested_image = nested_dir / "scan_0002.h5"
    cake = tmp_path / "scan_0001.int.cake.npy"
    for path in (root_image, nested_image, cake):
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
