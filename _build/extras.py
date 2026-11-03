# -*- coding: utf-8 -*-
"""
VISIT ONE 확장 기능 (generate.py 에서 호출)
 1) 주간 리포트   /news/weekly/<YYYY-Www>/
 2) 정책·제도     /news/policy/  /news/policy/<id>/   (정책브리핑 정책뉴스 API, 공공누리 1유형만 본문 게재)
 3) 분양가 vs 주변 실거래가  (국토부 아파트 매매 실거래가 API, 카카오 좌표→법정동코드)
 4) 분양 소식 허브 /news/
"""
import os, re, json, time, glob, html as _html, datetime as dt, urllib.request, urllib.parse
import xml.etree.ElementTree as ET

G = None  # generate 모듈 (init 에서 주입)

def init(gen_module):
    global G
    G = gen_module

def _get(url, headers=None, timeout=40):
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=headers or {})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:
            print("retry", url.split("?")[0], e); time.sleep(2 + attempt * 3)
    return ""

def _load(name, default):
    try: return json.load(open(os.path.join(G.ROOT, "data", name), encoding="utf-8"))
    except Exception: return default

def _save(name, obj):
    json.dump(obj, open(os.path.join(G.ROOT, "data", name), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))

esc = lambda s: _html.escape("" if s is None else str(s), quote=True)

# ═════════════════════════ 3) 실거래가 ═════════════════════════
RTMS = "https://apis.data.go.kr/1613000/RTMSDataSvcAptTrade/getRTMSDataSvcAptTrade"

def region_codes(all_h, geo):
    """단지 id → [시군구코드5, 법정동명] (카카오 coord2regioncode, 캐시)"""
    reg = _load("region.json", {})
    key = os.environ.get("KAKAO_REST_KEY")
    if key:
        for h in all_h:
            g = geo.get(h["id"])
            if not g or h["id"] in reg: continue
            u = "https://dapi.kakao.com/v2/local/geo/coord2regioncode.json?" + urllib.parse.urlencode({"x": g[1], "y": g[0]})
            t = _get(u, {"Authorization": "KakaoAK " + key})
            try:
                docs = json.loads(t).get("documents") or []
                b = next((d for d in docs if d.get("region_type") == "B"), None)
                if b: reg[h["id"]] = [b["code"][:5], b.get("region_3depth_name") or ""]
            except Exception: pass
            time.sleep(0.03)
        _save("region.json", reg)
    return reg

def fetch_trades(lawd, ym, cache, today):
    """한 달치 거래 (지난달 이전은 확정 → 캐시 재사용)"""
    k = f"{lawd}:{ym}"
    final = ym < (today.replace(day=1) - dt.timedelta(days=1)).strftime("%Y%m")
    if final and k in cache: return cache[k]
    key = os.environ.get("APPLYHOME_KEY")
    if not key: return cache.get(k, [])
    out, page = [], 1
    while True:
        t = _get(RTMS + "?" + urllib.parse.urlencode({"serviceKey": key, "LAWD_CD": lawd, "DEAL_YMD": ym, "numOfRows": 1000, "pageNo": page}))
        try: root = ET.fromstring(t)
        except Exception: break
        items = root.findall(".//item")
        for it in items:
            g = lambda n: (it.findtext(n) or "").strip()
            if g("cdealType") in ("O", "Y"): continue          # 해제 거래 제외
            try:
                out.append([g("umdNm"), round(float(g("excluUseAr") or 0), 1), int(g("dealAmount").replace(",", "") or 0), int(g("buildYear") or 0)])
            except Exception: pass
        total = int(root.findtext(".//totalCount") or 0)
        if page * 1000 >= total or not items: break
        page += 1
    cache[k] = out
    time.sleep(0.05)
    return out

def market_compare(all_h, geo, today):
    """대상 단지(아파트, 최근 공고)에 h['mkt'] = [{label, excl, price, avg, n, lo, hi, scope, new_avg, new_n}] 설정"""
    targets = [h for h in all_h if h["cat"] in ("A", "R", "T") and h["types"] and
               (G.status(h)[0] != "마감" or (G.d(h["notice"]) and G.d(h["notice"]) >= today - dt.timedelta(days=120)))]
    if not targets: return
    reg = region_codes(targets, geo)
    cache = _load("trades.json", {})
    months = [(today.replace(day=1) - dt.timedelta(days=31 * i)).strftime("%Y%m") for i in range(12)]
    by_lawd = {}
    for h in targets:
        r = reg.get(h["id"])
        if r: by_lawd.setdefault(r[0], []).append(h)
    for lawd, hs in by_lawd.items():
        trades = []
        for ym in months: trades += fetch_trades(lawd, ym, cache, today)
        for h in hs:
            dong = reg[h["id"]][1]
            rows = []
            for t in h["types"]:
                if not t["excl"] or not t["price"]: continue
                near = lambda tr: abs(tr[1] - t["excl"]) <= 5
                same = [tr for tr in trades if near(tr) and tr[0] == dong]
                scope = f"{dong} 같은 면적대" if len(same) >= 3 else ""
                if not scope:
                    same = [tr for tr in trades if near(tr)]
                    scope = "같은 시·군·구 같은 면적대"
                if len(same) < 3: continue
                ps = sorted(tr[2] for tr in same)
                new = [tr[2] for tr in same if tr[3] and tr[3] >= today.year - 10]
                rows.append(dict(label=t["label"], excl=t["excl"], price=t["price"], avg=int(sum(ps) / len(ps)), n=len(ps),
                                 lo=ps[0], hi=ps[-1], scope=scope, new_avg=int(sum(new) / len(new)) if len(new) >= 3 else 0, new_n=len(new)))
            # 같은 전용 59/84 등 중복 타입은 대표 1개만 (최고가 기준)
            uniq = {}
            for r_ in rows:
                k = int(r_["excl"])
                if k not in uniq or r_["price"] > uniq[k]["price"]: uniq[k] = r_
            if uniq: h["mkt"] = sorted(uniq.values(), key=lambda x: x["excl"])
    # 오래된 캐시 정리(13개월 이전)
    keep = set(months)
    cache = {k: v for k, v in cache.items() if k.split(":")[1] in keep}
    _save("trades.json", cache)

def mkt_box(h):
    rows = h.get("mkt") or []
    if not rows: return ""
    won = G.won
    trs = ""
    for r in rows:
        diff = r["price"] - (r["new_avg"] or r["avg"])
        base = r["new_avg"] or r["avg"]
        pct = diff / base * 100 if base else 0
        tag = (f'<span class="mk-lo">주변 시세보다 약 {won(abs(diff))} 낮음</span>' if pct <= -3 else
               f'<span class="mk-hi">주변 시세보다 약 {won(abs(diff))} 높음</span>' if pct >= 3 else '<span class="mk-eq">주변 시세와 비슷</span>')
        trs += (f'<tr><td><b>{esc(r["label"])}</b><small>{r["excl"]:.0f}㎡</small></td><td class="pr">{won(r["price"])}</td>'
                f'<td>{won(r["avg"])}<small>{r["n"]}건 · {won(r["lo"])}~{won(r["hi"])}</small></td>'
                f'<td>{won(r["new_avg"]) + f"<small>{r["new_n"]}건</small>" if r["new_avg"] else "-"}</td><td>{tag}</td></tr>')
    scope = rows[0]["scope"]
    return (f'<h2>분양가 vs 주변 실거래가</h2><p class="muted">최근 12개월 국토교통부 아파트 매매 실거래가 중 <b>{esc(scope)}</b>(전용 ±5㎡) 거래와 비교했습니다. '
            f'신축 기준은 준공 10년 이내 아파트입니다.</p><div class="tw"><table class="tbl dt mk"><thead><tr><th>타입</th><th>최고 분양가</th>'
            f'<th>주변 평균 실거래가</th><th>신축(10년 이내) 평균</th><th>비교</th></tr></thead><tbody>{trs}</tbody></table></div>'
            f'<p class="muted">※ 실거래가는 층·향·연식에 따라 차이가 크며, 분양가는 타입별 최고가 기준입니다. 단순 참고용으로만 활용하세요. 출처: 국토교통부 실거래가 공개시스템(공공데이터)</p>')

# ═════════════════════════ 2) 정책·제도 ═════════════════════════
POLICY = "https://apis.data.go.kr/1371000/policyNewsService2/policyNewsList2"
POL_MIN = ("국토교통부", "금융위원회", "기획재정부", "재정경제부", "행정안전부", "국무조정실")
POL_RE = re.compile(r"주택|청약|분양|부동산|아파트|전세|월세|임대주택|택지|재건축|재개발|신도시|주거|주담대|주택담보|DSR|LTV|공공주택|정비사업|집값|입주")

def fetch_policy(today):
    db = _load("policy.json", {})
    key = os.environ.get("APPLYHOME_KEY")
    if key:
        for back in (0, 3, 6):    # 최근 9일 (API는 한 번에 3일까지)
            e = today - dt.timedelta(days=back); s = e - dt.timedelta(days=2)
            t = _get(POLICY + "?" + urllib.parse.urlencode({"serviceKey": key, "startDate": s.strftime("%Y%m%d"), "endDate": e.strftime("%Y%m%d")}))
            try: root = ET.fromstring(t)
            except Exception: continue
            for it in root.iter("NewsItem"):
                g = lambda n: (it.findtext(n) or "").strip()
                nid, title, mins = g("NewsItemId"), g("Title"), g("MinisterCode")
                if not nid or nid in db: continue
                text = title + " " + g("SubTitle1")
                if not any(m in mins for m in POL_MIN) or not POL_RE.search(text): continue
                m = re.match(r"(\d{2})/(\d{2})/(\d{4})", g("ApproveDate"))
                date = f"{m.group(3)}-{m.group(1)}-{m.group(2)}" if m else today.isoformat()
                db[nid] = dict(id=nid, title=title, sub=g("SubTitle1"), body=g("DataContents"), min=mins, date=date,
                               url=g("OriginalUrl"), kogl=g("KoglType"))
            time.sleep(0.2)
        # 최근 400건만 유지
        db = dict(sorted(db.items(), key=lambda kv: kv[1]["date"], reverse=True)[:400])
        _save("policy.json", db)
    return sorted([x for x in db.values() if POL_RE.search(x["title"] + " " + (x.get("sub") or "")) and not (re.search(r"산업단지|산단", x["title"]) and not re.search(r"주택|아파트|분양|주거", x["title"]))], key=lambda x: (x["date"], x["id"]), reverse=True)

def clean_body(htm):
    htm = re.sub(r"(?is)<(script|style|iframe)[^>]*>.*?</\1>", "", htm or "")
    htm = re.sub(r"(?is)<img[^>]*>", "", htm)
    htm = re.sub(r"(?is)<(?!/?(p|br|b|strong|ul|ol|li|table|tr|td|th|thead|tbody|h3|h4)\b)[^>]+>", "", htm)
    htm = re.sub(r'(?i)\s(style|class|id|width|height|align)="[^"]*"', "", htm)
    htm = re.sub(r"(<br\s*/?>\s*){2,}", "<br>", htm)
    return htm.strip()

def plain(htm, n=160):
    t = re.sub(r"<[^>]+>", " ", htm or ""); t = _html.unescape(re.sub(r"\s+", " ", t)).strip()
    return t[:n] + ("…" if len(t) > n else "")

def related_danji(text, all_h):
    """기사 본문에 나온 지역(시군구)과 같은 지역의 진행중 단지 몇 곳"""
    hits = []
    for h in all_h:
        if G.status(h)[0] == "마감": continue
        parts = h["addr"].split()
        sgg = parts[1] if len(parts) > 1 else ""
        key = re.sub(r"(시|군|구)$", "", sgg)
        if len(key) >= 2 and key in text: hits.append(h)
    return hits[:4]

def policy_pages(items, all_h, updated):
    paths = []
    sub = "/news/policy/"
    lis = "".join(f'<li><a href="{sub}{p["id"]}/"><small class="nd">{p["date"]} · {esc(p["min"])}</small><b>{esc(p["title"])}</b><span>{esc(plain(p["sub"] or p["body"], 120))}</span></a></li>' for p in items[:120])
    body = (f'<header class="ph"><p class="cat">POLICY</p><h1>정책·제도 소식</h1><p class="lead">청약·분양·주택 공급·대출 등 부동산 관련 정부 정책 소식을 정책브리핑에서 매일 모아 정리합니다.</p></header>'
            f'<ul class="gl">{lis or "<li class=none>아직 수집된 소식이 없습니다.</li>"}</ul>'
            f'<p class="muted">출처: 대한민국 정책브리핑(www.korea.kr) · 공공누리 제1유형(출처표시) · 데이터 기준일 {updated}</p>')
    paths.append(G.page(G.ROOT, sub, "정책·제도 소식 · 청약·분양·주택 정책", "청약 제도, 주택 공급, 대출 규제 등 부동산 관련 정부 정책 소식을 매일 정리합니다. 출처 정책브리핑.",
                        body, [("분양 소식", "/news/"), ("정책·제도", sub)], [{"@context": "https://schema.org", "@type": "CollectionPage", "name": "정책·제도 소식", "url": G.SITE + sub}], og_type="website", updated=updated))
    for p in items[:150]:
        path = f"{sub}{p['id']}/"
        full = p.get("kogl") in ("1", "제1유형")   # 1유형(출처표시)만 본문 게재
        rel = related_danji(p["title"] + " " + plain(p["body"], 3000), all_h)
        relh = ('<h2>관련 지역 분양 단지</h2><ul class="drs">' + "".join(G.row(h) for h in rel) + "</ul>") if rel else ""
        content = clean_body(p["body"]) if full else f'<p>{esc(plain(p["body"], 400))}</p>'
        body = (f'<article class="guide"><p class="cat">정책·제도 · {esc(p["min"])}</p><h1>{esc(p["title"])}</h1>'
                f'<p class="upd" style="margin:0 0 6px">{p["date"]} · 출처 정책브리핑</p>'
                + (f'<p class="lead">{clean_body(p["sub"])}</p>' if p["sub"] else "")
                + f'<div class="polbody">{content}</div>'
                f'<p class="src muted">이 글은 대한민국 정책브리핑(www.korea.kr)의 기사를 공공누리 제1유형(출처표시)에 따라 게재했습니다. '
                f'<a href="{esc(p["url"])}" target="_blank" rel="noopener">원문 보기 →</a></p>{relh}'
                f'<nav class="pn"><a href="{sub}">← 정책·제도 목록</a><span></span><a href="/bunyang/">전국 분양정보 →</a></nav></article>')
        ld = [{"@context": "https://schema.org", "@type": "NewsArticle", "headline": p["title"][:110], "datePublished": p["date"], "inLanguage": "ko-KR",
               "isBasedOn": p["url"], "publisher": {"@type": "Organization", "name": "VISIT ONE"}, "sourceOrganization": {"@type": "GovernmentOrganization", "name": p["min"] or "대한민국 정부"}}]
        paths.append(G.page(G.ROOT, path, p["title"], plain(p["sub"] or p["body"], 150), body,
                            [("분양 소식", "/news/"), ("정책·제도", sub), (p["title"][:20], path)], ld, updated=updated))
    return paths

# ═════════════════════════ 1) 주간 리포트 ═════════════════════════
def week_info(today):
    mon = today - dt.timedelta(days=today.weekday())
    y, w, _ = mon.isocalendar()
    nth = (mon.day - 1) // 7
    return mon, f"{y}-W{w:02d}", f"{mon.month}월 {('첫째','둘째','셋째','넷째','다섯째')[nth]} 주"

def weekly_report(all_h, policy, updated):
    today = G.TODAY
    mon, wid, wname = week_info(today)
    sun = mon + dt.timedelta(days=6)
    pmon, psun = mon - dt.timedelta(days=7), mon - dt.timedelta(days=1)
    inweek = lambda s, a, b: G.d(s) and a <= G.d(s) <= b
    rcpt = sorted([h for h in all_h if inweek(h["sp_b"] or h["r_b"], mon, sun)], key=lambda h: h["sp_b"] or h["r_b"])
    wins = sorted([h for h in all_h if inweek(h["win"], mon, sun)], key=lambda h: h["win"])
    newn = sorted([h for h in all_h if inweek(h["notice"], pmon, sun) and h["cat"] != "R"], key=lambda h: h["notice"], reverse=True)
    remain = [h for h in rcpt if h["cat"] == "R"]
    top = sorted([h for h in all_h if h.get("rate_all") and inweek(h["r_b"] or h["sp_b"], pmon - dt.timedelta(days=14), psun)],
                 key=lambda h: h["rate_all"], reverse=True)[:10]
    pol = [p for p in policy if G.d(p["date"]) and G.d(p["date"]) >= pmon][:5]
    sido = {}
    for h in rcpt: sido[h["sido"]] = sido.get(h["sido"], 0) + 1
    sido_txt = ", ".join(f"{k} {v}곳" for k, v in sorted(sido.items(), key=lambda kv: -kv[1])[:4])
    title = f"{mon.year}년 {wname} 청약 일정 총정리 — 접수 {len(rcpt)}곳 · 당첨 발표 {len(wins)}곳"
    lead = (f"{mon.month}월 {mon.day}일부터 {sun.month}월 {sun.day}일까지 청약 접수가 시작되는 단지는 {len(rcpt)}곳"
            + (f"({sido_txt})" if sido_txt else "") + f"이고, 당첨자 발표는 {len(wins)}곳입니다."
            + (f" 지난주 청약 결과 가장 경쟁이 치열했던 곳은 {top[0]['name']}({G.cr_txt(top[0]['rate_all'])})입니다." if top else ""))
    def tbl(hs, cols):
        if not hs: return '<p class="none">해당 단지가 없습니다.</p>'
        th = "".join(f"<th>{c[0]}</th>" for c in cols)
        tr = "".join("<tr>" + "".join(f"<td>{c[1](h)}</td>" for c in cols) + "</tr>" for h in hs)
        return f'<div class="tw"><table class="tbl dt"><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table></div>'
    link = lambda h: f'<a href="/danji/{h["id"]}/"><b>{esc(h["name"])}</b></a>'
    c_rcpt = [("단지", link), ("지역", lambda h: esc(h["sido"])), ("유형", lambda h: esc(G.cat_label(h))), ("접수", lambda h: G.kdate(h["sp_b"] or h["r_b"])),
              ("세대", lambda h: f'{h["units"]:,}'), ("분양가", lambda h: esc(G.price_range(h)) or "-")]
    c_win = [("단지", link), ("지역", lambda h: esc(h["sido"])), ("발표", lambda h: G.kdate(h["win"])), ("계약", lambda h: G.kdate(h["c_b"]))]
    c_top = [("순위", lambda h: str(top.index(h) + 1)), ("단지", link), ("지역", lambda h: esc(h["sido"])), ("경쟁률", lambda h: f'<b class="crt">{G.cr_txt(h["rate_all"])}</b>')]
    c_new = [("단지", link), ("지역", lambda h: esc(h["sido"])), ("공고일", lambda h: G.kdate(h["notice"])), ("접수", lambda h: G.kdate(h["sp_b"] or h["r_b"]))]
    polh = ("".join(f'<li><a href="/news/policy/{p["id"]}/">{esc(p["title"])}</a> <small>{p["date"]} · {esc(p["min"])}</small></li>' for p in pol))
    body = (f'<article class="guide weekly"><p class="cat">WEEKLY REPORT · {wid}</p><h1>{esc(title)}</h1>'
            f'<p class="upd" style="margin:0 0 6px">{mon.isoformat()} ~ {sun.isoformat()} · VISIT ONE 데이터팀 · 업데이트 {updated}</p>'
            f'<p class="lead">{esc(lead)}</p>'
            f'<div class="wk-kpi"><div><b>{len(rcpt)}</b><small>이번 주 청약 접수</small></div><div><b>{len(wins)}</b><small>당첨 발표</small></div>'
            f'<div><b>{len(remain)}</b><small>무순위·잔여</small></div><div><b>{len(newn)}</b><small>새 입주자모집공고</small></div></div>'
            f'<h2>이번 주 청약 접수</h2>{tbl(rcpt, c_rcpt)}'
            f'<h2>이번 주 당첨자 발표</h2>{tbl(wins, c_win)}'
            f'<h2>무순위·잔여세대 (줍줍)</h2>{tbl(remain, c_rcpt)}'
            f'<h2>지난 청약 경쟁률 TOP 10</h2>{tbl(top, c_top)}'
            f'<h2>새로 나온 입주자모집공고</h2>{tbl(newn[:15], c_new)}'
            + (f'<h2>이번 주 정책·제도</h2><ul class="wk-pol">{polh}</ul>' if pol else "")
            + f'<p class="muted src">자료: 한국부동산원 청약홈 공공데이터, 대한민국 정책브리핑. 실제 청약 전에는 반드시 입주자모집공고를 확인하세요.</p>'
            f'<nav class="pn"><a href="/news/weekly/">← 주간 리포트 목록</a><span></span><a href="/calendar/">청약캘린더 →</a></nav></article>')
    path = f"/news/weekly/{wid}/"
    ld = [{"@context": "https://schema.org", "@type": "Article", "headline": title, "datePublished": mon.isoformat(), "dateModified": updated,
           "inLanguage": "ko-KR", "author": {"@type": "Organization", "name": "VISIT ONE"}, "publisher": {"@type": "Organization", "name": "VISIT ONE"}}]
    G.page(G.ROOT, path, title, esc(lead)[:150], body, [("분양 소식", "/news/"), ("주간 리포트", "/news/weekly/"), (wname, path)], ld, updated=updated)
    # 목록 메타 저장
    idx = _load("weekly.json", {})
    idx[wid] = dict(id=wid, title=title, lead=lead, date=mon.isoformat())
    _save("weekly.json", idx)
    reps = sorted(idx.values(), key=lambda x: x["id"], reverse=True)
    lis = "".join(f'<li><a href="/news/weekly/{r["id"]}/"><small class="nd">{r["date"]} 주간</small><b>{esc(r["title"])}</b><span>{esc(r["lead"][:120])}</span></a></li>' for r in reps)
    G.page(G.ROOT, "/news/weekly/", "주간 청약 리포트", "매주 청약 일정, 당첨 발표, 경쟁률 TOP, 무순위 줍줍, 새 공고를 데이터로 정리하는 VISIT ONE 주간 리포트.",
           f'<header class="ph"><p class="cat">WEEKLY</p><h1>주간 청약 리포트</h1><p class="lead">매주 월요일, 그 주의 청약 일정과 지난 청약 결과를 청약홈 데이터로 정리합니다.</p></header><ul class="gl">{lis}</ul>',
           [("분양 소식", "/news/"), ("주간 리포트", "/news/weekly/")], [{"@context": "https://schema.org", "@type": "CollectionPage", "name": "주간 청약 리포트", "url": G.SITE + "/news/weekly/"}], og_type="website", updated=updated)
    return [("/news/weekly/", "0.8", "weekly")] + [(f"/news/weekly/{r['id']}/", "0.7", "weekly") for r in reps], reps

# ═════════════════════════ 4) 분양 소식 허브 ═════════════════════════
def news_hub(reps, policy, updated, news=None):
    own = []
    for f in glob.glob(os.path.join(G.ROOT, "news", "*", "index.html")):
        slug = f.split(os.sep)[-2]
        if slug in ("weekly", "policy", "press"): continue
        s = open(f, encoding="utf-8").read()
        t = re.search(r"<h1>(.*?)</h1>", s); dte = re.search(r'"datePublished":\s*"([^"]+)"', s); ds = re.search(r'<meta name="description" content="([^"]*)"', s)
        if t: own.append(dict(slug=slug, title=_html.unescape(re.sub("<[^>]+>", "", t.group(1))), date=(dte.group(1) if dte else ""), desc=_html.unescape(ds.group(1)) if ds else ""))
    own.sort(key=lambda x: x["date"], reverse=True)
    w = "".join(f'<li><a href="/news/weekly/{r["id"]}/"><small class="nd">주간 리포트 · {r["date"]}</small><b>{esc(r["title"])}</b><span>{esc(r["lead"][:110])}</span></a></li>' for r in reps[:4])
    p = "".join(f'<li><a href="/news/policy/{x["id"]}/"><small class="nd">정책·제도 · {x["date"]} · {esc(x["min"])}</small><b>{esc(x["title"])}</b><span>{esc(plain(x["sub"] or x["body"], 110))}</span></a></li>' for x in policy[:8])
    o = "".join(f'<li><a href="/news/{x["slug"]}/"><small class="nd">VISIT ONE · {x["date"]}</small><b>{esc(x["title"])}</b><span>{esc(x["desc"][:110])}</span></a></li>' for x in own)
    nw = "".join(f'<li><a href="{esc(x["url"])}" target="_blank" rel="noopener nofollow"><small class="nd">분양 뉴스 · {esc(x["src"])} · {esc(x["date"][:10])}</small><b>{esc(x["title"])}</b><span>{esc(x["desc"][:110])}</span></a></li>' for x in (news or [])[:6])
    body = (f'<header class="ph"><p class="cat">NEWS</p><h1>분양 소식</h1><p class="lead">매주 청약 리포트와 부동산 정책·제도 변화를 한곳에서 확인하세요. 매일 자동으로 업데이트됩니다.</p></header>'
            f'<h2 class="nh">주간 청약 리포트 <a href="/news/weekly/">전체 보기 →</a></h2><ul class="gl">{w}</ul>'
            + (f'<h2 class="nh">분양 뉴스 <a href="/news/press/">전체 보기 →</a></h2><ul class="gl">{nw}</ul>' if nw else "")
            + f'<h2 class="nh">정책·제도 <a href="/news/policy/">전체 보기 →</a></h2><ul class="gl">{p or "<li class=none>수집 중입니다.</li>"}</ul>'
            + (f'<h2 class="nh">VISIT ONE 소식</h2><ul class="gl">{o}</ul>' if o else ""))
    G.page(G.ROOT, "/news/", "분양 소식 · 주간 청약 리포트 · 정책·제도", "매주 청약 일정 리포트와 청약·분양·주택 정책 소식을 매일 업데이트합니다. 비지트원 VISIT ONE 분양 소식.",
           body, [("분양 소식", "/news/")], [{"@context": "https://schema.org", "@type": "CollectionPage", "name": "분양 소식", "url": G.SITE + "/news/"}], og_type="website", updated=updated)
    return [("/news/", "0.8", "daily")]

# ═════════════════════════ 실행 ═════════════════════════
def run(all_h, geo, updated):
    out = []
    policy = []
    try: policy = fetch_policy(G.TODAY)
    except Exception as e: print("policy error", e)
    try: out += policy_pages(policy, all_h, updated)
    except Exception as e: print("policy pages error", e)
    reps = []
    try:
        w, reps = weekly_report(all_h, policy, updated); out += w
    except Exception as e: print("weekly error", e)
    news = []
    try:
        pp, news = press_page(PRESS_DB, all_h, updated); out += pp
    except Exception as e: print("press error", e)
    try: out += news_hub(reps, policy, updated, news)
    except Exception as e: print("hub error", e)
    try: out += keyword_pages(all_h, updated)
    except Exception as e:
        import traceback; traceback.print_exc()
    try: llms_txt(all_h, updated, policy, reps)
    except Exception as e: print("llms error", e)
    return [x if isinstance(x, tuple) else (x, "0.6", "monthly") for x in out]

def _meta(path):
    try: t = open(path, encoding="utf-8").read()
    except Exception: return None
    ti = re.search(r"<title>(.*?)</title>", t, re.S); de = re.search(r'<meta name="description" content="([^"]*)"', t)
    if not ti: return None
    return _html.unescape(ti.group(1).split(" | ")[0].strip()), _html.unescape(de.group(1)) if de else ""

def llms_txt(all_h, updated, policy=None, reps=None):
    """AI 검색(GEO)용 /llms.txt, /llms-full.txt 를 매 실행마다 최신 데이터로 생성"""
    S = G.SITE
    live = [h for h in all_h if G.status(h)[0] != "마감"]
    live.sort(key=lambda h: (h["sp_b"] or h["r_b"] or "9"))
    L = ["# VISIT ONE 비지트원", "",
         "> 전국 아파트·오피스텔·무순위·민간임대 분양정보와 청약 일정, 분양가, 경쟁률, 당첨 가점, 분양권 프리미엄, 주변 실거래가 비교를 매일 자동으로 정리하는 분양·청약 정보 플랫폼입니다. 데이터 출처는 한국부동산원 청약홈·국토교통부 실거래가 공개 API(공공데이터)이며, VISIT ONE은 개별 단지의 사업주체나 분양대행사가 아닙니다.",
         "", f"기준일: {updated} · 하루 2회(06시·12시 KST) 자동 업데이트 · 운영: 제이에이치기획(대표 하진훈) · shop0448@gmail.com", "",
         "## 주요 페이지", "",
         f"- [전국 분양정보]({S}/bunyang/): 지역·유형·청약 상태별 분양 단지 목록 ({len(all_h)}개 단지, 진행 중 {len(live)}개)",
         f"- [청약캘린더]({S}/calendar/): 이번 달·다음 달 청약 접수, 당첨 발표, 계약 일정",
         f"- [분양맵]({S}/map/): 전국 분양 단지를 지도에서 확인",
         f"- [무순위·잔여세대]({S}/remain/): 무순위(줍줍)·잔여세대 공고",
         f"- [분양 뉴스]({S}/news/press/): 분양·청약 관련 언론 보도 모음",
         f"- [정책·제도]({S}/news/policy/): 청약·주택 관련 정부 정책 소식(정책브리핑)",
         f"- [주간 청약 리포트]({S}/news/weekly/): 주간 일정·경쟁률 TOP·무순위 정리",
         f"- [청약·분양 가이드]({S}/guide/): 1순위 조건, 가점 계산, 특별공급, 분양 대금, 당첨 후 절차",
         f"- [부동산 용어사전]({S}/glossary/)", "",
         "## 지역별 분양정보", ""]
    for nm, sl in G.SIDO:
        n = sum(1 for h in all_h if h["sido"] == nm)
        if n: L.append(f"- [{nm} 분양정보]({S}/bunyang/{sl}/): {n}개 단지")
    if KW_INDEX:
        L += ["", "## 키워드별 분양정보", "", f"- [분양·청약 키워드 모음]({S}/keywords/)"]
        for g0 in ("월별", "유형", "브랜드"):
            L += [f"- [{kw} 분양정보]({S}{u}): {n}개 단지" for g, kw, u, n in KW_INDEX if g == g0]
    L += ["", "## 청약·분양 가이드", ""]
    for f in sorted(glob.glob(os.path.join(G.ROOT, "guide", "*", "index.html"))):
        slug = os.path.basename(os.path.dirname(f))
        m = _meta(f)
        if m and "이동" not in m[0]: L.append(f"- [{m[0]}]({S}/guide/{slug}/): {m[1]}")
    if reps:
        L += ["", "## 최근 주간 리포트", ""] + [f"- [{r['title']}]({S}/news/weekly/{r['id']}/)" for r in reps[:4] if isinstance(r, dict) and r.get("id")]
    L += ["", "## 지금 청약 중·예정 단지 (상위 40)", ""]
    for h in live[:40]:
        st = G.status(h)[1]; pr = G.price_range(h)
        L.append(f"- [{h['name']}]({S}/danji/{h['id']}/): {G.short_addr(h['addr'])} · {G.cat_label(h)} {h['units']:,}세대 · {st}" + (f" · 접수 {h['sp_b'] or h['r_b']}" if (h['sp_b'] or h['r_b']) else "") + (f" · 분양가 {pr}" if pr else ""))
    L += ["", f"전체 진행 단지의 핵심 정보는 [{S}/llms-full.txt]({S}/llms-full.txt)에 있습니다.", "",
          "## 제휴 현장 (광고)", "", f"- [청량리 시그니처]({S}/cheongnyangni/): 서울 동대문구 전농동 지역주택조합 조합원 모집. VISIT ONE 제휴 현장(광고)입니다.", "",
          "## 이용 안내", "", "- 청약 자격·일정은 반드시 청약홈 입주자모집공고 원문을 확인하세요.", "- 인용 시 출처를 'VISIT ONE 비지트원(visitone.co.kr), 청약홈 공공데이터 기반'으로 표기해 주세요."]
    open(os.path.join(G.ROOT, "llms.txt"), "w", encoding="utf-8").write("\n".join(L) + "\n")
    F = [f"# VISIT ONE 비지트원 · 진행 중 분양 단지 전체 ({updated} 기준)", "", "> 각 단지의 핵심 사실입니다. 출처: 한국부동산원 청약홈 공공데이터. 상세 페이지 링크를 함께 표기합니다.", ""]
    for h in live:
        F += [f"## {h['name']}", f"URL: {S}/danji/{h['id']}/"] + [f"- {x}" for x in G.facts(h)] + [""]
    open(os.path.join(G.ROOT, "llms-full.txt"), "w", encoding="utf-8").write("\n".join(F))

PRESS_DB = {"news": {}, "blog": {}}
NEWS_LIST = []

def before_pages(all_h, geo, today):
    """단지 페이지 만들기 전에 실행: 실거래 비교, 분양권, 뉴스·블로그 수집"""
    global PRESS_DB, NEWS_LIST
    for fn, args in ((market_compare, (all_h, geo, today)), (presale, (all_h, geo, today))):
        try: fn(*args)
        except Exception as e: print(fn.__name__, "error", e)
    try:
        PRESS_DB = fetch_press(all_h)
        NEWS_LIST = sorted(PRESS_DB.get("news", {}).values(), key=lambda x: x["date"], reverse=True)
        for x in NEWS_LIST: x["rel"] = [h["id"] for h in press_rel(all_h, x["title"] + " " + x["desc"])]
    except Exception as e: print("press fetch error", e)

def danji_extra(h):
    return pre_box(h) + danji_press(h, PRESS_DB, NEWS_LIST)

# ═════════════════════════ 5) LIVE 표시 ═════════════════════════
def now_kst():
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=9)))

def live_badge(extra=""):
    n = now_kst()
    return (f'<span class="live" data-ts="{n.isoformat()}"><i></i>LIVE</span> '
            f'<span class="live-t">{n.month}.{n.day} {n:%H:%M} 업데이트</span>{(" · " + extra) if extra else ""}')

LIVE_JS = ("<script>(function(){document.querySelectorAll('.live[data-ts]').forEach(function(e){var t=new Date(e.dataset.ts),m=Math.round((Date.now()-t)/60000),s;"
           "if(isNaN(m))return;s=m<1?'방금':m<60?m+'분 전':m<1440?Math.floor(m/60)+'시간 전':Math.floor(m/1440)+'일 전';var n=e.nextElementSibling;if(n)n.textContent=s+' 업데이트';});})();</script>")

# ═════════════════════════ 6) 분양권 프리미엄 ═════════════════════════
SILV = "https://apis.data.go.kr/1613000/RTMSDataSvcSilvTrade/getRTMSDataSvcSilvTrade"

def fetch_silv(lawd, ym, cache, today):
    k = f"S:{lawd}:{ym}"
    final = ym < (today.replace(day=1) - dt.timedelta(days=1)).strftime("%Y%m")
    if final and k in cache: return cache[k]
    key = os.environ.get("APPLYHOME_KEY")
    if not key: return cache.get(k, [])
    out, page = [], 1
    while True:
        t = _get(SILV + "?" + urllib.parse.urlencode({"serviceKey": key, "LAWD_CD": lawd, "DEAL_YMD": ym, "numOfRows": 1000, "pageNo": page}))
        try: root = ET.fromstring(t)
        except Exception: break
        items = root.findall(".//item")
        for it in items:
            g = lambda n: (it.findtext(n) or "").strip()
            if g("cdealType") in ("O", "Y"): continue
            try:
                out.append([g("aptNm"), round(float(g("excluUseAr") or 0), 1), int(g("dealAmount").replace(",", "") or 0),
                            f'{g("dealYear")}-{int(g("dealMonth") or 0):02d}-{int(g("dealDay") or 0):02d}'])
            except Exception: pass
        total = int(root.findtext(".//totalCount") or 0)
        if page * 1000 >= total or not items: break
        page += 1
    cache[k] = out
    time.sleep(0.05)
    return out

def _nm(s):
    s = re.sub(r"\(.*?\)|\[.*?\]", "", s or "")
    return re.sub(r"[\s·\-_.,]|아파트|단지$", "", s)

def presale(all_h, geo, today):
    """분양 단지 이름과 같은 분양권 전매 거래를 찾아 h['pre'] = [{label, excl, price, avg, n, last, lo, hi}]"""
    targets = [h for h in all_h if h["cat"] in ("A", "R", "T") and h["types"] and G.d(h["c_b"]) and G.d(h["c_b"]) <= today]
    if not targets: return
    reg = region_codes(targets, geo)
    cache = _load("silv.json", {})
    months = [(today.replace(day=1) - dt.timedelta(days=31 * i)).strftime("%Y%m") for i in range(6)]
    by = {}
    for h in targets:
        r = reg.get(h["id"])
        if r: by.setdefault(r[0], []).append(h)
    for lawd, hs in by.items():
        tr = []
        for ym in months: tr += fetch_silv(lawd, ym, cache, today)
        if not tr: continue
        for h in hs:
            hn = _nm(h["name"])
            if len(hn) < 3: continue
            mine = [x for x in tr if x[0] and (_nm(x[0]) in hn or hn in _nm(x[0]))]
            if not mine: continue
            rows = {}
            for t in h["types"]:
                if not t["excl"] or not t["price"]: continue
                same = [x for x in mine if abs(x[1] - t["excl"]) <= 1]
                if not same: continue
                k = int(t["excl"])
                ps = sorted(x[2] for x in same)
                cand = dict(label=t["label"], excl=t["excl"], price=t["price"], avg=int(sum(ps) / len(ps)), n=len(ps), lo=ps[0], hi=ps[-1],
                            last=max(x[3] for x in same))
                if k not in rows or t["price"] > rows[k]["price"]: rows[k] = cand
            if rows: h["pre"] = sorted(rows.values(), key=lambda x: x["excl"])
    keep = set(months)
    cache = {k: v for k, v in cache.items() if k.split(":")[2] in keep}
    _save("silv.json", cache)

def pre_box(h):
    rows = h.get("pre") or []
    if not rows: return ""
    won = G.won
    trs = ""
    for r in rows:
        prem = r["avg"] - r["price"]
        tag = (f'<span class="mk-hi">웃돈 약 {won(prem)}</span>' if prem > 300 else
               f'<span class="mk-lo">분양가보다 약 {won(-prem)} 낮게 거래</span>' if prem < -300 else '<span class="mk-eq">분양가 수준</span>')
        trs += (f'<tr><td><b>{esc(r["label"])}</b><small>{r["excl"]:.0f}㎡</small></td><td>{won(r["price"])}</td>'
                f'<td class="pr">{won(r["avg"])}<small>{r["n"]}건 · {won(r["lo"])}~{won(r["hi"])} · 최근 {r["last"]}</small></td><td>{tag}</td></tr>')
    return (f'<h2>분양권 실거래가 · 프리미엄</h2><p class="muted">최근 6개월 국토교통부 분양권 전매 실거래 신고 중 이 단지·같은 면적(전용 ±1㎡) 거래입니다.</p>'
            f'<div class="tw"><table class="tbl dt mk"><thead><tr><th>타입</th><th>최고 분양가</th><th>분양권 평균 거래가</th><th>프리미엄(추정)</th></tr></thead><tbody>{trs}</tbody></table></div>'
            f'<p class="muted">※ 프리미엄은 평균 거래가에서 타입별 최고 분양가를 뺀 단순 추정치이며, 층·옵션·발코니 확장 비용에 따라 실제와 다릅니다. 출처: 국토교통부 실거래가 공개시스템</p>')

# ═════════════════════════ 7) 분양 뉴스 (NAVER API HUB) ═════════════════════════
NAVER = "https://naverapihub.apigw.ntruss.com/search/v1/"
STOCK_RE = re.compile(r"IPO|공모주|공모가|상장|수요예측|코스닥|코스피|증권신고|유상증자|새내기주|청약증거금")
HOUSE_RE = re.compile(r"아파트|주택|가구|세대|분양|단지|오피스텔|임대|재건축|재개발|입주|부동산")
def is_housing(x):
    t = (x.get("title") or "") + " " + (x.get("desc") or "")
    return not STOCK_RE.search(t) or bool(HOUSE_RE.search(x.get("title") or ""))

PRESS_Q = ["아파트 분양", "청약 일정", "무순위 청약", "분양가", "견본주택 개관", "민간임대 아파트", "분양권 전매"]
OUTLET = {"chosun": "조선일보", "joongang": "중앙일보", "donga": "동아일보", "hani": "한겨레", "khan": "경향신문", "mk.co.kr": "매일경제",
          "hankyung": "한국경제", "sedaily": "서울경제", "mt.co.kr": "머니투데이", "edaily": "이데일리", "fnnews": "파이낸셜뉴스", "asiae": "아시아경제",
          "heraldcorp": "헤럴드경제", "news1": "뉴스1", "newsis": "뉴시스", "yna.co.kr": "연합뉴스", "yonhapnews": "연합뉴스", "kbs": "KBS", "mbc": "MBC",
          "sbs": "SBS", "ytn": "YTN", "jtbc": "JTBC", "nocutnews": "노컷뉴스", "inews24": "아이뉴스24", "etoday": "이투데이", "ajunews": "아주경제",
          "newspim": "뉴스핌", "dailian": "데일리안", "kukinews": "쿠키뉴스", "metroseoul": "메트로신문", "seoul.co.kr": "서울신문", "segye": "세계일보",
          "kmib": "국민일보", "munhwa": "문화일보", "hankookilbo": "한국일보", "bizwatch": "비즈워치", "businesspost": "비즈니스포스트",
          "dnews": "대한경제", "housingherald": "하우징헤럴드", "rcast": "알캐스트", "ddaily": "디지털데일리", "biz.chosun": "조선비즈", "mbn": "MBN"}

def naver(path, params):
    cid, sec = os.environ.get("NAVER_CLIENT_ID"), os.environ.get("NAVER_CLIENT_SECRET")
    if not (cid and sec): return []
    t = _get(NAVER + path + "?" + urllib.parse.urlencode(params), {"X-NCP-APIGW-API-KEY-ID": cid, "X-NCP-APIGW-API-KEY": sec})
    try: return json.loads(t).get("items") or []
    except Exception: return []

def outlet(url):
    host = urllib.parse.urlparse(url or "").netloc.lower()
    for k, v in OUTLET.items():
        if k in host: return v
    return re.sub(r"^(www|m|news|biz)\.", "", host).split(":")[0]

def strip_tags(s): return _html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()

def pubdate(s):
    try: return dt.datetime.strptime(s, "%a, %d %b %Y %H:%M:%S %z").astimezone(dt.timezone(dt.timedelta(hours=9)))
    except Exception: return None

def fetch_press(all_h):
    db = _load("press.json", {"news": {}, "blog": {}})
    if os.environ.get("NAVER_CLIENT_ID"):
        for q in PRESS_Q:
            for it in naver("news", {"query": q, "display": 40, "sort": "date"}):
                url = it.get("originallink") or it.get("link")
                if not url or url in db["news"]: continue
                p = pubdate(it.get("pubDate", ""))
                db["news"][url] = dict(url=url, nlink=it.get("link"), title=strip_tags(it.get("title")), desc=strip_tags(it.get("description")),
                                       src=outlet(url), date=p.strftime("%Y-%m-%d %H:%M") if p else "", q=q)
            time.sleep(0.15)
        # 진행 단지별 블로그 후기 (3일마다 갱신)
        today = G.TODAY.isoformat()
        for h in all_h:
            if G.status(h)[0] == "마감": continue
            b = db["blog"].get(h["id"])
            if b and b.get("at") and (G.TODAY - G.d(b["at"])).days < 3: continue
            items = naver("blog", {"query": re.sub(r"\(.*?\)", "", h["name"]).strip() + " 분양", "display": 5, "sort": "sim"})
            db["blog"][h["id"]] = dict(at=today, items=[dict(title=strip_tags(x.get("title")), url=x.get("link"), name=strip_tags(x.get("bloggername")),
                                                             date=x.get("postdate", "")) for x in items])
            time.sleep(0.1)
        news = sorted([x for x in db["news"].values() if is_housing(x)], key=lambda x: x["date"], reverse=True)[:400]
        db["news"] = {x["url"]: x for x in news}
        _save("press.json", db)
    return db

def press_rel(all_h, text):
    hits = []
    for h in all_h:
        n = re.sub(r"\(.*?\)", "", h["name"]).strip()
        if len(n) >= 5 and n in text: hits.append(h)
    return hits[:3]

def press_page(db, all_h, updated):
    news = sorted(db.get("news", {}).values(), key=lambda x: x["date"], reverse=True)
    for x in news: x["rel"] = [h["id"] for h in press_rel(all_h, x["title"] + " " + x["desc"])]
    byid = {h["id"]: h for h in all_h}
    lis = ""
    for x in news[:150]:
        rel = "".join(f'<a class="prel" href="/danji/{i}/">{esc(byid[i]["name"])} · {G.status(byid[i])[1]}</a>' for i in x["rel"] if i in byid)
        lis += (f'<li class="pr-item"><small class="nd">{esc(x["src"])} · {esc(x["date"])}</small><a class="pr-t" href="{esc(x["url"])}" target="_blank" rel="noopener nofollow">{esc(x["title"])}</a>'
                f'<p>{esc(x["desc"][:140])}</p><div class="pr-f">{rel}<a class="pr-more" href="{esc(x["url"])}" target="_blank" rel="noopener nofollow">원문 보기 →</a></div></li>')
    body = (f'<header class="ph"><p class="cat">PRESS</p><h1>분양 뉴스</h1><p class="lead">분양·청약 관련 언론 보도를 매일 모았습니다. 기사에 나온 단지가 VISIT ONE 분양정보에 있으면 청약 일정과 함께 바로 연결해 드립니다.</p>'
            f'<p class="liveline">{live_badge("네이버 뉴스 검색")}</p></header>'
            f'<ul class="press">{lis or "<li class=none>뉴스를 모으는 중입니다.</li>"}</ul>'
            f'<p class="muted src">기사의 저작권은 각 언론사에 있습니다. 제목과 요약은 네이버 검색 결과를 인용했으며, 전체 내용은 원문에서 확인하세요.</p>{LIVE_JS}')
    G.page(G.ROOT, "/news/press/", "분양 뉴스 · 오늘의 분양·청약 보도", "아파트 분양, 청약, 무순위, 분양가 관련 언론 보도를 매일 모아 관련 단지 청약 정보와 함께 보여드립니다.",
           body, [("분양 소식", "/news/"), ("분양 뉴스", "/news/press/")], [{"@context": "https://schema.org", "@type": "CollectionPage", "name": "분양 뉴스", "url": G.SITE + "/news/press/"}],
           og_type="website", updated=updated, robots="index,follow")
    return [("/news/press/", "0.7", "daily")], news

def danji_press(h, db, news):
    """단지 상세용: 관련 뉴스 + 블로그"""
    n = [x for x in news if h["id"] in (x.get("rel") or [])][:5]
    b = (db.get("blog", {}).get(h["id"]) or {}).get("items") or []
    if not n and not b: return ""
    out = ""
    if n:
        out += '<h2>관련 뉴스</h2><ul class="press sm">' + "".join(
            f'<li class="pr-item"><small class="nd">{esc(x["src"])} · {esc(x["date"][:10])}</small><a class="pr-t" href="{esc(x["url"])}" target="_blank" rel="noopener nofollow">{esc(x["title"])}</a></li>' for x in n) + "</ul>"
    if b:
        out += '<h2>블로그 후기·분석</h2><ul class="press sm">' + "".join(
            f'<li class="pr-item"><small class="nd">{esc(x["name"])} · {esc(x["date"][:4])}.{esc(x["date"][4:6])}.{esc(x["date"][6:8])}</small><a class="pr-t" href="{esc(x["url"])}" target="_blank" rel="noopener nofollow">{esc(x["title"])}</a></li>' for x in b) + "</ul>"
    return out + '<p class="muted">외부 글은 작성자 의견이며 VISIT ONE의 입장과 다를 수 있습니다.</p>'


# ───────────────────── 키워드 랜딩 페이지 (SEO·GEO) ─────────────────────
BRANDS = [("자이", ["자이"], "GS건설"), ("힐스테이트", ["힐스테이트"], "현대건설·현대엔지니어링"), ("래미안", ["래미안"], "삼성물산"),
          ("푸르지오", ["푸르지오"], "대우건설"), ("더샵", ["더샵"], "포스코이앤씨"), ("아이파크", ["아이파크"], "HDC현대산업개발"),
          ("롯데캐슬", ["롯데캐슬"], "롯데건설"), ("e편한세상", ["e편한세상", "이편한세상"], "DL이앤씨"), ("디에트르", ["디에트르"], "대방건설"),
          ("수자인", ["수자인"], "한양"), ("에피트", ["에피트"], "HL디앤아이한라"), ("호반써밋", ["호반써밋"], "호반건설"),
          ("두산위브", ["두산위브", "위브"], "두산건설"), ("서희스타힐스", ["서희스타힐스"], "서희건설"), ("중흥S-클래스", ["중흥", "S-클래스"], "중흥건설"),
          ("한화포레나", ["포레나"], "한화 건설부문"), ("SK뷰", ["SK뷰", "sk뷰"], "SK에코플랜트"), ("더휴", ["더휴"], "한신공영"),
          ("엘리프", ["엘리프"], "계룡건설"), ("해링턴", ["해링턴"], "효성중공업"), ("제일풍경채", ["풍경채"], "제일건설"),
          ("어울림", ["어울림"], "금호건설"), ("센트레빌", ["센트레빌"], "동부건설"), ("하늘채", ["하늘채"], "코오롱글로벌"),
          ("데시앙", ["데시앙"], "태영건설"), ("예미지", ["예미지"], "금성백조"), ("우미린", ["우미린"], "우미건설"),
          ("디에이치", ["디에이치"], "현대건설"), ("아크로", ["아크로"], "DL이앤씨"), ("르엘", ["르엘"], "롯데건설"), ("스위첸", ["스위첸"], "KCC건설")]
TYPE_KW = [("아파트", "A", "아파트", "민영·공공 아파트 일반분양"), ("오피스텔", "O", "오피스텔·도시형생활주택", "오피스텔과 도시형생활주택"),
           ("민간임대", "P", "민간임대 아파트", "공공지원·장기일반 민간임대 아파트"), ("무순위-줍줍", "R", "무순위 청약(줍줍)", "무순위·잔여세대·계약취소주택 재공급"),
           ("임의공급", "T", "임의공급 아파트", "청약 미달 후 사업주체가 선착순 등으로 공급하는 임의공급")]

def _q(p): return urllib.parse.quote(p)

_KO_PREFIX = {"/분양/": _q("/분양/"), "/브랜드/": _q("/브랜드/"), "/청약일정/": _q("/청약일정/")}
def fixhref(t):
    for a, b in _KO_PREFIX.items(): t = t.replace('href="' + a, 'href="' + b)
    return t

def _month_ok(ym):
    t = G.TODAY
    lo = (t.year, t.month - 2) if t.month > 2 else (t.year - 1, t.month + 10)
    return ym >= lo

def kpage(path, title, desc, body, crumbs, ld, updated):
    """한글 경로 페이지 생성 후 canonical·og:url·breadcrumb URL을 퍼센트 인코딩으로 정리"""
    G.page(G.ROOT, path, title, desc, body, crumbs, ld, og_type="website", updated=updated)
    f = os.path.join(G.ROOT, path.strip("/"), "index.html")
    t = fixhref(open(f, encoding="utf-8").read())
    for _, h in crumbs + [("", path)]:
        if any(ord(c) > 127 for c in h): t = t.replace(G.SITE + h + '"', G.SITE + _q(h) + '"')
    open(f, "w", encoding="utf-8").write(t)
    return _q(path)

def sgg_of(h):
    p = (h["addr"] or "").split()
    return p[1] if len(p) > 1 else ""

def _stats(items):
    live = [h for h in items if G.status(h)[0] != "마감"]
    done = [h for h in items if G.status(h)[0] == "마감" and h.get("rate_all") and h["cat"] != "R"] or [h for h in items if G.status(h)[0] == "마감" and h.get("rate_all")]
    nxt = sorted([h for h in live if G.d(h["sp_b"] or h["r_b"]) and G.d(h["sp_b"] or h["r_b"]) >= G.TODAY], key=lambda h: h["sp_b"] or h["r_b"])
    top = max(done, key=lambda h: h["rate_all"]) if done else None
    rs = sorted(h["rate_all"] for h in done)
    avg = (round(rs[len(rs) // 2], 1) if len(rs) % 2 else round((rs[len(rs) // 2 - 1] + rs[len(rs) // 2]) / 2, 1)) if rs else None
    units = sum(h["units"] for h in items)
    return live, done, nxt, top, avg, units

def kw_body(kw, intro, items, related, updated, faq_extra=None):
    live, done, nxt, top, avg, units = _stats(items)
    sm = [f"{kw} 관련 분양 단지는 최근 기준 {len(items)}곳, 총 {units:,}세대이며 이 중 {len(live)}곳이 청약 예정·진행 중입니다."]
    if nxt: sm.append(f"다음 청약은 {nxt[0]['name']}({G.kdate(nxt[0]['sp_b'] or nxt[0]['r_b'])} 접수)입니다.")
    if top: sm.append(f"최근 마감 단지 경쟁률 중간값은 {avg}:1이고, 가장 높았던 곳은 {top['name']}({G.cr_txt(top['rate_all'])})입니다.")
    faq = [(f"{kw} 앞으로 청약할 수 있는 곳은?", (", ".join(f"{h['name']}({G.kdate(h['sp_b'] or h['r_b'])})" for h in nxt[:5]) + " 등이 접수 예정·진행 중입니다.") if nxt else "현재 접수 예정인 단지가 없습니다. 새 공고가 나오면 매일 자동으로 이 페이지에 추가됩니다."),
           (f"{kw} 경쟁률은 어느 정도인가요?", f"최근 마감된 {len(done)}개 단지의 경쟁률 중간값은 {avg}:1입니다. 최고는 {top['name']}({G.cr_txt(top['rate_all'])})였습니다." if top else "아직 경쟁률이 집계된 마감 단지가 없습니다.")] + (faq_extra or [])
    rows_live = "".join(G.row(h) for h in sorted(live, key=lambda h: h["sp_b"] or h["r_b"] or "9"))
    rows_done = "".join(G.row(h) for h in sorted([h for h in items if G.status(h)[0] == "마감"], key=lambda h: h["sp_b"] or h["r_b"] or "", reverse=True)[:30])
    rel = ('<h2>함께 찾는 키워드</h2><div class="kwl">' + "".join(f'<a href="{u}">{esc(n)}</a>' for n, u in related) + "</div>") if related else ""
    body = (f'<header class="ph"><p class="cat">KEYWORD</p><h1>{esc(kw)} 분양정보 · 청약일정</h1><p class="lead">{intro}</p></header>'
            '<section class="sum" aria-label="한눈에 보기"><h2>한눈에 보기</h2><ul>' + "".join(f"<li>{esc(x)}</li>" for x in sm) + f'</ul><p class="muted">출처: 한국부동산원 청약홈 공공데이터 · 기준일 {updated} · 매일 자동 업데이트</p></section>'
            + (f'<h2>청약 예정·진행 중 <small>{len(live)}곳</small></h2><ul class="drs">{rows_live}</ul>' if live else '<p class="none">지금은 청약 예정·진행 중인 단지가 없습니다.</p>')
            + (f'<h2>최근 마감 단지</h2><ul class="drs">{rows_done}</ul>' if rows_done else "")
            + '<section class="faq"><h2>자주 묻는 질문</h2>' + "".join(f"<details><summary>{esc(a)}</summary><p>{esc(b)}</p></details>" for a, b in faq) + "</section>" + rel)
    ld = [{"@context": "https://schema.org", "@type": "CollectionPage", "name": f"{kw} 분양정보 · 청약일정", "dateModified": updated, "inLanguage": "ko-KR", "abstract": " ".join(sm),
           "isPartOf": {"@type": "WebSite", "name": "VISIT ONE 비지트원", "url": G.SITE + "/"}},
          {"@context": "https://schema.org", "@type": "ItemList", "name": f"{kw} 분양 단지", "numberOfItems": len(items),
           "itemListElement": [{"@type": "ListItem", "position": i + 1, "url": f"{G.SITE}/danji/{h['id']}/", "name": h["name"]} for i, h in enumerate((live + done)[:50])]},
          {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [{"@type": "Question", "name": a, "acceptedAnswer": {"@type": "Answer", "text": b}} for a, b in faq]}]
    return body, ld, sm

KW_INDEX = []   # (분류, 이름, url, 단지수)

def keyword_pages(all_h, updated):
    out = []; KW_INDEX.clear()
    import shutil
    for sub in ("분양", "브랜드", "청약일정", "keywords"): shutil.rmtree(os.path.join(G.ROOT, sub), ignore_errors=True)
    yr = G.TODAY.year
    def mk(group, kw, path, intro, items, crumbs, related, title=None, desc=None, faq_extra=None, prio="0.7"):
        if len(items) < 2: return
        body, ld, sm = kw_body(kw, intro, items, related, updated, faq_extra)
        url = kpage(path, title or f"{kw} 분양정보·청약일정 {yr}", desc or (" ".join(sm))[:155], body, crumbs, ld, updated)
        KW_INDEX.append((group, kw, url, len(items))); out.append((url, prio, "daily"))
    # 1) 시·군·구
    by = {}
    for h in all_h:
        if sgg_of(h): by.setdefault((h["sido"], sgg_of(h)), []).append(h)
    sgg_list = sorted(by.items(), key=lambda kv: -len(kv[1]))
    for (sd, sg), items in sgg_list:
        sib = [(f"{sd} {s2} 분양", f"/분양/{_q(sd + '-' + s2)}/") for (d2, s2), v in sgg_list if d2 == sd and s2 != sg and len(v) >= 2][:10]
        sib = [(f"{sd} 분양정보", f"/bunyang/{G.SIDO_SLUG.get(sd, '')}/")] + sib
        mk("지역", f"{sd} {sg}", f"/분양/{sd}-{sg}/", f"{sd} {sg}에서 공급되는 아파트·오피스텔·무순위·민간임대 분양 단지의 청약 일정, 분양가, 경쟁률을 모았습니다.",
           items, [("분양정보", "/bunyang/"), (sd, f"/bunyang/{G.SIDO_SLUG.get(sd, '')}/"), (sg, f"/분양/{sd}-{sg}/")], sib,
           title=f"{sd} {sg} 분양정보·청약일정 {yr} | {sg} 아파트 분양")
    # 2) 유형 + 시도×유형
    for slug, cat, kw, what in TYPE_KW:
        items = [h for h in all_h if h["cat"] == cat]
        rel = [(f"{sd} {kw}", f"/분양/{_q(sd + '-' + slug)}/") for sd, _ in G.SIDO if sum(1 for h in items if h["sido"] == sd) >= 2]
        mk("유형", kw, f"/분양/{slug}/", f"전국 {what} 단지의 청약 일정, 분양가, 경쟁률을 지역별로 정리했습니다.", items,
           [("분양정보", "/bunyang/"), (kw, f"/분양/{slug}/")], rel + [(k2, f"/분양/{_q(s2)}/") for s2, _, k2, _ in TYPE_KW if s2 != slug], prio="0.8")
        for sd, _ in G.SIDO:
            it2 = [h for h in items if h["sido"] == sd]
            mk("지역×유형", f"{sd} {kw}", f"/분양/{sd}-{slug}/", f"{sd} 지역 {what} 단지의 청약 일정, 분양가, 경쟁률입니다.", it2,
               [("분양정보", "/bunyang/"), (kw, f"/분양/{slug}/"), (sd, f"/분양/{sd}-{slug}/")], [(f"전국 {kw}", f"/분양/{_q(slug)}/"), (f"{sd} 분양정보", f"/bunyang/{G.SIDO_SLUG.get(sd, '')}/")] + [(x, u) for x, u in rel if not x.startswith(sd)][:8])
    # 3) 월별 청약 일정
    months = {}
    for h in all_h:
        x = G.d(h["sp_b"] or h["r_b"])
        if x: months.setdefault((x.year, x.month), []).append(h)
    mlist = sorted(months)
    for (y, m) in mlist:
        if not _month_ok((y, m)): continue
        rel = [(f"{y2}년 {m2}월 청약 일정", f"/청약일정/{_q(f'{y2}년-{m2}월')}/") for (y2, m2) in mlist if (y2, m2) != (y, m) and _month_ok((y2, m2)) and len(months[(y2, m2)]) >= 2][-5:]
        mk("월별", f"{y}년 {m}월 청약", f"/청약일정/{y}년-{m}월/", f"{y}년 {m}월에 청약 접수하는 전국 아파트·오피스텔·무순위·민간임대 단지를 접수일 순으로 정리했습니다.",
           months[(y, m)], [("청약캘린더", "/calendar/"), (f"{y}년 {m}월", f"/청약일정/{y}년-{m}월/")], [("청약캘린더", "/calendar/"), ("주간 청약 리포트", "/news/weekly/")] + rel,
           title=f"{y}년 {m}월 청약 일정 | 이번 달 아파트 청약·분양 일정", prio="0.8")
    # 4) 브랜드
    for name, keys, comp in BRANDS:
        items = [h for h in all_h if any(k.lower() in h["name"].lower() for k in keys)]
        mk("브랜드", name, f"/브랜드/{name}/", f"{name}({comp}) 아파트의 분양 일정, 청약 경쟁률, 분양가를 모았습니다.", items,
           [("분양정보", "/bunyang/"), (name, f"/브랜드/{name}/")], [(f"{n2} 분양", f"/브랜드/{_q(n2)}/") for n2, k2, _ in BRANDS if n2 != name and sum(1 for x in all_h if any(k.lower() in x["name"].lower() for k in k2)) >= 2][:12],
           title=f"{name} 분양 일정·청약 경쟁률 {yr} | {comp}",
           faq_extra=[(f"{name}는 어느 건설사 브랜드인가요?", f"{name}는 {comp}의 아파트 브랜드입니다. 같은 브랜드라도 단지마다 시행사·시공 참여사가 다를 수 있으니 공고문을 확인하세요.")])
    # 5) 주제
    mk("주제", "분양가상한제 아파트", "/분양/분양가상한제/", "분양가상한제가 적용된 단지는 주변 시세보다 분양가가 낮게 책정되는 대신 전매제한·실거주 의무가 붙을 수 있습니다.",
       [h for h in all_h if h.get("cap")], [("분양정보", "/bunyang/"), ("분양가상한제", "/분양/분양가상한제/")], [("전매제한 용어", "/glossary/jeonmae-jehan/"), ("분양가상한제 용어", "/glossary/bunyangga-sanghanje/")])
    mk("주제", "1000세대 이상 대단지", "/분양/대단지/", "1,000세대 이상 대단지 분양 단지입니다. 대단지는 커뮤니티 시설과 관리비 면에서 유리한 경우가 많습니다.",
       [h for h in all_h if h["units"] >= 1000], [("분양정보", "/bunyang/"), ("대단지", "/분양/대단지/")], [])
    # 6) 키워드 허브
    groups = {}
    for g, kw, url, n in KW_INDEX: groups.setdefault(g, []).append((kw, url, n))
    hb = ['<header class="ph"><p class="cat">KEYWORDS</p><h1>분양·청약 키워드 모음</h1><p class="lead">지역, 유형, 월별 일정, 건설사 브랜드별로 분양·청약 정보를 모아 볼 수 있습니다. 매일 자동으로 업데이트됩니다.</p></header>']
    for g in ("월별", "유형", "지역", "지역×유형", "브랜드", "주제"):
        if g in groups: hb.append(f'<h2>{g}</h2><div class="kwl">' + "".join(f'<a href="{u}">{esc(k)} <i>{n}</i></a>' for k, u, n in groups[g]) + "</div>")
    G.page(G.ROOT, "/keywords/", "분양·청약 키워드 모음 | 지역·유형·월별·브랜드", "지역별, 유형별, 월별 청약 일정, 건설사 브랜드별 분양 정보를 키워드로 모아 봅니다.",
           "\n".join(hb), [("키워드", "/keywords/")], [{"@context": "https://schema.org", "@type": "CollectionPage", "name": "분양·청약 키워드 모음", "url": G.SITE + "/keywords/"}], og_type="website", updated=updated)
    out.append(("/keywords/", "0.8", "daily"))
    return out

def sgg_chips(sido, all_h):
    """시도 목록 페이지 상단에 붙일 시·군·구 키워드 링크"""
    c = {}
    for h in all_h:
        if h["sido"] == sido and sgg_of(h): c[sgg_of(h)] = c.get(sgg_of(h), 0) + 1
    xs = [(s, n) for s, n in sorted(c.items(), key=lambda kv: -kv[1]) if n >= 2]
    if not xs: return ""
    return fixhref('<span class="kwl kwl-in">' + "".join(f'<a href="/분양/{_q(sido + "-" + s)}/">{esc(s)} <i>{n}</i></a>' for s, n in xs) + "</span>")

_KWC = {}
def _kw_counts(all_h):
    if _KWC.get("n") == len(all_h): return _KWC
    c = {"n": len(all_h), "sgg": {}, "type": {}, "st": {}, "brand": {}, "month": {}}
    for h in all_h:
        if sgg_of(h): c["sgg"][(h["sido"], sgg_of(h))] = c["sgg"].get((h["sido"], sgg_of(h)), 0) + 1
        c["type"][h["cat"]] = c["type"].get(h["cat"], 0) + 1
        c["st"][(h["sido"], h["cat"])] = c["st"].get((h["sido"], h["cat"]), 0) + 1
        for name, keys, _ in BRANDS:
            if any(k.lower() in h["name"].lower() for k in keys): c["brand"][name] = c["brand"].get(name, 0) + 1
        x = G.d(h["sp_b"] or h["r_b"])
        if x: c["month"][(x.year, x.month)] = c["month"].get((x.year, x.month), 0) + 1
    _KWC.clear(); _KWC.update(c); return _KWC

def kw_links(h, all_h):
    """단지 페이지 → 해당 키워드 페이지 내부 링크"""
    c = _kw_counts(all_h); L = []
    sg = sgg_of(h)
    if sg and c["sgg"].get((h["sido"], sg), 0) >= 2: L.append((f"{h['sido']} {sg} 분양", f"/분양/{_q(h['sido'] + '-' + sg)}/"))
    for slug, cat, kw, _ in TYPE_KW:
        if cat == h["cat"]:
            if c["st"].get((h["sido"], cat), 0) >= 2: L.append((f"{h['sido']} {kw}", f"/분양/{_q(h['sido'] + '-' + slug)}/"))
            if c["type"].get(cat, 0) >= 2: L.append((f"전국 {kw}", f"/분양/{_q(slug)}/"))
    for name, keys, _ in BRANDS:
        if any(k.lower() in h["name"].lower() for k in keys) and c["brand"].get(name, 0) >= 2:
            L.append((f"{name} 분양", f"/브랜드/{_q(name)}/")); break
    x = G.d(h["sp_b"] or h["r_b"])
    if x and _month_ok((x.year, x.month)) and c["month"].get((x.year, x.month), 0) >= 2: L.append((f"{x.year}년 {x.month}월 청약 일정", f"/청약일정/{_q(f'{x.year}년-{x.month}월')}/"))
    if h.get("cap"): L.append(("분양가상한제 아파트", f"/분양/{_q('분양가상한제')}/"))
    if not L: return ""
    return fixhref('<h2>관련 키워드</h2><div class="kwl">' + "".join(f'<a href="{u}">{esc(n)}</a>' for n, u in L) + '<a href="/keywords/">키워드 전체 →</a></div>')

def month_links(all_h):
    c = _kw_counts(all_h)
    ms = sorted(k for k, v in c["month"].items() if v >= 2 and _month_ok(k))[-5:]
    if not ms: return ""
    return fixhref('<div class="kwl">' + "".join(f'<a href="/청약일정/{_q(f"{y}년-{m}월")}/">{y}년 {m}월 청약 일정</a>' for y, m in ms) + '<a href="/keywords/">분양 키워드 전체 →</a></div>')
