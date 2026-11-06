"""Extract translation text from LangChain response content."""


def extractTranslationText(content: str | list) -> str:
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""

    parts = []
    for part in content:
        if isinstance(part, str):
            parts.append(part)
        elif isinstance(part, dict):
            if part.get("type") == "text":
                text = part.get("text", part.get("content"))
            elif "type" not in part:
                # Preserve the legacy untyped content blocks.
                text = part.get("content")
            else:
                continue
            if isinstance(text, str):
                parts.append(text)
    return "".join(parts).strip()
