# Construction Safety Monitoring — Project Docs

건설 현장 CCTV 영상에서 작업자의 안전고리 체결 여부를 판별하는 딥러닝 프로젝트의 문서 저장소입니다. 회의 기록, 최종 발표자료, 프로젝트 보고서와 실행 가이드를 관리합니다.

모델 학습·추론 코드는 [Tacademy-DL-team1/code](https://github.com/Tacademy-DL-team1/code) 저장소에서 별도로 관리합니다.

## 저장소 구성

```text
.
├── .github/ISSUE_TEMPLATE/   # GitHub 이슈 템플릿
├── assets/diagrams/          # 프로젝트 흐름도
├── meeting_log/              # 날짜별 회의록 (YYMMDD_meeting.md)
├── presentations/            # 최종 발표자료
├── reports/                  # 상세·요약 보고서 및 로컬 실행 가이드
├── research/                 # 참고문헌 목록(원문 PDF는 로컬 보관)
├── .gitattributes            # 줄바꿈·바이너리 파일 처리 규칙
├── FILE_GUIDE.txt            # 파일별 내용 요약
├── gitmessage.txt            # 커밋 메시지 템플릿
└── README.md
```

## 주요 문서

- [최종 발표자료](presentations/construction_safety_final_presentation.pdf)
- [프로젝트 상세 보고서](reports/construction_safety_enhancement_report.md)
- [프로젝트 요약 보고서](reports/construction_safety_enhancement_summary.md)
- [로컬 실행 가이드](reports/local_run_guide.md)
- [프로젝트 수행 흐름도](assets/diagrams/project_workflow.png)
- [파일별 설명](FILE_GUIDE.txt)

## 문서 관리 원칙

- 이 저장소에는 공개 가능한 문서와 이미지, 발표자료만 커밋합니다.
- 원천·가공 데이터, CCTV 영상, 모델 가중치, 체크포인트, 실험 결과와 비밀정보는 커밋하지 않습니다.
- 논문 원문 PDF는 저작권과 용량을 고려해 로컬에 보관하고, GitHub에는 참고문헌 정보만 남깁니다.
- 회의록 파일명은 `YYMMDD_meeting.md`, 일반 문서 파일명은 소문자 `snake_case`를 사용합니다.
- 변경은 이슈 생성 → 이슈 브랜치 작업 → Pull Request 검토 → `main` 병합 순서로 진행합니다.
