# 공사장 안전고리 모델 로컬 실행 가이드

## 1. 권장 환경

- Python 3.10~3.12
- NVIDIA GPU 및 CUDA 사용 권장
- Jupyter Notebook 또는 VS Code Notebook
- FFmpeg: YouTube 구간 다운로드 기능을 사용할 때 필요

CPU에서도 실행할 수 있지만 RF-DETR 영상 처리는 매우 느릴 수 있습니다.

## 2. 프로젝트 폴더 구조

```text
code/
├── data/classification/
│   ├── connected/
│   └── unconnected/
├── models/
│   ├── classification/efficientnet/
│   │   └── efficientnet_hook_classifier_best.pth
│   └── detection/rfdetr/
│       └── checkpoint_best_ema_v2.pth
├── notebooks/pipelines/
│   └── construction_safety_team_final.ipynb
├── samples/videos/
│   └── input_video.mp4
└── outputs/pipeline/
```

`data/classification` 아래 이미지의 상위 경로에는 `connected` 또는 `unconnected` 폴더명이 있어야 합니다.

## 3. 패키지 설치

노트북 첫 설치 셀을 실행하거나 터미널에서 다음 명령을 실행합니다.

```powershell
python -m pip install "rfdetr==1.8.0" "supervision>=0.29.0" scikit-learn seaborn opencv-python-headless yt-dlp jupyter
```

PyTorch는 팀원의 CUDA 버전에 맞는 공식 설치 방법을 사용해야 합니다.

## 4. 로컬 프로젝트 경로 지정

방법 A: 노트북에서 직접 지정

```python
PROJECT_ROOT = Path(r"C:\경로\DL\code")
```

방법 B: PowerShell 환경변수 사용

```powershell
$env:CONSTRUCTION_SAFETY_PROJECT_ROOT="C:\경로\DL\code"
jupyter notebook
```

환경변수가 없으면 노트북을 실행한 현재 작업 폴더를 프로젝트 루트로 사용합니다.

## 5. 실행 목적별 셀 순서

### 새 EfficientNet 학습

```text
설치 → import → 경로/CONFIG → 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8
```

### 저장된 가중치로 단일 이미지 추론

```text
설치 → import → 경로/CONFIG → 1 → 2 → 3 → 4 → 9
```

### 저장된 두 모델로 영상 추론

```text
설치 → import → 경로/CONFIG → 1 → 2 → 3 → 4 → 10 → 11 → 12
```

6번 학습을 건너뛰어도 10번에서 Drive/로컬에 저장된 EfficientNet 체크포인트를 다시 로드합니다.

## 6. 두 모델의 역할

```text
RF-DETR Seg Large
→ worker/harness/hook/lanyard/lifeline 위치 탐지 및 segmentation

EfficientNet-B0
→ RF-DETR가 찾은 hook crop을 Connected/Unconnected로 분류

상태 머신
→ 프레임별 결과를 작업자별 SAFE/WARNING/DANGER로 변환
```

## 7. 팀원이 반드시 확인할 CONFIG

```python
CONFIG["data_root"]
CONFIG["classifier_checkpoint"]
CONFIG["rfdetr_checkpoint"]
CONFIG["input_video"]
CONFIG["output_video"]
```

다음 검사 코드가 모두 `True`여야 합니다.

```python
for key in ["data_root", "classifier_checkpoint", "rfdetr_checkpoint", "input_video"]:
    path = Path(CONFIG[key])
    print(key, path.exists(), path)
```

## 8. 결과 파일

```text
outputs/pipeline/
├── efficientnet_training_metrics.csv
├── pipeline_output_v2.mp4
└── safety_events.csv
```

## 9. 주의사항

- Test 결과를 보고 threshold를 반복 조정하면 데이터 누수가 발생합니다.
- RF-DETR class names에 worker/harness/hook/lanyard/lifeline이 있는지 확인합니다.
- `test-CwuI`는 기존 체크포인트에 포함된 불필요한 임시 클래스이며 안전 판단에는 사용하지 않습니다.
- Hook 미탐 DANGER는 실제 미체결 확정이 아니라 영상에서 안전 상태를 확인하지 못한 상황일 수 있습니다.
- 여러 작업자가 있는 영상에서는 거리 기반 작업자-후크 매칭 오류를 확인해야 합니다.
- YouTube 영상은 이용 권한과 저작권을 확인한 테스트 용도로만 사용합니다.
