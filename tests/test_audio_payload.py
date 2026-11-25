import struct
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from waydroid_manager.audio_payload import AudioPayload, MODULE


class AudioPayloadTests(unittest.TestCase):
    def test_preserves_existing_override_and_rechecks_changed_image(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config"
            plugin = root / "plugin"
            audio = plugin / "bin/audio-native"
            audio.mkdir(parents=True)
            (audio / "manifest.json").write_text("{}")
            for abi in ("armeabi-v7a", "arm64-v8a"):
                module = audio / abi / MODULE
                module.parent.mkdir()
                module.write_bytes(b"module")
            image = root / "vendor.img"
            image.write_bytes(b"image")
            override = config / "overlay/vendor/lib/hw" / MODULE
            override.parent.mkdir(parents=True)
            override.write_bytes(b"user audio")
            manifest = {
                "sdk": 33,
                "libraries": {
                    "armeabi-v7a": {"alsaSymbols": ["snd_required"], "pulseSymbols": ["pa_required"]},
                    "arm64-v8a": {"alsaSymbols": ["snd_required"], "pulseSymbols": ["pa_required"]},
                },
            }
            calls = []

            def extract(config_path, image_name, paths, target, run, **kwargs):
                calls.append(paths[0])
                if paths[0] == "/build.prop":
                    target.write_text("ro.vendor.build.version.sdk=33\n")
                else:
                    header = bytearray(20)
                    header[:6] = b"\x7fELF" + (b"\x02" if "/lib64/" in paths[0] else b"\x01") + b"\x01"
                    struct.pack_into("<H", header, 18, 183 if "/lib64/" in paths[0] else 40)
                    target.write_bytes(header)
                return target

            def symbols(path):
                if path.name.endswith("-installed.so"):
                    return {"_snd_pcm_pulse_open": 1}
                if path.name.endswith("-libasound.so"):
                    return {"snd_required": 1}
                return {"pa_required": 1}

            payload = AudioPayload(config, plugin)
            with (patch("waydroid_manager.audio_payload.images_directory", return_value=root),
                  patch("waydroid_manager.audio_payload.validate_payload", return_value=manifest),
                  patch("waydroid_manager.audio_payload.extract", side_effect=extract),
                  patch("waydroid_manager.audio_payload.dynamic_symbols", side_effect=symbols)):
                selected = payload.files(None)
                self.assertEqual(set(selected), {"vendor/lib64/hw/" + MODULE})
                first_count = len(calls)
                self.assertEqual(payload.files(None), selected)
                self.assertEqual(len(calls), first_count)
                override.unlink()
                image.write_bytes(b"changed image")
                selected = payload.files(None)
                self.assertEqual(set(selected), {"vendor/lib/hw/" + MODULE, "vendor/lib64/hw/" + MODULE})
                self.assertGreater(len(calls), first_count)
                dependency = config / "overlay/vendor/lib64/libpulse.so"
                dependency.parent.mkdir(parents=True, exist_ok=True)
                dependency.write_bytes(b"custom pulse")
                self.assertEqual(set(payload.files(None)), {"vendor/lib/hw/" + MODULE})
                props = config / "overlay/vendor/build.prop"
                props.write_text("ro.vendor.build.version.sdk=33\n")
                self.assertEqual(payload.files(None), {})


if __name__ == "__main__":
    unittest.main()