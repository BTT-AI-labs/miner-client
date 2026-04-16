from __future__ import annotations

from miner_client.dcgm import parse_dcgm_metrics


def test_parse_dcgm_metrics_extracts_summary_fields() -> None:
    metrics_text = """
# HELP DCGM_FI_DEV_GPU_UTIL GPU utilization
DCGM_FI_DEV_GPU_UTIL{gpu="0"} 78
DCGM_FI_DEV_FB_USED{gpu="0"} 64512
DCGM_FI_DEV_FB_FREE{gpu="0"} 17408
DCGM_FI_DEV_GPU_TEMP{gpu="0"} 71
DCGM_FI_DEV_POWER_USAGE{gpu="0"} 285
"""

    metrics = parse_dcgm_metrics(metrics_text)

    assert len(metrics) == 1
    gpu0 = metrics[0].to_dict()
    assert gpu0["index"] == 0
    assert gpu0["utilization"] == 78
    assert gpu0["memory_used_mb"] == 64512
    assert gpu0["memory_total_mb"] == 81920
    assert gpu0["temperature"] == 71
    assert gpu0["power_usage_w"] == 285
