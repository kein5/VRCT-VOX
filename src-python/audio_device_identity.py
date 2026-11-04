"""Capture identity is separate from a device's human-readable label."""


def device_id(device):
    if not device or device.get("name") == "NoDevice":
        return ""
    return device.get("id", "")


def capture_key(device):
    if not device or device.get("name") == "NoDevice":
        return None
    return (
        device_id(device), device.get("name"), device.get("hostApi"),
        device.get("index"), device.get("incarnation"),
        device.get("defaultSampleRate"), device.get("maxInputChannels"),
        device.get("isLoopbackDevice"), device.get("node_name"),
        device.get("object_serial"),
    )


def resolve_device(devices, endpoint_id="", name=None):
    """Legacy names migrate only when unique. An absent ID never matches a name."""
    if endpoint_id:
        matches = [d for d in devices if device_id(d) == endpoint_id]
    else:
        matches = [d for d in devices if d.get("name") == name and name != "NoDevice"]
    return matches[0] if len(matches) == 1 else None


def device_options(devices):
    return [{"id": device_id(d), "label": d["name"]} for d in devices]
