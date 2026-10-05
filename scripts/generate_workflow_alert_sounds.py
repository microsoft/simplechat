# generate_workflow_alert_sounds.py
"""Generate deterministic local WAV assets for workflow alert sounds."""

import argparse
import math
from pathlib import Path
import struct
import wave


SAMPLE_RATE = 22050
SAMPLE_WIDTH = 2
CHANNELS = 1
TARGET_PEAK = 10 ** (-3 / 20)
MAX_INT16 = 32767


def fade_envelope(local_time, duration, attack=0.008, release=0.012):
    """Return a short attack/release envelope to avoid clicks."""
    if local_time < 0 or local_time >= duration:
        return 0.0
    attack_level = min(1.0, local_time / attack) if attack > 0 else 1.0
    release_time = duration - local_time
    release_level = min(1.0, release_time / release) if release > 0 else 1.0
    return min(attack_level, release_level)


def decaying_sine(local_time, duration, frequency, harmonic=0.18, decay=3.0):
    """Return a gentle sine tone with one soft harmonic and decay."""
    phase = 2 * math.pi * frequency * local_time
    body = math.sin(phase) + harmonic * math.sin(2 * phase)
    return body * math.exp(-decay * local_time / duration)


def bright_beep(local_time, frequency):
    """Return a square-ish bright beep from a few odd harmonics."""
    phase = 2 * math.pi * frequency * local_time
    return (
        math.sin(phase)
        + 0.33 * math.sin(3 * phase)
        + 0.20 * math.sin(5 * phase)
    )


def render_track(duration, events):
    """Render a list of tone events and normalize to the target peak."""
    frame_count = int(round(duration * SAMPLE_RATE))
    samples = []
    for index in range(frame_count):
        current_time = index / SAMPLE_RATE
        value = 0.0
        for event in events:
            start = event["start"]
            event_duration = event["duration"]
            local_time = current_time - start
            if 0 <= local_time < event_duration:
                envelope = fade_envelope(
                    local_time,
                    event_duration,
                    event.get("attack", 0.008),
                    event.get("release", 0.012),
                )
                if event["shape"] == "beep":
                    tone = bright_beep(local_time, event["frequency"])
                else:
                    tone = decaying_sine(
                        local_time,
                        event_duration,
                        event["frequency"],
                        event.get("harmonic", 0.18),
                        event.get("decay", 3.0),
                    )
                value += event.get("gain", 1.0) * envelope * tone
        samples.append(value)

    peak = max(abs(sample) for sample in samples) or 1.0
    scale = TARGET_PEAK / peak
    return [
        max(-MAX_INT16, min(MAX_INT16, int(round(sample * scale * MAX_INT16))))
        for sample in samples
    ]


def write_wave(path, samples):
    """Write 16-bit PCM mono WAV data."""
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = b"".join(struct.pack("<h", sample) for sample in samples)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(CHANNELS)
        wav_file.setsampwidth(SAMPLE_WIDTH)
        wav_file.setframerate(SAMPLE_RATE)
        wav_file.writeframes(frames)


def build_chime():
    """Build the gentle two-note ascending chime."""
    return render_track(
        0.70,
        [
            {
                "start": 0.00,
                "duration": 0.30,
                "frequency": 880.0,
                "shape": "sine",
                "gain": 0.82,
                "harmonic": 0.16,
                "decay": 4.0,
            },
            {
                "start": 0.30,
                "duration": 0.34,
                "frequency": 1174.66,
                "shape": "sine",
                "gain": 1.0,
                "harmonic": 0.14,
                "decay": 4.4,
            },
        ],
    )


def build_urgent():
    """Build the attention-getting alternating two-tone cue."""
    return render_track(
        0.82,
        [
            {
                "start": 0.00,
                "duration": 0.15,
                "frequency": 990.0,
                "shape": "sine",
                "gain": 1.0,
                "harmonic": 0.24,
                "decay": 0.9,
            },
            {
                "start": 0.19,
                "duration": 0.15,
                "frequency": 740.0,
                "shape": "sine",
                "gain": 0.96,
                "harmonic": 0.22,
                "decay": 0.9,
            },
            {
                "start": 0.38,
                "duration": 0.15,
                "frequency": 990.0,
                "shape": "sine",
                "gain": 1.0,
                "harmonic": 0.24,
                "decay": 0.9,
            },
            {
                "start": 0.57,
                "duration": 0.15,
                "frequency": 740.0,
                "shape": "sine",
                "gain": 0.96,
                "harmonic": 0.22,
                "decay": 0.9,
            },
        ],
    )


def build_alarm():
    """Build the critical three-beep alarm cue."""
    return render_track(
        0.90,
        [
            {
                "start": 0.00,
                "duration": 0.12,
                "frequency": 1400.0,
                "shape": "beep",
                "gain": 1.0,
                "attack": 0.006,
                "release": 0.008,
            },
            {
                "start": 0.20,
                "duration": 0.12,
                "frequency": 1400.0,
                "shape": "beep",
                "gain": 1.0,
                "attack": 0.006,
                "release": 0.008,
            },
            {
                "start": 0.40,
                "duration": 0.12,
                "frequency": 1400.0,
                "shape": "beep",
                "gain": 1.0,
                "attack": 0.006,
                "release": 0.008,
            },
        ],
    )


def default_output_dir():
    """Return the repository-local default workflow alert asset directory."""
    repo_root = Path(__file__).resolve().parents[1]
    return repo_root / "application" / "single_app" / "static" / "audio" / "workflow-alerts"


def generate_alert_sounds(output_dir=None):
    """Generate all workflow alert sounds and return their paths."""
    target_dir = Path(output_dir) if output_dir else default_output_dir()
    assets = {
        "chime.wav": build_chime(),
        "urgent.wav": build_urgent(),
        "alarm.wav": build_alarm(),
    }
    written_paths = []
    for filename, samples in assets.items():
        path = target_dir / filename
        write_wave(path, samples)
        written_paths.append(path)
    return written_paths


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Generate SimpleChat workflow alert WAV assets."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory to write workflow alert WAV files.",
    )
    return parser.parse_args()


def main():
    """Run the generator from the command line."""
    args = parse_args()
    generate_alert_sounds(args.output_dir)


if __name__ == "__main__":
    main()
