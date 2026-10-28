const LS_REMOTE_URL = "gripper-hl.remoteUrl";
const REMOTE_DEFAULT = "http://127.0.0.1:7020/gripper";
const GRIPPER_MIN_MM = 0;
const GRIPPER_MAX_MM = 65;

async function api(path, opts) {
  const r = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  const text = await r.text();
  let data;
  try { data = JSON.parse(text); } catch { data = { raw: text }; }
  if (!r.ok) throw new Error((data && (data.detail || data.error)) || r.statusText);
  return data;
}

function $(id) { return document.getElementById(id); }

function syncPosInputs(from) {
  const range = $("posRange");
  const num = $("posNum");
  if (from === "range") num.value = range.value;
  else range.value = num.value;
}

function fmt(v, unit, digits) {
  if (v == null || !Number.isFinite(Number(v))) return "—";
  return Number(v).toFixed(digits) + (unit || "");
}

function clampMm(v) {
  const n = Number(v);
  if (!Number.isFinite(n)) return null;
  return Math.max(GRIPPER_MIN_MM, Math.min(GRIPPER_MAX_MM, n));
}

/** @type {{ url: string, on: boolean, gripper: number|null, step: number, unit: string, es: EventSource|null, pollTimer: number|null, mode: string, remoteStreaming: boolean, writeInFlight: boolean, pendingMm: number|null, lastStreamedStep: number|null, lastStatus: object|null }} */
const remote = {
  url: "",
  on: false,
  gripper: null,
  step: 0,
  unit: "mm",
  es: null,
  pollTimer: null,
  mode: "",
  remoteStreaming: false,
  writeInFlight: false,
  pendingMm: null,
  lastStreamedStep: null,
  lastStatus: null,
};

function paintRemoteButtons() {
  const connected = !!(remote.lastStatus && remote.lastStatus.connected);
  const btnC = $("btnRemoteConnect");
  const btnD = $("btnRemoteDisconnect");
  const btnS = $("btnRemoteSend");
  const urlEl = $("remoteUrl");
  if (urlEl && document.activeElement !== urlEl) {
    urlEl.value = remote.url || REMOTE_DEFAULT;
    urlEl.disabled = !!remote.on;
  }
  if (btnC) btnC.disabled = !!remote.on;
  if (btnD) btnD.disabled = !remote.on;
  if (btnS) {
    if (remote.remoteStreaming) {
      btnS.disabled = false;
      btnS.textContent = "停止连续下发";
      btnS.classList.remove("primary");
      btnS.classList.add("danger");
    } else {
      btnS.disabled = !(remote.on && connected && remote.gripper != null);
      btnS.textContent = "远程连续下发";
      btnS.classList.add("primary");
      btnS.classList.remove("danger");
    }
  }
}

function paintRemoteHint() {
  const el = $("remoteHint");
  const box = $("remoteBox");
  if (!el) return;
  if (remote.remoteStreaming) {
    el.textContent = `远程连续下发中 · step=${remote.step} · ${fmt(remote.gripper, " mm", 2)}（再点停止）`;
    el.className = "meta remote-hint-ok";
  } else if (remote.on) {
    el.textContent = `远程拉取中 · step=${remote.step}` + (remote.mode ? ` · ${remote.mode}` : "")
      + (remote.gripper != null ? ` · gripper=${fmt(remote.gripper, " mm", 2)}` : "");
    el.className = "meta remote-hint-ok";
  } else {
    el.textContent = "未拉取远程";
    el.className = "meta";
  }
  if (box) {
    box.textContent = JSON.stringify({
      url: remote.url || null,
      on: remote.on,
      mode: remote.mode || null,
      streaming: remote.remoteStreaming,
      step: remote.step,
      unit: remote.unit,
      gripper: remote.gripper,
    }, null, 2);
  }
  paintRemoteButtons();
}

function stopRemoteStreaming() {
  remote.remoteStreaming = false;
  remote.pendingMm = null;
  remote.writeInFlight = false;
}

function stopRemote(opts) {
  opts = opts || {};
  if (remote.es) {
    try { remote.es.close(); } catch (_) {}
    remote.es = null;
  }
  if (remote.pollTimer) {
    clearInterval(remote.pollTimer);
    remote.pollTimer = null;
  }
  remote.on = false;
  remote.mode = "";
  stopRemoteStreaming();
  if (!opts.keepValue) remote.gripper = null;
  paintRemoteHint();
}

function streamUrlFor(raw) {
  let u;
  try { u = new URL(String(raw || "").trim()); }
  catch (_) { return null; }
  if (!u.searchParams.has("stream")) u.searchParams.set("stream", "1");
  if (!u.searchParams.has("hz")) u.searchParams.set("hz", "20");
  return u.toString();
}

function extractRemoteGripper(obj) {
  if (!obj || typeof obj !== "object") return null;
  if (obj.gripper == null && obj.ok === false) return null;
  const v = Number(obj.gripper);
  if (!Number.isFinite(v)) return null;
  return v;
}

function enqueueRemoteWrite(mm, step) {
  const clamped = clampMm(mm);
  if (clamped == null) return;
  remote.pendingMm = clamped;
  if (remote.writeInFlight) return;
  pumpRemoteWrite(step);
}

async function pumpRemoteWrite(step) {
  if (!remote.remoteStreaming) return;
  if (remote.pendingMm == null) return;
  const mm = remote.pendingMm;
  remote.pendingMm = null;
  remote.writeInFlight = true;
  try {
    const body = motionBody({ position_mm: mm });
    const r = await api("/api/command", {
      method: "POST",
      body: JSON.stringify(body),
    });
    remote.lastStreamedStep = step;
    $("cmdMeta").textContent = r.ok
      ? `远程下发 ${Number(r.position_mm != null ? r.position_mm : mm).toFixed(1)} mm`
      : (r.error || "失败");
    // Reflect commanded target on sliders
    $("posNum").value = String(mm);
    syncPosInputs("num");
  } catch (e) {
    $("cmdMeta").textContent = "远程下发失败: " + (e && e.message ? e.message : e);
    const el = $("remoteHint");
    if (el) {
      el.textContent = "远程下发失败: " + (e && e.message ? e.message : e);
      el.className = "meta remote-hint-err";
    }
  } finally {
    remote.writeInFlight = false;
    if (remote.remoteStreaming && remote.pendingMm != null) {
      pumpRemoteWrite(remote.step);
    }
  }
}

function applyRemoteFrame(obj) {
  if (!remote.on) return;
  const g = extractRemoteGripper(obj);
  if (g == null) return;
  remote.gripper = g;
  remote.step = Number(obj.step) || 0;
  if (obj.unit) remote.unit = String(obj.unit);
  if (remote.remoteStreaming) {
    enqueueRemoteWrite(g, remote.step);
  }
  paintRemoteHint();
}

function startRemotePoll(baseUrl) {
  remote.mode = "poll";
  const tick = async () => {
    if (!remote.on) return;
    try {
      const r = await fetch(baseUrl, { cache: "no-store" });
      const obj = await r.json();
      applyRemoteFrame(obj);
    } catch (e) {
      const el = $("remoteHint");
      if (el) {
        el.textContent = "远程 poll 失败: " + (e && e.message ? e.message : e);
        el.className = "meta remote-hint-err";
      }
    }
  };
  tick();
  remote.pollTimer = setInterval(tick, 50);
}

function startRemoteStream(url) {
  const sseUrl = streamUrlFor(url);
  if (!sseUrl) {
    alert("远程 URL 无效");
    return;
  }
  stopRemote({ keepValue: true });
  remote.url = String(url || "").trim();
  remote.on = true;
  remote.mode = "sse";
  paintRemoteHint();
  let es;
  try {
    es = new EventSource(sseUrl);
  } catch (_) {
    startRemotePoll(remote.url);
    return;
  }
  remote.es = es;
  const onPayload = (ev) => {
    try {
      const obj = JSON.parse(ev.data);
      applyRemoteFrame(obj);
    } catch (_) {}
  };
  es.addEventListener("gello", onPayload);
  es.onmessage = onPayload;
  es.onerror = () => {
    if (remote.es) {
      try { remote.es.close(); } catch (_) {}
      remote.es = null;
    }
    if (remote.on && !remote.pollTimer) {
      startRemotePoll(remote.url);
      const el = $("remoteHint");
      if (el) el.textContent = (el.textContent || "") + " · SSE→poll";
    }
  };
}

function renderStatus(s) {
  remote.lastStatus = s;
  if (s.host_config) $("hostConfigPath").textContent = s.host_config;
  if (s.sensors_config) $("sensorsConfigPath").textContent = s.sensors_config;

  const mm = s.position_mm;
  const pct = mm == null ? 50 : Math.max(0, Math.min(100, (Number(mm) / 65) * 100));
  $("jawFill").style.width = pct.toFixed(1) + "%";
  $("jawLabel").textContent = mm == null ? "—" : Number(mm).toFixed(2) + " mm";

  $("fbPos").textContent = fmt(mm, " mm", 2);
  $("fbSpd").textContent = fmt(s.speed_mm_s, " mm/s", 2);
  $("fbCur").textContent = fmt(s.current_a, " A", 3);
  $("fbInit").textContent = s.init_text
    ? (s.init_text + (s.init_code != null ? " (" + s.init_code + ")" : ""))
    : "—";
  $("fbGrip").textContent = s.grip_text
    ? (s.grip_text + (s.grip_code != null ? " (" + s.grip_code + ")" : ""))
    : "—";
  $("fbHz").textContent = fmt(s.hz, "", 1);

  $("statusBox").textContent = JSON.stringify({
    connected: s.connected,
    dry_run: s.dry_run,
    initialized: s.initialized,
    port: s.port,
    seq: s.seq,
    error: s.error,
    sensor_id: s.sensor_id,
    position_norm: s.position_norm,
  }, null, 2);

  $("meta").textContent = s.connected
    ? `live · ${Number(s.hz || 0).toFixed(1)} Hz · ${s.dry_run ? "dry_run" : "hardware"}`
    : "idle";
  if (typeof s.dry_run === "boolean") $("dryRun").checked = !!s.dry_run;
  paintRemoteButtons();
}

async function refresh() {
  try {
    const s = await api("/api/status");
    renderStatus(s);
  } catch (e) {
    $("meta").textContent = "status error: " + e.message;
  }
}

function motionBody(extra) {
  return {
    speed_mm_s: Number($("speedNum").value),
    current_a: Number($("currentNum").value),
    ...extra,
  };
}

$("posRange").oninput = () => syncPosInputs("range");
$("posNum").oninput = () => syncPosInputs("num");

$("btnConnect").onclick = async () => {
  try {
    await api("/api/connect", {
      method: "POST",
      body: JSON.stringify({ dry_run: $("dryRun").checked }),
    });
    await refresh();
  } catch (e) { alert(e.message); }
};

$("btnDisconnect").onclick = async () => {
  try {
    stopRemoteStreaming();
    await api("/api/disconnect", { method: "POST" });
    await refresh();
  } catch (e) { alert(e.message); }
};

$("btnInit").onclick = async () => {
  if (!confirm("执行找零？行程内不要放置物体。")) return;
  try {
    const r = await api("/api/initialize", {
      method: "POST",
      body: JSON.stringify({ timeout_s: 15 }),
    });
    $("cmdMeta").textContent = r.message || (r.ok ? "初始化完成" : "失败");
    await refresh();
  } catch (e) { alert(e.message); }
};

$("btnProbe").onclick = async () => {
  try {
    const r = await api("/api/probe", { method: "POST" });
    alert(JSON.stringify(r, null, 2));
  } catch (e) { alert(e.message); }
};

$("btnRate").onclick = async () => {
  try {
    const r = await api("/api/rate-probe", {
      method: "POST",
      body: JSON.stringify({ duration_s: 3 }),
    });
    alert(JSON.stringify(r, null, 2));
  } catch (e) { alert(e.message); }
};

$("btnPorts").onclick = async () => {
  try {
    const r = await api("/api/ports");
    alert((r.ports || []).join("\n") || "(no ports)");
  } catch (e) { alert(e.message); }
};

$("btnSend").onclick = async () => {
  try {
    const r = await api("/api/command", {
      method: "POST",
      body: JSON.stringify(motionBody({ position_mm: Number($("posNum").value) })),
    });
    $("cmdMeta").textContent = r.ok ? "已下发 " + Number(r.position_mm).toFixed(1) + " mm" : (r.error || "失败");
    await refresh();
  } catch (e) { alert(e.message); }
};

$("btnOpen").onclick = async () => {
  $("posNum").value = 65;
  syncPosInputs("num");
  try {
    const r = await api("/api/command", {
      method: "POST",
      body: JSON.stringify(motionBody({ open: true })),
    });
    $("cmdMeta").textContent = r.ok ? "张开" : (r.error || "失败");
    await refresh();
  } catch (e) { alert(e.message); }
};

$("btnClose").onclick = async () => {
  $("posNum").value = 0;
  syncPosInputs("num");
  try {
    const r = await api("/api/command", {
      method: "POST",
      body: JSON.stringify(motionBody({ close: true })),
    });
    $("cmdMeta").textContent = r.ok ? "闭合" : (r.error || "失败");
    await refresh();
  } catch (e) { alert(e.message); }
};

$("btnRemoteConnect").onclick = () => {
  const urlEl = $("remoteUrl");
  const url = (urlEl && urlEl.value ? urlEl.value : "").trim() || REMOTE_DEFAULT;
  try {
    // eslint-disable-next-line no-new
    new URL(url);
  } catch (_) {
    alert("远程 URL 无效");
    return;
  }
  try { localStorage.setItem(LS_REMOTE_URL, url); } catch (_) {}
  remote.url = url;
  startRemoteStream(url);
};

$("btnRemoteDisconnect").onclick = () => {
  stopRemote();
};

$("btnRemoteSend").onclick = () => {
  if (remote.remoteStreaming) {
    stopRemoteStreaming();
    paintRemoteHint();
    return;
  }
  if (!remote.on || remote.gripper == null) {
    alert("请先拉取远程且收到 gripper");
    return;
  }
  if (!(remote.lastStatus && remote.lastStatus.connected)) {
    alert("请先连接本机夹爪");
    return;
  }
  remote.remoteStreaming = true;
  enqueueRemoteWrite(remote.gripper, remote.step);
  paintRemoteHint();
};

async function waitForBackend(timeoutMs) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    try {
      const r = await fetch("/api/health", { cache: "no-store" });
      if (r.ok) return true;
    } catch (_) {}
    await new Promise((res) => setTimeout(res, 400));
  }
  return false;
}

$("btnRestart").onclick = async () => {
  if (!confirm("重启 gripper-hl 后端并刷新页面？")) return;
  stopRemote();
  $("meta").textContent = "restarting…";
  try { await api("/api/restart", { method: "POST" }); } catch (_) {}
  await waitForBackend(20000);
  location.reload();
};

(function initRemoteUrl() {
  let saved = "";
  try { saved = localStorage.getItem(LS_REMOTE_URL) || ""; } catch (_) {}
  remote.url = saved || REMOTE_DEFAULT;
  const el = $("remoteUrl");
  if (el) el.value = remote.url;
  paintRemoteHint();
})();

setInterval(refresh, 250);
refresh();
