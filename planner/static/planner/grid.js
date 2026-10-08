(function () {
  "use strict";

  const data = JSON.parse(document.getElementById("grid-data").textContent);
  const URLS = window.GRID_URLS;
  const PX = 3; // пикселей на минуту
  const SNAP = 5; // шаг перетаскивания, минут

  const toMin = (hhmm) => {
    const [h, m] = hhmm.split(":").map(Number);
    return h * 60 + m;
  };
  const toHHMM = (min) =>
    `${String(Math.floor(min / 60)).padStart(2, "0")}:${String(min % 60).padStart(2, "0")}`;

  // Диапазон сетки — по окнам аудиторий, но не уже 08:00–20:00.
  let dayStart = 8 * 60;
  let dayEnd = 20 * 60;
  data.rooms.forEach((r) =>
    r.windows.forEach((w) => {
      dayStart = Math.min(dayStart, Math.floor(toMin(w.from) / 60) * 60);
      dayEnd = Math.max(dayEnd, Math.ceil(toMin(w.to) / 60) * 60);
    })
  );
  const width = (dayEnd - dayStart) * PX;
  const x = (min) => (min - dayStart) * PX;

  const allLessons = new Map();
  data.lessons.concat(data.unplaced).forEach((l) => allLessons.set(l.id, l));

  function csrf() {
    const m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : "";
  }

  async function post(url, body) {
    const resp = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
      body: JSON.stringify(body || {}),
    });
    let payload = {};
    try {
      payload = await resp.json();
    } catch (e) {
      payload = { ok: false, errors: [`Ошибка сервера (${resp.status})`] };
    }
    return payload;
  }

  // Жёсткие правила — ошибка; мягкие — предупреждение с подтверждением.
  async function postWithRules(url, body) {
    let res = await post(url, body);
    if (res.errors && res.errors.length) {
      alert("Нельзя:\n• " + res.errors.join("\n• "));
      return false;
    }
    if (!res.ok && res.warnings && res.warnings.length) {
      if (!confirm("Предупреждение:\n• " + res.warnings.join("\n• ") + "\n\nВсё равно сохранить?")) {
        return false;
      }
      res = await post(url, Object.assign({}, body, { force: true }));
      if (res.errors && res.errors.length) {
        alert("Нельзя:\n• " + res.errors.join("\n• "));
        return false;
      }
    }
    return res.ok;
  }

  function el(tag, attrs, ...children) {
    const node = document.createElement(tag);
    Object.entries(attrs || {}).forEach(([k, v]) => {
      if (k === "class") node.className = v;
      else if (k === "style") Object.assign(node.style, v);
      else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
      else node.setAttribute(k, v);
    });
    children.flat().forEach((c) => c != null && node.append(c));
    return node;
  }

  // ---------- сетка ----------
  function renderGrid() {
    const grid = document.getElementById("grid");
    grid.innerHTML = "";
    const head = el("div", { class: "g-row head" }, el("div", { class: "g-label" }, "Аудитория"));
    const headTrack = el("div", { class: "g-track", style: { width: width + "px" } });
    for (let m = dayStart; m < dayEnd; m += 60) {
      headTrack.append(el("div", { class: "g-hour", style: { left: x(m) + "px" } }, toHHMM(m)));
    }
    head.append(headTrack);
    grid.append(head);

    const bySite = new Map();
    data.rooms.forEach((r) => {
      if (!bySite.has(r.site)) bySite.set(r.site, []);
      bySite.get(r.site).push(r);
    });
    bySite.forEach((rooms, site) => {
      grid.append(el("div", { class: "g-site" }, site));
      rooms.forEach((room) => grid.append(renderRoom(room)));
    });
  }

  function renderRoom(room) {
    const track = el("div", { class: "g-track", style: { width: width + "px" } });
    for (let m = dayStart; m < dayEnd; m += 60) {
      track.append(el("div", { class: "g-hour", style: { left: x(m) + "px" } }));
    }
    room.windows.forEach((w) => {
      track.append(
        el("div", {
          class: "g-window",
          title: `Окно ${w.from}–${w.to}`,
          style: { left: x(toMin(w.from)) + "px", width: (toMin(w.to) - toMin(w.from)) * PX + "px" },
          onclick: (e) => {
            e.stopPropagation();
            editWindow(room, w);
          },
        })
      );
    });
    data.lessons
      .filter((l) => l.room_id === room.id)
      .forEach((l) => track.append(renderLesson(l)));

    track.addEventListener("dblclick", (e) => {
      if (e.target !== track) return;
      const min = snapFromEvent(track, e, 0);
      editWindow(room, null, toHHMM(min));
    });
    track.addEventListener("dragover", (e) => {
      e.preventDefault();
      track.classList.add("drop");
    });
    track.addEventListener("dragleave", () => track.classList.remove("drop"));
    track.addEventListener("drop", async (e) => {
      e.preventDefault();
      track.classList.remove("drop");
      const id = Number(e.dataTransfer.getData("text/lesson"));
      const grab = Number(e.dataTransfer.getData("text/grab") || 0);
      if (!id) return;
      const start = snapFromEvent(track, e, grab);
      const ok = await postWithRules(URLS.place(id), { date: data.date, room_id: room.id, start: toHHMM(start) });
      if (ok) location.reload();
    });

    const label = el(
      "div",
      { class: "g-label" },
      el("b", {}, room.label),
      `${room.capacity} мест${room.pc ? `, ${room.pc} ПК` : ""}`
    );
    return el("div", { class: "g-row" }, label, track);
  }

  function snapFromEvent(track, e, grabOffset) {
    const rect = track.getBoundingClientRect();
    const px = e.clientX - rect.left - grabOffset;
    const min = dayStart + Math.round(px / PX / SNAP) * SNAP;
    return Math.max(dayStart, Math.min(dayEnd - SNAP, min));
  }

  function renderLesson(l) {
    const node = el(
      "div",
      {
        class: "g-lesson" + (l.is_manual ? " manual" : ""),
        draggable: "true",
        "data-id": l.id,
        title: `${l.title}\n${l.school}, ${l.classes} (${l.participants} чел.)\n${l.start}–${l.end}`,
        style: { left: x(toMin(l.start)) + "px", width: Math.max((toMin(l.end) - toMin(l.start)) * PX - 2, 20) + "px" },
        onclick: () => select(l.id),
        ondragstart: (e) => {
          e.dataTransfer.setData("text/lesson", String(l.id));
          e.dataTransfer.setData("text/grab", String(e.offsetX));
        },
      },
      el("b", {}, l.title),
      el("br"),
      el("small", {}, `${l.start}–${l.end} · ${l.school}, ${l.classes}`)
    );
    return node;
  }

  // ---------- нераспределённые ----------
  function renderUnplaced() {
    const box = document.getElementById("unplaced");
    box.innerHTML = "";
    document.getElementById("unplaced-count").textContent = `(${data.unplaced.length})`;
    if (!data.unplaced.length) box.append(el("p", { class: "muted" }, "Все занятия распределены."));
    data.unplaced.forEach((l) => {
      box.append(
        el(
          "div",
          {
            class: `u-card ${l.status}`,
            draggable: "true",
            "data-id": l.id,
            onclick: () => select(l.id),
            ondragstart: (e) => {
              e.dataTransfer.setData("text/lesson", String(l.id));
              e.dataTransfer.setData("text/grab", "0");
            },
          },
          el("b", {}, l.title),
          ` · ${l.duration} мин`,
          el("br"),
          `${l.school}, ${l.classes} (${l.participants} чел.)`,
          el("br"),
          el("span", { class: "tag" }, l.status_display),
          l.reason ? el("div", { class: "muted" }, l.reason) : null,
          el("div", { class: "muted" }, "Дни: " + (l.days.join("; ") || "—"))
        )
      );
    });
  }

  // ---------- карточка занятия ----------
  function select(id) {
    document.querySelectorAll(".selected").forEach((n) => n.classList.remove("selected"));
    document.querySelectorAll(`[data-id="${id}"]`).forEach((n) => n.classList.add("selected"));
    const l = allLessons.get(id);
    const box = document.getElementById("details");
    box.innerHTML = "";
    const teacherSelect = el(
      "select",
      {},
      el("option", { value: "" }, "— не назначен —"),
      data.teachers.map((t) => {
        const opt = el("option", { value: t.id }, t.name);
        if (t.id === l.teacher_id) opt.selected = true;
        return opt;
      })
    );
    teacherSelect.addEventListener("change", async () => {
      const ok = await postWithRules(URLS.teacher(l.id), { teacher_id: teacherSelect.value || null });
      if (ok) location.reload();
      else teacherSelect.value = l.teacher_id || "";
    });
    const room = data.rooms.find((r) => r.id === l.room_id);
    box.append(
      ...[
      el("h2", {}, l.title),
      el("div", {}, `${l.school}, ${l.classes} — ${l.participants} чел.`),
      el("div", {}, room ? `${room.label}, ${l.start}–${l.end}` : `Не поставлено · ${l.duration} мин`),
      el("div", {}, el("span", { class: "tag" }, l.status_display), l.is_manual ? " вручную" : l.room_id ? " авто" : ""),
      l.reason ? el("p", { class: "muted" }, l.reason) : null,
      el("div", { class: "field" }, el("label", {}, "Преподаватель"), teacherSelect),
      el(
        "div",
        { class: "details-actions" },
        l.room_id
          ? el("button", { class: "btn secondary", onclick: () => act(URLS.unplace(l.id)) }, "Снять с расписания")
          : null,
        el(
          "button",
          {
            class: "btn secondary",
            onclick: () => confirm("Удалить занятие из заявки?") && act(URLS.remove(l.id)),
          },
          "Удалить"
        ),
        el("a", { class: "btn secondary", href: URLS.adminRequest(l.request_id) }, `Заявка №${l.request_id}`)
      ),
      ].filter(Boolean)
    );
  }

  async function act(url) {
    const res = await post(url);
    if (res.ok) location.reload();
    else alert((res.errors || ["Ошибка"]).join("\n"));
  }

  // ---------- окна аудиторий ----------
  async function editWindow(room, w, at) {
    const current = w ? `${w.from}-${w.to}` : `${at}-${toHHMM(Math.min(toMin(at) + 240, dayEnd))}`;
    const answer = prompt(
      `${room.label}: окно аудитории (например 09:00-17:00).\nОставьте пустым, чтобы удалить окно.`,
      current
    );
    if (answer === null) return;
    let body;
    if (!answer.trim()) {
      if (!w) return;
      if (!confirm("Удалить окно? Занятия в нём получат статус «конфликт».")) return;
      body = { id: w.id, delete: true };
    } else {
      const m = answer.match(/^\s*(\d{1,2}:\d{2})\s*[-–]\s*(\d{1,2}:\d{2})\s*$/);
      if (!m) return alert("Формат: 09:00-17:00");
      const pad = (s) => s.padStart(5, "0");
      body = { id: w ? w.id : null, room_id: room.id, date: data.date, from: pad(m[1]), to: pad(m[2]) };
    }
    const res = await post(URLS.window, body);
    if (!res.ok) return alert((res.errors || ["Ошибка"]).join("\n"));
    if (res.released) alert(`Не поместились и сняты с расписания: ${res.released}.`);
    location.reload();
  }

  document.getElementById("distribute").addEventListener("click", async () => {
    const res = await post(URLS.distribute);
    if (res.ok) {
      alert(`Назначено: ${res.assigned}, конфликтов: ${res.conflicts}, повторов: ${res.repeats}.`);
      location.reload();
    }
  });

  renderGrid();
  renderUnplaced();
})();
