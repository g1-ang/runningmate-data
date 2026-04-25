#!/usr/bin/env python3
"""
roadrun.co.kr 의 한국 마라톤 일정 페이지를 파싱해서 RunningMate 스키마
JSON 으로 변환한다. GitHub Actions cron 또는 로컬에서 실행 가능.

사용:
    pip install requests beautifulsoup4
    python3 scripts/scrape_marathons.py > RunningMate/Resources/marathons.json

Politeness:
- list.php 1회 + 각 view.php?no=N 마다 sleep(REQUEST_DELAY)
- 식별 가능한 User-Agent 로 본인 contact 명시
- 출처 attribution 을 각 마라톤 데이터에 source 필드로 포함

법적/윤리적 노트:
- 가져오는 건 "사실" (공개 마라톤 일정) 이라 저작권 직접 대상 아님
- 출처 표기 + 신청 URL deeplink (원본 사이트로 트래픽 보냄) + 저트래픽
  (주 1회) 로 윤리 부담 최소화
- 사이트 측 클레임 시 즉시 중단 + 협력 요청으로 전환
"""

from __future__ import annotations

import json
import re
import sys
import time
import uuid
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone, timedelta
from typing import Optional

import requests
from bs4 import BeautifulSoup

LIST_URL = "http://www.roadrun.co.kr/schedule/list.php"
VIEW_URL_TMPL = "http://www.roadrun.co.kr/schedule/view.php?no={no}"
USER_AGENT = "RunningMateBot/1.0 (+https://github.com/g1-ang/RunningMate; contact:sn_contentsmkt@snowcorp.com)"
REQUEST_DELAY = 1.2  # 초당 1회 미만으로 정중하게
MAX_DETAIL_FAILS = 5  # 연속 실패 N회면 중단
KST = timezone(timedelta(hours=9))

# UUID v5 namespace — `marathon.pe.kr` 도메인을 키로 변환해서 안정적
# 마라톤 UUID 생성. 같은 no 는 매번 같은 UUID 가 나온다.
NAMESPACE = uuid.uuid5(uuid.NAMESPACE_DNS, "marathon.pe.kr")

# 우리 앱 Region enum 은 9개 광역 (서울/경기/인천/부산/대구/광주/대전/강원/제주).
# 다른 도(충청·전라·경상·울산·세종) 는 인접 광역으로 흡수.
#
# Detection 우선순위: 먼저 venue (정확 가능성 높음), 다음 organizer, 다음 name.
# 짧은 키워드(예: "동")가 긴 키워드("강동")보다 먼저 매칭되지 않게,
# 긴 키워드부터 검사한다.
REGION_MAP: list[tuple[str, str]] = [
    # 광역명 우선
    ("서울", "서울"), ("경기", "경기"), ("인천", "인천"),
    ("부산", "부산"), ("대구", "대구"), ("광주", "광주"),
    ("대전", "대전"), ("강원", "강원"), ("제주", "제주"),
    ("울산", "부산"), ("세종", "대전"),

    # 서울 구·동·랜드마크
    ("강남", "서울"), ("서초", "서울"), ("송파", "서울"), ("강동", "서울"),
    ("마포", "서울"), ("영등포", "서울"), ("여의도", "서울"), ("강서", "서울"),
    ("종로", "서울"), ("광화문", "서울"), ("중구", "서울"), ("용산", "서울"),
    ("성동", "서울"), ("동대문", "서울"), ("동작", "서울"), ("관악", "서울"),
    ("구로", "서울"), ("금천", "서울"), ("양천", "서울"), ("성북", "서울"),
    ("강북", "서울"), ("도봉", "서울"), ("노원", "서울"), ("은평", "서울"),
    ("서대문", "서울"), ("중랑", "서울"), ("광진", "서울"), ("상암", "서울"),
    ("잠실", "서울"), ("한강", "서울"), ("올림픽공원", "서울"), ("월드컵", "서울"),
    ("남산", "서울"), ("북한산", "서울"), ("관악산", "서울"),

    # 경기
    ("수원", "경기"), ("성남", "경기"), ("용인", "경기"), ("안양", "경기"),
    ("안산", "경기"), ("부천", "경기"), ("의왕", "경기"), ("과천", "경기"),
    ("화성", "경기"), ("평택", "경기"), ("파주", "경기"), ("김포", "경기"),
    ("고양", "경기"), ("의정부", "경기"), ("동두천", "경기"), ("양주", "경기"),
    ("구리", "경기"), ("남양주", "경기"), ("하남", "경기"), ("광명", "경기"),
    ("이천", "경기"), ("여주", "경기"), ("양평", "경기"), ("가평", "경기"),
    ("포천", "경기"), ("연천", "경기"), ("DMZ", "경기"), ("도라산", "경기"),
    ("남한산성", "경기"), ("청계산", "경기"),

    # 인천
    ("송도", "인천"), ("부평", "인천"), ("계양", "인천"), ("강화", "인천"),
    ("영종도", "인천"), ("을왕리", "인천"),

    # 부산·울산·경남
    ("해운대", "부산"), ("광안리", "부산"), ("동래", "부산"), ("부산진", "부산"),
    ("기장", "부산"),
    ("창원", "부산"), ("진주", "부산"), ("김해", "부산"), ("거제", "부산"),
    ("통영", "부산"), ("양산", "부산"), ("밀양", "부산"), ("사천", "부산"),

    # 대구·경북
    ("수성", "대구"), ("달서", "대구"), ("달성", "대구"), ("동성로", "대구"),
    ("두류공원", "대구"),
    ("포항", "대구"), ("경주", "대구"), ("안동", "대구"), ("구미", "대구"),
    ("영천", "대구"), ("상주", "대구"), ("문경", "대구"), ("청도", "대구"),
    ("울진", "대구"), ("울릉", "대구"), ("영주", "대구"), ("영덕", "대구"),

    # 광주·전라
    ("광산", "광주"), ("상무지구", "광주"),
    ("전주", "광주"), ("군산", "광주"), ("익산", "광주"), ("남원", "광주"),
    ("정읍", "광주"), ("새만금", "광주"), ("부안", "광주"), ("무주", "광주"),
    ("순창", "광주"), ("진안", "광주"), ("장수", "광주"),
    ("여수", "광주"), ("순천", "광주"), ("목포", "광주"), ("나주", "광주"),
    ("영암", "광주"), ("해남", "광주"), ("강진", "광주"), ("영광", "광주"),
    ("담양", "광주"), ("보성", "광주"), ("장흥", "광주"), ("함평", "광주"),
    ("화순", "광주"), ("곡성", "광주"), ("구례", "광주"), ("완도", "광주"),
    ("진도", "광주"), ("신안", "광주"),

    # 대전·충청·세종
    ("유성", "대전"), ("둔산", "대전"), ("대덕", "대전"),
    ("천안", "대전"), ("아산", "대전"), ("당진", "대전"), ("서산", "대전"),
    ("청주", "대전"), ("충주", "대전"), ("음성", "대전"), ("진천", "대전"),
    ("보은", "대전"), ("옥천", "대전"), ("영동", "대전"), ("증평", "대전"),
    ("괴산", "대전"), ("단양", "대전"), ("제천", "대전"), ("홍성", "대전"),
    ("예산", "대전"), ("태안", "대전"), ("부여", "대전"), ("논산", "대전"),
    ("계룡", "대전"), ("금산", "대전"), ("공주", "대전"), ("보령", "대전"),
    ("서천", "대전"), ("청양", "대전"), ("건양", "대전"),

    # 강원
    ("춘천", "강원"), ("강릉", "강원"), ("속초", "강원"), ("원주", "강원"),
    ("동해", "강원"), ("삼척", "강원"), ("태백", "강원"), ("정선", "강원"),
    ("평창", "강원"), ("홍천", "강원"), ("횡성", "강원"), ("영월", "강원"),
    ("화천", "강원"), ("양양", "강원"), ("고성", "강원"), ("인제", "강원"),
    ("철원", "강원"), ("설악산", "강원"), ("오대산", "강원"),
    ("오크밸리", "강원"),

    # 제주
    ("서귀포", "제주"), ("애월", "제주"), ("한라", "제주"), ("성산", "제주"),
    ("우도", "제주"), ("표선", "제주"), ("협재", "제주"),
]
DEFAULT_REGION = "서울"

# 대회 코스 추출용 정규식 패턴.
# - 우리 앱 enum 은 5km / 10km / Half / Full 4종
# - 울트라(50/100/200km, trail 등) 는 풀로 정규화 (지도 카테고리 부합)
# - "100km" 가 "10km" 로 오인되지 않도록 lookbehind 로 앞 자릿수 차단
COURSE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"풀|42(?:\.195)?\s*km|Full", re.IGNORECASE), "Full"),
    (re.compile(r"하프|21\s*km|Half", re.IGNORECASE), "Half"),
    (re.compile(r"(?<!\d)10\s*km", re.IGNORECASE), "10km"),
    (re.compile(r"(?<!\d)5\s*km|5\s*K\b", re.IGNORECASE), "5km"),
    # 울트라 카테고리도 Full 풀로 묶음 (50km / 100km / 200km / trail)
    (re.compile(r"(?<!\d)(?:50|100|200|300)\s*km|울트라|ultra|trail", re.IGNORECASE), "Full"),
]


@dataclass
class ScrapedMarathon:
    id: str
    name: str
    region: str
    courses: list[str]
    registrationOpenDate: str
    registrationCloseDate: str
    announcementDate: str
    raceDate: str
    venue: str
    officialURL: str
    organizer: str
    entryFee: str
    sourceID: str  # roadrun.co.kr 의 view.php no
    source: str = "roadrun.co.kr"


# ----------------- HTTP helpers -----------------

def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    return s


def _fetch(session: requests.Session, url: str) -> Optional[str]:
    try:
        r = session.get(url, timeout=15)
        r.encoding = "euc-kr"
        if r.status_code != 200:
            return None
        return r.text
    except requests.RequestException as e:
        print(f"⚠️  fetch failed {url}: {e}", file=sys.stderr)
        return None


# ----------------- Parsing -----------------

VIEW_HREF_RE = re.compile(r"view\.php\?no=(\d+)")
COURSE_TEXT_RE = re.compile(r"<font[^>]*color=\"#990000\"[^>]*>([^<]+)</font>")


def parse_list(html: str) -> list[tuple[str, str, list[str]]]:
    """리스트 페이지에서 (no, 대회명, 코스 문자열들) 추출."""
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for a in soup.find_all("a", href=re.compile(r"view\.php\?no=\d+")):
        m = VIEW_HREF_RE.search(a["href"])
        if not m:
            continue
        no = m.group(1)
        name = a.get_text(strip=True)
        if not name or len(name) < 3:
            continue
        # 코스: 같은 부모 또는 다음 형제의 #990000 빨간 글씨
        parent = a.find_parent()
        course_str = ""
        if parent:
            red = parent.find("font", color="#990000")
            if red:
                course_str = red.get_text(strip=True)
        out.append((no, name, _normalize_courses(course_str)))
    return out


def _normalize_courses(raw: str) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for pattern, label in COURSE_PATTERNS:
        if pattern.search(raw) and label not in seen:
            seen.add(label)
            result.append(label)
    # 표시 순서 정규화: 짧은 코스 먼저 → 긴 코스
    order = {"5km": 0, "10km": 1, "Half": 2, "Full": 3}
    result.sort(key=lambda c: order.get(c, 9))
    return result or ["10km"]  # fallback


def parse_view(html: str) -> dict:
    """상세 페이지에서 일시/장소/주최/접수기간/홈페이지 추출."""
    soup = BeautifulSoup(html, "html.parser")
    fields = {}
    # label cell (#86B7DF) 다음 형제 cell 이 value
    for label_td in soup.find_all("td", bgcolor="#86B7DF"):
        label = label_td.get_text(strip=True)
        # 다음 형제 td (white) 가 값
        nxt = label_td.find_next("td", bgcolor="white")
        if not nxt:
            continue
        value = nxt.get_text(" ", strip=True)
        if label and value:
            fields[label] = value
    return fields


# ----------------- Date parsing -----------------

KOREAN_DATE_RE = re.compile(r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일")
RANGE_SEP_RE = re.compile(r"[~∼–-]")


def _parse_korean_date(text: str) -> Optional[datetime]:
    m = KOREAN_DATE_RE.search(text)
    if not m:
        return None
    y, mo, d = (int(x) for x in m.groups())
    try:
        return datetime(y, mo, d, 9, 0, 0, tzinfo=KST)
    except ValueError:
        return None


def _parse_range(text: str) -> tuple[Optional[datetime], Optional[datetime]]:
    """ '2026년1월23일~2026년3월8일' → (open, close)."""
    if not text:
        return None, None
    parts = RANGE_SEP_RE.split(text, 1)
    if len(parts) != 2:
        d = _parse_korean_date(text)
        return d, d
    return _parse_korean_date(parts[0]), _parse_korean_date(parts[1])


def _iso(d: Optional[datetime]) -> str:
    if not d:
        return ""
    return d.strftime("%Y-%m-%dT%H:%M:%S+09:00")


# ----------------- Region detection -----------------

def detect_region(venue: str, name: str, organizer: str = "") -> str:
    """venue → organizer → name 순으로 매칭. 더 정확한 쪽 우선."""
    for haystack in (venue, organizer, name):
        if not haystack:
            continue
        for needle, mapped in REGION_MAP:
            if needle in haystack:
                return mapped
    return DEFAULT_REGION


# ----------------- URL extraction -----------------

URL_RE = re.compile(r"https?://[^\s\"'<>]+")


def extract_official_url(text: str, fallback: str) -> str:
    m = URL_RE.search(text)
    return m.group(0) if m else fallback


# ----------------- Main pipeline -----------------

def build_marathon(
    no: str, name: str, courses: list[str], session: requests.Session
) -> Optional[ScrapedMarathon]:
    detail_html = _fetch(session, VIEW_URL_TMPL.format(no=no))
    if not detail_html:
        return None
    fields = parse_view(detail_html)

    race_dt = _parse_korean_date(fields.get("대회일시", ""))
    if not race_dt:
        return None

    reg_open, reg_close = _parse_range(fields.get("접수기간", ""))
    if not reg_open:
        reg_open = race_dt - timedelta(days=60)
    if not reg_close:
        reg_close = race_dt - timedelta(days=14)

    venue = fields.get("대회장소", "")
    organizer = fields.get("주최단체", "")
    homepage = fields.get("홈페이지", "")
    official = extract_official_url(homepage, fallback=VIEW_URL_TMPL.format(no=no))

    region = detect_region(venue, name, organizer)
    announcement = race_dt - timedelta(days=7)

    stable_uuid = str(uuid.uuid5(NAMESPACE, f"roadrun-{no}")).upper()

    return ScrapedMarathon(
        id=stable_uuid,
        name=name,
        region=region,
        courses=courses,
        registrationOpenDate=_iso(reg_open),
        registrationCloseDate=_iso(reg_close),
        announcementDate=_iso(announcement),
        raceDate=_iso(race_dt),
        venue=venue,
        officialURL=official,
        organizer=organizer,
        entryFee="",
        sourceID=no,
    )


def _is_future(iso_date: str, days_buffer: int = 7) -> bool:
    """raceDate 가 (오늘 - 버퍼) 보다 미래인 것만 통과."""
    try:
        dt = datetime.strptime(iso_date[:10], "%Y-%m-%d").replace(tzinfo=KST)
    except ValueError:
        return False
    cutoff = datetime.now(KST) - timedelta(days=days_buffer)
    return dt > cutoff


def main(limit: Optional[int] = None) -> int:
    session = _session()
    print("📥 list.php 가져오는 중…", file=sys.stderr)
    list_html = _fetch(session, LIST_URL)
    if not list_html:
        print("❌ list.php 실패", file=sys.stderr)
        return 1

    rows = parse_list(list_html)
    print(f"🔍 {len(rows)}개 대회 후보 발견", file=sys.stderr)
    if limit:
        rows = rows[:limit]
        print(f"   (limit={limit} 적용)", file=sys.stderr)

    marathons: list[ScrapedMarathon] = []
    consecutive_fails = 0
    for i, (no, name, courses) in enumerate(rows, 1):
        time.sleep(REQUEST_DELAY)
        m = build_marathon(no, name, courses, session)
        if m is None:
            consecutive_fails += 1
            print(f"  [{i}/{len(rows)}] ✗ no={no} {name[:30]}", file=sys.stderr)
            if consecutive_fails >= MAX_DETAIL_FAILS:
                print(f"⚠️ 연속 실패 {MAX_DETAIL_FAILS}회, 중단", file=sys.stderr)
                break
            continue
        consecutive_fails = 0
        # 과거 대회 (오늘 - 7일 이전) 는 V1 캘린더에서 의미 없음
        if not _is_future(m.raceDate):
            print(f"  [{i}/{len(rows)}] · {name[:40]} ({m.raceDate[:10]}) past, skip", file=sys.stderr)
            continue
        marathons.append(m)
        print(f"  [{i}/{len(rows)}] ✓ {name[:40]} ({m.raceDate[:10]}, {m.region})", file=sys.stderr)

    # Output schema 1
    payload = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(KST).strftime("%Y-%m-%dT%H:%M:%S+09:00"),
        "source": "roadrun.co.kr (마라톤온라인)",
        "marathons": [asdict(m) for m in marathons],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"✅ {len(marathons)}개 대회 → JSON 출력 완료", file=sys.stderr)
    return 0


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="처음 N개만 (테스트용)")
    args = ap.parse_args()
    sys.exit(main(limit=args.limit))
