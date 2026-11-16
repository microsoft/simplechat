# functions_image_adapters.py
"""Image wire operations over an already authorized, provider-authenticated client."""

import base64
import inspect

from functions_image_api_route import build_image_generation_tool
from functions_image_capabilities import validate_image_options


def _native_dimensions(capability, size):
    sizes = capability.get("sizes") or []
    if not size and not sizes:
        raise ValueError("The image model has no configured output dimensions.")
    resolved_size = size or sizes[0]
    validate_image_options(capability, size=resolved_size)
    return tuple(int(part) for part in resolved_size.split("x"))


def _source_data_url(source):
    return f'data:{source["mime_type"]};base64,{base64.b64encode(source["bytes"]).decode("ascii")}'


def _image_options(size, quality, background):
    arguments = {"n": 1}
    if size:
        arguments["size"] = size
    optional = {name: value for name, value in {"quality": quality, "background": background}.items() if value}
    if optional:
        arguments["extra_body"] = optional
    return arguments


def _image_edit_accepts_named_argument(method, name):
    try:
        return name in inspect.signature(method).parameters
    except (TypeError, ValueError):
        return False


def _reference_limit(capability):
    value = capability.get("max_reference_images")
    if type(value) is not int or value <= 0:
        value = 1
    return min(value, 10)


def _normalize_sources(source, capability):
    sources = source if isinstance(source, list) else [source]
    if not sources:
        raise ValueError("At least one source image is required for editing.")
    limit = _reference_limit(capability)
    if len(sources) > limit:
        raise ValueError(f"The selected image model supports at most {limit} reference image(s).")
    input_formats = capability.get("input_formats", [])
    for item in sources:
        if not isinstance(item, dict) or not isinstance(item.get("bytes"), bytes) or not item["bytes"]:
            raise ValueError("Each source image must include non-empty bytes for editing.")
        if item.get("mime_type") not in input_formats:
            raise ValueError("A source image format is unsupported by this model.")
    return sources


def generate_image(client, model, capability, prompt, size="", quality="", background=""):
    """Generate one image without imposing an OpenAI schema on MAI or FLUX."""
    validate_image_options(capability, size, quality, background)
    api = capability["api"]
    if api == "responses":
        return client.responses.create(
            model=model,
            input=prompt,
            tools=[build_image_generation_tool(size, quality, background)],
            tool_choice={"type": "image_generation"},
        )
    if capability.get("transport") == "openai_images":
        size = size or capability["sizes"][0]
        return client.images.generate(model=model, prompt=prompt, **_image_options(size, quality, background))
    if api == "images":
        return client.images.generate(model=model, prompt=prompt, **_image_options(size, quality, background))
    width, height = _native_dimensions(capability, size)
    body = {"model": model, "prompt": prompt, "width": width, "height": height}
    if api == "mai":
        return client.post("images/generations", cast_to=dict[str, object], body=body)
    if api == "flux":
        body["output_format"] = "png"
        if capability["model_path"] == "flux-2-pro":
            body["num_images"] = 1
        elif capability["model_path"] == "flux-pro-1.1":
            body["n"] = 1
        return client.post(capability["model_path"], cast_to=dict[str, object], body=body)
    raise ValueError("The image operation is unsupported.")


def edit_image(client, model, capability, prompt, source, mask=None, size="", quality="", background="", input_fidelity=""):
    """Edit actual source bytes; a mask is never silently degraded into a prompt-only request."""
    validate_image_options(capability, size, quality, background)
    if not capability.get("editing"):
        raise ValueError("The selected image model does not support source-image editing.")
    if mask and not capability.get("masking"):
        raise ValueError("The selected image model does not support uploaded masks.")
    sources = _normalize_sources(source, capability)
    if mask and len(sources) != 1:
        raise ValueError("A selected region can only be applied to a single reference image.")
    image_files = [(item["file_name"], item["bytes"], item["mime_type"]) for item in sources]
    requested_input_fidelity = input_fidelity if capability.get("input_fidelity") else ""
    api = capability["api"]
    if api == "responses":
        tool = build_image_generation_tool(size, quality, background)
        tool["action"] = "edit"
        if requested_input_fidelity:
            tool["input_fidelity"] = requested_input_fidelity
        if mask:
            tool["input_image_mask"] = {
                "image_url": f'data:image/png;base64,{base64.b64encode(mask["bytes"]).decode("ascii")}',
            }
        return client.responses.create(
            model=model,
            input=[{
                "role": "user",
                "content": [{"type": "input_text", "text": prompt}] + [
                    {"type": "input_image", "image_url": _source_data_url(item)} for item in sources
                ],
            }],
            tools=[tool],
            tool_choice={"type": "image_generation"},
        )
    if api == "images" or capability.get("transport") == "openai_images":
        if capability.get("transport") == "openai_images":
            size = size or capability["sizes"][0]
        arguments = _image_options(size, quality, background)
        if requested_input_fidelity:
            if _image_edit_accepts_named_argument(client.images.edit, "input_fidelity"):
                arguments["input_fidelity"] = requested_input_fidelity
            else:
                extra_body = dict(arguments.get("extra_body") or {})
                extra_body["input_fidelity"] = requested_input_fidelity
                arguments["extra_body"] = extra_body
        if mask:
            arguments["mask"] = ("mask.png", mask["bytes"], "image/png")
        return client.images.edit(model=model, prompt=prompt, image=image_files[0] if len(image_files) == 1 else image_files, **arguments)
    if api == "mai":
        if len(sources) != 1:
            raise ValueError("MAI source edits accept exactly one reference image.")
        # MAI edits accept the reference image and prompt, not generation-only dimensions.
        if size:
            raise ValueError("MAI source edits do not accept an output-size override; regenerate to change dimensions.")
        return client.post(
            "images/edits",
            cast_to=dict[str, object],
            body={"model": model, "prompt": prompt},
            files={"image": image_files[0]},
            options={"headers": {"Content-Type": "multipart/form-data"}},
        )
    if api == "flux":
        if size:
            raise ValueError("Native FLUX reference edits do not expose a size override here; regenerate to change dimensions.")
        body = {
            "model": model, "prompt": prompt,
            "output_format": "png",
        }
        for index, item in enumerate(sources, start=1):
            key = "input_image" if index == 1 else f"input_image_{index}"
            body[key] = base64.b64encode(item["bytes"]).decode("ascii")
        return client.post(
            capability["model_path"],
            cast_to=dict[str, object],
            body=body,
        )
    raise ValueError("The image edit operation is unsupported.")
