/* VISIT ONE 분양맵 */
(function () {
  var COLORS = { "예정": "#2f62c9", "접수중": "#c2a46d", "발표대기": "#8a6d38", "계약예정": "#2c8350", "계약중": "#2c8350", "마감": "#9a958b" };
  var ORDER = { "접수중": 0, "예정": 1, "발표대기": 2, "계약예정": 3, "계약중": 4, "마감": 5 };
  var state = { st: "", c: "", fit: false };
  var items = [], markers = {}, map, clusterer, imgs = {};

  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  function won(m) { if (!m) return ""; var e = Math.floor(m / 10000), r = m % 10000; return e ? (e + "억" + (r ? " " + r.toLocaleString() + "만" : "")) : r.toLocaleString() + "만"; }
  function kd(s) { if (!s) return "-"; var d = new Date(s + "T00:00:00"); return (d.getMonth() + 1) + "." + d.getDate() + "(" + "일월화수목금토"[d.getDay()] + ")"; }
  function img(st) {
    if (imgs[st]) return imgs[st];
    var c = COLORS[st] || "#555";
    var svg = '<svg xmlns="http://www.w3.org/2000/svg" width="28" height="36" viewBox="0 0 28 36"><path d="M14 35s12-12.3 12-21A12 12 0 0 0 2 14c0 8.7 12 21 12 21z" fill="' + c + '" stroke="#fff" stroke-width="2"/><circle cx="14" cy="14" r="4.5" fill="#fff"/></svg>';
    imgs[st] = new kakao.maps.MarkerImage("data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg), new kakao.maps.Size(28, 36), { offset: new kakao.maps.Point(14, 35) });
    return imgs[st];
  }
  function visible(d) {
    if (state.st === "all") { } else if (state.st === "계약") { if (d.st !== "계약예정" && d.st !== "계약중") return false; }
    else if (state.st) { if (d.st !== state.st) return false; } else if (d.st === "마감") return false;
    if (state.c && d.c !== state.c) return false;
    if (state.fit && window.VO) { var p = VO.load(); if (p && !VO.match(d, p).ok) return false; }
    return true;
  }
  function card(d) {
    var el = document.getElementById("mcard");
    el.innerHTML = '<button type="button" class="mx" aria-label="닫기">×</button><span class="st st-' + d.st + '">' + esc(d.stt) + '</span>' +
      "<b>" + esc(d.n) + "</b><small>" + esc(d.a) + " · " + esc(d.cl) + " · " + (d.u || 0).toLocaleString() + "세대</small>" +
      '<dl><div><dt>청약 접수</dt><dd>' + kd(d.rb) + '</dd></div><div><dt>당첨 발표</dt><dd>' + kd(d.w) + '</dd></div>' +
      (d.pn ? '<div><dt>분양가</dt><dd>' + won(d.pn) + (d.px !== d.pn ? " ~ " + won(d.px) : "") + "</dd></div>" : "") +
      (d.cr ? '<div><dt>경쟁률</dt><dd class="crt">' + d.cr.toFixed(2) + ":1</dd></div>" : "") + "</dl>" +
      (d.g === "area" ? '<p class="mnote">※ 정확한 지번이 없어 동·구 단위 위치로 표시했습니다.</p>' : "") +
      '<div class="ma"><a href="/danji/' + d.id + '/">상세 보기</a><a class="g" href="/danji/' + d.id + '/#consult">' + (d.st === "마감" ? "새 분양 알림" : "청약 알림 받기") + '</a></div>';
    el.hidden = false;
    el.querySelector(".mx").onclick = function () { el.hidden = true; };
  }
  function focus(d) {
    if (!d || d.y == null) return;
    var ll = new kakao.maps.LatLng(d.y, d.x);
    if (map.getLevel() > 6) map.setLevel(6);
    map.panTo(ll); card(d);
  }
  function render() {
    clusterer.clear();
    var list = [];
    items.forEach(function (d) { if (visible(d)) list.push(markers[d.id]); });
    clusterer.addMarkers(list);
    side();
  }
  function side() {
    var b = map.getBounds(), rows = [];
    items.forEach(function (d) { if (visible(d) && b.contain(new kakao.maps.LatLng(d.y, d.x))) rows.push(d); });
    rows.sort(function (a, z) { return (ORDER[a.st] - ORDER[z.st]) || String(a.rb).localeCompare(String(z.rb)); });
    document.getElementById("mcnt").textContent = rows.length;
    var ul = document.getElementById("mlist");
    ul.innerHTML = rows.slice(0, 80).map(function (d) {
      return '<li data-id="' + d.id + '"><span class="st st-' + d.st + '">' + esc(d.stt) + "</span><b>" + esc(d.n) + "</b><small>" + esc(d.a) + " · " + esc(d.cl) + "</small>" +
        "<span class='ml'>접수 " + kd(d.rb) + (d.pn ? " · " + won(d.pn) + "~" : "") + (d.cr ? " · <em class='crt'>" + d.cr.toFixed(1) + ":1</em>" : "") + "</span></li>";
    }).join("") || '<li class="empty">이 지역에 조건에 맞는 단지가 없습니다. 지도를 움직이거나 확대·축소해 보세요.</li>';
  }
  function chips(id, key) {
    var g = document.getElementById(id);
    g.addEventListener("click", function (e) {
      var b = e.target.closest("button"); if (!b) return;
      g.querySelectorAll("button").forEach(function (x) { x.classList.toggle("on", x === b); });
      state[key] = b.dataset.v; render();
    });
  }
  function init() {
    var el = document.getElementById("map");
    map = new kakao.maps.Map(el, { center: new kakao.maps.LatLng(37.45, 127.0), level: 10 });
    map.addControl(new kakao.maps.ZoomControl(), kakao.maps.ControlPosition.RIGHT);
    clusterer = new kakao.maps.MarkerClusterer({ map: map, averageCenter: true, minLevel: 7, gridSize: 50,
      styles: [{ width: "40px", height: "40px", background: "rgba(12,12,13,.85)", borderRadius: "50%", color: "#d9c08e", textAlign: "center", fontWeight: "700", lineHeight: "40px", fontSize: "14px", border: "2px solid #c2a46d" }] });
    fetch("/data/danji.json", { cache: "no-cache" }).then(function (r) { return r.json(); }).then(function (j) {
      items = j.items.filter(function (d) { return d.y != null; });
      items.forEach(function (d) {
        var m = new kakao.maps.Marker({ position: new kakao.maps.LatLng(d.y, d.x), image: img(d.st), title: d.n });
        kakao.maps.event.addListener(m, "click", function () { card(d); });
        markers[d.id] = m;
      });
      render();
      var q = new URLSearchParams(location.search).get("id");
      if (q) { var t = items.filter(function (d) { return d.id === q; })[0]; if (t) { state.st = "all"; document.querySelectorAll("#mst button").forEach(function (x) { x.classList.toggle("on", x.dataset.v === "all"); }); render(); focus(t); } }
    });
    kakao.maps.event.addListener(map, "idle", side);
    chips("mst", "st"); chips("mct", "c");
    document.getElementById("mlist").addEventListener("click", function (e) {
      var li = e.target.closest("li[data-id]"); if (!li) return;
      focus(items.filter(function (d) { return d.id === li.dataset.id; })[0]);
      if (window.innerWidth < 900) document.getElementById("map").scrollIntoView({ behavior: "smooth" });
    });
    var fb = document.getElementById("mfit");
    fb.addEventListener("click", function () {
      if (!window.VO) return;
      if (!VO.load()) { VO.openPanel(function (p) { state.fit = !!p; fb.classList.toggle("on", state.fit); render(); }); return; }
      state.fit = !state.fit; fb.classList.toggle("on", state.fit); fb.textContent = state.fit ? "내 조건 적용중 ✓" : "내 조건만"; render();
    });
  }
  if (window.kakao && kakao.maps) kakao.maps.load(init);
  else document.getElementById("map").innerHTML = '<p style="padding:40px;text-align:center">지도를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.</p>';
})();
