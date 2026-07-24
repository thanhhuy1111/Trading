# Phase 04 — XGBoost

## Trạng thái

- 4A — Research & Design: **COMPLETE**
- 4B — Dataset & Labels: **COMPLETE**
- 4C — Training & Walk-forward: **COMPLETE**
- 4D — Approval & Artifact: **NEXT**
- 4E — Runtime Serving & Final Verification: PENDING

Phase 4C đã triển khai training/evaluation offline. Chưa tạo model artifact, approval state
hay runtime serving.

## 1. Kết quả khảo sát

### Thành phần có thể tái sử dụng

- `packages.features.pipeline.FeaturePipeline`: lọc candle đóng với
  `close_time <= as_of_time`, tính `standard_v1`, trả values, quality và candle lineage.
- `packages.features.models.FeatureSnapshot`: Pydantic contract frozen với validator chặn
  `lookback_end`/`event_time > as_of_time`.
- `packages.features.derivatives_pipeline.DerivativesFeaturePipeline`: lọc
  `exchange_timestamp <= as_of_time`, không impute, phân biệt `VALID`, `WARMING_UP`,
  `DEGRADED` và có sample lineage.
- `packages.market_data.derivatives_history.load_history`: point-in-time history read với
  `exchange_timestamp <= as_of`.
- `packages.features.registry` và `packages.features.derivatives_registry`: giữ nguyên hai
  calculator Protocol riêng vì `List[Candle]` và `List[DerivativesSnapshot]` không tương thích
  structural typing.
- `packages.registries.models.RegistryEntry` và
  `packages.registries.registry.ArtifactRegistry`: exact `(name, version)` lookup,
  compatibility scope và status transitions.
- `packages.retraining.price_projection`: pattern past-only feature construction, held-out
  evaluation, honest rejection và native JSON artifact.
- `packages.retraining.calibration`: Brier score pattern và validation-only calibration
  discipline.
- Pydantic, NumPy, pandas, scikit-learn và joblib đã nằm trong môi trường quan sát; Pydantic
  được dùng cho external/runtime contracts.
- Test patterns dùng fixture deterministic, `tmp_path`, monkeypatch và không gọi network.

### Thành phần không tái sử dụng nguyên trạng

- `WalkForwardRunner.generate_folds()` chia toàn khoảng thời gian thành các segment độc lập
  60/20/20; đây không phải expanding/rolling walk-forward và purge theo giờ không đảm bảo
  đúng horizon một bar. Phase 4C cần splitter theo sample/bar mới; có thể tái sử dụng
  `WalkForwardFold` làm record nếu không làm mất metadata.
- `packages.retraining.workflow` là binary logistic smoke workflow với triple-barrier label,
  một fold và artifact inline `RESEARCH_ONLY`; không đúng bài toán 3 lớp, approval gate hay
  artifact XGBoost của Phase 4.
- `_RegistryBackedMetaLabelService._find_entry()` hiện cho phép cả `APPROVED` và
  `RESEARCH_ONLY`. Runtime Phase 4E không được tái sử dụng behavior này; loader mới phải lọc
  duy nhất `RegistryEntryStatus.APPROVED`.
- `ArtifactRegistry.register()` cho phép ghi đè key và đăng ký trực tiếp bất kỳ status nào.
  Approval service Phase 4D phải tạo entry mới, từ chối duplicate và đi qua
  `DRAFT -> RESEARCH_ONLY -> VALIDATED -> APPROVED` hoặc trạng thái `REJECTED`; không coi
  registry generic là approval gate.
- `price_projection.write_artifact()` ghi một JSON không có schema/manifest/checksum
  verification và runtime loader đọc file trực tiếp. Chỉ reuse convention thư mục
  `data/research/models`, không reuse loader.
- Derivatives cache chỉ giữ 30 ngày và Binance endpoints không hỗ trợ arbitrary backfill.
  Vì vậy `price_plus_derivatives` có thể không đủ samples; phải trả thiếu dữ liệu trung thực,
  không sinh hoặc forward-fill history.

## 2. Bài toán được chốt

| Thuộc tính | Quyết định |
|---|---|
| Campaign/exchange symbol | `BTCUSDT` |
| Internal canonical symbol | `BTC/USDT`, chỉ map qua exact registered `SymbolInfo` |
| Spot exchange | `binance` |
| Derivatives exchange | `binance_usdm_futures` |
| Timeframe | `4h` (`Timeframe.H4`) |
| Horizon | 1 bar |
| Prediction as-of | deterministic source availability của candle đóng tại `t` |
| Target time | deterministic source availability của candle đóng kế tiếp `t + 1` |
| Classes | `BEARISH`, `NEUTRAL`, `BULLISH` |
| Random seed | `42` |
| Price feature set | `standard_v1`, version `1.0.0` |
| Derivatives feature set | `derivatives_v1`, version `1.0.0` |
| Dataset schema version | `xgb_direction_dataset_v1` |
| Label version | `volatility_band_1bar_v1` |

Dataset request nhận `BTCUSDT`, resolve đúng một lần qua entry có sẵn trong `SymbolRegistry`
thành `BTC/USDT`, rồi lưu cả `exchange_symbol` và `canonical_symbol`. Không dùng heuristic
`endswith("USDT")`, không normalize ở nhiều tầng. Mọi candle/derivatives record phải exact
canonical symbol, exchange và timeframe được yêu cầu; record lẫn symbol/exchange làm source
hoặc row bị reject với reason code, không được dùng chỉ vì cache filename trùng.

Spot candle phải exact `exchange="binance"`; derivatives record phải exact
`exchange="binance_usdm_futures"`. Hai venue được validate độc lập, không dùng một exchange
field chung. Input candle còn phải timezone-aware, closed, OHLC hợp lệ, không duplicate
`close_time`, tăng thời gian nghiêm ngặt và có khoảng cách đúng 4h. Gap không được tạo candle
giả; sample cần bar `t+1` liền kề sẽ bị loại với reason code và được đếm trong dataset report.

## 3. Label formula và threshold

Với candle đóng tại `t`:

```text
future_return[t] = close[t + 1] / close[t] - 1
rolling_volatility[t] = std(population) của 20 log-return một bar,
                        chỉ dùng candle có close_time <= as_of_time[t]
threshold[t] = k * rolling_volatility[t]

BULLISH khi future_return[t] > threshold[t]
BEARISH khi future_return[t] < -threshold[t]
NEUTRAL trong các trường hợp còn lại, bao gồm đúng biên ±threshold
```

Không thay rolling volatility thiếu bằng zero. Sample chưa đủ 21 candle quá khứ hoặc chưa có
candle `t+1` hợp lệ không có target class.

Candidate grid cố định:

```text
k in [0.25, 0.50, 0.75, 1.00]
```

Phase 4B xây labeler nhận `k` tường minh và report distribution cho từng candidate. Phase 4C
chọn `k` riêng trong mỗi fold chỉ từ training rows: chọn candidate có neutral share gần 30%
nhất, với điều kiện mỗi class có ít nhất 10% training rows; tie-break theo `k` nhỏ hơn. Nếu
không candidate nào đủ ba class, fold/dataset bị reject. Validation/test không được dùng để
chọn `k`. `k` của final artifact được chọn lại bằng cùng rule trên final training history,
không đọc final holdout.

## 4. Dataset modes và feature schema

### `price_only`

Feature order cố định:

```text
return_1p
return_3p
return_5p
high_low_range
ema_20_slope
adx_14
rsi_14
atr_14
volatility_20
relative_volume_20
zscore_20
bollinger_pos_20
donchian_breakout_20
```

Không impute missing value. `FeatureQualityStatus.INVALID` hoặc bất kỳ required feature
`None` nào làm sample không hợp lệ. `DEGRADED` chỉ được chấp nhận nếu mọi required feature
có giá trị thật và tất cả issue chỉ liên quan feature ngoài schema; quyết định phải được ghi
trong reason codes.

### `price_plus_derivatives`

Gồm toàn bộ `price_only` theo đúng order, sau đó:

```text
funding_rate_zscore_20
open_interest_roc_12
```

Mode này chỉ nhận `DerivativesFeatureSnapshot.quality_status == VALID`, mọi required value
khác `None`, và các source snapshot dùng cho calculator có trạng thái `HEALTHY`.

Derivatives window có cadence cố định 5 phút: tối thiểu 20 observations, mỗi cặp observations
cách 4–6 phút, latest observation không cũ quá 10 phút tại prediction as-of. Chỉ chọn một
real snapshot cho mỗi cutoff bằng backward selection; burst/sparse history hoặc gap vượt
tolerance bị reject, không resample/forward-fill. Cadence/tolerance là một phần của feature
schema/version.

`futures_basis_momentum_6` bị loại khỏi Phase 4 vì snapshot hiện tại không lưu timestamp/
lineage của spot reference dùng để tính basis. Chỉ được thêm lại trong version sau khi có
point-in-time lineage cho cả mark price và spot reference.

Không forward-fill qua gap, không dùng zero, không chuyển ngầm về `price_only`. Khi không đạt,
price-only row vẫn có thể tồn tại nhưng plus-derivatives row không được tạo và report reason
code như
`DERIVATIVES_HISTORY_MISSING`, `DERIVATIVES_WARMING_UP`,
`DERIVATIVES_FEATURES_INVALID`, `DERIVATIVES_CADENCE_INVALID`,
`DERIVATIVES_SOURCE_MISMATCH` hoặc `DERIVATIVES_SNAPSHOT_STALE`.

## 5. Point-in-time join

Cho mỗi candle `t`:

1. Với Binance closed kline, `source_available_at = close_time + 1 millisecond` theo declared
   source contract (Binance close timestamp là cuối interval, inclusive). `as_of_time` của
   row bằng `source_available_at`; provider khác phải khai báo deterministic publication lag
   hoặc bị reject.
2. Candle pipeline chỉ nhận candle có `source_available_at <= as_of_time`.
   `received_timestamp` chỉ là ingestion/audit time; không quyết định historical market
   availability và không đi vào deterministic checksum.
3. Mỗi derivatives metric phải lưu `event_time` và `available_at`, trong đó
   `available_at = max(received_timestamp, metric event time, contributing source times)`.
   Existing cached snapshot thiếu field-level availability bị reject khỏi plus mode, không
   được suy timestamp.
4. `load_history`/dataset boundary chỉ nhận metric có `available_at <= as_of_time`.
5. Join backward tới derivatives sample mới nhất thỏa availability/cadence; không nearest
   join hai chiều và không lấy sample tương lai.
6. Assert mọi price source availability và derivatives event/availability timestamp
   `<= as_of_time`.
7. Target lấy duy nhất từ candle liền kề tại `t+1`, với
   `target_time > as_of_time`; target fields không được đưa vào `feature_values` hay
   feature checksum.

Anti-lookahead test phải chứng minh việc append candles/snapshots tương lai không đổi
feature values, lineage, sample ID hay target của các rows đã đủ target trước đó. Test riêng
phải cover event timestamp trước boundary nhưng delayed receipt sau boundary, cùng metric có
mixed source timestamps.

## 6. Dataset contract

Mỗi row là Pydantic frozen model:

```text
sample_id
exchange_symbol
canonical_symbol
spot_exchange
derivatives_exchange
timeframe
as_of_time
target_time
close_at_as_of
future_close
future_return
rolling_volatility
label_threshold_k
label_threshold
target_class
dataset_mode
feature_names
feature_values
feature_status
feature_lineage
feature_available_at
ingestion_audit
dataset_version
```

`sample_id` là SHA-256 deterministic của
`dataset_version|dataset_mode|exchange_symbol|canonical_symbol|timeframe|as_of_time|`
`target_time|feature_schema_hash`.
Dataset checksum dùng canonical JSON sorted keys và không chứa UUID ngẫu nhiên,
`computed_at`, candle `received_timestamp`, `ingestion_audit` hay filesystem path.
Deterministic candle `source_available_at` và derivatives field-level `available_at` là
lineage kiểm chứng và được canonicalize vào dataset fingerprint. Dataset report gồm input/
accepted/rejected counts, reason-code counts, time range, checksum, feature schema hash và
class distribution theo count/share. Output rows sắp theo `(as_of_time, sample_id)`.

Mỗi built dataset và mỗi training/evaluation run chứa **đúng một** `dataset_mode`. Hai mode có
thể sinh từ cùng sources nhưng không được concat rồi split. Splitter group theo timestamp và
assert không `as_of_time`, `target_time` hay target interval nào xuất hiện ở hơn một partition.

## 7. Walk-forward design

Phase 4C dùng ba expanding folds trên ordered samples:

```text
Fold 1: train = lịch sử đầu -> trước 60%; validation = 60–70%; test = 70–80%
Fold 2: train = lịch sử đầu -> trước 70%; validation = 70–80%; test = 80–90%
Fold 3: train = lịch sử đầu -> trước 80%; validation = 80–90%; test = 90–100%
```

Tỷ lệ được tính trên unique ordered timestamp groups trong một dataset mode, không trên row
count hỗn hợp. Tại mỗi boundary, purge một sample horizon giữa train/validation và
validation/test. Với mọi row ở split trước, `target_time < as_of_time` đầu tiên của split sau.
Minimum mỗi fold: 200 train, 50 validation, 50 test rows và đủ cả ba class sau khi chọn `k`;
nếu không, fold invalid và toàn model không được approve. Không shuffle, không random split.

Mỗi fold lưu:

```text
fold_number
train_start / train_end
validation_start / validation_end
test_start / test_end
train_samples / validation_samples / test_samples
selected_k
class_distribution
baseline_metrics
model_metrics
reason_codes
```

## 8. Models và reproducibility

Baselines bắt buộc:

1. Majority-class lấy class phổ biến từ train; tie theo enum order
   `BEARISH, NEUTRAL, BULLISH`.
2. Seeded random dùng `numpy.random.default_rng(42 + fold_number)` và empirical training
   class probabilities.
3. Multinomial Logistic Regression với `StandardScaler` chỉ fit trên train; không fit
   scaler trên validation/test.
4. `XGBClassifier` với `objective="multi:softprob"`, fixed class mapping, `random_state=42`,
   `n_jobs=1` và deterministic, bounded hyperparameters được khai báo trong code/metadata.

Comparator contract tách `predict` và `predict_proba`:

- majority `predict` luôn trả training-majority class;
- random `predict` sample categorical theo empirical training priors và seeded RNG;
- cả hai `predict_proba` trả cùng empirical training-prior vector cho mỗi row, clip từng
  probability tại `1e-15` rồi renormalize theo class order cố định;
- labels và probability vectors đều được lưu, không dùng random one-hot làm log-loss input.

XGBoost probability phải được temperature-scale: fit đúng một scalar temperature trên
validation logits/labels, freeze trước khi đọc test, rồi apply lên test/runtime. Degenerate
validation hoặc calibration failure làm fold/model invalid. Final artifact lưu calibration
recipe/temperature. Không gọi raw `multi:softprob` là confidence.

Sau khi ba folds đã đánh giá và gate pass, final artifact có recipe cố định trên ordered
dataset mode đó:

1. Chọn final `k` bằng rule training-only trên prefix 0–90%.
2. Fit final base XGBoost trên prefix 0–90%.
3. Fit duy nhất temperature trên disjoint trailing 90–100% calibration window, tối thiểu
   50 rows và đủ ba classes.
4. Không bao giờ refit base model sau khi temperature đã fit.

Artifact lưu/checksum `base_train_start/end`, `calibration_start/end`, counts/distributions và
assert `base_train_end < calibration_start`. Final artifact path có test riêng; calibration
window không được dùng cho base model, threshold hay hyperparameters.

Không dùng test fold để chọn threshold, feature, hyperparameter, early stopping hay
calibration. Hyperparameters Phase 4C được fixed trước evaluation; nếu một version sau có
selection/early stopping, chỉ validation được dùng và mọi candidate result phải được lưu, kể
cả fold kém.

## 9. Metrics

Từng fold và aggregate phải lưu:

- accuracy;
- balanced accuracy;
- macro F1;
- multiclass MCC;
- log loss với explicit class order;
- multiclass Brier score `mean(sum((p_k - y_k)^2))`;
- expected calibration error với bins khai báo trước và reliability counts;
- 3x3 confusion matrix với class order cố định;
- sample count và class distribution.

Probability phải finite, mỗi giá trị trong `[0, 1]` và tổng mỗi row bằng 1 trong tolerance
`1e-6`. Không suy confidence từ decision score không chuẩn hóa.

## 10. Approval gate

Một XGBoost artifact chỉ `APPROVED` khi tất cả điều kiện sau đạt:

1. Dataset validation pass và checksum/schema/version hiện diện.
2. Anti-lookahead audit pass; mọi feature lineage `<= as_of_time`, mọi target
   `> as_of_time`.
3. Không có fabricated/imputed derivatives data.
4. Tất cả ba folds hợp lệ.
5. XGBoost balanced accuracy **strictly greater** majority baseline trên từng fold.
6. XGBoost macro F1 không thấp hơn majority baseline trên bất kỳ fold nào.
7. XGBoost MCC dương trên mọi fold.
8. Probability validation pass trên mọi prediction.
9. Calibrated XGBoost log loss và Brier score không tệ hơn empirical training-prior
   probability baseline trên từng fold.
10. Calibration chỉ fit validation, hiện diện trong artifact và round-trip được.
11. Artifact feature schema exact-match dataset schema.
12. Native model save/load round-trip tái tạo calibrated class probabilities trong
    tolerance `1e-9`.
13. Required offline tests pass.

Fail bất kỳ điều kiện nào:

```text
status = REJECTED
reason_codes = [machine-readable reasons]
```

Không approve để unblock 4E. Logistic/random/majority không phải candidate để approve trong
Phase 4; chúng là comparators.

## 11. Artifact structure

Runtime files đặt tại gitignored path:

```text
data/research/models/xgboost/btcusdt_4h/<model_version>/
├── model.json
├── metadata.json
├── feature_schema.json
├── evaluation.json
└── approval.json
```

- `model.json`: XGBoost native JSON từ `save_model`, không pickle.
- `metadata.json`: model ID/version, exact exchange/canonical symbol, separate spot/
  derivatives exchanges, timeframe/horizon, dataset mode/checksum, label/version/k,
  calibration, base-train/calibration ranges, library versions, seed, code commit, UTC
  timestamps.
- `feature_schema.json`: ordered names, dtypes, feature set names/versions và schema checksum.
- `evaluation.json`: mọi fold/baseline/model metrics, không bỏ fold kém.
- `approval.json`: `APPROVED` hoặc `REJECTED`, reason codes, gate version và checksums của bốn
  file còn lại.

Writer dùng staging directory rồi atomic rename; loader verify JSON schema, checksums và
cross-file metadata trước khi load model. `data/` đang gitignore nên không force-add weights.
Registry entry chỉ lưu location/checksum/compatibility và audit status; artifact files là
nguồn persistence.

`XGBoostApprovalService` là publisher duy nhất. Service tự recompute gate từ immutable
dataset/evaluation inputs, tạo entry ban đầu ở `DRAFT`, từ chối duplicate key/overwrite, rồi
own toàn bộ transitions. Runtime chỉ nhận read-only `ApprovedModelRepository`, không nhận
mutable generic registry. Forged `approval.json` hoặc direct-injected `APPROVED` registry
entry không đủ để load.

## 12. Runtime loader và prediction contract

Loader Phase 4E:

- nhận exact artifact version/model ID; nếu không truyền version, chỉ load khi đúng một
  approved artifact match, nhiều match trả `AMBIGUOUS_APPROVED_MODEL`;
- chỉ chấp nhận `approval.status == APPROVED` **và** registry entry
  `RegistryEntryStatus.APPROVED`;
- reject DRAFT, RESEARCH_ONLY, VALIDATED/EVALUATING-equivalent, REJECTED, DEGRADED, STALE,
  DISABLED và DEPRECATED-equivalent;
- verify exact symbol, timeframe, horizon, dataset mode, feature order/version/checksum,
  artifact checksums và feature/data status;
- không fallback sang Ridge, Logistic, heuristic hay unapproved model.

Pydantic output:

```json
{
  "status": "AVAILABLE",
  "direction": "BULLISH",
  "probabilities": {
    "bullish": 0.57,
    "neutral": 0.28,
    "bearish": 0.15
  },
  "confidence": 0.57,
  "model_id": "xgb_btcusdt_4h_v1",
  "feature_snapshot_id": "feature_snapshot_001",
  "prediction_time": "2026-07-24T08:00:00Z",
  "reason_codes": []
}
```

`confidence` chỉ bằng max **calibrated** probability đã validate; artifact thiếu calibration
không được approved/load. `prediction_time` là request as-of thực, timezone-aware; không tự
tạo timestamp thay cho dữ liệu thiếu. Khi không có model:

```json
{
  "status": "UNAVAILABLE",
  "direction": null,
  "probabilities": null,
  "confidence": null,
  "model_id": null,
  "feature_snapshot_id": null,
  "prediction_time": null,
  "reason_codes": ["NO_APPROVED_MODEL"]
}
```

## 13. Dependency decision

`pyproject.toml` hiện có NumPy/pandas và research extra có scikit-learn, nhưng thiếu direct
dependency `xgboost` và `joblib`. Môi trường Phase 4A có sklearn/joblib/numpy/pandas nhưng
không có xgboost.

Phase 4C phải thêm XGBoost vào research dependencies với bounded compatible range sau khi
xác nhận Python 3.12 environment. Native XGBoost JSON được chọn cho production artifact nên
joblib không cần cho model persistence; nếu StandardScaler của Logistic chỉ dùng trong cùng
evaluation process thì không cần artifact joblib. Không dựa vào transitive joblib dependency.

## 14. File plan

### Phase 4B

- `packages/retraining/xgboost_contracts.py`
- `packages/retraining/xgboost_dataset.py`
- `packages/market_data/derivatives_models.py` và public adapter/cache chỉ khi cần thêm
  field-level event/availability lineage; không mở rộng network scope;
- `tests/unit/test_xgboost_dataset.py`
- `docs/campaign/PROGRESS.md`

### Phase 4C

- `packages/retraining/xgboost_training.py`
- `pyproject.toml`
- `tests/unit/test_xgboost_training.py`
- `docs/campaign/PROGRESS.md`

### Phase 4D

- `packages/retraining/xgboost_artifacts.py`
- `packages/retraining/xgboost_approval.py`
- `tests/unit/test_xgboost_artifacts.py`
- `tests/unit/test_xgboost_approval.py`
- `docs/campaign/PROGRESS.md`

### Phase 4E

- `packages/retraining/xgboost_runtime.py`
- `tests/unit/test_xgboost_runtime.py`
- chỉ thêm API wiring nếu task 4E xác nhận cần thiết; không tích hợp Gemini/agent;
- `docs/campaign/PROGRESS.md`

Tên file có thể điều chỉnh nếu research ở task tương ứng tìm thấy conflict, nhưng không được
gộp các phase hoặc mở rộng scope âm thầm.

## 15. Test matrix

### 4B — Dataset & Labels

- success cho `price_only` và đủ history `price_plus_derivatives`;
- missing/short/stale/invalid derivatives history không tạo plus row;
- invalid symbol/timeframe, duplicate/out-of-order/gapped candles;
- legitimate spot/futures venue pair success; swapped/cross-venue record, wrong symbol và
  cache alias collision bị reject;
- threshold boundary bằng đúng `±threshold` -> `NEUTRAL`;
- append future candles/snapshots không đổi feature/lineage/sample;
- frozen-clock reload ở ingestion times khác nhau vẫn cho cùng historical rows/checksum;
- delayed receipt sau as-of và mixed source timestamps bị loại;
- sparse/bursty derivatives hoặc 5m cadence gap bị loại, không fill;
- basis feature không xuất hiện khi thiếu two-source point-in-time lineage;
- `target_time > as_of_time` và target không nằm trong features;
- deterministic rows/checksum/class report;
- no-network và filesystem chỉ `tmp_path`.

### 4C — Training

- expanding folds, one-bar purge và không overlap leakage;
- mỗi run chỉ một mode; timestamp group/target interval không cắt qua partitions;
- majority, seeded random, Logistic và XGBoost đều được evaluate;
- baseline label/probability semantics và class order đúng contract;
- seed reproducibility;
- threshold/scaler/hyperparameter/calibration không fit trên test;
- validation-only temperature scaling và calibration round-trip;
- final base-train/calibration windows disjoint, ordered, checksummed và không refit base model;
- all metrics/probabilities/confusion matrix hợp lệ;
- class missing, empty/undersized fold và invalid probability bị reject;
- mọi fold, kể cả fold kém, hiện trong report.

### 4D — Approval & Artifact

- strong fixture pass gate; weak/noise fixture `REJECTED`;
- leakage/dataset/schema/probability/fold failures có reason code;
- write/load round-trip probabilities;
- checksum tamper, missing file, schema mismatch, duplicate version và wrong compatibility
  đều safe reject;
- direct `APPROVED` injection, duplicate overwrite, forged approval JSON,
  approval/evaluation checksum mismatch và rejected resurrection đều bị chặn;
- rejected artifact không chuyển approved;
- filesystem dùng `tmp_path`.

### 4E — Runtime

- approved exact-match success;
- no model -> `NO_APPROVED_MODEL`;
- DRAFT/RESEARCH_ONLY/VALIDATED/REJECTED/DEGRADED/STALE/DISABLED không load;
- wrong symbol/timeframe/horizon/version/schema/feature status bị reject;
- missing feature không impute;
- probability/confidence/timestamp validation;
- uncalibrated artifact không load và confidence không dùng raw softprob;
- corrupted/tampered artifact safe rejection;
- deterministic output với fixed inputs/clock; no network.

## 16. Acceptance criteria Phase 4A

- [x] Đã khảo sát retraining, price projection, candle/derivatives pipelines, registry,
  artifact conventions, dependencies và tests.
- [x] Đã chốt symbol, timeframe, horizon, classes, formula và threshold strategy.
- [x] Đã chốt dataset schema, modes, temporal join và missing derivatives behavior.
- [x] Đã chốt baselines, expanding split, metrics và approval gate.
- [x] Đã chốt artifact, runtime loader, file plan và test matrix.
- [x] Đã liệt kê open risks.
- [x] Không sửa production code.
- [x] Không tạo model/artifact hoặc approval giả.

## 17. Acceptance criteria Phase 4B

- [x] Pydantic frozen dataset/label/lineage/report contracts có version.
- [x] `price_only` và `price_plus_derivatives` build riêng, deterministic và không fallback
  qua lại.
- [x] Exact registered mapping `BTCUSDT -> BTC/USDT`; wrong symbol/exchange/timeframe và cache
  alias contamination bị reject.
- [x] Spot `binance` và derivatives `binance_usdm_futures` được lưu/validate độc lập; correct
  pair success, swapped/cross-venue pair reject.
- [x] Candle source availability deterministic theo close contract; ingestion time chỉ audit;
  reload ở clocks khác nhau không đổi rows/checksum.
- [x] Feature availability dùng `available_at`, không chỉ event time; delayed receipt và
  mixed-source timestamps có offline tests.
- [x] Derivatives cadence 5m/tolerance/gaps được enforce; history thiếu/legacy không có lineage
  bị reject, không fill/zero.
- [x] Basis feature bị loại đến khi có two-source point-in-time lineage.
- [x] Mọi feature lineage `<= as_of_time`, mọi target `> as_of_time`; append future inputs
  không đổi row quá khứ.
- [x] Label boundary, missing history, invalid input, gap, deterministic checksum và class
  distribution tests pass offline.
- [x] Không có trainer, approval service hoặc runtime serving trong 4B.
- [x] Targeted Ruff/mypy/pytest đạt; full baseline không xấu đi; progress được cập nhật.

## 18. Acceptance criteria Phase 4C

- [x] Split theo unique timestamp groups trong đúng một dataset mode; ba expanding folds và
  one-bar purge thỏa no-overlap target interval.
- [x] Majority, seeded random, Logistic Regression và XGBoost đều chạy với fixed class order.
- [x] Baseline `predict`/`predict_proba` đúng semantics đã chốt và deterministic.
- [x] `k`, scaler, model và temperature calibration không đọc test data.
- [x] Final base model fit trên 0–90%, calibration fit disjoint 90–100%, chronology được
  checksum và base model không refit sau calibration.
- [x] Mọi fold lưu đủ train/validation/test ranges, counts, class distributions, labels,
  probabilities, metrics và reason codes; không bỏ fold kém.
- [x] Accuracy, balanced accuracy, macro F1, MCC, log loss, Brier, ECE và confusion matrix
  được tính/validate.
- [x] Probability finite, bounded và sum-to-one; calibration failure safe reject.
- [x] Missing class/undersized fold/invalid probability có offline tests; seed reproducibility
  pass.
- [x] Không triển khai approval registry hoặc runtime serving trong 4C.
- [x] Targeted/full verification và progress update hoàn tất, safety flags không đổi.

## 19. Acceptance criteria Phase 4D

- [x] `XGBoostApprovalService` là write authority duy nhất, recompute toàn gate từ immutable
  inputs, từ chối duplicate/overwrite và direct-approved injection.
- [x] Tất cả per-fold gates, leakage/schema/probability/calibration checks phải pass mới
  transition tới `APPROVED`; mọi fail tạo `REJECTED` với reason codes.
- [x] Weak/noise model, forged approval JSON, checksum mismatch, schema mismatch, duplicate
  version và rejected resurrection đều safe reject.
- [x] Năm artifact files được write atomic dưới `tmp_path` trong tests; native JSON round-trip
  tái tạo calibrated probabilities.
- [x] Rejected artifact không được load/publish approved; không approve chỉ để unblock 4E.
- [x] Model weights dưới `data/` không force-add vào Git; không chứa secret.
- [x] Không triển khai runtime API trong 4D.
- [x] Targeted/full verification và progress update hoàn tất, safety flags không đổi.

## 20. Acceptance criteria Phase 4E

- [ ] Runtime dùng read-only approved repository và exact model/version/symbol/timeframe/
  horizon/mode/schema matching.
- [ ] Chỉ dual-verified `APPROVED` artifact được load; mọi trạng thái khác, direct registry
  injection, forged/tampered/uncalibrated artifact bị reject.
- [ ] Không model trả `UNAVAILABLE` + `NO_APPROVED_MODEL`, không fallback heuristic/model khác.
- [ ] Missing/invalid/stale feature data trả reason code, không impute hay bịa timestamp.
- [ ] `confidence` chỉ từ calibrated probability; probability/class order/timestamp contracts
  được validate.
- [ ] Runtime tests offline cover success, no model, all unsafe statuses, wrong compatibility,
  missing feature, corruption và deterministic fixed-clock output.
- [ ] Không tích hợp Gemini, Technical Agent hoặc Phase 5.
- [ ] Targeted/full pytest, Ruff, mypy, diff/safety review hoàn tất và progress được cập nhật.

## 21. Acceptance criteria toàn Phase 4

- [ ] 4A–4E hoàn thành tuần tự; không bỏ phase.
- [ ] Có deterministic point-in-time datasets, label pipeline, two modes, lineage/version và
  anti-lookahead/availability tests.
- [ ] Có đủ four-model evaluation, expanding walk-forward và per-fold/full metrics.
- [ ] Có fail-closed approval/rejection, artifact checksums/round-trip và bypass tests.
- [ ] Runtime approved-only, exact schema/compatibility, `NO_APPROVED_MODEL` và không fabricated
  confidence/data/timestamp.
- [ ] Test mới 100% offline; Ruff clean; mypy không vượt baseline; full pytest không có
  regression mới.
- [ ] `LIVE_TRADING_ENABLED`, `PRIVATE_EXCHANGE_API_ENABLED` và live feature flag vẫn `False`;
  không private API, secret, order hay withdrawal path.
- [ ] `PROGRESS.md` ghi commands/kết quả thật, known issues, commit và push status.
- [ ] Mỗi task đạt criteria mới commit/push `main`; không PR; Phase 5 vẫn chưa bắt đầu.

## 22. Open risks

1. Derivatives cache retention 30 ngày và polling không đều có thể không đủ 300+ valid 4h
   samples với complete 5m windows; `price_plus_derivatives` có thể phải dừng ở
   `INSUFFICIENT_DERIVATIVES_HISTORY`.
2. XGBoost chưa cài/khai báo; Phase 4C cần Python 3.12 environment tái lập được.
3. Repo không có committed lockfile; Phase 4A đã tạo local gitignored Python 3.12 `.venv`,
   nhưng dependency versions cần được pin/bounded để CI tái lập.
4. Model performance/approval không được giả định; Phase 4D có thể kết thúc bằng REJECTED và
   Phase 4E phải trả `NO_APPROVED_MODEL`.
5. In-memory generic registry không tự persistence và vẫn cho initial direct-status
   registration; Phase 4D đã làm entry append-only/deeply immutable, nhưng Phase 4E vẫn phải
   dual-verify private approval receipt để direct injection không thành trusted approval.
6. Existing meta-label runtime chấp nhận `RESEARCH_ONLY`; XGBoost runtime phải độc lập và
   approved-only. Việc migrate meta-label service cũ ngoài Phase 4 nếu không trực tiếp cần cho
   quantitative prediction contract.
7. `standard_v1` có version string tách giữa name (`standard_v1`) và snapshot version
   (`1.0.0`); artifact phải lưu và validate cả hai để tránh mismatch.
8. `computed_at` và snapshot UUID hiện không deterministic; dataset fingerprint phải loại
   chúng và dùng canonical values/lineage.
9. Volatility regimes và class balance có thể drift; threshold selection report phải được
   giữ theo fold, không che giấu class collapse.
10. Existing derivatives snapshots không có field-level event/availability lineage; plus mode
    phải reject legacy data cho đến khi Phase 4B bổ sung contract và real polls tích lũy.
