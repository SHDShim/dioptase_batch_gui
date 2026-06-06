import importlib
import json
import sys
import types
from pathlib import Path

import h5py
import numpy as np


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


def _install_dioptas_stubs(monkeypatch):
    config_module = types.ModuleType("dioptas.model.Configuration")
    config_module.Configuration = _FakeConfiguration

    loader_module = types.ModuleType("dioptas.model.loader")
    lambda_loader_module = types.SimpleNamespace(LambdaImage=_FakeLambdaImage)
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
