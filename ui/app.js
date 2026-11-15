const api = () => window.pywebview && window.pywebview.api;
const $ = (id) => document.getElementById(id);
const fmt = (s) => { s = Math.max(0, Math.floor(s || 0)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; };
let dragging = false;

function bindWindowBar(name) {
  document.querySelectorAll("[data-win-min]").forEach((b) => b.onclick = () => api().minimize(name));
  document.querySelectorAll("[data-win-close]").forEach((b) => b.onclick = () => api().close_window(name));
}

function applySkin(name) { document.body.className = name === "graphite" ? "" : name; }

async function pollMain() {
  const a = api(); if (!a) return;
  const s = await a.state();
  applySkin(s.skin);
  $("title").textContent = s.title;
  $("time").textContent = fmt(s.time);
  $("play").textContent = s.playing && !s.paused ? "❚❚" : "►";
  $("seek").max = s.duration || 100;
  if (!dragging) $("seek").value = s.time || 0;
  if (document.activeElement !== $("vol")) $("vol").value = s.volume;
}

function initMain() {
  bindWindowBar("main");
  $("play").onclick = () => api().toggle();
  $("prev").onclick = () => api().prev();
  $("next").onclick = () => api().next();
  $("stop").onclick = () => api().stop();
  $("open").onclick = async () => { await api().add_files(); };
  $("pl").onclick = () => api().open_window("playlist");
  $("eq").onclick = () => api().open_window("eq");
  $("skin").onchange = () => api().set_skin($("skin").value).then(applySkin);
  $("vol").oninput = () => api().set_volume(parseInt($("vol").value, 10));
  $("seek").onpointerdown = () => dragging = true;
  $("seek").onpointerup = () => { dragging = false; api().seek(parseFloat($("seek").value)); };
  setInterval(pollMain, 300);
}

async function pollPlaylist() {
  const a = api(); if (!a) return;
  const p = await a.playlist();
  $("list").innerHTML = p.items.map((it, i) =>
    `<div class="${i === p.index ? "on" : ""}" data-i="${i}">${i + 1}. ${it.title.replace(/[<>&]/g, "")}</div>`).join("");
  $("count").textContent = `${p.items.length} tracks`;
}

function initPlaylist() {
  bindWindowBar("playlist");
  $("list").onclick = (e) => { const d = e.target.closest("[data-i]"); if (d) api().play(parseInt(d.dataset.i, 10)); };
  $("add").onclick = async () => { await api().add_files(); pollPlaylist(); };
  $("addf").onclick = async () => { await api().add_folder(); pollPlaylist(); };
  $("del").onclick = async () => { const i = (await api().playlist()).index; if (i >= 0) await api().remove(i); pollPlaylist(); };
  $("clear").onclick = async () => { await api().clear(); pollPlaylist(); };
  setInterval(pollPlaylist, 1000);
  pollPlaylist();
}

const EQ_LABELS = ["31", "62", "125", "250", "500", "1k", "2k", "4k", "8k", "16k"];
function initEq() {
  bindWindowBar("eq");
  const box = $("bands");
  box.innerHTML = EQ_LABELS.map((l, i) =>
    `<div class="band"><input type="range" min="-12" max="12" step="1" value="0" data-b="${i}"><span>${l}</span></div>`).join("");
  const push = () => api().set_eq([...box.querySelectorAll("input")].map((x) => +x.value), +$("pre").value);
  box.oninput = push;
  $("pre").oninput = push;
  $("flat").onclick = () => { box.querySelectorAll("input").forEach((x) => x.value = 0); $("pre").value = 0; push(); };
}

window.addEventListener("pywebviewready", () => {
  const page = document.body.dataset.page;
  if (page === "main") initMain();
  if (page === "playlist") initPlaylist();
  if (page === "eq") initEq();
});
