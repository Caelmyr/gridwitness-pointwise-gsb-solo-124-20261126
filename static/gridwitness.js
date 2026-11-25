"use strict";

const get = (id) => document.getElementById(id);
const state = {card: null, result: null, photo: null, probe: null, mode: "probe", chart: "profile", busy: false};
const settings = [...document.querySelectorAll("[data-setting]")];

async function api(path, options) {
  const response = await fetch("/gridwitness" + path, options);
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || "请求失败，请检查输入后重试。");
  return body;
}

function route(tail) {
  return "/cards/" + state.card.id + tail;
}

function savedQuery() {
  return "?revision=" + state.card.revision;
}

function notice(message, target = "notice") {
  const element = get(target);
  element.textContent = message;
  element.hidden = !message;
}

async function action(work, target = "notice") {
  if (state.busy) return;
  state.busy = true;
  document.querySelectorAll("button, select").forEach((node) => { node.disabled = true; });
  notice("", target);
  try {
    await work();
  } catch (error) {
    notice(error.message, target);
  } finally {
    state.busy = false;
    document.querySelectorAll("button, select").forEach((node) => { node.disabled = false; });
  }
}

async function library() {
  const {cards} = await api("/cards");
  const select = get("library");
  select.replaceChildren(new Option("选取已存卡片", ""));
  for (const card of cards) select.append(new Option(card.name, card.id));
  select.value = state.card?.id || "";
}

function paintSource() {
  const canvas = get("capture");
  const ctx = canvas.getContext("2d");
  const {photo,card,probe,result} = state;
  if (!photo) return;
  canvas.width = card.width;
  canvas.height = card.height;
  ctx.drawImage(photo,0,0);
  for (const cells of result.grid) {
    for (const cell of cells) {
      const x = cell.nominal_x;
      const y = cell.nominal_y;
      ctx.strokeStyle = "#4b97a2";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x-3,y);
      ctx.lineTo(x+3,y);
      ctx.moveTo(x,y-3);
      ctx.lineTo(x,y+3);
      ctx.stroke();
      if (!cell.center) continue;
      ctx.strokeStyle = cell.row === result.focus ? "#db8953" : "#6e74ac";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(x,y);
      ctx.lineTo(cell.center.x,cell.center.y);
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(cell.center.x,cell.center.y,6,0,2*Math.PI);
      ctx.stroke();
    }
  }
  if (probe) {
    ctx.strokeStyle = "#f5dcb8";
    ctx.strokeRect(probe.x-5,probe.y-5,10,10);
  }
}

function paintChart() {
  const canvas = get("chart");
  const ctx = canvas.getContext("2d");
  const {width,height} = canvas;
  const {result,card} = state;
  const support = state.chart === "coverage";
  const maxX = support ? card.settings.rows : card.settings.columns;
  const upper = support ? card.settings.columns : Math.max(1,...result.profile.flatMap((cell) =>
    cell.center ? [Math.abs(cell.dx),Math.abs(cell.dy)] : []));
  const lower = support ? 0 : -upper;
  const xAt = (x) => 48 + (width-82) * (x-1) / Math.max(1,maxX-1);
  const yAt = (v) => height-25 - (height-43) * (v-lower) / (upper-lower);
  get("chart-title").textContent = support ? "各点阵行实测支持" : "所选行实测位移";
  get("chart-caption").textContent = support ? "实测格点数 · 名义行" : "橙 ΔX · 紫 ΔY · 名义列";
  ctx.fillStyle = "#f3f8fb";
  ctx.fillRect(0,0,width,height);
  ctx.font = "12px monospace";
  ctx.fillStyle = "#51677a";
  ctx.strokeStyle = "#d8e5ed";
  for (const level of [lower,(lower+upper)/2,upper]) {
    ctx.fillText(Number(level.toFixed(1)),8,yAt(level)+3);
    ctx.beginPath();
    ctx.moveTo(xAt(1),yAt(level));
    ctx.lineTo(xAt(maxX),yAt(level));
    ctx.stroke();
  }
  ctx.fillText("1",xAt(1),height-6);
  ctx.fillText(String(maxX),xAt(maxX)-10,height-6);
  const plot = (values,color) => {
    ctx.strokeStyle = color;
    ctx.fillStyle = color;
    ctx.lineWidth = 2;
    ctx.beginPath();
    let prior=false;
    for (const [pos,value] of values) {
      if (value === null) {
        prior=false;
        continue;
      }
      if (prior) ctx.lineTo(xAt(pos),yAt(value));
      else ctx.moveTo(xAt(pos),yAt(value));
      ctx.fillRect(xAt(pos)-2,yAt(value)-2,4,4);
      prior=true;
    }
    ctx.stroke();
  };
  if (support) plot(result.row_counts.map((row) => [row.row,row.valid]),"#4e7e97");
  else {
    plot(result.profile.map((cell) => [cell.column,cell.center ? cell.dx : null]),"#c27a50");
    plot(result.profile.map((cell) => [cell.column,cell.center ? cell.dy : null]),"#7767aa");
  }
}

function pointLabel(point) {
  const disposition = point.dark ? "暗点" : "高于暗点上限";
  return "(" + point.x + ", " + point.y + ") · RGB " + point.rgb.join("/") +
    " · 亮度 " + point.brightness.toFixed(2) + " · " + disposition;
}

function inspectCell() {
  const column = Number(get("inspect-column").value);
  const cell = state.result.profile[column-1];
  const target = get("cell-readout");
  if (!cell) {
    target.textContent = "选择本行内的列。";
    return;
  }
  const nominal = "名义 (" + cell.nominal_x + ", " + cell.nominal_y + ")";
  target.textContent = cell.center
    ? nominal + " · 实测 (" + cell.center.x.toFixed(2) + ", " + cell.center.y.toFixed(2) + ") · " + cell.center.support + " 原暗点"
    : nominal + " · 无足够暗点";
}

function show() {
  const {card, result} = state;
  get("workspace").hidden = false;
  get("empty").hidden = true;
  get("origin").textContent = (card.synthetic ? "合成练习图" : "导入原片") + " · 修订 " + card.revision;
  get("card-title").textContent = card.name;
  get("dimensions").textContent = card.width + " × " + card.height + " px · " + card.photo_name;
  get("name").value = card.name;
  for (const field of settings) field.value = card.settings[field.dataset.setting];
  get("probe-x").max = card.width - 1;
  get("probe-y").max = card.height - 1;
  get("probe-x").value = state.probe?.x ?? card.settings.origin_x;
  get("probe-y").value = state.probe?.y ?? card.settings.origin_y;
  get("probe-result").textContent = state.probe ? pointLabel(state.probe) : "选择原片像素";
  const reading = result.reading;
  get("offset-value").textContent = reading ? reading.rms.toFixed(2) : "—";
  get("offset-unit").textContent = "px";
  get("measurement-state").textContent = "名义第 " + result.focus + " 行";
  get("selected-level").textContent = reading
    ? "本行 " + reading.valid + " / " + reading.columns + " 格有原像素证据"
    : "该行无实测格点";
  get("area-level").textContent = result.row_counts.reduce((sum, row) => sum + row.valid,0) +
    " / " + (card.settings.rows * card.settings.columns) + " 全板格点有证";
  get("inspect-column").max = card.settings.columns;
  if (Number(get("inspect-column").value) > card.settings.columns) get("inspect-column").value = 1;
  inspectCell();
  for (const [id, filename] of Object.entries({proof: "proof.png", csv: "profile.csv", zip: "observation.zip"})) {
    get(id).href = "/gridwitness" + route("/export/" + filename) + savedQuery();
  }
  paintSource();
  paintChart();
}

async function open(card) {
  const base = "/cards/" + card.id;
  const photo = new Image();
  photo.src = "/gridwitness" + base + "/capture.png";
  const [result] = await Promise.all([api(base + "/measurement?revision=" + card.revision), photo.decode()]);
  Object.assign(state, {card, result, photo, probe: null});
  get("library").value = card.id;
  show();
}

async function probe(x, y) {
  state.probe = await api(route("/probe") + savedQuery() + "&x=" + x + "&y=" + y);
  get("probe-x").value = x;
  get("probe-y").value = y;
  get("probe-result").textContent = pointLabel(state.probe);
  paintSource();
}

get("practice").addEventListener("click", () => action(async () => {
  await open(await api("/practice", {method: "POST"}));
  await library();
}));

get("library").addEventListener("change", () => {
  if (get("library").value) action(async () => open(await api("/cards/" + get("library").value)));
});
get("open-import").addEventListener("click", () => {
  notice("", "import-notice");
  get("import").showModal();
});
get("cancel-import").addEventListener("click", () => get("import").close());
get("upload").addEventListener("submit", (event) => {
  event.preventDefault();
  action(async () => {
    const card = await api("/cards", {method: "POST", body: new FormData(event.target)});
    await open(card);
    await library();
    get("import").close();
    event.target.reset();
  }, "import-notice");
});
document.querySelectorAll("[data-mode]").forEach((button) => button.addEventListener("click", () => {
  state.mode = button.dataset.mode;
  document.querySelectorAll("[data-mode]").forEach((item) =>
    item.setAttribute("aria-pressed", String(item === button)));
}));
get("capture").addEventListener("click", (event) => {
  if (!state.card) return;
  const canvas = event.currentTarget;
  const rect = canvas.getBoundingClientRect();
  const x = Math.max(0, Math.min(canvas.width - 1, Math.floor((event.clientX - rect.left) * canvas.width / rect.width)));
  const y = Math.max(0, Math.min(canvas.height - 1, Math.floor((event.clientY - rect.top) * canvas.height / rect.height)));
  action(async () => {
    await probe(x, y);
    const field = (name) => settings.find((item) => item.dataset.setting === name);
    if (state.mode === "center") {
      field("origin_x").value = x;
      field("origin_y").value = y;
      notice("已填入原片坐标作为名义首点。");
    }
    if (state.mode === "mark") {
      const row = Math.round((y - Number(field("origin_y").value)) / Number(field("step_y").value)) + 1;
      field("focus").value = Math.min(Number(field("rows").value),Math.max(1,row));
      notice("已填入此原点附近的名义行。");
    }
  });
});
get("probe-form").addEventListener("submit", (event) => {
  event.preventDefault();
  action(() => probe(get("probe-x").value, get("probe-y").value));
});
get("calibration").addEventListener("submit", (event) => {
  event.preventDefault();
  action(async () => {
    const fields = Object.fromEntries(settings.map((field) => [
      field.dataset.setting, Number(field.value),
    ]));
    const card = await api(route(""), {
      method: "PATCH", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({revision: state.card.revision, name: get("name").value, settings: fields}),
    });
    await open(card);
    await library();
  });
});
get("prepare").addEventListener("click", () => action(async () => {
  const {url} = await api(route("/prepare") + savedQuery(), {method: "POST"});
  location.assign(url);
}));
document.querySelectorAll("[data-chart]").forEach((button) => button.addEventListener("click", () => {
  state.chart = button.dataset.chart;
  document.querySelectorAll("[data-chart]").forEach((item) =>
    item.setAttribute("aria-pressed", String(item === button)));
  if (state.card) paintChart();
}));
get("inspect-column").addEventListener("input",inspectCell);
action(library);
