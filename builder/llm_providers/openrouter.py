"""OpenRouter text-completion provider. See builder/llm_providers/__init__.py
for the shared call(api_key, model, system, prompt, timeout) -> str contract
every provider follows.
"""


def call(api_key: str, model: str, system: str, prompt: str, timeout: float = 90.0) -> str:
    import httpx

    resp = httpx.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def call_vision(
    api_key: str, model: str, system: str, prompt: str,
    image_data_uris: list, timeout: float = 90.0,
) -> str:
    """Vision-capable sibling of call() -- same endpoint/auth, but the user
    message is a multi-part OpenAI-compatible content array (text + one or
    more image_url parts) instead of a plain string, since call()'s shape
    can't carry image input at all.

    image_data_uris must already be data:<mime>;base64,... strings using each
    file's REAL mime type (see tools/drive_download.py's
    get_drive_file_metadata) -- never assume image/png.
    """
    import httpx

    content = [{"type": "text", "text": prompt}]
    for uri in image_data_uris:
        content.append({"type": "image_url", "image_url": {"url": uri}})

    resp = httpx.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": content},
            ],
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]
