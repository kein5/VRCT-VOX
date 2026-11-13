"""Which GPU "auto" and "gpu" start the bundled speech.cpp on, for any vendor."""
import pytest

from models.speech_server.runtime import preferred_gpu, resolve_device


def row(name, description, kind, memory=8 << 30):
    return dict(name=name, description=description, kind=kind, memory_total=memory, memory_free=memory)


CPU = row("CPU", "12th Gen Intel(R) Core(TM) i7-1255U", "cpu", 32 << 30)


@pytest.mark.parametrize("devices, chosen", [
    # speech.cpp lists the integrated GPU first; a separate one is chosen whatever its vendor.
    ([row("Vulkan0", "Intel(R) Iris(R) Xe Graphics", "igpu", 16 << 30),
      row("Vulkan1", "NVIDIA GeForce RTX 3060 Ti", "gpu"), CPU], "Vulkan1"),
    ([row("Vulkan0", "AMD Radeon(TM) Graphics", "igpu", 2 << 30),
      row("Vulkan1", "AMD Radeon RX 7800 XT", "gpu", 16 << 30), CPU], "Vulkan1"),
    ([row("Vulkan0", "Intel(R) UHD Graphics 770", "igpu"),
      row("Vulkan1", "Intel(R) Arc(TM) B580 Graphics", "gpu", 12 << 30), CPU], "Vulkan1"),
    # Two separate GPUs: the one with more memory.
    ([row("Vulkan0", "AMD Radeon RX 6600", "gpu", 8 << 30),
      row("Vulkan1", "NVIDIA GeForce RTX 4090", "gpu", 24 << 30)], "Vulkan1"),
    # Only an integrated GPU (a laptop with Intel or AMD graphics only).
    ([row("Vulkan0", "AMD Radeon(TM) 780M", "igpu"), CPU], "Vulkan0"),
    # The Direct3D 12 mapping layer and software rasterizers are not GPUs to compute on.
    ([row("Vulkan0", "Microsoft Direct3D12 (Intel(R) Iris(R) Xe Graphics)", "igpu"), CPU], None),
    ([row("Vulkan0", "llvmpipe (LLVM 19.1.7, 256 bits)", "igpu"), CPU], None),
    ([CPU], None),
    ([], None),
])
def test_a_separate_gpu_comes_first_for_every_vendor(devices, chosen):
    assert preferred_gpu(devices) == chosen


def test_rows_that_are_not_devices_are_ignored():
    assert preferred_gpu([None, "Vulkan0", {"name": "Vulkan0; rm", "kind": "gpu"},
                          row("Vulkan2", "AMD Radeon RX 7600", "gpu", memory=None)]) == "Vulkan2"


def test_only_auto_and_gpu_are_resolved():
    def devices():
        return [row("Vulkan0", "Intel(R) Iris(R) Xe Graphics", "igpu"),
                row("Vulkan1", "NVIDIA GeForce RTX 3060 Ti", "gpu")]

    assert resolve_device("auto", devices) == "Vulkan1"
    assert resolve_device("gpu", devices) == "Vulkan1"
    # A device the user named, and the CPU, are passed on as they are.
    assert resolve_device("Vulkan0", devices) == "Vulkan0"
    assert resolve_device("cpu", devices) == "cpu"


def test_without_a_gpu_or_a_device_list_the_choice_is_left_to_speech_cpp():
    assert resolve_device("auto", lambda: [CPU]) == "auto"
    assert resolve_device("gpu", lambda: []) == "gpu"

    def broken():
        raise OSError("speech.cpp could not run")

    assert resolve_device("auto", broken) == "auto"


def test_only_devices_that_cannot_compute_mean_the_cpu_for_auto():
    # Windows with only Microsoft's Vulkan-on-Direct3D 12 layer: models load, then the first
    # request fails. "auto" runs on the CPU instead; "gpu" keeps failing with its notice.
    def layer():
        return [row("Vulkan0", "Microsoft Direct3D12 (Intel(R) Iris(R) Xe Graphics)", "igpu"),
                row("Vulkan1", "Microsoft Direct3D12 (NVIDIA GeForce RTX 3060 Ti)", "gpu"), CPU]

    assert resolve_device("auto", layer) == "cpu"
    assert resolve_device("gpu", layer) == "gpu"
