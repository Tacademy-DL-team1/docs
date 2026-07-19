# 공사장 안전고리 체결 판별 시스템 고도화 요약

## 1. 프로젝트 목표

공사장 영상에서 작업자와 안전장비를 탐지하고, 안전고리의 체결 여부를 판단해 작업자별 `SAFE / WARNING / DANGER` 상태와 경고 기록을 제공하는 시스템이다.

가장 중요한 목표는 실제 미체결을 SAFE로 판단하는 `False SAFE`를 줄이는 것이다. 다만 모든 상황을 DANGER로 판단하면 오경보가 지나치게 많아지므로 Recall과 Precision의 균형도 함께 고려했다.

## 2. 전체 구조

```text
영상
→ RF-DETR Seg Large: worker/harness/hook/lanyard/lifeline 탐지
→ ByteTrack: 프레임 사이 객체 ID 추적
→ 작업자와 Hook 매칭
→ EfficientNet-B0: Hook 체결/미체결 분류
→ EMA + 시간 상태 머신
→ SAFE/WARNING/DANGER 표시 및 이벤트 CSV 저장
```

## 3. 사용 데이터

| 구분 | Connected | Unconnected | 합계 |
|---|---:|---:|---:|
| Train | 1,228 | 382 | 1,610 |
| Validation | 153 | 47 | 200 |
| Test | 154 | 49 | 203 |
| 전체 | 1,535 | 478 | 2,013 |

클래스 비율은 약 `3.21:1`로 Connected가 많았다. 이를 보정하기 위해 Unconnected 오분류 loss를 약 3.2147배 크게 적용했다.

## 4. 데이터 증강

두 클래스에 동일한 기본 Online Augmentation을 적용했다.

- 224×224 Resize
- 50% 확률 좌우 반전
- ±15도 회전
- 밝기 ±20% 수준 변화
- 대비 ±20% 수준 변화
- 채도 ±10% 수준 변화
- ImageNet 정규화

최종 학습은 13 epoch에서 Early stopping 됐다.

```text
Train 1,610장 × 13 epoch = 총 20,930회 학습 입력
```

20,930개의 파일을 새로 만든 것이 아니라, 원본 이미지에 학습 시점마다 무작위 증강을 적용한 것이다.

Unconnected에만 강한 Crop, Blur, Perspective, Random Erasing과 반복 샘플링을 적용한 실험도 했지만 실제 Connected까지 DANGER로 판단하는 오경보가 크게 증가해 최종 방식에서 제외했다.

## 5. EfficientNet-B0 고도화

실시간 처리 성능을 고려해 EfficientNet-B0를 유지했다.

- ImageNet-1K 사전학습 가중치 사용
- Average Pooling과 Max Pooling 결합
- 2,560차원 특징을 512차원으로 압축하는 MLP 분류기
- Connected / Unconnected 2개 클래스 출력
- Weighted Cross Entropy로 클래스 불균형 보정

모델 구조는 다음과 같다.

```text
EfficientNet-B0
→ Average Pooling + Max Pooling
→ Linear 2560→512
→ BatchNorm + SiLU + Dropout
→ Linear 512→2
```

## 6. 모델 저장 및 Threshold 선정

기존 코드는 미체결 Recall이 가장 높은 모델만 저장했다. 그러나 모든 이미지를 DANGER로 예측해도 Recall 100%가 될 수 있어 오경보가 심한 모델이 선택될 위험이 있었다.

개선 후 기준은 다음과 같다.

```text
1. Validation Danger Recall ≥ 95%
2. Validation 오경보율 ≤ 10%
3. 위 조건을 만족하는 후보 중 Danger F1-score 최대
4. 동률이면 Precision과 Validation loss 비교
```

Validation에서 Connected threshold를 0.50~0.99까지 0.01 간격으로 비교했고, 최종 모델은 Epoch 8의 threshold `0.81`로 선택됐다.

```text
Connected 확률 ≥ 0.81 → SAFE 후보
Connected 확률 < 0.81 → DANGER 후보
```

팀 회의에서 정한 영상 운영 기준 0.85는 더 엄격한 별도 정책값으로 사용할 수 있다. 실제 최종 영상 실행에는 체크포인트의 0.81이 적용됐다.

## 7. 최종 Test 결과

| 지표 | 결과 |
|---|---:|
| Test 이미지 | 203장 |
| Accuracy | 95.57% |
| Danger Recall | 97.96% |
| Danger Precision | 85.71% |
| Danger F1-score | 91.43% |
| False SAFE | 1장 |
| 오경보율 | 5.19% |
| Test loss | 0.0579 |
| Connected threshold | 0.81 |

Confusion Matrix는 다음과 같다.

| 실제 상태 | SAFE 예측 | DANGER 예측 |
|---|---:|---:|
| Connected 154장 | 146장 | 8장 |
| Unconnected 49장 | 1장 | 48장 |

실제 미체결 49건 중 48건을 탐지했고, 가장 위험한 False SAFE는 1건이었다.

## 8. 영상 판단 로직 개선

기존에는 Hook 중심점이 작업자 박스 안에 있을 때만 연결했다. 실제 Hook은 lanyard 끝에 있어 작업자와 멀어질 수 있으므로 확장된 작업자 박스와 정규화 거리를 이용하도록 개선했다.

또한 단일 프레임 결과 대신 EMA와 시간 상태 머신을 사용했다.

| 설정 | 값 |
|---|---:|
| EMA alpha | 0.35 |
| SAFE 확인 시간 | 1.5초 |
| DANGER 확인 시간 | 0.3초 |
| Hook 미탐 WARNING | 1초 |
| Hook 미탐 DANGER | 3초 |
| 작업자 상태 TTL | 3초 |
| 알림 cooldown | 10초 |

주요 상태는 다음과 같다.

- `PENDING_SAFE`: 체결 확률은 높지만 SAFE 지속시간을 확인 중
- `SAFE`: 체결 상태가 1.5초 이상 유지됨
- `WARNING`: 확률이 불확실하거나 Hook이 일시적으로 보이지 않음
- `DANGER`: 미체결 확률이 지속되거나 Hook을 3초 이상 확인하지 못함

Hook 미탐은 실제 미체결 확정이 아니라 카메라에서 안전 상태를 확인하지 못한 상황일 수 있으므로 향후 `CHECK_REQUIRED` 또는 `NOT_VISIBLE` 상태로 분리할 필요가 있다.

## 9. 실제 영상 실행 결과

YouTube 00:00~01:47 구간을 최종 파이프라인으로 처리했다.

| 항목 | 결과 |
|---|---:|
| 해상도 | 1280×720 |
| FPS | 29.97 |
| 프레임 | 3,207 |
| 영상 길이 | 약 107초 |
| 처리 시간 | 약 3.7분 |
| 처리 속도 | 약 14.4 FPS |
| DANGER 이벤트 | 13건 |

DANGER 이벤트 원인은 다음과 같다.

- EfficientNet이 Unconnected로 분류: 6건
- Hook이 3초 동안 미탐 또는 미매칭: 7건

이 13건은 시스템이 발생시킨 이벤트 수이며, 사람이 정답과 대조한 결과는 아니다. 실제 True/False alert 여부는 영상 수동 검수가 필요하다.

## 10. RF-DETR 현황

현재 사용한 모델은 기존 팀원이 제공한 `RF-DETR Segmentation Large`의 6클래스 fine-tuned 체크포인트다.

```text
models/detection/rfdetr/checkpoint_best_ema_v2.pth
```

클래스는 다음과 같다.

```text
test-CwuI / harness / hook / lanyard / lifeline / worker
```

`test-CwuI`는 불필요한 임시 클래스일 가능성이 있어 개선 모델에서는 제거하는 것이 좋다.

첫 프레임 smoke test에서는 Worker 2개, Harness 3개, Hook 3개, Lanyard 1개, Lifeline 2개가 출력됐다. 이는 연결 정상 여부만 확인한 것이며 탐지 성능 평가가 아니다.

RF-DETR의 다음 지표는 아직 확보되지 않았다.

- mAP@0.5
- mAP@0.5:0.95
- Hook AP 및 Recall
- Small-object AP
- 클래스별 AP

최초 학습 담당자에게 로그를 받거나 COCO Validation 데이터로 재평가해야 한다.

## 11. 현재 한계와 다음 작업

1. RF-DETR mAP와 클래스별 AP/Recall 확보
2. 13개 DANGER 이벤트 수동 검증
3. 거리 기반 매칭을 `Worker→Harness→Lanyard→Hook` 관계 기반으로 개선
4. Hook 미탐과 실제 미체결 상태 분리
5. 영상/촬영 세션 단위 데이터 분할로 데이터 누수 방지
6. False SAFE와 유사한 새로운 Unconnected 원본 데이터 추가
7. 약 14.4 FPS의 영상 처리 속도 개선
8. 이벤트 로그를 TTS 또는 관제 알림과 연동

## 12. 핵심 결론

EfficientNet-B0의 실시간 장점을 유지하면서 데이터 불균형 처리, Threshold 탐색, Test 평가, 시간 상태 머신과 이벤트 기록을 추가했다.

최종 분류 모델은 Test 203장에서 Accuracy 95.57%, Danger Recall 97.96%, Precision 85.71%, F1-score 91.43%를 기록했다. 실제 미체결 49건 중 48건을 탐지했고 False SAFE는 1건이었다.

RF-DETR 객체 탐지 성능은 아직 mAP 검증이 필요하고, 실제 영상에서 발생한 DANGER 이벤트도 수동 정답 검수가 필요하다. 따라서 현재 결과는 분류 모델 성능은 정량 검증됐지만 전체 영상 안전 시스템 성능은 추가 검증 중인 단계로 정리하는 것이 정확하다.
