import importlib
import json
import queue
import sys
import threading
import types
from pathlib import Path

import h5py
import numpy as np
import pytest


class _FakeSignalModel:
    def blockSignals(self, _state):
        return None


class _FakeImageModel(_FakeSignalModel):
    img_data = np.zeros((4, 4))

    def load(self, _path, _image_index):
        self.img_data = np.zeros((4, 4))


class _FakeMaskModel:
    roi = None
    roi_mask = None

    def set_dimension(self, _shape):
        return None

    def load_mask(self, _path):
        return None

    def get_mask(self):
        return None


class _FakeCalibrationModel:
    cake_img = np.ones((360, 8))
    cake_tth = np.arange(8)
    cake_azi = np.arange(360)

    def load(self, _path):
        return None

    def calculate_number_of_pattern_points(self, _shape, _dimension):
        return 8

    def integrate_2d(self, **_kwargs):
        return None


class _FakeConfiguration:
    def __init__(self):
        self.img_model = _FakeImageModel()
        self.mask_model = _FakeMaskModel()
        self.calibration_model = _FakeCalibrationModel()
        self.cake_azimuth_range = None
        self.use_mask = False
        self.auto_integrate_cake = False

    def integrate_image_1d(self):
        return None

    def save_pattern(self, path):
        Path(path).write_text("# fake pattern\n", encoding="utf-8")


class _FakeLambdaImage:
    def __init__(self, file_list):
        self.file_list = file_list

    def get_image(self, _image_index):
        return np.zeros((4, 4))


class _FakeFabioLoader:
    def __init__(self, _filename):
        raise OSError("not a real fabIO image")


def _install_dioptas_stubs(monkeypatch):
    config_module = types.ModuleType("dioptas.model.Configuration")
    config_module.Configuration = _FakeConfiguration

    loader_module = types.ModuleType("dioptas.model.loader")
    fabio_loader_module = types.SimpleNamespace(FabioLoader=_FakeFabioLoader)
    lambda_loader_module = types.SimpleNamespace(LambdaImage=_FakeLambdaImage)
    loader_module.FabioLoader = fabio_loader_module
    loader_module.LambdaLoader = lambda_loader_module

    monkeypatch.setitem(sys.modules, "dioptas", types.ModuleType("dioptas"))
    monkeypatch.setitem(sys.modules, "dioptas.model", types.ModuleType("dioptas.model"))
    monkeypatch.setitem(sys.modules, "dioptas.model.Configuration", config_module)
    monkeypatch.setitem(sys.modules, "dioptas.model.loader", loader_module)


def _batch_processor_module(monkeypatch):
    _install_dioptas_stubs(monkeypatch)
    sys.modules.pop("dioptas_batch_gui.batch_processor", None)
    return importlib.import_module("dioptas_batch_gui.batch_processor")


def _write_hdf5(path, n_images=1):
    with h5py.File(path, "w") as h5_file:
        h5_file.attrs["facility"] = "test beamline"
        entry = h5_file.create_group("entry")
        entry.attrs["NX_class"] = "NXentry"
        detector = entry.create_group("instrument/detector")
        detector.attrs["NX_class"] = "NXdetector"
        detector.create_dataset("distance", data=123.4)
        detector.create_dataset("data", data=np.zeros((n_images, 4, 4)))
        scan = entry.create_group("scan")
        scan.create_dataset("sample_x", data=np.array([1.0, 2.0]))
        scan.create_dataset("sample_y", data=np.array([3.0, 4.0]))


def _processor(tmp_path, monkeypatch, output_dir=None, overwrite=False):
    module = _batch_processor_module(monkeypatch)
    poni = tmp_path / "calibration.poni"
    poni.write_text("poni\n", encoding="utf-8")
    return module.BatchProcessor(
        calibration_file=str(poni),
        output_directory=str(output_dir or tmp_path / "processed-2026-06-06"),
        overwrite=overwrite,
    )


def test_default_processed_output_directory_is_created(tmp_path, monkeypatch):
    output_dir = tmp_path / "processed-2026-06-06"
    assert not output_dir.exists()

    _processor(tmp_path, monkeypatch, output_dir=output_dir)

    assert output_dir.is_dir()


def test_user_selected_output_directory_is_used(tmp_path, monkeypatch):
    selected_output = tmp_path / "processed-existing"
    selected_output.mkdir()
    source = tmp_path / "scan_0001.h5"
    _write_hdf5(source)

    processor = _processor(tmp_path, monkeypatch, output_dir=selected_output)
    path, action = processor.export_metadata_for_image([str(source)], 0, "scan_0001")

    assert action == "created"
    assert path.parent == selected_output / "scan_0001-param"
    assert path.exists()


def test_metadata_file_created_when_param_folder_is_missing(tmp_path, monkeypatch):
    source = tmp_path / "scan_0001.h5"
    _write_hdf5(source)
    processor = _processor(tmp_path, monkeypatch)

    path, action = processor.export_metadata_for_image([str(source)], 0, "scan_0001")

    assert action == "created"
    assert path.name == "scan_0001.metadata.v1.json"
    assert path.parent.is_dir()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["schema_version"] == "1.0"
    assert data["source_files"][0]["hdf5"]["nodes"]["/entry"]["NX_class"] == "NXentry"


def test_generic_image_metadata_created_for_non_hdf5_source(tmp_path, monkeypatch):
    source = tmp_path / "scan_0001.tiff"
    source.write_bytes(b"fake-tiff")
    processor = _processor(tmp_path, monkeypatch)

    path, action = processor.export_metadata_for_image([str(source)], 0, "scan_0001")

    assert action == "created"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["source_files"][0]["name"] == "scan_0001.tiff"
    assert data["source_files"][0]["format"]["metadata_detail"] == "generic_file"
    assert "hdf5" not in data["source_files"][0]


def test_non_hdf5_image_count_defaults_to_one_when_fabio_cannot_read(tmp_path, monkeypatch):
    source = tmp_path / "scan_0001.tiff"
    source.write_bytes(b"fake-tiff")
    processor = _processor(tmp_path, monkeypatch)

    assert processor.get_image_count([str(source)]) == 1


def test_existing_metadata_is_left_untouched_when_complete(tmp_path, monkeypatch):
    source = tmp_path / "scan_0001.h5"
    _write_hdf5(source)
    processor = _processor(tmp_path, monkeypatch)

    path, _action = processor.export_metadata_for_image([str(source)], 0, "scan_0001")
    before = path.read_text(encoding="utf-8")
    path, action = processor.export_metadata_for_image([str(source)], 0, "scan_0001")

    assert action == "unchanged"
    assert path.read_text(encoding="utf-8") == before


def test_partial_metadata_is_additively_updated(tmp_path, monkeypatch):
    source = tmp_path / "scan_0001.h5"
    _write_hdf5(source)
    processor = _processor(tmp_path, monkeypatch)
    metadata_path = processor._build_output_paths("scan_0001")["metadata_path"]
    metadata_path.parent.mkdir(parents=True)
    metadata_path.write_text(
        json.dumps({"schema_version": "1.0", "user_note": "preserve"}),
        encoding="utf-8",
    )

    path, action = processor.export_metadata_for_image([str(source)], 0, "scan_0001")

    data = json.loads(path.read_text(encoding="utf-8"))
    assert action == "updated"
    assert data["user_note"] == "preserve"
    assert "source_files" in data


def test_incompatible_metadata_writes_versioned_file(tmp_path, monkeypatch):
    source = tmp_path / "scan_0001.h5"
    _write_hdf5(source)
    processor = _processor(tmp_path, monkeypatch)
    metadata_path = processor._build_output_paths("scan_0001")["metadata_path"]
    metadata_path.parent.mkdir(parents=True)
    metadata_path.write_text(
        json.dumps({"schema_version": "legacy", "legacy": True}),
        encoding="utf-8",
    )

    path, action = processor.export_metadata_for_image([str(source)], 0, "scan_0001")

    assert action == "versioned"
    assert path != metadata_path
    assert json.loads(metadata_path.read_text(encoding="utf-8"))["legacy"] is True


def test_existing_processed_outputs_receive_metadata_without_overwriting(tmp_path, monkeypatch):
    source = tmp_path / "scan_0001.h5"
    _write_hdf5(source)
    output_dir = tmp_path / "processed-existing"
    param_dir = output_dir / "scan_0001-param"
    param_dir.mkdir(parents=True)
    chi = output_dir / "scan_0001.chi"
    cake = param_dir / "scan_0001.int.cake.npy"
    tth = param_dir / "scan_0001.tth.cake.npy"
    azi = param_dir / "scan_0001.azi.cake.npy"
    chi.write_text("existing chi\n", encoding="utf-8")
    np.save(cake, np.ones((360, 8)))
    np.save(tth, np.arange(8))
    np.save(azi, np.arange(360))
    before = chi.read_text(encoding="utf-8")

    processor = _processor(tmp_path, monkeypatch, output_dir=output_dir)
    result = processor.process_lambda_image([str(source)], 0, "scan_0001")

    assert result["success"] is True
    assert result["skipped"] is True
    assert result["metadata_action"] == "created"
    assert chi.read_text(encoding="utf-8") == before
    assert (param_dir / "scan_0001.metadata.v1.json").exists()


def test_existing_processed_outputs_skip_unchecked_metadata(tmp_path, monkeypatch):
    source = tmp_path / "scan_0001.h5"
    _write_hdf5(source)
    output_dir = tmp_path / "processed-existing"
    param_dir = output_dir / "scan_0001-param"
    param_dir.mkdir(parents=True)
    chi = output_dir / "scan_0001.chi"
    cake = param_dir / "scan_0001.int.cake.npy"
    tth = param_dir / "scan_0001.tth.cake.npy"
    azi = param_dir / "scan_0001.azi.cake.npy"
    chi.write_text("existing chi\n", encoding="utf-8")
    np.save(cake, np.ones((360, 8)))
    np.save(tth, np.arange(8))
    np.save(azi, np.arange(360))

    processor = _processor(tmp_path, monkeypatch, output_dir=output_dir)
    result = processor.process_lambda_image(
        [str(source)],
        0,
        "scan_0001",
        export_metadata=False,
    )

    assert result["success"] is True
    assert result["skipped"] is True
    assert result["metadata_action"] is None
    assert not (param_dir / "scan_0001.metadata.v1.json").exists()


def test_no_selected_outputs_fails_explicitly(tmp_path, monkeypatch):
    source = tmp_path / "scan_0001.h5"
    _write_hdf5(source)
    processor = _processor(tmp_path, monkeypatch)

    result = processor.process_lambda_image(
        [str(source)],
        0,
        "scan_0001",
        export_chi=False,
        export_xy=False,
        export_dat=False,
        export_cake_npy=False,
        export_metadata=False,
    )

    assert result["success"] is False
    assert "No outputs selected" in result["error"]


def test_existing_wrong_resolution_cake_requires_overwrite(tmp_path, monkeypatch):
    source = tmp_path / "scan_0001.h5"
    _write_hdf5(source)
    output_dir = tmp_path / "processed-existing"
    param_dir = output_dir / "scan_0001-param"
    param_dir.mkdir(parents=True)
    np.save(param_dir / "scan_0001.int.cake.npy", np.ones((360, 7)))
    np.save(param_dir / "scan_0001.tth.cake.npy", np.arange(7))
    np.save(param_dir / "scan_0001.azi.cake.npy", np.arange(360))

    processor = _processor(tmp_path, monkeypatch, output_dir=output_dir)
    result = processor.process_lambda_image(
        [str(source)],
        0,
        "scan_0001",
        export_chi=False,
        export_cake_npy=True,
        export_metadata=False,
    )

    assert result["success"] is False
    assert "Enable overwrite" in result["error"]
    assert np.load(param_dir / "scan_0001.tth.cake.npy").shape == (7,)


def test_existing_wrong_resolution_cake_regenerates_with_overwrite(tmp_path, monkeypatch):
    source = tmp_path / "scan_0001.h5"
    _write_hdf5(source)
    output_dir = tmp_path / "processed-existing"
    param_dir = output_dir / "scan_0001-param"
    param_dir.mkdir(parents=True)
    np.save(param_dir / "scan_0001.int.cake.npy", np.ones((360, 7)))
    np.save(param_dir / "scan_0001.tth.cake.npy", np.arange(7))
    np.save(param_dir / "scan_0001.azi.cake.npy", np.arange(360))

    processor = _processor(tmp_path, monkeypatch, output_dir=output_dir, overwrite=True)
    result = processor.process_lambda_image(
        [str(source)],
        0,
        "scan_0001",
        export_chi=False,
        export_cake_npy=True,
        export_metadata=False,
    )

    assert result["success"] is True
    assert result["overwritten"] is True
    assert np.load(param_dir / "scan_0001.int.cake.npy").shape == (360, 8)
    assert np.load(param_dir / "scan_0001.tth.cake.npy").shape == (8,)


def test_process_file_set_stops_when_cancellation_is_requested(tmp_path, monkeypatch):
    source = tmp_path / "scan_0001.h5"
    _write_hdf5(source, n_images=3)
    processor = _processor(tmp_path, monkeypatch)
    processed_images = []
    continue_checks = {"count": 0}

    def fake_process_lambda_image(file_set, image_index, base_output_name, *args, **kwargs):
        processed_images.append((image_index, base_output_name))
        return {"success": True}

    def should_continue():
        continue_checks["count"] += 1
        return len(processed_images) < 1

    monkeypatch.setattr(processor, "process_lambda_image", fake_process_lambda_image)

    stats = processor.process_file_set([str(source)], should_continue=should_continue)

    assert stats["cancelled"] is True
    assert stats["processed"] == 1
    assert len(processed_images) == 1


def test_sequential_frames_reuse_dioptas_series_reader(tmp_path, monkeypatch):
    processor = _processor(tmp_path, monkeypatch)
    image_model = processor.config.img_model
    calls = []
    image_model.series_get_image = lambda index: np.full((4, 4), index)

    def load(_path, index):
        calls.append(("open", index))

    def load_series_img(position):
        calls.append(("series", position))

    monkeypatch.setattr(image_model, "load", load)
    monkeypatch.setattr(image_model, "load_series_img", load_series_img, raising=False)
    source = str(tmp_path / "map.h5")

    for index in range(3):
        processor._load_image_into_config([source], index)

    assert calls == [("open", 0), ("series", 2), ("series", 3)]


def test_metadata_source_tree_is_reused_across_snapshots(tmp_path, monkeypatch):
    source = tmp_path / "map.h5"
    _write_hdf5(source, n_images=3)
    processor = _processor(tmp_path, monkeypatch)
    original = processor._export_source_file_metadata
    calls = []

    def counted(path):
        calls.append(path)
        return original(path)

    monkeypatch.setattr(processor, "_export_source_file_metadata", counted)
    for index in range(3):
        processor.export_metadata_for_image([str(source)], index, f"map_{index:03d}")

    assert len(calls) == 1
    for index in range(3):
        metadata_path = processor._build_output_paths(f"map_{index:03d}")["metadata_path"]
        assert json.loads(metadata_path.read_text())["image_index"] == index


def test_selected_frame_indices_keep_full_file_snapshot_names(tmp_path, monkeypatch):
    source = tmp_path / "map.h5"
    _write_hdf5(source, n_images=4)
    processor = _processor(tmp_path, monkeypatch)
    names = []

    def fake_process(file_set, image_index, base_output_name, *args, **kwargs):
        names.append((image_index, base_output_name))
        return {"success": True}

    monkeypatch.setattr(processor, "process_lambda_image", fake_process)
    stats = processor.process_file_set([str(source)], image_indices=[2, 3])

    assert stats["total_images"] == 2
    assert stats["processed"] == 2
    assert names == [(2, "map_003"), (3, "map_004")]


@pytest.mark.parametrize("requested_workers", [2, 3])
def test_worker_count_is_capped_for_multi_frame_file(tmp_path, monkeypatch, requested_workers):
    source = tmp_path / "map.h5"
    _write_hdf5(source, n_images=4)
    processor = _processor(tmp_path, monkeypatch)
    module = sys.modules[processor.__class__.__module__]
    monkeypatch.setattr(module, "conservative_worker_limit", lambda: 2)
    captured = []

    def fake_parallel(file_set, n_images, options, progress_callback, estimate_callback,
                      should_continue, worker_count):
        captured.append((file_set, n_images, options["export_cake_npy"], worker_count))
        return {"total_images": n_images, "processed": n_images}

    monkeypatch.setattr(processor, "_process_file_set_parallel", fake_parallel)
    stats = processor.process_file_set(
        [str(source)], workers=requested_workers, export_cake_npy=False
    )

    assert stats["processed"] == 4
    assert captured == [([str(source)], 4, False, 2)]


@pytest.mark.parametrize(
    "cpus,memory_gib,expected",
    [(2, 32, 1), (8, 8, 1), (8, 16, 2), (12, 32, 3)],
)
def test_conservative_worker_limit_reserves_cpu_and_memory(
    monkeypatch, cpus, memory_gib, expected
):
    module = _batch_processor_module(monkeypatch)
    monkeypatch.setattr(module.os, "cpu_count", lambda: cpus)
    monkeypatch.setattr(
        module.os, "sysconf",
        lambda name: memory_gib * 1024**3 if name == "SC_PHYS_PAGES" else 1,
    )
    assert module.conservative_worker_limit() == expected


@pytest.mark.parametrize("workers,last_frame_failures", [(2, 1), (2, 2), (3, 0)])
def test_parallel_workers_cover_final_image_of_odd_length_series(
    tmp_path, monkeypatch, workers, last_frame_failures
):
    source = tmp_path / "map.h5"
    _write_hdf5(source, n_images=121)
    processor = _processor(tmp_path, monkeypatch)
    seen = []
    progress = []
    failures = {120: last_frame_failures}

    def fake_process(self, file_set, image_index, base_output_name, *args, **kwargs):
        seen.append(image_index)
        if failures.get(image_index, 0):
            failures[image_index] -= 1
            return {"success": False, "error": "transient frame error"}
        return {"success": True, "chi_file": base_output_name}

    class FakeQueue(queue.Queue):
        def close(self):
            pass

        def join_thread(self):
            pass

    class FakeProcess:
        def __init__(self, target, args):
            self.target = target
            self.args = args

        def start(self):
            self.target(*self.args)

        def is_alive(self):
            return False

        def join(self, timeout=None):
            pass

    context = types.SimpleNamespace(Queue=FakeQueue, Event=threading.Event, Process=FakeProcess)
    monkeypatch.setattr(processor.__class__, "process_lambda_image", fake_process)
    module = sys.modules[processor.__class__.__module__]
    monkeypatch.setattr(module.multiprocessing, "get_context", lambda method: context)
    if workers == 3:
        monkeypatch.setattr(module, "conservative_worker_limit", lambda: 3)

    def process():
        return processor.process_file_set(
            [str(source)], workers=workers, export_cake_npy=False, export_metadata=False,
            progress_callback=lambda current, total, message: progress.append(current),
        )

    if last_frame_failures == 2:
        with pytest.raises(RuntimeError, match="image indices \\[120\\]"):
            process()
    else:
        stats = process()
        assert stats["total_images"] == stats["processed"] == 121
        assert stats["failed"] == 0
        assert stats["failed_indices"] == []
        assert "map_121" in stats["chi_files"]

    assert sorted(set(seen)) == list(range(121))
    assert seen.count(120) == (2 if last_frame_failures else 1)
    assert progress == list(range(1, 122 if last_frame_failures != 2 else 121))


@pytest.mark.parametrize("last_frame_failures", [0, 1, 2])
def test_batch_workers_process_mixed_file_sets_and_report_completed_frames(
    tmp_path, monkeypatch, last_frame_failures
):
    sources = [tmp_path / name for name in ("single.h5", "series.h5", "other.h5")]
    sources.extend(tmp_path / f"extra_{index:03d}.h5" for index in range(20))
    counts = [1, 5, 3] + [1] * 20
    for source, count in zip(sources, counts):
        _write_hdf5(source, n_images=count)
    processor = _processor(tmp_path, monkeypatch)
    module = sys.modules[processor.__class__.__module__]
    monkeypatch.setattr(module, "conservative_worker_limit", lambda: 2)
    assignments = []
    remaining_failures = last_frame_failures

    def fake_process(self, file_set, image_index, base_output_name, *args, **kwargs):
        nonlocal remaining_failures
        if (remaining_failures and Path(file_set[0]).name == "series.h5"
                and image_index == 4):
            remaining_failures -= 1
            return {"success": False, "error": "bad frame"}
        destination = self.output_directory / f"{base_output_name}.chi"
        destination.write_text(str(image_index), encoding="utf-8")
        return {"success": True, "chi_file": str(destination)}

    class FakeQueue(queue.Queue):
        def close(self):
            pass

        def join_thread(self):
            pass

    class FakeProcess:
        def __init__(self, target, args):
            self.target = target
            self.args = args
            assignments.append(args[1])

        def start(self):
            self.target(*self.args)

        def is_alive(self):
            return False

        def join(self, timeout=None):
            pass

    context = types.SimpleNamespace(Queue=FakeQueue, Event=threading.Event, Process=FakeProcess)
    monkeypatch.setattr(module.multiprocessing, "get_context", lambda method: context)
    monkeypatch.setattr(processor.__class__, "process_lambda_image", fake_process)
    output_dirs = [tmp_path / "out-a", tmp_path / "out-b"] + [tmp_path / "out-a"] * 21
    progress = []

    result = processor.process_file_sets(
        [[str(source)] for source in sources], output_dirs, workers=2,
        progress_callback=lambda current, total, message: progress.append(
            (current, total, message)
        ),
        export_cake_npy=False, export_metadata=False,
    )

    assert len(assignments) == 2
    assert all(assignment for assignment in assignments)
    permanent_failure = last_frame_failures == 2
    assert result["processed"] == 29 - int(permanent_failure)
    assert result["total_images"] == 29
    assert not result["cancelled"]
    assert [stats["processed"] for _, stats in result["file_results"]] == (
        [1, 5 - int(permanent_failure), 3] + [1] * 20
    )
    assert result["file_results"][1][1]["failed_indices"] == (
        [4] if permanent_failure else []
    )
    assert [current for current, _, _ in progress] == list(
        range(1, 30 - int(permanent_failure))
    )
    assert all(total == 29 and "Completed image" in message for _, total, message in progress)
    assert (output_dirs[0] / "single.chi").exists()
    assert (output_dirs[1] / "series_005.chi").exists() == (not permanent_failure)
    assert (output_dirs[2] / "other_003.chi").exists()
    assert (output_dirs[-1] / "extra_019.chi").exists()


def test_progress_reports_frame_only_after_output_exists(tmp_path, monkeypatch):
    source = tmp_path / "single.h5"
    _write_hdf5(source)
    processor = _processor(tmp_path, monkeypatch)

    def fake_process(self, file_set, image_index, base_output_name, *args, **kwargs):
        destination = self.output_directory / f"{base_output_name}.chi"
        destination.write_text("done", encoding="utf-8")
        return {"success": True, "chi_file": str(destination)}

    monkeypatch.setattr(processor, "process_lambda_image", types.MethodType(fake_process, processor))
    progress = []
    processor.process_file_set(
        [str(source)], export_cake_npy=False, export_metadata=False,
        progress_callback=lambda current, total, message: progress.append(
            (current, total, message, (processor.output_directory / "single.chi").exists())
        ),
    )
    assert progress == [(1, 1, "Completed image 1/1", True)]


def test_batch_output_name_collision_runs_serially(tmp_path, monkeypatch):
    sources = [tmp_path / "map.h5", tmp_path / "map_001.h5"]
    _write_hdf5(sources[0], n_images=2)
    _write_hdf5(sources[1], n_images=1)
    processor = _processor(tmp_path, monkeypatch)
    module = sys.modules[processor.__class__.__module__]
    monkeypatch.setattr(module, "conservative_worker_limit", lambda: 2)
    monkeypatch.setattr(
        module.multiprocessing, "get_context",
        lambda method: pytest.fail("Overlapping output names must not run concurrently"),
    )
    seen = []

    def fake_process(self, file_set, image_index, base_output_name, *args, **kwargs):
        seen.append((Path(file_set[0]).name, base_output_name))
        return {"success": True}

    monkeypatch.setattr(processor.__class__, "process_lambda_image", fake_process)
    result = processor.process_file_sets(
        [[str(source)] for source in sources], [str(tmp_path / "out")] * 2,
        workers=2, export_cake_npy=False, export_metadata=False,
    )
    assert result["processed"] == 3
    assert seen == [
        ("map.h5", "map_001"), ("map.h5", "map_002"),
        ("map_001.h5", "map_001"),
    ]


@pytest.mark.parametrize("multiple_files", [False, True])
def test_abort_terminates_busy_parallel_workers(tmp_path, monkeypatch, multiple_files):
    sources = [tmp_path / "first.h5", tmp_path / "second.h5"]
    _write_hdf5(sources[0], n_images=5)
    _write_hdf5(sources[1])
    processor = _processor(tmp_path, monkeypatch)
    module = sys.modules[processor.__class__.__module__]
    monkeypatch.setattr(module, "conservative_worker_limit", lambda: 2)
    monkeypatch.setattr(module, "ABORT_WORKER_GRACE_SECONDS", 0.0)
    processes = []

    class FakeQueue(queue.Queue):
        def close(self):
            pass

        def join_thread(self):
            pass

    class FakeProcess:
        def __init__(self, target, args):
            self.alive = False
            self.terminated = False
            processes.append(self)

        def start(self):
            self.alive = True

        def is_alive(self):
            return self.alive

        def join(self, timeout=None):
            pass

        def terminate(self):
            self.terminated = True
            self.alive = False

    context = types.SimpleNamespace(Queue=FakeQueue, Event=threading.Event, Process=FakeProcess)
    monkeypatch.setattr(module.multiprocessing, "get_context", lambda method: context)

    if multiple_files:
        result = processor.process_file_sets(
            [[str(source)] for source in sources], [str(tmp_path / "out")] * 2,
            workers=2, should_continue=lambda: False,
        )
        assert all(stats is None for _, stats in result["file_results"])
    else:
        result = processor.process_file_set(
            [str(sources[0])], workers=2, should_continue=lambda: False,
        )
    assert result["cancelled"]
    assert result["processed"] == 0
    assert len(processes) == 2
    assert all(process.terminated for process in processes)


def test_atomic_pattern_write_preserves_existing_file_on_failure(tmp_path, monkeypatch):
    processor = _processor(tmp_path, monkeypatch)
    destination = processor.output_directory / "pattern.chi"
    destination.write_text("existing\n")

    def interrupted_save(path):
        Path(path).write_text("partial\n")
        raise OSError("interrupted")

    monkeypatch.setattr(processor.config, "save_pattern", interrupted_save)
    with pytest.raises(OSError, match="interrupted"):
        processor._save_pattern_atomic(destination)

    assert destination.read_text() == "existing\n"
    assert list(processor.output_directory.glob(".*.chi")) == []


def test_atomic_pattern_header_names_final_file(tmp_path, monkeypatch):
    processor = _processor(tmp_path, monkeypatch)
    destination = processor.output_directory / "pattern.chi"

    def save_with_filename_header(path):
        Path(path).write_text(f"{path}\n1 2\n")

    monkeypatch.setattr(processor.config, "save_pattern", save_with_filename_header)
    processor._save_pattern_atomic(destination)

    assert destination.read_text() == f"{destination}\n1 2\n"
