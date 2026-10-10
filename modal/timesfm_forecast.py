"""TimesFM 3.0 inference wrapper (PyTorch, via the `timesfm` PyPI package).

Role in the pipeline (no hardcoded weights anywhere):
  - volatilityCluster (0..1) is computed deterministically in quant_job.py as
    the 63-day rolling realized-vol percentile vs 2-yr history (numpy).
  - This module supplies forwardVolRatio: TimesFM's 30-day forecast interval
    dispersion (mean q90-q10) divided by the trailing realized dispersion.
    > 1 means the model expects volatility expansion; < 1 contraction.
    It is stored raw alongside the other factors.

Resilience: any load/inference failure raises TimesFMUnavailable with a clear
message. The cron catches it, logs to /quant/system_logs, records
forwardVolRatio=None, and continues the price update — never a silent crash,
never fake factors.
"""

import numpy as np

MODEL_ID = "google/timesfm-3.0-pytorch"
HORIZON = 30

_forecaster = None


class TimesFMUnavailable(Exception):
    pass


def get_forecaster(device: str = "cuda"):
    """Lazy singleton. Downloads the checkpoint from HF on first use."""
    global _forecaster
    if _forecaster is None:
        try:
            from timesfm3 import TimesFM3Evaluator, ModelConfig
        except ImportError as e:
            raise TimesFMUnavailable(f"timesfm3 not importable: {e}")
        try:
            cfg = ModelConfig(
                checkpoint_path=MODEL_ID,
                per_core_batch_size=16,
                device=device,
            )
            _forecaster = TimesFM3Evaluator(cfg)
        except Exception as e:
            raise TimesFMUnavailable(f"could not load {MODEL_ID}: {e}")
    return _forecaster


def _ffill(series):
    """Forward-fill then back-fill leading NaNs. Returns np.float32 array."""
    s = np.asarray(series, dtype=np.float32)
    mask = np.isnan(s)
    if mask.all():
        return None
    idx = np.where(~mask, np.arange(len(s)), 0)
    np.maximum.accumulate(idx, out=idx)
    filled = s[idx]
    return filled


def build_covariates(dates, supplier_maps, revenue_yoy_by_date):
    """Align past-only covariate channels to the manufacturer's date index.

    dates: sorted list of 'YYYY-MM-DD' (manufacturer trading days).
    supplier_maps: {supplier_symbol: {date: close}}.
    revenue_yoy_by_date: {date: yoy_growth} (forward-filled quarterly).
    Returns np.float32 array of shape (n_channels, len(dates)), or None.
    """
    channels = []
    for _sup, m in supplier_maps.items():
        s = [m.get(d, np.nan) for d in dates]
        f = _ffill(s)
        if f is not None:
            channels.append(f)
    if revenue_yoy_by_date:
        s = [revenue_yoy_by_date.get(d, np.nan) for d in dates]
        f = _ffill(s)
        if f is not None:
            channels.append(f)
    if not channels:
        return None
    return np.stack(channels).astype(np.float32)


def forward_vol_ratio(dates, closes, supplier_maps=None, revenue_yoy_by_date=None):
    """TimesFM 30-day forecast -> forwardVolRatio (float) or raises
    TimesFMUnavailable. Uses up to 512 trailing points as context."""
    fc = get_forecaster()
    ts = np.asarray(closes[-512:], dtype=np.float32)
    dates = dates[-len(ts):]

    cov = None
    if supplier_maps or revenue_yoy_by_date:
        cov = build_covariates(dates, supplier_maps or {}, revenue_yoy_by_date or {})

    kwargs = dict(horizon=HORIZON, return_quantiles=True, use_symmetric_averaging=False)
    if cov is not None:
        outputs = list(
            fc.predict_batch(contexts=[ts], past_only_covariates=[cov], **kwargs)
        )
    else:
        outputs = list(fc.predict_batch([ts], **kwargs))
    q = outputs[0].quantiles  # (HORIZON, 9): q10..q90

    fwd_spread = float(np.mean(q[:, 8] - q[:, 0]))
    trail = np.asarray(closes[-64:], dtype=float)
    trail_scale = float(np.abs(np.diff(trail)).mean()) * np.sqrt(HORIZON) + 1e-9
    return fwd_spread / trail_scale
