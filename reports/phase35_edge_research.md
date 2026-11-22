# Phase 3.5 — Edge research

_Generated 2026-11-22T17:41:29.936898+00:00 | commit `523bfdb0c63750fd849ceed9a3ed2a943e2b424f`_

## BTCUSDT

Generated 2026-11-22T17:41:42.755998+00:00 | features tested: **18** (|t| < 3.0 flagged as likely noise)

## IS selection (exploration)

| feature | horizon | mean_ic | ic_tstat | ic_sign_pct | likely_noise | n_features_tested |
| --- | --- | --- | --- | --- | --- | --- |
| taker_buy_ratio | 1 | -0.0188 | -2.0808 | 0.5333 | True | 72 |
| taker_buy_ratio | 4 | -0.0151 | -1.7347 | 0.7333 | True | 72 |
| taker_buy_ratio | 12 | -0.0119 | -1.3055 | 0.4667 | True | 72 |
| taker_buy_ratio | 24 | -0.0181 | -2.5068 | 0.6667 | True | 72 |
| taker_buy_ratio_z24 | 1 | -0.0138 | -1.4641 | 0.6000 | True | 72 |
| taker_buy_ratio_z24 | 4 | -0.0106 | -1.2336 | 0.6667 | True | 72 |
| taker_buy_ratio_z24 | 12 | -0.0136 | -1.3615 | 0.7333 | True | 72 |
| taker_buy_ratio_z24 | 24 | -0.0243 | -4.4370 | 0.9333 | False | 72 |
| taker_buy_ratio_z72 | 1 | -0.0174 | -1.9737 | 0.6000 | True | 72 |
| taker_buy_ratio_z72 | 4 | -0.0124 | -1.4228 | 0.7333 | True | 72 |
| taker_buy_ratio_z72 | 12 | -0.0103 | -1.0899 | 0.6000 | True | 72 |
| taker_buy_ratio_z72 | 24 | -0.0200 | -2.7075 | 0.7333 | True | 72 |
| taker_delta_4h | 1 | -0.0278 | -2.8579 | 0.8000 | True | 72 |
| taker_delta_4h | 4 | -0.0293 | -1.9654 | 0.6667 | True | 72 |
| taker_delta_4h | 12 | -0.0260 | -1.8187 | 0.7333 | True | 72 |
| taker_delta_4h | 24 | -0.0171 | -0.9418 | 0.4667 | True | 72 |
| taker_delta_12h | 1 | -0.0309 | -3.7985 | 0.8000 | False | 72 |
| taker_delta_12h | 4 | -0.0328 | -2.6561 | 0.7333 | True | 72 |
| taker_delta_12h | 12 | -0.0142 | -0.6506 | 0.4667 | True | 72 |
| taker_delta_12h | 24 | 0.0131 | 0.4761 | 0.6000 | True | 72 |
| taker_delta_24h | 1 | -0.0258 | -2.9095 | 0.8667 | True | 72 |
| taker_delta_24h | 4 | -0.0178 | -1.1297 | 0.6000 | True | 72 |
| taker_delta_24h | 12 | 0.0132 | 0.5193 | 0.7333 | True | 72 |
| taker_delta_24h | 24 | 0.0428 | 1.3761 | 0.6667 | True | 72 |
| taker_buy_ratio_15m | 1 | -0.0321 | -3.5949 | 0.8667 | False | 72 |
| taker_buy_ratio_15m | 4 | -0.0184 | -2.0834 | 0.6000 | True | 72 |
| taker_buy_ratio_15m | 12 | -0.0147 | -1.2034 | 0.6667 | True | 72 |
| taker_buy_ratio_15m | 24 | -0.0125 | -1.2959 | 0.5333 | True | 72 |
| taker_buy_ratio_15m_z24 | 1 | -0.0301 | -3.5397 | 0.8667 | False | 72 |
| taker_buy_ratio_15m_z24 | 4 | -0.0178 | -2.3147 | 0.6000 | True | 72 |
| taker_buy_ratio_15m_z24 | 12 | -0.0155 | -1.3942 | 0.6000 | True | 72 |
| taker_buy_ratio_15m_z24 | 24 | -0.0175 | -1.8312 | 0.6000 | True | 72 |
| above_ema50_1h | 1 | -0.0267 | -3.2596 | 0.8000 | False | 72 |
| above_ema50_1h | 4 | -0.0458 | -3.3724 | 0.8000 | False | 72 |
| above_ema50_1h | 12 | -0.0390 | -1.3084 | 0.6667 | True | 72 |
| above_ema50_1h | 24 | -0.0340 | -0.8318 | 0.6667 | True | 72 |
| above_ema200_1h | 1 | -0.0264 | -3.1683 | 0.7333 | False | 72 |
| above_ema200_1h | 4 | -0.0474 | -2.8056 | 0.8000 | True | 72 |
| above_ema200_1h | 12 | -0.0680 | -2.4920 | 0.8667 | True | 72 |
| above_ema200_1h | 24 | -0.0836 | -2.2775 | 0.8000 | True | 72 |

## OOS confirmation (single pass)

| feature | horizon | mean_ic | ic_tstat | ic_sign_pct | likely_noise | n_features_tested |
| --- | --- | --- | --- | --- | --- | --- |
| taker_buy_ratio | 1 | -0.0100 | -0.7610 | 0.7273 | True | 72 |
| taker_buy_ratio | 4 | -0.0108 | -0.7098 | 0.5455 | True | 72 |
| taker_buy_ratio | 12 | -0.0148 | -1.2096 | 0.5455 | True | 72 |
| taker_buy_ratio | 24 | -0.0097 | -0.6854 | 0.6364 | True | 72 |
| taker_buy_ratio_z24 | 1 | -0.0073 | -0.5255 | 0.6364 | True | 72 |
| taker_buy_ratio_z24 | 4 | -0.0054 | -0.3902 | 0.6364 | True | 72 |
| taker_buy_ratio_z24 | 12 | -0.0062 | -0.5715 | 0.6364 | True | 72 |
| taker_buy_ratio_z24 | 24 | 0.0005 | 0.0407 | 0.4545 | True | 72 |
| taker_buy_ratio_z72 | 1 | -0.0091 | -0.6571 | 0.6364 | True | 72 |
| taker_buy_ratio_z72 | 4 | -0.0064 | -0.4667 | 0.5455 | True | 72 |
| taker_buy_ratio_z72 | 12 | -0.0063 | -0.4659 | 0.5455 | True | 72 |
| taker_buy_ratio_z72 | 24 | -0.0000 | -0.0017 | 0.4545 | True | 72 |
| taker_delta_4h | 1 | -0.0164 | -1.1738 | 0.6364 | True | 72 |
| taker_delta_4h | 4 | -0.0276 | -2.0710 | 0.8182 | True | 72 |
| taker_delta_4h | 12 | -0.0075 | -0.3643 | 0.4545 | True | 72 |
| taker_delta_4h | 24 | -0.0187 | -0.7609 | 0.7273 | True | 72 |
| taker_delta_12h | 1 | -0.0114 | -1.2363 | 0.7273 | True | 72 |
| taker_delta_12h | 4 | -0.0268 | -1.7332 | 0.6364 | True | 72 |
| taker_delta_12h | 12 | -0.0094 | -0.2866 | 0.5455 | True | 72 |
| taker_delta_12h | 24 | -0.0499 | -1.2998 | 0.8182 | True | 72 |
| taker_delta_24h | 1 | -0.0226 | -2.1391 | 0.7273 | True | 72 |
| taker_delta_24h | 4 | -0.0494 | -2.2062 | 0.7273 | True | 72 |
| taker_delta_24h | 12 | -0.0664 | -1.7790 | 0.8182 | True | 72 |
| taker_delta_24h | 24 | -0.0793 | -1.9019 | 0.8182 | True | 72 |
| taker_buy_ratio_15m | 1 | -0.0128 | -0.9010 | 0.5455 | True | 72 |
| taker_buy_ratio_15m | 4 | 0.0034 | 0.3312 | 0.5455 | True | 72 |
| taker_buy_ratio_15m | 12 | -0.0065 | -0.8925 | 0.6364 | True | 72 |
| taker_buy_ratio_15m | 24 | 0.0006 | 0.1050 | 0.5455 | True | 72 |
| taker_buy_ratio_15m_z24 | 1 | -0.0143 | -0.9039 | 0.5455 | True | 72 |
| taker_buy_ratio_15m_z24 | 4 | 0.0013 | 0.1173 | 0.4545 | True | 72 |
| taker_buy_ratio_15m_z24 | 12 | -0.0088 | -0.9273 | 0.7273 | True | 72 |
| taker_buy_ratio_15m_z24 | 24 | 0.0017 | 0.2038 | 0.4545 | True | 72 |
| above_ema50_1h | 1 | -0.0253 | -4.7304 | 0.9091 | False | 72 |
| above_ema50_1h | 4 | -0.0376 | -4.1064 | 0.9091 | False | 72 |
| above_ema50_1h | 12 | -0.0349 | -1.4540 | 0.7273 | True | 72 |
| above_ema50_1h | 24 | -0.0761 | -2.4440 | 0.7273 | True | 72 |
| above_ema200_1h | 1 | -0.0289 | -3.8325 | 0.9091 | False | 72 |
| above_ema200_1h | 4 | -0.0464 | -2.8479 | 0.8182 | True | 72 |
| above_ema200_1h | 12 | -0.0844 | -2.4939 | 0.7273 | True | 72 |
| above_ema200_1h | 24 | -0.1426 | -3.0608 | 0.7273 | False | 72 |

## Quintile spreads vs round-trip cost (low-fee)
Round-trip cost fraction used: **0.0012**

### IS
- **taker_buy_ratio**: top-bottom -0.0003
- **taker_buy_ratio_z24**: top-bottom -0.0011
- **taker_buy_ratio_z72**: top-bottom -0.0007
- **taker_delta_4h**: top-bottom -0.0007
- **taker_delta_12h**: top-bottom 0.0022
- **taker_delta_24h**: top-bottom 0.0027
- **taker_buy_ratio_15m**: top-bottom 0.0002
- **taker_buy_ratio_15m_z24**: top-bottom -0.0005
- **above_ema50_1h**: top-bottom -0.0047
- **above_ema200_1h**: top-bottom -0.0053
- **above_ema50_4h**: top-bottom -0.0049
- **above_ema200_4h**: top-bottom -0.0039
- **atr_pct**: top-bottom 0.0027
- **realized_vol_24h**: top-bottom 0.0029
- **weekday**: top-bottom -0.0002
- **setup_score**: top-bottom -0.0045
- **has_breakout**: top-bottom -0.0053
- **has_pullback**: top-bottom -0.0065

### OOS
- **taker_buy_ratio**: top-bottom 0.0003
- **taker_buy_ratio_z24**: top-bottom 0.0005
- **taker_buy_ratio_z72**: top-bottom 0.0009
- **taker_delta_4h**: top-bottom 0.0020
- **taker_delta_12h**: top-bottom 0.0010
- **taker_delta_24h**: top-bottom -0.0004
- **taker_buy_ratio_15m**: top-bottom 0.0008
- **taker_buy_ratio_15m_z24**: top-bottom 0.0012
- **above_ema50_1h**: top-bottom 0.0006
- **above_ema200_1h**: top-bottom 0.0015
- **above_ema50_4h**: top-bottom 0.0017
- **above_ema200_4h**: top-bottom 0.0041
- **atr_pct**: top-bottom -0.0039
- **realized_vol_24h**: top-bottom -0.0054
- **weekday**: top-bottom 0.0014
- **setup_score**: top-bottom -0.0008
- **has_breakout**: top-bottom -0.0008
- **has_pullback**: top-bottom -0.0019

## Simple rule backtests (top/bottom quintile)

### IS
- trades=8241 win_rate=0.00% net_E=-0.3574 PF=0.33

### OOS
- trades=5 win_rate=0.00% net_E=0.2605 PF=2.90

## Spearman correlation (top features)
| above_ema200_4h | taker_buy_ratio_z24 | taker_delta_12h | taker_buy_ratio_15m | taker_buy_ratio_15m_z24 |
| --- | --- | --- | --- | --- |
| 1.0000 | -0.0290 | 0.1360 | -0.0080 | -0.0090 |
| -0.0290 | 1.0000 | 0.0780 | 0.3730 | 0.3830 |
| 0.1360 | 0.0780 | 1.0000 | 0.0800 | 0.0310 |
| -0.0080 | 0.3730 | 0.0800 | 1.0000 | 0.9680 |
| -0.0090 | 0.3830 | 0.0310 | 0.9680 | 1.0000 |

## Plain-English verdicts
- **taker_buy_ratio**: noise
- **taker_buy_ratio_z24**: noise
- **taker_buy_ratio_z72**: noise
- **taker_delta_4h**: noise
- **taker_delta_12h**: weak
- **taker_delta_24h**: noise
- **taker_buy_ratio_15m**: weak
- **taker_buy_ratio_15m_z24**: weak
- **above_ema50_1h**: weak
- **above_ema200_1h**: weak
- **above_ema50_4h**: weak
- **above_ema200_4h**: weak
- **atr_pct**: noise
- **realized_vol_24h**: noise
- **weekday**: noise
- **setup_score**: noise
- **has_breakout**: noise
- **has_pullback**: noise
## ETHUSDT

Generated 2026-11-22T17:41:55.305982+00:00 | features tested: **18** (|t| < 3.0 flagged as likely noise)

## IS selection (exploration)

| feature | horizon | mean_ic | ic_tstat | ic_sign_pct | likely_noise | n_features_tested |
| --- | --- | --- | --- | --- | --- | --- |
| taker_buy_ratio | 1 | -0.0179 | -1.6591 | 0.7333 | True | 72 |
| taker_buy_ratio | 4 | -0.0030 | -0.2843 | 0.4667 | True | 72 |
| taker_buy_ratio | 12 | 0.0011 | 0.1313 | 0.5333 | True | 72 |
| taker_buy_ratio | 24 | -0.0150 | -1.9985 | 0.6667 | True | 72 |
| taker_buy_ratio_z24 | 1 | -0.0108 | -1.0413 | 0.6667 | True | 72 |
| taker_buy_ratio_z24 | 4 | 0.0051 | 0.5084 | 0.6000 | True | 72 |
| taker_buy_ratio_z24 | 12 | 0.0040 | 0.3882 | 0.5333 | True | 72 |
| taker_buy_ratio_z24 | 24 | -0.0170 | -2.0838 | 0.6000 | True | 72 |
| taker_buy_ratio_z72 | 1 | -0.0149 | -1.4530 | 0.7333 | True | 72 |
| taker_buy_ratio_z72 | 4 | 0.0001 | 0.0095 | 0.5333 | True | 72 |
| taker_buy_ratio_z72 | 12 | 0.0025 | 0.2943 | 0.4667 | True | 72 |
| taker_buy_ratio_z72 | 24 | -0.0135 | -2.2741 | 0.8000 | True | 72 |
| taker_delta_4h | 1 | -0.0191 | -2.3177 | 0.6667 | True | 72 |
| taker_delta_4h | 4 | 0.0024 | 0.1739 | 0.5333 | True | 72 |
| taker_delta_4h | 12 | 0.0062 | 0.4261 | 0.5333 | True | 72 |
| taker_delta_4h | 24 | -0.0070 | -0.3892 | 0.4667 | True | 72 |
| taker_delta_12h | 1 | -0.0265 | -4.0801 | 0.9333 | False | 72 |
| taker_delta_12h | 4 | -0.0132 | -0.9935 | 0.6667 | True | 72 |
| taker_delta_12h | 12 | -0.0108 | -0.4024 | 0.6000 | True | 72 |
| taker_delta_12h | 24 | 0.0047 | 0.1454 | 0.8000 | True | 72 |
| taker_delta_24h | 1 | -0.0334 | -3.4993 | 0.8667 | False | 72 |
| taker_delta_24h | 4 | -0.0264 | -1.4018 | 0.6000 | True | 72 |
| taker_delta_24h | 12 | -0.0041 | -0.1283 | 0.4000 | True | 72 |
| taker_delta_24h | 24 | 0.0218 | 0.6195 | 0.6667 | True | 72 |
| taker_buy_ratio_15m | 1 | -0.0351 | -3.1956 | 0.8000 | False | 72 |
| taker_buy_ratio_15m | 4 | -0.0096 | -0.8973 | 0.6000 | True | 72 |
| taker_buy_ratio_15m | 12 | 0.0035 | 0.3732 | 0.5333 | True | 72 |
| taker_buy_ratio_15m | 24 | 0.0074 | 0.6815 | 0.6667 | True | 72 |
| taker_buy_ratio_15m_z24 | 1 | -0.0339 | -3.2189 | 0.8000 | False | 72 |
| taker_buy_ratio_15m_z24 | 4 | -0.0152 | -1.3884 | 0.5333 | True | 72 |
| taker_buy_ratio_15m_z24 | 12 | -0.0087 | -0.8983 | 0.6667 | True | 72 |
| taker_buy_ratio_15m_z24 | 24 | -0.0102 | -1.3320 | 0.6000 | True | 72 |
| above_ema50_1h | 1 | -0.0264 | -3.8332 | 0.8667 | False | 72 |
| above_ema50_1h | 4 | -0.0419 | -2.4774 | 0.8667 | True | 72 |
| above_ema50_1h | 12 | -0.0436 | -1.6618 | 0.6667 | True | 72 |
| above_ema50_1h | 24 | -0.0462 | -1.5948 | 0.8000 | True | 72 |
| above_ema200_1h | 1 | -0.0347 | -5.2475 | 0.9333 | False | 72 |
| above_ema200_1h | 4 | -0.0602 | -3.7022 | 0.9333 | False | 72 |
| above_ema200_1h | 12 | -0.0919 | -3.7058 | 0.8667 | False | 72 |
| above_ema200_1h | 24 | -0.1088 | -3.6718 | 0.8667 | False | 72 |

## OOS confirmation (single pass)

| feature | horizon | mean_ic | ic_tstat | ic_sign_pct | likely_noise | n_features_tested |
| --- | --- | --- | --- | --- | --- | --- |
| taker_buy_ratio | 1 | -0.0074 | -0.5951 | 0.6364 | True | 72 |
| taker_buy_ratio | 4 | 0.0002 | 0.0244 | 0.4545 | True | 72 |
| taker_buy_ratio | 12 | -0.0069 | -0.4492 | 0.4545 | True | 72 |
| taker_buy_ratio | 24 | 0.0060 | 0.3285 | 0.5455 | True | 72 |
| taker_buy_ratio_z24 | 1 | -0.0019 | -0.1611 | 0.6364 | True | 72 |
| taker_buy_ratio_z24 | 4 | 0.0026 | 0.2770 | 0.3636 | True | 72 |
| taker_buy_ratio_z24 | 12 | -0.0034 | -0.3264 | 0.4545 | True | 72 |
| taker_buy_ratio_z24 | 24 | 0.0082 | 0.9657 | 0.5455 | True | 72 |
| taker_buy_ratio_z72 | 1 | -0.0044 | -0.3466 | 0.6364 | True | 72 |
| taker_buy_ratio_z72 | 4 | 0.0040 | 0.4414 | 0.3636 | True | 72 |
| taker_buy_ratio_z72 | 12 | 0.0009 | 0.0525 | 0.4545 | True | 72 |
| taker_buy_ratio_z72 | 24 | 0.0135 | 0.7754 | 0.7273 | True | 72 |
| taker_delta_4h | 1 | -0.0127 | -1.4654 | 0.6364 | True | 72 |
| taker_delta_4h | 4 | -0.0179 | -1.0319 | 0.7273 | True | 72 |
| taker_delta_4h | 12 | -0.0068 | -0.1778 | 0.5455 | True | 72 |
| taker_delta_4h | 24 | 0.0069 | 0.1422 | 0.4545 | True | 72 |
| taker_delta_12h | 1 | -0.0189 | -1.3931 | 0.8182 | True | 72 |
| taker_delta_12h | 4 | -0.0360 | -1.4222 | 0.7273 | True | 72 |
| taker_delta_12h | 12 | -0.0087 | -0.1658 | 0.6364 | True | 72 |
| taker_delta_12h | 24 | -0.0179 | -0.2674 | 0.7273 | True | 72 |
| taker_delta_24h | 1 | -0.0133 | -1.2180 | 0.7273 | True | 72 |
| taker_delta_24h | 4 | -0.0268 | -0.9697 | 0.7273 | True | 72 |
| taker_delta_24h | 12 | -0.0223 | -0.4033 | 0.6364 | True | 72 |
| taker_delta_24h | 24 | -0.0297 | -0.3659 | 0.6364 | True | 72 |
| taker_buy_ratio_15m | 1 | 0.0246 | 2.0165 | 0.6364 | True | 72 |
| taker_buy_ratio_15m | 4 | 0.0099 | 0.6967 | 0.6364 | True | 72 |
| taker_buy_ratio_15m | 12 | 0.0052 | 0.3194 | 0.4545 | True | 72 |
| taker_buy_ratio_15m | 24 | 0.0157 | 1.3108 | 0.7273 | True | 72 |
| taker_buy_ratio_15m_z24 | 1 | 0.0204 | 1.6931 | 0.5455 | True | 72 |
| taker_buy_ratio_15m_z24 | 4 | 0.0073 | 0.5867 | 0.6364 | True | 72 |
| taker_buy_ratio_15m_z24 | 12 | 0.0004 | 0.0250 | 0.4545 | True | 72 |
| taker_buy_ratio_15m_z24 | 24 | 0.0118 | 0.9221 | 0.5455 | True | 72 |
| above_ema50_1h | 1 | -0.0335 | -3.4979 | 0.9091 | False | 72 |
| above_ema50_1h | 4 | -0.0371 | -1.5055 | 0.9091 | True | 72 |
| above_ema50_1h | 12 | -0.0417 | -0.9248 | 0.7273 | True | 72 |
| above_ema50_1h | 24 | -0.0633 | -1.0445 | 0.6364 | True | 72 |
| above_ema200_1h | 1 | -0.0285 | -4.7383 | 0.9091 | False | 72 |
| above_ema200_1h | 4 | -0.0472 | -3.6324 | 0.8182 | False | 72 |
| above_ema200_1h | 12 | -0.0750 | -2.8510 | 0.7273 | True | 72 |
| above_ema200_1h | 24 | -0.1446 | -3.9388 | 0.9091 | False | 72 |

## Quintile spreads vs round-trip cost (low-fee)
Round-trip cost fraction used: **0.0012**

### IS
- **taker_buy_ratio**: top-bottom -0.0016
- **taker_buy_ratio_z24**: top-bottom -0.0014
- **taker_buy_ratio_z72**: top-bottom -0.0003
- **taker_delta_4h**: top-bottom 0.0002
- **taker_delta_12h**: top-bottom 0.0008
- **taker_delta_24h**: top-bottom 0.0023
- **taker_buy_ratio_15m**: top-bottom 0.0009
- **taker_buy_ratio_15m_z24**: top-bottom -0.0003
- **above_ema50_1h**: top-bottom -0.0014
- **above_ema200_1h**: top-bottom -0.0016
- **above_ema50_4h**: top-bottom -0.0004
- **above_ema200_4h**: top-bottom -0.0043
- **atr_pct**: top-bottom 0.0021
- **realized_vol_24h**: top-bottom 0.0032
- **weekday**: top-bottom 0.0001
- **setup_score**: top-bottom -0.0068
- **has_breakout**: top-bottom -0.0068
- **has_pullback**: top-bottom -0.0068

### OOS
- **taker_buy_ratio**: top-bottom 0.0012
- **taker_buy_ratio_z24**: top-bottom 0.0018
- **taker_buy_ratio_z72**: top-bottom 0.0020
- **taker_delta_4h**: top-bottom 0.0014
- **taker_delta_12h**: top-bottom 0.0007
- **taker_delta_24h**: top-bottom 0.0009
- **taker_buy_ratio_15m**: top-bottom 0.0005
- **taker_buy_ratio_15m_z24**: top-bottom 0.0005
- **above_ema50_1h**: top-bottom 0.0007
- **above_ema200_1h**: top-bottom 0.0009
- **above_ema50_4h**: top-bottom 0.0002
- **above_ema200_4h**: top-bottom 0.0055
- **atr_pct**: top-bottom -0.0080
- **realized_vol_24h**: top-bottom -0.0109
- **weekday**: top-bottom 0.0012
- **setup_score**: top-bottom -0.0025
- **has_breakout**: top-bottom -0.0025
- **has_pullback**: top-bottom -0.0025

## Simple rule backtests (top/bottom quintile)

### IS
- trades=5671 win_rate=0.00% net_E=-0.1997 PF=0.55

### OOS
- trades=5 win_rate=0.00% net_E=-0.2102 PF=0.43

## Spearman correlation (top features)
| above_ema200_1h | taker_delta_12h | above_ema50_1h | above_ema50_4h | above_ema200_4h |
| --- | --- | --- | --- | --- |
| 1.0000 | 0.1420 | 0.5610 | 0.9070 | 0.4130 |
| 0.1420 | 1.0000 | 0.4140 | 0.1020 | -0.0530 |
| 0.5610 | 0.4140 | 1.0000 | 0.5150 | 0.1750 |
| 0.9070 | 0.1020 | 0.5150 | 1.0000 | 0.4210 |
| 0.4130 | -0.0530 | 0.1750 | 0.4210 | 1.0000 |

## Plain-English verdicts
- **taker_buy_ratio**: noise
- **taker_buy_ratio_z24**: noise
- **taker_buy_ratio_z72**: noise
- **taker_delta_4h**: noise
- **taker_delta_12h**: weak
- **taker_delta_24h**: weak
- **taker_buy_ratio_15m**: weak
- **taker_buy_ratio_15m_z24**: weak
- **above_ema50_1h**: weak
- **above_ema200_1h**: weak
- **above_ema50_4h**: weak
- **above_ema200_4h**: noise
- **atr_pct**: noise
- **realized_vol_24h**: noise
- **weekday**: noise
- **setup_score**: noise
- **has_breakout**: noise
- **has_pullback**: noise
## SOLUSDT

Generated 2026-11-22T17:42:10.613349+00:00 | features tested: **18** (|t| < 3.0 flagged as likely noise)

## IS selection (exploration)

| feature | horizon | mean_ic | ic_tstat | ic_sign_pct | likely_noise | n_features_tested |
| --- | --- | --- | --- | --- | --- | --- |
| taker_buy_ratio | 1 | -0.0247 | -3.2311 | 0.8667 | False | 72 |
| taker_buy_ratio | 4 | -0.0089 | -1.2915 | 0.6000 | True | 72 |
| taker_buy_ratio | 12 | 0.0001 | 0.0080 | 0.5333 | True | 72 |
| taker_buy_ratio | 24 | 0.0024 | 0.3021 | 0.5333 | True | 72 |
| taker_buy_ratio_z24 | 1 | -0.0250 | -3.1027 | 0.8667 | False | 72 |
| taker_buy_ratio_z24 | 4 | -0.0125 | -1.5091 | 0.6667 | True | 72 |
| taker_buy_ratio_z24 | 12 | -0.0112 | -1.4119 | 0.6000 | True | 72 |
| taker_buy_ratio_z24 | 24 | -0.0109 | -1.5772 | 0.6667 | True | 72 |
| taker_buy_ratio_z72 | 1 | -0.0246 | -3.0844 | 0.8667 | False | 72 |
| taker_buy_ratio_z72 | 4 | -0.0081 | -1.0935 | 0.6000 | True | 72 |
| taker_buy_ratio_z72 | 12 | -0.0005 | -0.0563 | 0.4667 | True | 72 |
| taker_buy_ratio_z72 | 24 | 0.0001 | 0.0108 | 0.4667 | True | 72 |
| taker_delta_4h | 1 | -0.0194 | -1.9009 | 0.7333 | True | 72 |
| taker_delta_4h | 4 | 0.0092 | 0.6408 | 0.4000 | True | 72 |
| taker_delta_4h | 12 | 0.0094 | 0.5174 | 0.6667 | True | 72 |
| taker_delta_4h | 24 | 0.0209 | 1.1567 | 0.6000 | True | 72 |
| taker_delta_12h | 1 | -0.0210 | -2.9878 | 0.7333 | True | 72 |
| taker_delta_12h | 4 | -0.0046 | -0.2620 | 0.4667 | True | 72 |
| taker_delta_12h | 12 | 0.0150 | 0.7185 | 0.6000 | True | 72 |
| taker_delta_12h | 24 | 0.0485 | 1.8402 | 0.6667 | True | 72 |
| taker_delta_24h | 1 | -0.0185 | -2.2129 | 0.6667 | True | 72 |
| taker_delta_24h | 4 | 0.0030 | 0.1594 | 0.4667 | True | 72 |
| taker_delta_24h | 12 | 0.0315 | 1.2991 | 0.7333 | True | 72 |
| taker_delta_24h | 24 | 0.0520 | 1.8457 | 0.6667 | True | 72 |
| taker_buy_ratio_15m | 1 | -0.0311 | -2.9090 | 0.8000 | True | 72 |
| taker_buy_ratio_15m | 4 | -0.0097 | -1.0389 | 0.4667 | True | 72 |
| taker_buy_ratio_15m | 12 | 0.0057 | 0.5712 | 0.4667 | True | 72 |
| taker_buy_ratio_15m | 24 | -0.0002 | -0.0149 | 0.5333 | True | 72 |
| taker_buy_ratio_15m_z24 | 1 | -0.0317 | -3.0880 | 0.8000 | False | 72 |
| taker_buy_ratio_15m_z24 | 4 | -0.0123 | -1.6486 | 0.6667 | True | 72 |
| taker_buy_ratio_15m_z24 | 12 | 0.0060 | 0.6796 | 0.5333 | True | 72 |
| taker_buy_ratio_15m_z24 | 24 | -0.0031 | -0.3140 | 0.4667 | True | 72 |
| above_ema50_1h | 1 | -0.0202 | -2.5426 | 0.6667 | True | 72 |
| above_ema50_1h | 4 | -0.0345 | -1.9916 | 0.5333 | True | 72 |
| above_ema50_1h | 12 | -0.0388 | -1.6778 | 0.6000 | True | 72 |
| above_ema50_1h | 24 | -0.0463 | -1.7094 | 0.7333 | True | 72 |
| above_ema200_1h | 1 | -0.0217 | -1.7813 | 0.6667 | True | 72 |
| above_ema200_1h | 4 | -0.0410 | -1.9108 | 0.6667 | True | 72 |
| above_ema200_1h | 12 | -0.0644 | -2.0467 | 0.6667 | True | 72 |
| above_ema200_1h | 24 | -0.0874 | -2.0984 | 0.6667 | True | 72 |

## OOS confirmation (single pass)

| feature | horizon | mean_ic | ic_tstat | ic_sign_pct | likely_noise | n_features_tested |
| --- | --- | --- | --- | --- | --- | --- |
| taker_buy_ratio | 1 | -0.0282 | -2.4916 | 0.8182 | True | 72 |
| taker_buy_ratio | 4 | -0.0117 | -0.8159 | 0.6364 | True | 72 |
| taker_buy_ratio | 12 | -0.0051 | -0.2429 | 0.7273 | True | 72 |
| taker_buy_ratio | 24 | 0.0118 | 0.5969 | 0.4545 | True | 72 |
| taker_buy_ratio_z24 | 1 | -0.0258 | -2.1401 | 0.7273 | True | 72 |
| taker_buy_ratio_z24 | 4 | -0.0106 | -0.7859 | 0.6364 | True | 72 |
| taker_buy_ratio_z24 | 12 | -0.0071 | -0.3439 | 0.9091 | True | 72 |
| taker_buy_ratio_z24 | 24 | -0.0014 | -0.0846 | 0.7273 | True | 72 |
| taker_buy_ratio_z72 | 1 | -0.0243 | -1.9804 | 0.7273 | True | 72 |
| taker_buy_ratio_z72 | 4 | -0.0064 | -0.3788 | 0.5455 | True | 72 |
| taker_buy_ratio_z72 | 12 | 0.0024 | 0.0935 | 0.1818 | True | 72 |
| taker_buy_ratio_z72 | 24 | 0.0195 | 0.8042 | 0.6364 | True | 72 |
| taker_delta_4h | 1 | -0.0299 | -2.5707 | 0.7273 | True | 72 |
| taker_delta_4h | 4 | -0.0260 | -1.1181 | 0.7273 | True | 72 |
| taker_delta_4h | 12 | -0.0008 | -0.0221 | 0.5455 | True | 72 |
| taker_delta_4h | 24 | -0.0051 | -0.1511 | 0.5455 | True | 72 |
| taker_delta_12h | 1 | -0.0237 | -1.7109 | 0.6364 | True | 72 |
| taker_delta_12h | 4 | -0.0271 | -1.1103 | 0.7273 | True | 72 |
| taker_delta_12h | 12 | -0.0177 | -0.4594 | 0.7273 | True | 72 |
| taker_delta_12h | 24 | -0.0351 | -0.8992 | 0.6364 | True | 72 |
| taker_delta_24h | 1 | -0.0242 | -2.3759 | 0.8182 | True | 72 |
| taker_delta_24h | 4 | -0.0430 | -1.9799 | 0.7273 | True | 72 |
| taker_delta_24h | 12 | -0.0555 | -1.5015 | 0.7273 | True | 72 |
| taker_delta_24h | 24 | -0.0322 | -0.8061 | 0.6364 | True | 72 |
| taker_buy_ratio_15m | 1 | 0.0031 | 0.2943 | 0.7273 | True | 72 |
| taker_buy_ratio_15m | 4 | 0.0009 | 0.1442 | 0.5455 | True | 72 |
| taker_buy_ratio_15m | 12 | 0.0015 | 0.0749 | 0.5455 | True | 72 |
| taker_buy_ratio_15m | 24 | 0.0157 | 1.0848 | 0.7273 | True | 72 |
| taker_buy_ratio_15m_z24 | 1 | 0.0019 | 0.1607 | 0.7273 | True | 72 |
| taker_buy_ratio_15m_z24 | 4 | -0.0013 | -0.1472 | 0.5455 | True | 72 |
| taker_buy_ratio_15m_z24 | 12 | -0.0043 | -0.1771 | 0.7273 | True | 72 |
| taker_buy_ratio_15m_z24 | 24 | 0.0074 | 0.3752 | 0.3636 | True | 72 |
| above_ema50_1h | 1 | -0.0313 | -3.6184 | 0.9091 | False | 72 |
| above_ema50_1h | 4 | -0.0412 | -2.4423 | 0.8182 | True | 72 |
| above_ema50_1h | 12 | -0.0465 | -1.2993 | 0.6364 | True | 72 |
| above_ema50_1h | 24 | -0.0621 | -1.2538 | 0.7273 | True | 72 |
| above_ema200_1h | 1 | -0.0397 | -3.5608 | 0.8182 | False | 72 |
| above_ema200_1h | 4 | -0.0588 | -4.1694 | 0.9091 | False | 72 |
| above_ema200_1h | 12 | -0.0616 | -2.4710 | 0.8182 | True | 72 |
| above_ema200_1h | 24 | -0.0955 | -2.6865 | 0.8182 | True | 72 |

## Quintile spreads vs round-trip cost (low-fee)
Round-trip cost fraction used: **0.0012**

### IS
- **taker_buy_ratio**: top-bottom 0.0015
- **taker_buy_ratio_z24**: top-bottom 0.0001
- **taker_buy_ratio_z72**: top-bottom 0.0011
- **taker_delta_4h**: top-bottom 0.0032
- **taker_delta_12h**: top-bottom 0.0063
- **taker_delta_24h**: top-bottom 0.0065
- **taker_buy_ratio_15m**: top-bottom 0.0011
- **taker_buy_ratio_15m_z24**: top-bottom 0.0002
- **above_ema50_1h**: top-bottom -0.0022
- **above_ema200_1h**: top-bottom -0.0036
- **above_ema50_4h**: top-bottom -0.0038
- **above_ema200_4h**: top-bottom -0.0007
- **atr_pct**: top-bottom 0.0059
- **realized_vol_24h**: top-bottom 0.0071
- **weekday**: top-bottom -0.0009
- **setup_score**: top-bottom -0.0099
- **has_breakout**: top-bottom -0.0099
- **has_pullback**: top-bottom -0.0099

### OOS
- **taker_buy_ratio**: top-bottom 0.0012
- **taker_buy_ratio_z24**: top-bottom -0.0003
- **taker_buy_ratio_z72**: top-bottom 0.0010
- **taker_delta_4h**: top-bottom 0.0002
- **taker_delta_12h**: top-bottom 0.0002
- **taker_delta_24h**: top-bottom 0.0029
- **taker_buy_ratio_15m**: top-bottom -0.0011
- **taker_buy_ratio_15m_z24**: top-bottom -0.0013
- **above_ema50_1h**: top-bottom 0.0006
- **above_ema200_1h**: top-bottom 0.0030
- **above_ema50_4h**: top-bottom 0.0027
- **above_ema200_4h**: top-bottom 0.0098
- **atr_pct**: top-bottom -0.0046
- **realized_vol_24h**: top-bottom -0.0065
- **weekday**: top-bottom 0.0031
- **setup_score**: top-bottom -0.0029
- **has_breakout**: top-bottom -0.0029
- **has_pullback**: top-bottom -0.0029

## Simple rule backtests (top/bottom quintile)

### IS
- trades=11177 win_rate=0.00% net_E=-0.1630 PF=0.60

### OOS
- trades=5 win_rate=0.00% net_E=-0.8524 PF=0.00

## Spearman correlation (top features)
| taker_buy_ratio | taker_buy_ratio_z24 | taker_buy_ratio_15m_z24 | taker_buy_ratio_z72 | taker_delta_12h |
| --- | --- | --- | --- | --- |
| 1.0000 | 0.9670 | 0.3920 | 0.9840 | 0.2070 |
| 0.9670 | 1.0000 | 0.4030 | 0.9820 | 0.0790 |
| 0.3920 | 0.4030 | 1.0000 | 0.3990 | 0.0220 |
| 0.9840 | 0.9820 | 0.3990 | 1.0000 | 0.1460 |
| 0.2070 | 0.0790 | 0.0220 | 0.1460 | 1.0000 |

## Plain-English verdicts
- **taker_buy_ratio**: weak
- **taker_buy_ratio_z24**: weak
- **taker_buy_ratio_z72**: weak
- **taker_delta_4h**: noise
- **taker_delta_12h**: noise
- **taker_delta_24h**: noise
- **taker_buy_ratio_15m**: noise
- **taker_buy_ratio_15m_z24**: weak
- **above_ema50_1h**: noise
- **above_ema200_1h**: noise
- **above_ema50_4h**: noise
- **above_ema200_4h**: noise
- **atr_pct**: noise
- **realized_vol_24h**: noise
- **weekday**: noise
- **setup_score**: noise
- **has_breakout**: noise
- **has_pullback**: noise