# 공사장 안전고리 체결 판별 시스템 고도화 보고서

## 1. 프로젝트 목적

본 프로젝트의 목적은 공사 현장 영상에서 작업자와 안전장비를 탐지하고, 작업자의 안전고리(hook)가 실제로 체결되었는지를 자동으로 판별하여 위험 상황을 빠르게 알리는 것이다.

안전 시스템에서 가장 치명적인 오류는 실제 미체결 상태를 안전하다고 판단하는 `False SAFE`이다. 따라서 전체 정확도만 높이는 것이 아니라 다음 우선순위로 시스템을 고도화했다.

1. 실제 미체결을 최대한 놓치지 않는다.
2. 안전한 작업자를 반복적으로 위험하다고 경고하는 오경보를 허용 가능한 수준으로 제한한다.
3. 단일 프레임의 순간적인 오판보다 일정 시간 동안의 상태를 이용한다.
4. 최종적으로 작업자별 SAFE/DANGER 상태와 경고 이벤트를 영상과 로그로 남긴다.

## 2. 전체 시스템 구조

최종 시스템은 두 AI 모델과 시간 상태 판단 로직으로 구성된다.

```text
입력 영상
  ↓
RF-DETR Segmentation
worker / harness / hook / lanyard / lifeline 탐지
  ↓
ByteTrack
프레임 사이에서 같은 작업자와 장비 ID 추적
  ↓
작업자-후크 거리 기반 매칭
  ↓
후크 주변 이미지 Crop
  ↓
EfficientNet-B0
Connected / Unconnected 분류
  ↓
EMA + 시간 상태 머신
SAFE / PENDING_SAFE / WARNING / DANGER 결정
  ↓
결과 영상 및 DANGER 이벤트 CSV 저장
```

## 3. 기존 코드의 구성과 한계

기존 코드는 다음 기능을 이미 포함하고 있었다.

- RF-DETR로 작업자와 안전장비 탐지
- EfficientNet-B0로 후크 체결/미체결 분류
- Custom Average/Max Pooling
- 미체결 클래스에 더 큰 loss 부여
- ByteTrack을 이용한 객체 추적
- 최근 15프레임 체결 확률 평균
- 체결 확률 0.85 이상일 때만 SAFE 처리

다만 다음 문제가 있었다.

1. 모델 저장 기준이 미체결 Recall 하나뿐이었다.
   - 모든 이미지를 DANGER로 판단해도 Recall 100%가 될 수 있었다.
2. Test 데이터를 만들었지만 실제 최종 평가를 하지 않았다.
3. threshold 0.85에 대한 Validation 근거가 없었다.
4. RF-DETR의 class ID를 고정 숫자로 사용해 클래스 순서가 바뀌면 잘못 해석될 위험이 있었다.
5. 후크가 탐지될 때만 안전 상태를 판단했다.
6. 후크가 사라지면 작업자 상태도 화면에서 사라졌다.
7. 프레임 평균만 사용해 SAFE/DANGER 경계에서 깜빡일 수 있었다.
8. 후크 중심이 작업자 박스 안에 있을 때만 연결해, lanyard 끝의 멀리 있는 후크를 놓쳤다.
9. harness, lanyard, lifeline을 탐지해도 영상에는 표시하지 않았다.
10. 단일 긴 코드로 구성되어 평가, 상태 판단, 알림 기능의 분리가 부족했다.

## 4. 사용 데이터

### 4.1 전체 데이터 수

| 클래스 | 이미지 수 | 비율 |
|---|---:|---:|
| Connected | 1,535장 | 76.3% |
| Unconnected | 478장 | 23.7% |
| 합계 | 2,013장 | 100% |

Connected와 Unconnected의 비율은 약 `3.21:1`이다.

### 4.2 Train/Validation/Test 분할

각 클래스를 별도로 섞은 후 8:1:1로 분할했다.

| 분할 | Connected | Unconnected | 합계 |
|---|---:|---:|---:|
| Train | 1,228장 | 382장 | 1,610장 |
| Validation | 153장 | 47장 | 200장 |
| Test | 154장 | 49장 | 203장 |
| 합계 | 1,535장 | 478장 | 2,013장 |

### 4.3 데이터 분할 시 주의점

현재 data1, data2, data3 및 별도 unconnected 폴더의 이미지가 이미 무작위로 섞인 상태이므로 전체를 재귀적으로 탐색해 다시 분할했다.

다만 동일 원본 영상에서 추출한 연속 프레임이 Train과 Test에 동시에 포함되었을 가능성은 남아 있다. 경로가 다르더라도 장면이 거의 같으면 실제보다 높은 성능이 측정될 수 있다. 향후에는 원본 영상 또는 촬영 세션 단위로 Train/Validation/Test를 분리해야 한다.

## 5. 데이터 증강

### 5.1 최종 적용 증강

두 클래스에 동일한 Online Augmentation을 적용했다.

```python
Resize(224, 224)
RandomHorizontalFlip(p=0.5)
RandomRotation(degrees=15)
ColorJitter(
    brightness=0.20,
    contrast=0.20,
    saturation=0.10
)
ImageNet Normalize
```

적용 내용은 다음과 같다.

- 50% 확률 좌우 반전
- 최대 ±15도 회전
- 밝기 최대 ±20% 수준 변화
- 대비 최대 ±20% 수준 변화
- 채도 최대 ±10% 수준 변화
- 입력 크기 224×224 통일
- ImageNet 평균과 표준편차로 정규화

상하 반전은 후크의 중력 방향과 실제 설치 방향을 훼손할 수 있어 제외했다.

### 5.2 증강 이미지 수의 의미

증강 이미지를 별도 파일로 저장하지 않고, 학습 시 매 epoch마다 무작위 변형을 적용했다.

- Train 원본: 1,610장
- 설정한 최대 epoch: 15
- 실제 실행 epoch: 13(Early stopping)
- 실제 학습 이미지 입력 횟수: `1,610 × 13 = 20,930회`

이는 서로 다른 이미지 파일 20,930장을 생성했다는 뜻이 아니라, 원본 1,610장이 13 epoch 동안 총 20,930회 입력되며 매번 무작위 변형을 적용받았다는 의미다.

### 5.3 강한 증강 실험과 결론

Unconnected에만 RandomResizedCrop, Perspective, Blur, RandomErasing을 강하게 적용하고 WeightedRandomSampler까지 사용한 실험을 수행했다. False SAFE는 줄었지만 모델이 거의 모든 이미지를 DANGER로 판단하는 문제가 발생했다.

| 실험 | Accuracy | Danger Recall | Danger Precision | False SAFE | False alarm |
|---|---:|---:|---:|---:|---:|
| 강한 증강 1차 | 82.27% | 97.96% | 57.83% | 1장 | 35장 |
| 강한 증강 2차 | 52.71% | 100.00% | 33.79% | 0장 | 96장 |

원인은 다음과 같이 판단했다.

- 특정 클래스에만 다른 증강을 적용해 모델이 실제 체결 특징이 아니라 증강 흔적을 학습할 수 있었다.
- 좁은 후크 crop에 RandomResizedCrop/Erasing을 적용하면서 체결 판단에 필요한 부분이 사라질 수 있었다.
- WeightedRandomSampler와 위험 중심 학습이 결합되어 DANGER 편향이 과도해졌다.

따라서 최종 모델에서는 두 클래스에 동일한 기본 증강을 적용하고 WeightedRandomSampler를 제거했다.

## 6. EfficientNet-B0 고도화

### 6.1 모델 구조

실시간 영상 처리 속도를 고려해 EfficientNet-B0를 유지했다. ImageNet 사전학습 가중치를 사용하고, 마지막 Pooling과 Classifier를 변경했다.

```text
EfficientNet-B0 Feature Extractor
  ↓
Global Average Pooling + Global Max Pooling
  ↓
특징 결합: 1280 + 1280 = 2560차원
  ↓
Dropout(0.3)
  ↓
Linear(2560 → 512)
  ↓
BatchNorm + SiLU
  ↓
Dropout(0.3)
  ↓
Linear(512 → 2)
  ↓
Connected / Unconnected
```

Average Pooling은 전체적인 형태를, Max Pooling은 체결 부위와 같이 국소적으로 강한 특징을 보존하기 위해 함께 사용했다.

### 6.2 클래스 불균형 처리

Train 데이터 비율에서 Unconnected loss weight를 자동 계산했다.

```text
Connected weight   = 1.0
Unconnected weight = 1,228 / 382 ≈ 3.2147
```

WeightedRandomSampler는 최종 모델에서 사용하지 않았다. Sampler와 class weight를 동시에 사용하면 미체결 클래스가 이중으로 강화되어 오경보가 급증할 수 있기 때문이다.

### 6.3 학습 설정

| 항목 | 설정 |
|---|---|
| 모델 | EfficientNet-B0 |
| 사전학습 | ImageNet1K V1 |
| 입력 크기 | 224×224 |
| Batch size | 32 |
| 최대 Epoch | 15 |
| Optimizer | AdamW |
| Learning rate | 1e-4 |
| Weight decay | 1e-4 |
| Scheduler | ReduceLROnPlateau |
| Early stopping patience | 5 epochs |
| Loss | Weighted Cross Entropy |

### 6.4 실제 학습 실행 결과

실행 완료 노트북의 로그를 기준으로 다음과 같이 확인했다.

| 항목 | 실제 실행 결과 |
|---|---:|
| 사용 장치 | CUDA GPU |
| 실행 epoch | 13/15 |
| 종료 방식 | Early stopping |
| 총 학습 시간 | 1.8분 |
| epoch당 batch | 51 batch |
| 최종 선택 체크포인트 | Epoch 8 |
| Epoch 8 Validation threshold | 0.81 |
| Epoch 8 Danger Recall | 95.7% |
| Epoch 8 Danger Precision | 78.9% |
| Epoch 8 Danger F1-score | 86.5% |
| Epoch 8 Validation False SAFE | 2장 |

Epoch 13의 Validation F1-score는 91.7%로 더 높았지만 Danger Recall이 93.6%로 최소 목표 95%를 충족하지 못했다. 따라서 Recall과 오경보 안전 조건을 충족한 Epoch 8 체크포인트가 최종 저장됐다. 이는 단순히 F1-score가 가장 높은 마지막 모델을 선택한 것이 아니라, 사전에 정의한 안전 조건을 우선한 결과다.

## 7. 평가 기준과 Threshold 선정

### 7.1 Positive 클래스 정의

본 프로젝트에서는 `Unconnected/DANGER`를 Positive로 정의했다.

```text
TP: 실제 미체결 → DANGER
FN: 실제 미체결 → SAFE       (가장 위험한 False SAFE)
FP: 실제 체결 → DANGER       (오경보)
TN: 실제 체결 → SAFE
```

### 7.2 모델 저장 조건

Recall만으로 모델을 저장하면 전부 DANGER로 예측하는 모델이 선택될 수 있어 다음 조건으로 변경했다.

1. Validation Danger Recall 95% 이상
2. Validation False alarm rate 10% 이하
3. 위 조건을 만족하는 후보 중 Danger F1-score가 가장 높은 모델
4. 동률이면 Precision이 높고 Validation loss가 낮은 모델

두 조건을 동시에 만족하는 threshold가 없으면 Recall만 최대화하지 않고, 오경보율 10% 이내 후보 중 F1-score가 가장 높은 값을 선택한다.

### 7.3 최종 Threshold

Validation으로 선택된 최종 Connected threshold는 `0.81`이다.

```text
Connected 확률 ≥ 0.81 → Connected/SAFE 후보
Connected 확률 < 0.81 → Unconnected/DANGER 후보
```

영상 운영에서는 팀 회의에서 정한 더 엄격한 `0.85`를 별도 운영 threshold로 사용할 수 있다.

```text
모델 평가 threshold: 0.81
영상 운영 threshold: 0.85 권장
```

Test 결과를 보고 threshold를 다시 조정하지 않았다. Test 데이터로 설정을 변경하면 Test가 더 이상 독립적인 최종 평가 데이터가 아니게 되기 때문이다.

## 8. 최종 EfficientNet Test 결과

### 8.1 핵심 지표

| 지표 | 결과 |
|---|---:|
| Test 이미지 | 203장 |
| Accuracy | 95.57% |
| Danger Precision | 85.71% |
| Danger Recall | 97.96% |
| Danger F1-score | 91.43% |
| False SAFE | 1장 |
| False alarm rate | 5.19% |
| Connected threshold | 0.81 |
| Test loss | 0.0579 |

### 8.2 Confusion Matrix

| 실제 상태 | SAFE 예측 | DANGER 예측 |
|---|---:|---:|
| Connected 154장 | 146장(TN) | 8장(FP) |
| Unconnected 49장 | 1장(FN) | 48장(TP) |

해석하면 다음과 같다.

- 실제 미체결 49장 중 48장을 탐지했다.
- 가장 위험한 False SAFE는 1장이다.
- 실제 체결 154장 중 8장을 DANGER로 잘못 경고했다.
- 전체 203장 중 약 95.57%를 정확히 분류했다.

### 8.3 이전 실험과 비교

| 버전 | Accuracy | Danger Recall | Danger Precision | Danger F1 | False SAFE | False alarm |
|---|---:|---:|---:|---:|---:|---:|
| 초기 고도화 실험 | 96.06% | 93.88% | 90.20% | 92.00% | 3장 | 5장 |
| 강한 증강 1차 | 82.27% | 97.96% | 57.83% | 72.73% | 1장 | 35장 |
| 강한 증강 2차 | 52.71% | 100.00% | 33.79% | 50.52% | 0장 | 96장 |
| 최종 균형 모델 | 95.57% | 97.96% | 85.71% | 91.43% | 1장 | 8장 |

최종 모델은 초기 고도화 실험보다 Accuracy와 Precision이 소폭 낮지만, 가장 위험한 False SAFE를 3장에서 1장으로 줄였다. 강한 증강 모델과 달리 오경보율도 5.19%로 억제했다. 안전성을 우선하면서 현장 사용 가능성을 유지한 균형점으로 판단했다.

## 9. RF-DETR 객체 탐지

### 9.1 사용 가중치와 클래스

최초 작성자가 제공한 체크포인트를 `models/detection/rfdetr/checkpoint_best_ema_v2.pth`로 정리해 사용했다.

체크포인트의 클래스는 0부터 다음 순서로 확인됐다.

```text
0: test-CwuI
1: harness
2: hook
3: lanyard
4: lifeline
5: worker
```

`test-CwuI`는 데이터셋 생성 과정에서 포함된 불필요한 임시 클래스일 가능성이 있다. 최종 안전 로직은 클래스 이름을 기준으로 `worker`, `harness`, `hook`, `lanyard`, `lifeline`만 사용한다.

### 9.2 Detection threshold

낮은 base threshold로 후보를 받은 뒤 클래스별 threshold를 적용한다.

| 클래스 | Detection threshold |
|---|---:|
| Base 후보 | 0.20 |
| Worker | 0.40 |
| Harness | 0.35 |
| Hook | 0.30 |
| Lanyard | 0.25 |
| Lifeline | 0.30 |

작은 객체인 hook과 lanyard는 놓치지 않도록 worker보다 낮은 threshold를 사용한다. 탐지 threshold를 무조건 높이면 오탐은 줄지만 실제 후크까지 놓쳐 안전 시스템의 Recall이 낮아질 수 있다.

### 9.3 mAP 기록

| RF-DETR 평가 지표 | 현재 상태 |
|---|---|
| mAP@0.5 | 미측정 / 원본 RF-DETR 학습 로그 확인 필요 |
| mAP@0.5:0.95 | 미측정 / 원본 RF-DETR 학습 로그 확인 필요 |
| Hook AP | 미측정 |
| Hook Recall | 미측정 |
| Small-object AP | 미측정 |

현재 작업에서는 제공받은 RF-DETR 체크포인트로 추론만 수행했으며, RF-DETR 평가 데이터와 원본 학습 로그가 제공되지 않아 mAP 수치를 새로 계산하지 못했다. mAP는 EfficientNet 분류 지표가 아니라 RF-DETR 객체 탐지 성능 지표이므로 임의로 EfficientNet Accuracy와 혼용하면 안 된다.

최종 발표 전 다음 중 하나가 필요하다.

1. 최초 RF-DETR 작성자에게 Validation mAP 로그 요청
2. COCO 형식 Validation annotation으로 RF-DETR 재평가
3. 클래스별 AP와 Recall, 특히 hook AP/Recall 추가 기록

## 10. 영상 처리 로직 고도화

### 10.1 고정 class ID 제거

기존 숫자 ID 매핑 대신 RF-DETR 출력의 `class_name`을 우선 사용한다. 체크포인트마다 클래스 ID 순서가 다를 수 있는 문제를 줄였다.

### 10.2 모든 안전장비 시각화

기존에는 worker와 hook만 주요 박스로 표시했다. 개선 후에는 다음 객체를 모두 표시한다.

```text
Harness  : 청록색
Hook     : 주황색, 판정 후 녹색/빨간색
Lanyard  : 자홍색
Lifeline : 파란색
Worker   : 상태별 색상
```

### 10.3 작업자-후크 매칭 개선

기존에는 후크가 작업자 박스 내부 또는 매우 가까운 경우에만 연결했다. 그러나 실제 hook은 lanyard 끝에 있어 작업자로부터 멀리 떨어질 수 있다.

```text
기존 최대 거리 비율: 0.75
개선 최대 거리 비율: 1.50
작업자 박스 확장 비율: 0.50
```

현재는 거리 기반 매칭이며, 여러 작업자가 겹치는 장면에서는 잘못 연결될 가능성이 있다. 향후에는 `worker → harness → lanyard → hook` 관계를 이용해야 한다.

### 10.4 EMA와 Hysteresis

순간적인 확률 변화로 상태가 깜빡이는 문제를 줄이기 위해 EMA와 서로 다른 진입/해제 threshold를 적용했다.

```text
EMA alpha: 0.35
SAFE 진입 threshold: 0.81 또는 운영 기준 0.85
SAFE 해제 threshold: 진입 threshold보다 0.10 낮음
```

예를 들어 운영 threshold 0.85를 사용하면:

```text
0.85 이상 → SAFE 후보
0.75 미만 → SAFE 해제 후보
0.75~0.85 → 기존 확정 상태 유지
```

### 10.5 작업자별 시간 상태 머신

| 설정 | 값 |
|---|---:|
| SAFE 연속 확인 시간 | 1.5초 |
| DANGER 연속 확인 시간 | 0.3초 |
| Hook 미탐 WARNING | 1.0초 |
| Hook 미탐 DANGER | 3.0초 |
| 작업자 상태 유지 TTL | 3.0초 |
| 알림 재발생 방지 시간 | 10초 |

상태는 다음과 같이 구성했다.

```text
UNKNOWN
→ PENDING_SAFE
→ SAFE

UNKNOWN/SAFE
→ WARNING
→ DANGER
```

SAFE 전환은 느리고 엄격하게, DANGER 전환은 상대적으로 빠르게 구성했다.

### 10.6 Hook missing 처리

기존에는 hook이 탐지될 때만 판단했다. 개선 후에는 작업자는 보이지만 hook이 일정 시간 보이지 않는 경우 다음과 같이 판단한다.

```text
1초 미탐 → WARNING
3초 미탐 → DANGER
```

마지막 체결 확률이 남아 있어도 현재 hook이 보이지 않는다면 `C(last):0.95`처럼 표시해 과거 확률임을 명확히 했다.

### 10.7 이벤트 로그

작업자 상태가 DANGER로 전환될 때 다음 내용을 CSV로 저장한다.

- 영상 시간
- 프레임 번호
- 작업자 tracker ID
- 상태
- 경고 이유
- 마지막 Connected EMA

같은 경고가 매 프레임 반복되지 않도록 10초 cooldown을 적용했다.

## 11. Google Drive 및 테스트 영상 관리

다음 결과물을 Google Drive에 저장하도록 변경했다.

```text
outputs/pipeline/
├── best_efficientnet_b0_safety.pth
├── efficientnet_training_metrics.csv
├── pipeline_output_v2.mp4
└── safety_events.csv
```

YouTube 테스트 영상은 yt-dlp와 FFmpeg를 이용해 필요한 구간만 720p 이하로 저장할 수 있도록 했다.

```text
youtube_test_clips/
├── youtube_01_from_20m30s.mp4
├── youtube_02_full.mp4
├── youtube_03_08m15s_to_14m00s.mp4
├── youtube_03_19m30s_to_20m00s.mp4
└── youtube_04_00m00s_to_01m47s.mp4
```

실행 로그에서 위 5개 테스트 영상이 모두 Google Drive에 저장된 것을 확인했다. 세 번째 영상의 19:30~20:00 구간은 이미 존재해 재다운로드하지 않고 기존 파일을 사용했다.

## 12. 실제 RF-DETR 및 영상 실행 결과

### 12.1 첫 프레임 RF-DETR 동작 확인

최종 영상 처리 전에 첫 프레임으로 smoke test를 수행했다. 총 11개 객체가 탐지됐다.

| 클래스 | 탐지 수 |
|---|---:|
| Worker | 2개 |
| Harness | 3개 |
| Hook | 3개 |
| Lanyard | 1개 |
| Lifeline | 2개 |
| 합계 | 11개 |

탐지 confidence 범위는 약 0.201~0.940이었다. 이 결과는 RF-DETR가 필요한 클래스들을 실제로 출력하고 영상 파이프라인과 연결됐음을 확인하는 smoke test이다. 정답 annotation과 비교한 평가가 아니므로 mAP, AP 또는 Recall로 해석하면 안 된다.

### 12.2 YouTube 테스트 영상 처리 결과

`youtube_04_00m00s_to_01m47s.mp4`를 최종 파이프라인으로 처리했다.

| 항목 | 실행 결과 |
|---|---:|
| 영상 해상도 | 1280×720 |
| FPS | 29.97 |
| 전체 프레임 | 3,207 |
| 영상 길이 | 약 107초(1분 47초) |
| 처리 시간 | 약 3.7분 |
| 평균 처리 속도 | 약 14.4 FPS |
| 실시간 대비 | 약 2.1배 느림 |
| 기록된 DANGER 이벤트 | 13건 |

13건의 DANGER 이벤트는 원인별로 다음과 같다.

| DANGER 원인 | 이벤트 수 |
|---|---:|
| EfficientNet이 Unconnected로 분류 | 6건 |
| Hook이 3초 동안 미탐/미매칭 | 7건 |
| 합계 | 13건 |

실제 영상 처리에는 체크포인트에서 불러온 Connected threshold `0.81`과 exit threshold `0.71`이 사용됐다. 보고서에서 제안한 운영 threshold 0.85는 권장 정책값이며, 이번 실행 결과에 실제 적용된 값은 0.81이다.

영상 결과 파일과 이벤트 로그는 다음 위치에 정상 저장됐다.

```text
outputs/videos/inference/youtube_04.mp4
outputs/pipeline/events_youtube_04.csv
```

이번 13건은 시스템이 발생시킨 경고 이벤트 수이며, 사람이 영상 정답을 라벨링해 맞고 틀림을 판정한 수치는 아니다. 따라서 영상 단위 Precision/Recall로 해석할 수 없고, 후속 단계에서 이벤트별 수동 검증이 필요하다.

## 13. 용어 설명

### Accuracy(정확도)

전체 이미지 중 맞힌 비율이다.

```text
(정확한 SAFE + 정확한 DANGER) / 전체 이미지
```

데이터 불균형이 크면 Accuracy만 높고 미체결은 놓치는 모델이 나올 수 있어 안전 시스템의 단독 핵심 지표로 사용하지 않았다.

### Recall(재현율)

실제 미체결 중 모델이 DANGER로 탐지한 비율이다.

```text
TP / (TP + FN)
```

본 프로젝트의 가장 중요한 지표다. Recall이 높을수록 실제 미체결을 덜 놓친다.

### Precision(정밀도)

모델이 DANGER라고 경고한 것 중 실제로 미체결인 비율이다.

```text
TP / (TP + FP)
```

Precision이 낮으면 안전한 작업자에게도 경고가 너무 많이 발생한다.

### F1-score

Recall과 Precision의 조화평균이다.

```text
2 × Precision × Recall / (Precision + Recall)
```

Recall만 높이기 위해 모든 것을 DANGER로 판단하는 모델을 걸러내는 데 사용했다.

### False SAFE(False Negative)

실제로는 미체결인데 모델이 SAFE로 판단한 경우다. 안전 시스템에서 가장 위험한 오류다.

### False alarm(False Positive)

실제로는 체결인데 모델이 DANGER로 판단한 경우다. 직접적인 사고 위험은 낮지만 너무 많으면 작업자와 관리자가 경고를 신뢰하지 않게 된다.

### Threshold(임계값)

모델 확률을 최종 상태로 바꾸는 기준이다.

```text
Connected 확률 ≥ threshold → SAFE 후보
Connected 확률 < threshold → DANGER 후보
```

Connected threshold를 높이면 SAFE 판정이 엄격해져 False SAFE는 줄 수 있지만 오경보가 증가한다.

### Detection threshold

RF-DETR가 객체 후보를 실제 탐지로 인정하는 최소 신뢰도다. 분류 threshold와 다른 개념이다. 너무 높이면 작은 hook을 놓칠 수 있다.

### mAP

객체 탐지 모델이 객체 위치와 클래스를 얼마나 정확히 찾는지 나타내는 종합 지표다.

- `mAP@0.5`: 예측 박스와 정답 박스의 IoU가 0.5 이상이면 맞은 탐지로 평가
- `mAP@0.5:0.95`: IoU 0.5부터 0.95까지 여러 엄격한 기준의 평균

mAP는 RF-DETR 평가 지표이고, EfficientNet 분류에는 Precision/Recall/F1/Accuracy를 사용한다.

### IoU

예측 박스와 정답 박스가 얼마나 겹치는지를 나타낸다.

```text
겹치는 영역 / 두 박스의 합집합 영역
```

### EMA

최근 프레임의 확률에 더 큰 가중치를 주면서 과거 확률도 일부 반영하는 이동평균이다. 한 프레임의 순간 오판으로 상태가 바뀌는 것을 줄인다.

### Hysteresis

SAFE 진입 기준과 SAFE 해제 기준을 다르게 설정하는 방법이다. 경계 확률에서 상태가 계속 깜빡이는 것을 방지한다.

### ByteTrack

영상 프레임 사이에서 같은 객체에 동일한 ID를 부여하는 추적 알고리즘이다. 작업자별로 안전 상태를 유지하는 데 사용한다.

## 14. 현재 한계

1. RF-DETR의 mAP와 클래스별 AP/Recall이 아직 기록되지 않았다.
2. RF-DETR 체크포인트에 불필요한 `test-CwuI` 클래스가 포함되어 있다.
3. 작업자-후크 관계가 거리 기반이라 다중 작업자 장면에서 잘못 연결될 수 있다.
4. Harness와 lanyard는 표시 및 보조 증거로 사용하지만 최종 관계 추론은 아직 제한적이다.
5. 연속 영상 프레임이 데이터 분할에 섞였을 가능성이 있다.
6. Test Unconnected가 49장이라 한 장에 Recall이 약 2.04% 변한다.
7. 최종 False SAFE 1장은 Connected 확률 0.915로 나온 hard example이며 라벨과 영상을 직접 확인해야 한다.
8. YouTube 영상은 기존 학습 환경과 도메인이 달라 실제 성능이 낮아질 수 있다.
9. 107초 영상에서 worker tracker ID가 여러 차례 새로 부여됐다. 가림, 화면 이탈 또는 탐지 단절에 따른 ID fragmentation 가능성이 있어 작업자별 장기 상태 추적을 추가 검증해야 한다.
10. 영상에서 발생한 DANGER 13건은 아직 사람이 정답 라벨과 대조하지 않았으므로 실제 True/False alert 비율을 알 수 없다.
11. 영상 평균 처리 속도는 약 14.4 FPS로 원본 29.97 FPS 실시간 처리에는 미달했다. 모델 최적화 또는 프레임 샘플링이 필요하다.

## 15. 다음 작업 우선순위

1. 최초 RF-DETR 작성자에게 mAP@0.5, mAP@0.5:0.95 및 클래스별 AP 로그를 요청한다.
2. 짧은 영상에서 모든 장비 탐지 박스가 올바르게 표시되는지 확인한다.
3. Hook이 멀어져도 동일 작업자에게 연결되는지 확인한다.
4. 작업자가 여러 명인 영상에서 잘못된 hook 연결을 점검한다.
5. `worker → harness → lanyard → hook` 관계 기반 매칭을 구현한다.
6. False SAFE와 유사한 새로운 Unconnected 데이터를 수집한다.
7. 원본 영상 단위로 분리한 독립 Test 세트를 구축한다.
8. 영상별 False SAFE, 시간당 오경보, 위험 발생 후 경고까지의 시간을 기록한다.
9. 최종 이벤트 로그를 TTS 또는 관제 알림 시스템과 연결한다.
10. 13개 DANGER 이벤트를 사람이 확인해 True alert, False alert, hook 미탐, 작업자-후크 오매칭으로 분류한다.
11. RF-DETR 추론 최적화, 입력 해상도 조절 또는 프레임 간격 처리로 영상 처리 속도를 비교한다.

## 16. 팀 공유용 핵심 결론

본 고도화에서는 EfficientNet-B0의 실시간 처리 장점을 유지하면서 평가 체계와 영상 안전 판단 로직을 강화했다. 기존의 Recall 단독 모델 선택을 Recall, F1-score, Precision, 오경보율을 함께 고려하는 방식으로 변경했고, 독립 Test 평가를 추가했다.

최종 EfficientNet 모델은 Test 203장에서 Accuracy 95.57%, 미체결 Recall 97.96%, Precision 85.71%, F1-score 91.43%를 기록했다. 실제 미체결 49건 중 48건을 탐지했으며 False SAFE는 1건, 체결 오경보율은 5.19%였다.

영상에서는 작업자별 상태 머신, EMA, Hysteresis, hook 미탐 타이머, 장비 시각화, 거리 기반 작업자-후크 매칭 및 이벤트 로그를 추가했다. 실제 1280×720, 3,207프레임 영상을 약 3.7분에 처리해 평균 약 14.4 FPS를 기록했고 DANGER 이벤트 13건을 CSV로 저장했다. 단, 이 이벤트는 아직 수동 정답 검증 전이다. RF-DETR mAP도 현재 확인되지 않았으므로 최종 발표 전에 반드시 원본 학습 로그를 확보하거나 COCO Validation 데이터로 재평가해야 한다.
