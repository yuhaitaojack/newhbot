from __future__ import annotations

import re

_UNQUOTED = re.compile(r"^[A-Za-z0-9_./+\-]+$")


class YamlLiteError(ValueError):
    pass


def parse_yaml_lite(text: str) -> object:
    """Parse a restricted YAML subset. No tags, aliases, or tabs."""
    if "\x00" in text:
        raise YamlLiteError("NUL byte is not allowed")
    if "\t" in text:
        raise YamlLiteError("tabs are not allowed")
    if "!!" in text or re.search(r"(^|\s)[&*]", text):
        raise YamlLiteError("YAML tags and aliases are not allowed")
    lines = [line.rstrip() for line in text.splitlines()]
    lines = [line for line in lines if line.strip() and not line.lstrip().startswith("#")]
    if not lines:
        raise YamlLiteError("manifest is empty")
    value, index = _parse_block(lines, 0, 0)
    if index != len(lines):
        raise YamlLiteError("unexpected trailing content")
    return value


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _parse_block(lines: list[str], index: int, indent: int) -> tuple[object, int]:
    if index >= len(lines):
        raise YamlLiteError("unexpected end of document")
    line = lines[index]
    if _indent(line) != indent:
        raise YamlLiteError("invalid indentation")
    stripped = line.lstrip(" ")
    if stripped.startswith("- "):
        return _parse_list(lines, index, indent)
    return _parse_map(lines, index, indent)


def _parse_map(lines: list[str], index: int, indent: int) -> tuple[dict, int]:
    result: dict[str, object] = {}
    while index < len(lines):
        line = lines[index]
        current = _indent(line)
        if current < indent:
            break
        if current > indent:
            raise YamlLiteError("invalid indentation")
        stripped = line.lstrip(" ")
        if stripped.startswith("- "):
            raise YamlLiteError("unexpected list item in mapping")
        if ":" not in stripped:
            raise YamlLiteError("mapping line must contain ':'")
        key, rest = stripped.split(":", 1)
        key = key.strip()
        if not key:
            raise YamlLiteError("empty mapping key")
        rest = rest.strip()
        index += 1
        if rest == "|" or rest == ">":
            folded, index = _parse_multiline(lines, index, indent + 2)
            result[key] = folded
        elif rest:
            result[key] = _parse_scalar(rest)
        else:
            if index >= len(lines) or _indent(lines[index]) <= indent:
                result[key] = None
            else:
                child, index = _parse_block(lines, index, _indent(lines[index]))
                result[key] = child
    return result, index


def _parse_list(lines: list[str], index: int, indent: int) -> tuple[list, int]:
    result: list[object] = []
    while index < len(lines):
        line = lines[index]
        current = _indent(line)
        if current < indent:
            break
        if current != indent:
            raise YamlLiteError("invalid list indentation")
        stripped = line.lstrip(" ")
        if not stripped.startswith("- "):
            break
        rest = stripped[2:].strip()
        index += 1
        if rest == "|" or rest == ">":
            folded, index = _parse_multiline(lines, index, indent + 2)
            result.append(folded)
        elif rest and not (":" in rest and not rest.startswith("{")):
            result.append(_parse_scalar(rest))
        elif rest:
            key, after = rest.split(":", 1)
            item = {key.strip(): _parse_scalar(after.strip()) if after.strip() else None}
            if index < len(lines) and _indent(lines[index]) > indent:
                nested, index = _parse_map_continue(lines, index, _indent(lines[index]), item)
                result.append(nested)
            else:
                if after.strip() == "":
                    if index < len(lines) and _indent(lines[index]) > indent:
                        child, index = _parse_block(lines, index, _indent(lines[index]))
                        item[key.strip()] = child
                result.append(item)
        else:
            child, index = _parse_block(lines, index, _indent(lines[index]))
            result.append(child)
    return result, index


def _parse_map_continue(lines: list[str], index: int, indent: int, start: dict) -> tuple[dict, int]:
    extra, index = _parse_map(lines, index, indent)
    start.update(extra)
    return start, index


def _parse_multiline(lines: list[str], index: int, indent: int) -> tuple[str, int]:
    chunks: list[str] = []
    while index < len(lines) and _indent(lines[index]) >= indent:
        chunks.append(lines[index].lstrip(" "))
        index += 1
    return " ".join(chunks), index


def _parse_scalar(raw: str) -> object:
    if raw in {"null", "~", "Null"}:
        return None
    if raw in {"true", "True"}:
        return True
    if raw in {"false", "False"}:
        return False
    if (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")):
        return raw[1:-1]
    if re.fullmatch(r"-?\d+", raw):
        return int(raw)
    if re.fullmatch(r"-?\d+\.\d+", raw):
        return float(raw)
    return raw
