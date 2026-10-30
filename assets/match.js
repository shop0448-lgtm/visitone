/* VISIT ONE 맞춤 분양 — 가입 없이 내 조건을 이 브라우저에 저장하고 맞는 단지를 골라줍니다 */
(function () {
  var KEY = "vo_prefs_v1";
  var SIDO = ["서울", "경기", "인천", "부산", "대구", "광주", "대전", "울산", "세종", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주"];
  var CATS = [["A", "아파트"], ["O", "오피스텔·도시형"], ["R", "무순위·잔여"], ["P", "민간임대"]];
  var BUD = [[0, "상관없음"], [30000, "3억 이하"], [50000, "5억 이하"], [70000, "7억 이하"], [100000, "10억 이하"], [150000, "15억 이하"]];
  var SIZE = [["", "상관없음"], ["S", "소형 (전용 60㎡ 이하 · 24평형 안팎)"], ["M", "중형 (60~85㎡ · 25~34평형)"], ["L", "대형 (85㎡ 초과)"]];
  var SP = ["신혼부부", "생애최초", "다자녀", "신생아", "청년", "노부모부양"];

  function load() { try { return JSON.parse(localStorage.getItem(KEY)) || null; } catch (e) { return null; } }
  function save(p) { try { localStorage.setItem(KEY, JSON.stringify(p)); } catch (e) {} }
  function won(m) { if (!m) return ""; var e = Math.floor(m / 10000), r = m % 10000; return e ? (e + "억" + (r ? " " + r.toLocaleString() + "만" : "")) : r.toLocaleString() + "만"; }
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  function kd(s) { if (!s) return "-"; var d = new Date(s + "T00:00:00"); return (d.getMonth() + 1) + "." + d.getDate() + "(" + "일월화수목금토"[d.getDay()] + ")"; }

  function match(d, p) {
    if (!p) return { ok: true, why: [], score: 0 };
    var why = [], score = 0;
    if (d.st === "마감") return { ok: false };
    if (p.r && p.r.length && p.r.indexOf(d.s) < 0) return { ok: false };
    if (p.bk === "n" && d.c !== "R" && d.c !== "O") return { ok: false };
    if (p.c && p.c.length && p.c.indexOf(d.c) < 0) return { ok: false };
    if (p.b) { if (d.pn && d.pn > p.b) return { ok: false }; if (d.pn) { why.push("예산 이내 " + won(d.pn) + "부터"); score += 2; } }
    if (p.z && d.ex && d.ex.length) {
      var hit = d.ex.some(function (x) { return p.z === "S" ? x <= 60 : p.z === "M" ? (x > 60 && x <= 85) : x > 85; });
      if (!hit) return { ok: false };
      why.push({ S: "소형 타입 있음", M: "국민평형대 있음", L: "대형 타입 있음" }[p.z]); score += 1;
    }
    if (p.bk === "n") { why.push(d.c === "R" ? "통장 없이 신청 가능(요건 확인)" : "통장 없이 청약 가능"); score += 1; }
    if (p.sp && p.sp.length && d.sp) p.sp.forEach(function (k) { if (d.sp[k]) { why.push(k + " 특공 " + d.sp[k] + "세대"); score += 3; } });
    if (d.st === "접수중") { why.unshift("지금 접수중"); score += 2; } else if (d.st === "예정") score += 1;
    return { ok: true, why: why, score: score };
  }

  function summary(p) {
    if (!p) return "";
    var t = [];
    t.push(p.r && p.r.length ? p.r.join("·") : "전국");
    if (p.c && p.c.length) t.push(p.c.map(function (c) { return (CATS.filter(function (x) { return x[0] === c; })[0] || [0, c])[1]; }).join("·"));
    if (p.b) t.push(won(p.b) + " 이하");
    if (p.z) t.push({ S: "소형", M: "중형", L: "대형" }[p.z]);
    t.push(p.bk === "n" ? "청약통장 없음" : "청약통장 있음");
    if (p.sp && p.sp.length) t.push(p.sp.join("·") + " 특공");
    return t.join(" · ");
  }

  function chips(name, list, sel, multi) {
    return '<div class="mf-chips" data-name="' + name + '" data-multi="' + (multi ? 1 : 0) + '">' + list.map(function (x) {
      var v = Array.isArray(x) ? x[0] : x, l = Array.isArray(x) ? x[1] : x;
      var on = multi ? (sel || []).indexOf(v) > -1 : String(sel == null ? "" : sel) === String(v);
      return '<button type="button" data-v="' + esc(v) + '" class="' + (on ? "on" : "") + '">' + esc(l) + "</button>";
    }).join("") + "</div>";
  }

  function openPanel(onSave) {
    var p = load() || { r: [], c: [], b: 0, z: "", bk: "y", sp: [] };
    var el = document.createElement("div");
    el.className = "mf-modal";
    el.innerHTML = '<div class="mf-box" role="dialog" aria-modal="true" aria-labelledby="mfT"><button type="button" class="mf-x" aria-label="닫기">×</button>' +
      '<h3 id="mfT">내 조건 설정</h3><p class="mf-sub">가입 없이 이 기기에만 저장됩니다. 조건에 맞는 단지만 골라 보여드려요.</p>' +
      "<h4>관심 지역 <small>여러 개 선택</small></h4>" + chips("r", SIDO, p.r, true) +
      "<h4>청약통장</h4>" + chips("bk", [["y", "있음"], ["n", "없음"]], p.bk) +
      "<h4>주택 유형 <small>선택 안 하면 전체</small></h4>" + chips("c", CATS, p.c, true) +
      "<h4>예산 <small>최고 분양가 기준</small></h4>" + chips("b", BUD, p.b) +
      "<h4>원하는 크기</h4>" + chips("z", SIZE, p.z) +
      "<h4>특별공급 해당 <small>해당되는 것 모두</small></h4>" + chips("sp", SP, p.sp, true) +
      '<div class="mf-act"><button type="button" class="mf-reset">초기화</button><button type="button" class="mf-save">이 조건으로 보기</button></div></div>';
    document.body.appendChild(el);
    document.body.style.overflow = "hidden";
    function close() { el.remove(); document.body.style.overflow = ""; }
    el.addEventListener("click", function (e) {
      if (e.target === el || e.target.closest(".mf-x")) return close();
      var b = e.target.closest(".mf-chips button");
      if (b) { var g = b.parentNode; if (g.dataset.multi === "1") b.classList.toggle("on"); else g.querySelectorAll("button").forEach(function (x) { x.classList.toggle("on", x === b); }); return; }
      if (e.target.closest(".mf-reset")) { try { localStorage.removeItem(KEY); } catch (_) {} close(); onSave && onSave(null); return; }
      if (e.target.closest(".mf-save")) {
        var o = {};
        el.querySelectorAll(".mf-chips").forEach(function (g) {
          var v = [].map.call(g.querySelectorAll("button.on"), function (x) { return x.dataset.v; });
          o[g.dataset.name] = g.dataset.multi === "1" ? v : (v[0] || "");
        });
        o.b = +o.b || 0;
        save(o); close(); onSave && onSave(o);
      }
    });
    document.addEventListener("keydown", function k(e) { if (e.key === "Escape") { close(); document.removeEventListener("keydown", k); } });
  }

  var cache = null;
  function data() { return cache ? Promise.resolve(cache) : fetch("/data/danji.json", { cache: "no-cache" }).then(function (r) { return r.json(); }).then(function (j) { cache = j; return j; }); }

  function card(d, why) {
    return '<li><a href="/danji/' + d.id + '/"><span class="st st-' + d.st + '">' + esc(d.stt) + "</span><b>" + esc(d.n) + "</b><small>" + esc(d.s) + " · " + esc(d.cl) + " · " + d.u.toLocaleString() + "세대</small>" +
      (why && why.length ? '<div class="why">' + why.slice(0, 3).map(function (w) { return "<i>" + esc(w) + "</i>"; }).join("") + "</div>" : "") +
      "<span>접수 " + kd(d.rb) + " · 발표 " + kd(d.w) + "</span>" + (d.pn ? "<em>" + won(d.pn) + (d.px !== d.pn ? " ~ " + won(d.px) : "") + "</em>" : "") + "</a></li>";
  }

  /* 메인: 나에게 맞는 분양 */
  function renderHome() {
    var box = document.getElementById("fit");
    if (!box) return;
    var p = load(), sum = box.querySelector(".fit-sum"), list = box.querySelector(".fit-list");
    sum.innerHTML = p ? '<b>내 조건</b> ' + esc(summary(p)) : "지역·예산·청약통장·특별공급 조건을 알려주시면 <b>나에게 맞는 단지만</b> 골라 드려요.";
    box.querySelector(".fit-btn").textContent = p ? "조건 바꾸기" : "내 조건 설정하기";
    data().then(function (j) {
      var rows = j.items.map(function (d) { var m = match(d, p || { bk: "y" }); return { d: d, m: m }; })
        .filter(function (x) { return x.m.ok && x.d.st !== "마감"; })
        .sort(function (a, b) { return (b.m.score - a.m.score) || String(a.d.rb).localeCompare(String(b.d.rb)); });
      list.innerHTML = rows.length ? rows.slice(0, 8).map(function (x) { return card(x.d, x.m.why); }).join("") :
        '<li class="empty">지금은 조건에 맞는 단지가 없습니다. 조건을 넓혀 보시거나, 새 공고가 올라오면 다시 확인해 주세요.</li>';
      var more = box.querySelector(".fit-more");
      if (more) more.innerHTML = rows.length > 8 ? '<a href="/bunyang/?fit=1">맞춤 단지 ' + rows.length + "곳 모두 보기 →</a>" : "";
    }).catch(function () { list.innerHTML = '<li class="empty">분양 데이터를 불러오지 못했습니다.</li>'; });
  }

  /* 목록: 내 조건만 보기 */
  function renderList() {
    var bar = document.getElementById("fitbar");
    if (!bar) return;
    var on = /[?&]fit=1/.test(location.search);
    function apply() {
      var p = load();
      bar.querySelector(".fb-sum").innerHTML = p ? "<b>내 조건</b> " + esc(summary(p)) : "내 조건을 설정하면 맞는 단지만 볼 수 있어요.";
      var t = bar.querySelector(".fb-toggle");
      t.hidden = !p; t.classList.toggle("on", on && !!p); t.textContent = on && p ? "내 조건 적용중 ✓" : "내 조건만 보기";
      if (!p || !on) { document.querySelectorAll(".drs .dr").forEach(function (li) { li.classList.remove("nf"); }); window.dispatchEvent(new Event("vo-filter")); return; }
      data().then(function (j) {
        var ok = {};
        j.items.forEach(function (d) { if (match(d, p).ok) ok[d.id] = 1; });
        document.querySelectorAll(".drs .dr").forEach(function (li) { li.classList.toggle("nf", !ok[li.dataset.id]); });
        window.dispatchEvent(new Event("vo-filter"));
      });
    }
    bar.querySelector(".fb-set").addEventListener("click", function () { openPanel(function () { on = true; apply(); }); });
    bar.querySelector(".fb-toggle").addEventListener("click", function () { on = !on; apply(); });
    apply();
  }

  window.VO = { openPanel: openPanel, load: load, match: match };
  document.addEventListener("DOMContentLoaded", function () {
    var b = document.querySelector("#fit .fit-btn");
    if (b) b.addEventListener("click", function () { openPanel(renderHome); });
    renderHome(); renderList();
  });
})();
