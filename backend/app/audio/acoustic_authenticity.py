import numpy as np

class HeuristicAuthenticityScorer:
    """
    Rule-based (no training required) acoustic authenticity scorer built
    directly on the MFCC / F0 / CQT components from FeatureExtractor.

    Signals used, based on known vocoder/deepfake artifacts:
      1. cqt_highband_ratio: neural vocoders tend to leak extra energy into
         high-frequency CQT bins vs. natural speech's high-frequency roll-off.
         Higher ratio -> more synthetic-sounding. (Strongest signal observed.)
      2. f0_jitter: pitch trackers get unstable/jumpy on vocoder output due to
         irregular harmonic structure, even when the voice sounds smooth to
         a human ear. Higher jitter -> more synthetic-sounding.
      3. mfcc_delta_mag: overall frame-to-frame spectral movement; weaker
         tie-breaking signal.

    Thresholds were calibrated by spot-checking this project's own
    test_voiceai*.wav vs test_voiceh*.wav clips (n=5) -- NOT a statistically
    validated dataset. Re-calibrate CQT_RATIO_*/JITTER_*/DELTA_* as more
    real call data comes in, or replace this class with a trained
    logistic-regression head once labeled data exists (raw_metrics below
    are exactly the feature vector you'd feed it).
    """

    CQT_RATIO_LOW = 0.4
    CQT_RATIO_HIGH = 0.9
    JITTER_LOW = 0.20
    JITTER_HIGH = 0.40
    DELTA_LOW = 6.8
    DELTA_HIGH = 8.2

    # Must sum to 1.0
    WEIGHT_CQT = 0.5
    WEIGHT_JITTER = 0.35
    WEIGHT_DELTA = 0.15

    def _score_band(self, value: float, low: float, high: float) -> float:
        """Linearly maps a raw metric to a 0-1 'suspicion' score."""
        if value <= low:
            return 0.0
        if value >= high:
            return 1.0
        return (value - low) / (high - low)

    def score(self, components: dict) -> dict:
        mfccs = components["mfccs"]
        f0 = components["f0"]
        cqt = components["cqt"]

        # --- CQT high-band energy ratio ---
        n_bins = cqt.shape[0]
        high_band = cqt[int(n_bins * 0.7):, :]
        cqt_highband_ratio = float(np.mean(high_band) / (np.mean(cqt) + 1e-9))

        # --- F0 jitter (relative frame-to-frame movement, voiced frames only) ---
        voiced = f0[f0 > 0]
        if len(voiced) > 5:
            rel_diff = np.abs(np.diff(voiced)) / voiced[:-1]
            f0_jitter = float(np.mean(rel_diff))
        else:
            f0_jitter = None  # not enough voiced frames to judge

        # --- MFCC frame-to-frame movement ---
        delta = np.diff(mfccs, axis=1)
        mfcc_delta_mag = float(np.mean(np.abs(delta))) if delta.size else None

        cqt_s = self._score_band(cqt_highband_ratio, self.CQT_RATIO_LOW, self.CQT_RATIO_HIGH)

        if f0_jitter is not None:
            jitter_s = self._score_band(f0_jitter, self.JITTER_LOW, self.JITTER_HIGH)
            w_jitter = self.WEIGHT_JITTER
        else:
            jitter_s, w_jitter = 0.0, 0.0

        if mfcc_delta_mag is not None:
            delta_s = self._score_band(mfcc_delta_mag, self.DELTA_LOW, self.DELTA_HIGH)
            w_delta = self.WEIGHT_DELTA
        else:
            delta_s, w_delta = 0.0, 0.0

        total_weight = self.WEIGHT_CQT + w_jitter + w_delta
        composite = (self.WEIGHT_CQT * cqt_s + w_jitter * jitter_s + w_delta * delta_s) / total_weight

        return {
            "heuristic_risk_score": round(composite * 100, 2),
            "raw_metrics": {
                "cqt_highband_ratio": round(cqt_highband_ratio, 4),
                "f0_jitter": round(f0_jitter, 4) if f0_jitter is not None else None,
                "mfcc_delta_mag": round(mfcc_delta_mag, 4) if mfcc_delta_mag is not None else None,
            },
        }