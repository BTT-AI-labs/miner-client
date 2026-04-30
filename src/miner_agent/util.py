def parse_metric_line(line: str) -> tuple[str, dict[str, str], float] | None:
    """Parse Prometheus-style text line
    Args:
        line: A single metric line

    Returns:
        A tuple of `(metric_name, labels, value)` when parsing succeeds.
        Returns `None` when the line is malformed or the value is not numeric.
    """
    try:
        left, raw_value = line.rsplit(" ", 1)
    except ValueError:
        return None

    if "{" in left and left.endswith("}"):
        metric_name, labels_blob = left.split("{", 1)
        labels = _parse_labels(labels_blob[:-1])
    else:
        metric_name = left
        labels = {}

    try:
        value = float(raw_value)
    except ValueError:
        return None
    return metric_name, labels, value


def _parse_labels(text: str) -> dict[str, str]:
    labels: dict[str, str] = {}
    if not text:
        return labels
    for item in text.split(","):
        key, value = item.split("=", 1)
        labels[key.strip()] = value.strip().strip('"')
    return labels
