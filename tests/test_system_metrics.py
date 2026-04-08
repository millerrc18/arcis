"""Tests for src.monitoring.system_metrics collectors."""

from unittest.mock import patch, MagicMock


class TestCollectGpuMetrics:
    def test_nvidia_smi_success(self):
        from src.monitoring.system_metrics import _collect_gpu_metrics

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "45, 4096, 12288, 62, 120.5"
        with patch("subprocess.run", return_value=mock_result):
            metrics = _collect_gpu_metrics()
        assert metrics["gpu_util_pct"] == 45.0
        assert metrics["gpu_vram_used_mb"] == 4096.0
        assert metrics["gpu_vram_total_mb"] == 12288.0
        assert metrics["gpu_temp_c"] == 62.0
        assert metrics["gpu_power_w"] == 120.5

    def test_nvidia_smi_not_available(self):
        from src.monitoring.system_metrics import _collect_gpu_metrics

        with patch("subprocess.run", side_effect=FileNotFoundError):
            metrics = _collect_gpu_metrics()
        assert metrics["gpu_util_pct"] is None
        assert metrics["gpu_vram_used_mb"] is None

    def test_nvidia_smi_timeout(self):
        import subprocess
        from src.monitoring.system_metrics import _collect_gpu_metrics

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("nvidia-smi", 5)):
            metrics = _collect_gpu_metrics()
        assert metrics["gpu_util_pct"] is None

    def test_nvidia_smi_nonzero_return(self):
        from src.monitoring.system_metrics import _collect_gpu_metrics

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        with patch("subprocess.run", return_value=mock_result):
            metrics = _collect_gpu_metrics()
        assert metrics["gpu_util_pct"] is None


class TestCollectCpuRam:
    def test_psutil_metrics(self):
        from src.monitoring.system_metrics import _collect_cpu_ram_metrics

        metrics = _collect_cpu_ram_metrics()
        assert "cpu_pct" in metrics
        assert metrics["cpu_pct"] >= 0
        assert "ram_used_mb" in metrics
        assert metrics["ram_used_mb"] > 0
        assert "ram_total_mb" in metrics
        assert metrics["ram_total_mb"] > 0


class TestCollectDisk:
    def test_disk_metrics(self):
        from src.monitoring.system_metrics import _collect_disk_metrics

        metrics = _collect_disk_metrics()
        assert "disk_used_gb" in metrics
        assert metrics["disk_used_gb"] > 0
        assert "disk_total_gb" in metrics
        assert metrics["disk_total_gb"] > 0


class TestCollectProcessMetrics:
    def test_process_rss(self):
        from src.monitoring.system_metrics import _collect_process_metrics

        metrics = _collect_process_metrics()
        assert "python_rss_mb" in metrics
        assert metrics["python_rss_mb"] > 0


class TestCollectOllamaStatus:
    def test_ollama_running(self):
        from src.monitoring.system_metrics import _collect_ollama_status

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"models": [{"name": "halcyon-v1.0.0"}]}
        with patch("requests.get", return_value=mock_resp):
            metrics = _collect_ollama_status()
        assert metrics["ollama_status"] == "running"
        assert metrics["ollama_model"] == "halcyon-v1.0.0"

    def test_ollama_down(self):
        from src.monitoring.system_metrics import _collect_ollama_status

        with patch("requests.get", side_effect=Exception("refused")):
            metrics = _collect_ollama_status()
        assert metrics["ollama_status"] == "error"
        assert metrics["ollama_model"] is None

    def test_ollama_no_models(self):
        from src.monitoring.system_metrics import _collect_ollama_status

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"models": []}
        with patch("requests.get", return_value=mock_resp):
            metrics = _collect_ollama_status()
        assert metrics["ollama_status"] == "running"
        assert metrics["ollama_model"] is None


class TestFullSnapshot:
    def test_snapshot_returns_dict(self):
        from src.monitoring.system_metrics import collect_system_snapshot

        with patch(
            "src.monitoring.system_metrics._collect_gpu_metrics",
            return_value={
                "gpu_util_pct": 50,
                "gpu_vram_used_mb": 4000,
                "gpu_vram_total_mb": 12000,
                "gpu_temp_c": 60,
                "gpu_power_w": 120,
            },
        ), patch(
            "src.monitoring.system_metrics._collect_ollama_status",
            return_value={
                "ollama_status": "running",
                "ollama_model": "halcyon-v1.0.0",
            },
        ), patch(
            "src.monitoring.system_metrics._store_snapshot",
        ):
            snapshot = collect_system_snapshot()
        assert snapshot["gpu_util_pct"] == 50
        assert snapshot["gpu_vram_total_mb"] == 12000
        assert snapshot["ollama_status"] == "running"
        assert "timestamp" in snapshot
        assert "snapshot_id" in snapshot
        assert "cpu_pct" in snapshot
        assert "ram_used_mb" in snapshot
        assert "disk_used_gb" in snapshot
        assert "python_rss_mb" in snapshot

    def test_snapshot_survives_all_failures(self):
        """Even if every sub-collector fails, snapshot should return a dict."""
        from src.monitoring.system_metrics import collect_system_snapshot

        with patch(
            "src.monitoring.system_metrics._collect_gpu_metrics",
            return_value={
                "gpu_util_pct": None,
                "gpu_vram_used_mb": None,
                "gpu_vram_total_mb": None,
                "gpu_temp_c": None,
                "gpu_power_w": None,
            },
        ), patch(
            "src.monitoring.system_metrics._collect_cpu_ram_metrics",
            return_value={
                "cpu_pct": None,
                "ram_used_mb": None,
                "ram_total_mb": None,
            },
        ), patch(
            "src.monitoring.system_metrics._collect_disk_metrics",
            return_value={
                "disk_used_gb": None,
                "disk_total_gb": None,
            },
        ), patch(
            "src.monitoring.system_metrics._collect_ollama_status",
            return_value={
                "ollama_status": "error",
                "ollama_model": None,
            },
        ), patch(
            "src.monitoring.system_metrics._collect_process_metrics",
            return_value={
                "python_rss_mb": None,
            },
        ), patch(
            "src.monitoring.system_metrics._store_snapshot",
        ):
            snapshot = collect_system_snapshot()
        assert "timestamp" in snapshot
        assert "snapshot_id" in snapshot
        assert snapshot["gpu_util_pct"] is None
        assert snapshot["ollama_status"] == "error"
