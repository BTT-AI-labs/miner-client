from __future__ import annotations

from dataclasses import dataclass

from miner_agent.util import parse_metric_line

METRIC_GPU_UTIL = "DCGM_FI_DEV_GPU_UTIL"
METRIC_FB_USED = "DCGM_FI_DEV_FB_USED"
METRIC_FB_FREE = "DCGM_FI_DEV_FB_FREE"
METRIC_FB_TOTAL = "DCGM_FI_DEV_FB_TOTAL"
METRIC_GPU_TEMP = "DCGM_FI_DEV_GPU_TEMP"
METRIC_POWER_USAGE = "DCGM_FI_DEV_POWER_USAGE"


@dataclass(frozen=True)
class GpuMetric:
    index: int
    utilization: float | None = None
    memory_used_mb: float | None = None
    memory_total_mb: float | None = None
    temperature: float | None = None
    power_usage_w: float | None = None

    def to_dict(self) -> dict[str, float | int | None]:
        return {
            "index": self.index,
            "utilization": self.utilization,
            "memory_used_mb": self.memory_used_mb,
            "memory_total_mb": self.memory_total_mb,
            "temperature": self.temperature,
            "power_usage_w": self.power_usage_w,
        }


def parse_dcgm_metrics(metrics_text: str) -> list[GpuMetric]:
    values: dict[int, dict[str, float]] = {}
    for line in metrics_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parsed = parse_metric_line(line)
        if parsed is None:
            continue
        metric_name, labels, value = parsed
        gpu_index = _gpu_index_from_labels(labels)
        if gpu_index is None:
            continue
        values.setdefault(gpu_index, {})[metric_name] = value

    metrics: list[GpuMetric] = []
    for gpu_index in sorted(values):
        gpu_values = values[gpu_index]
        memory_total = gpu_values.get(METRIC_FB_TOTAL)
        if memory_total is None and METRIC_FB_USED in gpu_values and METRIC_FB_FREE in gpu_values:
            memory_total = gpu_values[METRIC_FB_USED] + gpu_values[METRIC_FB_FREE]
        metrics.append(
            GpuMetric(
                index=gpu_index,
                utilization=gpu_values.get(METRIC_GPU_UTIL),
                memory_used_mb=gpu_values.get(METRIC_FB_USED),
                memory_total_mb=memory_total,
                temperature=gpu_values.get(METRIC_GPU_TEMP),
                power_usage_w=gpu_values.get(METRIC_POWER_USAGE),
            )
        )
    return metrics


def _gpu_index_from_labels(labels: dict[str, str]) -> int | None:
    for key in ("gpu", "index", "minor_number", "device"):
        raw_value = labels.get(key)
        if raw_value is None:
            continue
        try:
            return int(raw_value)
        except ValueError:
            continue
    return None
