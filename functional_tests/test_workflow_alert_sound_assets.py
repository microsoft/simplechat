# test_workflow_alert_sound_assets.py
"""
Functional test for workflow alert sound assets.
Version: 0.261.235
Implemented in: 0.261.235

This test ensures local workflow alert WAV assets are valid, distinct, and
byte-identical when regenerated.
"""

import hashlib
import importlib.util
import shutil
import struct
import sys
import wave
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT_DIR / "scripts" / "generate_workflow_alert_sounds.py"
AUDIO_DIR = ROOT_DIR / "application" / "single_app" / "static" / "audio" / "workflow-alerts"
REGEN_DIR = ROOT_DIR / "functional_tests" / "__workflow_alert_sound_regen__"
EXPECTED_FILES = ["chime.wav", "urgent.wav", "alarm.wav"]
MIN_PEAK = 4000
MAX_INT16 = 32767


def load_generator():
    """Import the generator script directly from its file path."""
    spec = importlib.util.spec_from_file_location(
        "generate_workflow_alert_sounds",
        SCRIPT_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def read_wave_details(path):
    """Read WAV metadata, duration, samples, and hash."""
    with wave.open(str(path), "rb") as wav_file:
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        frame_rate = wav_file.getframerate()
        frame_count = wav_file.getnframes()
        frames = wav_file.readframes(frame_count)

    samples = [sample[0] for sample in struct.iter_unpack("<h", frames)]
    duration = frame_count / frame_rate
    peak = max(abs(sample) for sample in samples)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "channels": channels,
        "sample_width": sample_width,
        "frame_rate": frame_rate,
        "frame_count": frame_count,
        "duration": duration,
        "peak": peak,
        "digest": digest,
        "bytes": path.read_bytes(),
    }


def test_workflow_alert_sound_assets_exist_and_are_valid():
    """Validate the bundled workflow alert WAV files."""
    details = {}
    for filename in EXPECTED_FILES:
        path = AUDIO_DIR / filename
        assert path.exists(), f"{filename} must exist"
        assert path.stat().st_size < 60 * 1024, f"{filename} must stay under 60 KB"

        asset = read_wave_details(path)
        details[filename] = asset
        assert asset["channels"] == 1, f"{filename} must be mono"
        assert asset["sample_width"] == 2, f"{filename} must be 16-bit PCM"
        assert asset["frame_rate"] == 22050, f"{filename} must be 22050 Hz"
        assert 0.3 <= asset["duration"] <= 1.5, f"{filename} duration is out of range"
        assert MIN_PEAK <= asset["peak"] < MAX_INT16, f"{filename} peak is invalid"

    assert len({details[name]["digest"] for name in EXPECTED_FILES}) == len(EXPECTED_FILES)
    assert len({details[name]["bytes"] for name in EXPECTED_FILES}) == len(EXPECTED_FILES)


def test_workflow_alert_sound_generator_is_deterministic():
    """Regenerate assets in a repo-local scratch directory and compare bytes."""
    if REGEN_DIR.exists():
        shutil.rmtree(REGEN_DIR)
    try:
        generator = load_generator()
        generated_paths = generator.generate_alert_sounds(REGEN_DIR)
        assert sorted(path.name for path in generated_paths) == sorted(EXPECTED_FILES)

        for filename in EXPECTED_FILES:
            expected_path = AUDIO_DIR / filename
            regenerated_path = REGEN_DIR / filename
            assert regenerated_path.exists(), f"{filename} must regenerate"
            assert regenerated_path.read_bytes() == expected_path.read_bytes()
    finally:
        if REGEN_DIR.exists():
            shutil.rmtree(REGEN_DIR)


def main():
    """Run all workflow alert sound asset checks."""
    tests = [
        test_workflow_alert_sound_assets_exist_and_are_valid,
        test_workflow_alert_sound_generator_is_deterministic,
    ]
    for test in tests:
        test()
        print(f"Passed: {test.__name__}")
    return True


if __name__ == "__main__":
    try:
        success = main()
    except Exception as error:
        print(f"Failed: {error}")
        raise
    sys.exit(0 if success else 1)
