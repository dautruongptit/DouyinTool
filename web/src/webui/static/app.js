"use strict";

// ---------- tiện ích ----------
const $ = (id) => document.getElementById(id);
const logEl = $("log");

function appendLogs(lines) {
  if (!lines || !lines.length) return;
  logEl.textContent += (logEl.textContent ? "\n" : "") + lines.join("\n");
  logEl.scrollTop = logEl.scrollHeight;
}

async function api(path, opts) {
  const r = await fetch(path, Object.assign({ headers: { "Content-Type": "application/json" } }, opts));
  let data = {};
  try { data = await r.json(); } catch (e) {}
  if (!r.ok) throw new Error(data.error || ("Lỗi " + r.status));
  return data;
}
const post = (p, body) => api(p, { method: "POST", body: JSON.stringify(body || {}) });
const get = (p) => api(p, { method: "GET" });

function toast(msg) { appendLogs([">>> " + msg]); }

// ---------- tabs ----------
document.querySelectorAll(".tab").forEach((t) => {
  t.onclick = () => {
    document.querySelectorAll(".tab").forEach((x) => x.classList.remove("active"));
    document.querySelectorAll(".panel").forEach((x) => x.classList.remove("active"));
    t.classList.add("active");
    $(t.dataset.tab).classList.add("active");
  };
});

// ---------- poll job ----------
const ACTION_BTNS = ["b_list", "b_download", "b_dry", "b_render", "b_sub", "w_genlogo"];
let state = { cursor: 0, kind: null, lastBusy: false };

function setBusy(b) {
  ACTION_BTNS.forEach((id) => { if ($(id)) $(id).disabled = b; });
  $("b_stop").disabled = !b;
  if (!b) refreshDownloadBtn();
}

async function poll() {
  let j;
  try { j = await get("/api/job?since=" + state.cursor); }
  catch (e) { setTimeout(poll, 1500); return; }

  appendLogs(j.logs);
  if (typeof j.log_cursor === "number") state.cursor = j.log_cursor;
  $("bar_fill").style.width = (j.progress || 0) + "%";
  $("pct").textContent = (j.progress || 0) + "%";

  const busy = !!j.busy;
  setBusy(busy);
  $("b_stop").textContent = busy ? "Dừng (" + (j.progress || 0) + "%)" : "Dừng";

  // cần đăng nhập?
  $("login_banner").classList.toggle("hidden", j.status !== "needs_login");

  // vừa kết thúc?
  if (state.lastBusy && !busy) onFinish(j.status, j.result);
  state.lastBusy = busy;

  setTimeout(poll, 1000);
}

function onFinish(status, result) {
  if (state.kind === "list" && status === "done") loadVideos();
  if (state.kind === "download" && status === "done") loadVideos();
  if (state.kind === "compose" && status === "done" && result && result.download) {
    $("c_result").innerHTML = 'Xong. <a href="/api/download?rel=' + encodeURIComponent(result.download) +
      '">Tải file về máy</a>';
  }
  state.kind = null;
}

$("b_stop").onclick = () => post("/api/job/stop").catch((e) => toast(e.message));
$("b_continue").onclick = () => post("/api/job/continue").catch((e) => toast(e.message));

// ================= TAB 1: Douyin =================
let videos = [];
const selected = new Set();

$("b_list").onclick = async () => {
  try {
    $("d_status").textContent = "Đang lấy danh sách video...";
    state.kind = "list";
    await post("/api/douyin/list", {
      url: $("d_url").value.trim(),
      folder: $("d_folder").value.trim(),
      limit: parseInt($("d_limit").value || "0", 10),
      thumbs: $("d_thumbs").checked,
    });
  } catch (e) { state.kind = null; toast(e.message); $("d_status").textContent = "Lỗi: " + e.message; }
};

async function loadVideos() {
  const d = await get("/api/douyin/videos");
  videos = d.items || [];
  selected.clear();
  const tb = $("d_table").querySelector("tbody");
  tb.innerHTML = "";
  videos.forEach((v) => {
    const tr = document.createElement("tr");
    if (v.downloaded) tr.classList.add("done");
    tr.innerHTML =
      '<td class="w-chk"><input type="checkbox" data-id="' + v.id + '"></td>' +
      "<td>" + v.n + "</td><td>" + v.date + "</td>" +
      '<td class="' + (v.downloaded ? "state-done" : "") + '">' + (v.downloaded ? "Đã tải" : "") + "</td>" +
      "<td>" + escapeHtml(v.desc) + "</td>";
    const cb = tr.querySelector("input");
    if (!v.downloaded) { cb.checked = true; selected.add(v.id); }
    cb.onchange = () => { cb.checked ? selected.add(v.id) : selected.delete(v.id); refreshDownloadBtn(); };
    tb.appendChild(tr);
  });
  const tot = d.total ? "/" + d.total : "";
  $("d_status").textContent = "Đã lấy " + videos.length + tot + " video" +
    (d.folder ? "  •  thư mục: " + d.folder : "") + ".  Tích chọn rồi bấm “Tải video đã chọn”.";
  refreshDownloadBtn();
}

function refreshDownloadBtn() {
  const b = $("b_download");
  if (b) b.disabled = state.lastBusy || selected.size === 0;
}

function setAll(val, onlyNew) {
  $("d_table").querySelectorAll("tbody input[type=checkbox]").forEach((cb, i) => {
    const v = videos[i];
    const want = onlyNew ? !v.downloaded : val;
    cb.checked = want;
    want ? selected.add(v.id) : selected.delete(v.id);
  });
  refreshDownloadBtn();
}
$("d_all").onchange = () => setAll($("d_all").checked, false);
$("d_check_all").onclick = () => setAll(true, false);
$("d_uncheck_all").onclick = () => setAll(false, false);
$("d_check_new").onclick = () => setAll(true, true);

$("b_download").onclick = async () => {
  try {
    state.kind = "download";
    await post("/api/douyin/download", { ids: Array.from(selected) });
  } catch (e) { state.kind = null; toast(e.message); }
};

// noVNC
$("b_novnc").onclick = () => {
  $("vnc_frame").src = "/novnc/vnc.html?autoconnect=true&reconnect=true&resize=remote&path=websockify";
  $("vnc_modal").classList.remove("hidden");
};
$("vnc_close").onclick = () => { $("vnc_modal").classList.add("hidden"); $("vnc_frame").src = "about:blank"; };

// ================= TAB 2: ghép =================
async function loadFolders() {
  const d = await get("/api/folders");
  ["c_folder", "s_folder"].forEach((id) => {
    const sel = $(id);
    const cur = sel.value;
    sel.innerHTML = "";
    (d.folders || []).forEach((f) => {
      const o = document.createElement("option"); o.value = o.textContent = f; sel.appendChild(o);
    });
    if (cur) sel.value = cur;
  });
}
$("c_reload").onclick = loadFolders;
$("s_reload").onclick = loadFolders;

$("w_genlogo").onclick = async () => {
  try {
    const d = await post("/api/logo");
    $("w_logo").value = d.rel;
    document.querySelector('input[name=wm][value=logo]').checked = true;
    toast("Đã tạo logo: " + d.rel);
  } catch (e) { toast(e.message); }
};

function wmMode() {
  const r = document.querySelector("input[name=wm]:checked");
  return r ? r.value : "text";
}
function composeBody(dry) {
  return {
    folder: $("c_folder").value, out: $("c_out").value.trim(),
    target_min: parseFloat($("c_target").value || "10"), order: $("c_order").value,
    size: $("c_size").value, fps: parseInt($("c_fps").value, 10), exact: $("c_exact").checked,
    crf: parseInt($("c_crf").value, 10), dry: dry,
    wm: {
      mode: wmMode(), text: $("w_text").value, fontsize: parseInt($("w_fontsize").value, 10),
      logo: $("w_logo").value.trim(), logo_h: parseInt($("w_logoh").value, 10),
      opacity: parseFloat($("w_op").value), speed: parseFloat($("w_speed").value),
    },
  };
}
$("b_dry").onclick = async () => {
  try { state.kind = "composedry"; $("c_result").textContent = ""; await post("/api/compose", composeBody(true)); }
  catch (e) { state.kind = null; toast(e.message); }
};
$("b_render").onclick = async () => {
  try { state.kind = "compose"; $("c_result").textContent = ""; await post("/api/compose", composeBody(false)); }
  catch (e) { state.kind = null; toast(e.message); }
};

// ================= TAB 3: phụ đề =================
$("b_sub").onclick = async () => {
  try {
    state.kind = "sub";
    const src = $("s_src").value.trim();
    const body = {
      model: $("s_model").value, lang: $("s_lang").value, task: $("s_task").value,
      skip: $("s_skip").checked, txt: $("s_txt").checked,
      src_folder: "", src_file: "",
    };
    if (!src) {
      body.src_folder = $("s_folder").value;                 // dùng thư mục chọn ở dropdown
    } else if (/\.(mp4|mov|mkv|webm|m4a|mp3|wav)$/i.test(src)) {
      body.src_file = src;                                   // là 1 file video
    } else {
      body.src_folder = src;                                 // là 1 thư mục
    }
    await post("/api/subtitle", body);
  } catch (e) { state.kind = null; toast(e.message); }
};

// ---------- helpers ----------
function escapeHtml(s) {
  return (s || "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

// ---------- khởi động ----------
loadFolders().catch(() => {});
poll();
