# functions_image_adapters.py
"""Image wire operations over an already authorized, provider-authenticated client."""

import base64

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


def edit_image(client, model, capability, prompt, source, mask=None, size="", quality="", background=""):
    """Edit actual source bytes; a mask is never silently degraded into a prompt-only request."""
    validate_image_options(capability, size, quality, background)
    if not capability.get("editing"):
        raise ValueError("The selected image model does not support source-image editing.")
    if mask and not capability.get("masking"):
        raise ValueError("The selected image model does not support uploaded masks.")
    if not source or not isinstance(source.get("bytes"), bytes) or not source["bytes"]:
        raise ValueError("A source image is required for editing.")
    if source.get("mime_type") not in capability.get("input_formats", []):
        raise ValueError("The source image format is unsupported by this model.")
    image_file = (source["file_name"], source["bytes"], source["mime_type"])
    api = capability["api"]
    if api == "responses":
        tool = build_image_generation_tool(size, quality, background)
        tool["action"] = "edit"
        if mask:
            tool["input_image_mask"] = {
                "image_url": f'data:image/png;base64,{base64.b64encode(mask["bytes"]).decode("ascii")}',
            }
        return client.responses.create(
            model=model,
            input=[{
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {"type": "input_image", "image_url": _source_data_url(source)},
                ],
            }],
            tools=[tool],
            tool_choice={"type": "image_generation"},
        )
    if api == "images" or capability.get("transport") == "openai_images":
        if capability.get("transport") == "openai_images":
            size = size or capability["sizes"][0]
        arguments = _image_options(size, quality, background)
        if mask:
            arguments["mask"] = ("mask.png", mask["bytes"], "image/png")
        return client.images.edit(model=model, prompt=prompt, image=image_file, **arguments)
    if api == "mai":
        # MAI edits accept the reference image and prompt, not generation-only dimensions.
        if size:
            raise ValueError("MAI source edits do not accept an output-size override; regenerate to change dimensions.")
        return client.post(
            "images/edits",
            cast_to=dict[str, object],
            body={"model": model, "prompt": prompt},
            files={"image": image_file},
            options={"headers": {"Content-Type": "multipart/form-data"}},
        )
    if api == "flux":
        if size:
            raise ValueError("Native FLUX reference edits do not expose a size override here; regenerate to change dimensions.")
        return client.post(
            capability["model_path"],
            cast_to=dict[str, object],
            body={
                "model": model, "prompt": prompt,
                "output_format": "png",
                "input_image": base64.b64encode(source["bytes"]).decode("ascii"),
            },
        )
    raise ValueError("The image edit operation is unsupported.")
