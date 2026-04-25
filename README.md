# runningmate-data

[러닝메이트 iOS 앱](https://github.com/g1-ang/RunningMate) 의 마라톤 일정 데이터.

## 구조

```
data/
└── marathons.json     ← 앱이 fetch 하는 정적 데이터
scripts/
└── scrape_marathons.py
.github/workflows/
└── scrape.yml         ← 매주 일요일 03:00 KST 자동 갱신
```

## 데이터 출처

- 1차: [마라톤온라인 (roadrun.co.kr)](http://www.roadrun.co.kr/schedule/list.php) — 한국 마라톤 일정 통합 인덱스
- 정중한 자동화: 주 1회 / 요청당 1.2초 간격 / 식별 가능한 User-Agent

각 대회의 정확한 일정·신청·참가비는 **반드시 대회 공식 사이트**에서 재확인하세요.

## 라이브 URL

```
https://raw.githubusercontent.com/g1-ang/runningmate-data/main/data/marathons.json
```

러닝메이트 앱은 시작할 때 이 URL 에서 fetch 후 단말 캐시에 저장. 실패 시 앱 번들 fallback.

## 스키마

```json
{
  "schemaVersion": 1,
  "generatedAt": "2026-04-25T22:01:55+09:00",
  "source": "roadrun.co.kr (마라톤온라인)",
  "marathons": [
    {
      "id": "UUID",
      "name": "대회명",
      "region": "서울 | 경기 | 인천 | 부산 | 대구 | 광주 | 대전 | 강원 | 제주",
      "courses": ["5km", "10km", "Half", "Full"],
      "registrationOpenDate": "ISO8601 +09:00",
      "registrationCloseDate": "ISO8601 +09:00",
      "announcementDate": "ISO8601 +09:00",
      "raceDate": "ISO8601 +09:00",
      "venue": "장소",
      "officialURL": "공식 사이트",
      "organizer": "주최",
      "entryFee": "참가비",
      "sourceID": "원본 시스템 ID",
      "source": "출처 도메인"
    }
  ]
}
```

## 수동 실행

```bash
pip install requests beautifulsoup4
python3 scripts/scrape_marathons.py > data/marathons.json
```

## 라이선스

스크래퍼 코드는 본 레포 소유. 마라톤 일정 *데이터* 자체의 1차 출처는 위 명시. 데이터 사용 시 출처 표기를 권장합니다.
