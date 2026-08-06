"""
The custom-training contract.

Three artefacts have to agree on what class index 3 means: the dataset's
data.yaml, the exported model's own head, and the .classes.txt sidecar the
ONNX detector reads at startup to map indices back to taxonomy names.

Nothing checks this at runtime, and nothing can. If the sidecar order drifts
from the training order the model still loads, still runs at full speed, and
still reports high confidence — it just calls every door a person. There is
no exception, no warning, and no symptom except a HUD that is confidently
wrong about the one thing a search turns on.

So all three are generated from vision/classes.TRAINABLE_CLASSES, and this
file asserts the round trip end to end.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))

from pyrosight.vision import classes as taxonomy

import importlib.util

_spec = importlib.util.spec_from_file_location(
    "pyrosight_train",
    pathlib.Path(__file__).resolve().parent.parent / "scripts" / "train.py")
train = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(train)


def _sidecar_roundtrip(lines):
    """Replay OnnxDetector.__init__'s sidecar mapping, exactly."""
    class_map = {}
    for i, n in enumerate(lines):
        if taxonomy.known(n):
            class_map[i] = n
        elif n.lower() in taxonomy.WORLD_PROMPT_TO_CLASS:
            class_map[i] = taxonomy.WORLD_PROMPT_TO_CLASS[n.lower()]
    return class_map


def test_every_trainable_class_is_a_real_class():
    for n in taxonomy.TRAINABLE_CLASSES:
        assert taxonomy.known(n), f"{n} is not in the registry"


def test_sidecar_maps_each_index_back_to_itself():
    """The whole contract, in one assertion."""
    sidecar = list(taxonomy.TRAINABLE_CLASSES)
    mapped = _sidecar_roundtrip(sidecar)
    for i, name in enumerate(taxonomy.TRAINABLE_CLASSES):
        assert mapped[i] == name, (
            f"index {i} trains as {name} but the detector reads it as "
            f"{mapped.get(i)}")


def test_data_yaml_order_matches_the_taxonomy():
    text = train.data_yaml_text()
    for i, name in enumerate(taxonomy.TRAINABLE_CLASSES):
        assert f"  {i}: {name}" in text


def test_data_yaml_declares_both_splits():
    """No val split means the reported accuracy is measured on the training
    data, which is not accuracy."""
    text = train.data_yaml_text()
    assert "train: images/train" in text
    assert "val: images/val" in text


def test_thermal_derived_classes_are_not_trainable():
    """hotspot and floor_hazard come from the Lepton and from depth. There
    are no RGB pixels to label, so including them would train the model to
    hallucinate them from appearance."""
    assert "hotspot" not in taxonomy.TRAINABLE_CLASSES
    assert "floor_hazard" not in taxonomy.TRAINABLE_CLASSES


def test_person_keeps_index_zero():
    """Not cosmetic: a stock COCO checkpoint puts person at 0, so fine-tuning
    from one starts that class already aligned instead of relearning it."""
    assert taxonomy.TRAINABLE_CLASSES[0] == "person"


def test_trainable_classes_are_unique():
    assert len(set(taxonomy.TRAINABLE_CLASSES)) == len(taxonomy.TRAINABLE_CLASSES)


def test_export_default_matches_config_path():
    """The trainer drops its ONNX where VisionConfig already looks, so
    deploying a retrained model is a restart and nothing else."""
    from pyrosight.config import VisionConfig
    expected = train.MODELS_DIR / "yolov8n.onnx"
    assert pathlib.Path(VisionConfig().onnx_model) == expected
