// Playlist detail page: queue player (video or audio), drag/keyboard reorder,
// per-row downloads, remove confirmation and the free-listening switch.
// Wrapped in a closure because Turbo re-runs this script on every visit.
(function () {
  const root = document.querySelector("[data-playlist-player]");
  if (!root) return;

  const playlistId = root.dataset.playlistId;
  const list = root.querySelector("[data-list]");
  const media = root.querySelector("[data-media]");
  const art = root.querySelector("[data-art]");
  const artImg = root.querySelector("[data-art-img]");
  const nowTitle = root.querySelector("[data-now-title]");
  const nowSub = root.querySelector("[data-now-sub]");
  const seek = root.querySelector("[data-seek]");
  const fullscreenButton = root.querySelector("[data-fullscreen]");
  const timeCurrent = root.querySelector("[data-time-current]");
  const timeTotal = root.querySelector("[data-time-total]");
  const playPause = root.querySelector("[data-playpause]");
  const iconPlay = root.querySelector("[data-icon-play]");
  const iconPause = root.querySelector("[data-icon-pause]");
  const shuffleButton = root.querySelector("[data-shuffle]");
  const loopButton = root.querySelector("[data-loop]");
  const modeButtons = Array.from(root.querySelectorAll("[data-mode]"));

  const MODE_KEY = "raton:playlist-mode";
  const SHUFFLE_KEY = "raton:playlist-shuffle";
  const LOOP_KEY = "raton:playlist-loop";

  const store = {
    get(key) {
      try {
        return window.localStorage.getItem(key);
      } catch {
        return null;
      }
    },
    set(key, value) {
      try {
        window.localStorage.setItem(key, value);
      } catch {
        /* private mode: the setting just doesn't persist */
      }
    },
  };

  const rows = () => Array.from(list.querySelectorAll("[data-row]"));
  const flag = (row, name) => row.dataset[name] === "1";
  const hasFile = (row, mode) => flag(row, mode === "audio" ? "hasAudio" : "hasVideo");
  const isFree = () => root.dataset.free === "1";

  let mode = store.get(MODE_KEY);
  if (mode !== "audio" && mode !== "video") {
    mode = rows().some((row) => hasFile(row, "audio")) || !rows().length ? "audio" : "video";
  }
  let shuffle = store.get(SHUFFLE_KEY) === "1";
  let loop = store.get(LOOP_KEY) === "1";
  let current = null;
  let history = [];
  let shuffleSeen = new Set();
  const pendingDownloads = new Set();

  const eligible = (row) => hasFile(row, mode);

  // Audio mode plays through the persistent mini player (app.js): its queue
  // goes on from page to page, and the bar shows the playlist's track. This
  // page's <video> only serves Video mode.
  const QUEUE_KEY = `playlist:${playlistId}`;
  const mini = () => window.ratonMiniPlayer;
  const miniAudio = () => mini()?.audioElement();
  const viaMini = () => mode === "audio";
  const ownsMini = () => Boolean(mini()) && mini().queueKey() === QUEUE_KEY;
  // Position to start from when Audio mode was entered paused.
  let pendingStartAt = 0;

  function trackOf(row) {
    const id = row.dataset.videoId;
    return {
      id,
      title: row.dataset.title,
      channel: row.dataset.channel,
      src: `/api/videos/${id}/audio`,
      thumb: row.dataset.thumb === "1" ? `/api/videos/${id}/thumbnail?w=320` : "",
      // Free listening logs nothing: the mini player skips a track without URL.
      activityUrl: isFree() ? "" : `/api/videos/${id}/activity`,
      detailUrl: `/videos/${id}`,
    };
  }

  function queueOptions() {
    return { tracks: rows().filter((row) => hasFile(row, "audio")).map(trackOf), shuffle, loop };
  }

  // The rows changed (order, downloads, switches): the playing queue follows.
  function syncQueue() {
    if (ownsMini()) mini().updateQueue(QUEUE_KEY, queueOptions());
  }

  function startQueue(row, startAt = 0, autoplay = true) {
    mini()?.playQueue({
      key: QUEUE_KEY,
      url: `/playlists/${playlistId}`,
      ...queueOptions(),
      startId: row.dataset.videoId,
      startAt,
      autoplay,
    });
  }

  function formatTime(seconds) {
    if (!Number.isFinite(seconds) || seconds < 0) return "0:00";
    const total = Math.floor(seconds);
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    const s = String(total % 60).padStart(2, "0");
    return h ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${m}:${s}`;
  }

  function seenCount() {
    return rows().filter((row) => flag(row, "seen")).length;
  }

  function plural(count) {
    return count === 1 ? "" : "s";
  }

  function refreshRows() {
    const all = rows();
    all.forEach((row) => {
      const skipped = !eligible(row);
      row.classList.toggle("is-skipped", skipped);
      row.classList.toggle("is-current", row === current);
      row.classList.toggle("is-seen", flag(row, "seen") && !isFree());
      const note = row.querySelector("[data-skip-note]");
      if (note) {
        note.textContent = skipped ? ` · ignorée : ${mode === "audio" ? "audio" : "vidéo"} non téléchargé${mode === "audio" ? "" : "e"}` : "";
      }
      row.querySelectorAll("[data-dl]").forEach((button) => {
        const kind = button.dataset.dl;
        const have = hasFile(row, kind);
        const pending = pendingDownloads.has(`${row.dataset.videoId}:${kind}`);
        const noun = kind === "audio" ? "l'audio" : "la vidéo";
        button.classList.toggle("is-have", have);
        button.classList.toggle("is-pending", pending);
        button.dataset.tip = have
          ? kind === "audio" ? "Audio téléchargé" : "Vidéo téléchargée"
          : pending ? "Téléchargement en file d'attente…" : `Télécharger ${noun}`;
        button.dataset.tipEnd = "";
        button.setAttribute("aria-label", button.dataset.tip);
        button.setAttribute("aria-disabled", have || pending ? "true" : "false");
      });
    });
    const views = root.querySelector("[data-views-meta]");
    const seen = seenCount();
    const hint = root.querySelector("[data-free-hint]");
    if (views) views.textContent = isFree() ? " · écoute libre" : ` · ${seen} vue${plural(seen)} sur ${all.length}`;
    if (hint) hint.textContent = isFree() ? "Les vidéos ne sont jamais marquées comme vues" : `${seen} vue${plural(seen)} sur ${all.length}`;
  }

  function updatePlayIcon() {
    const playing = viaMini() ? ownsMini() && !miniAudio().paused : !media.paused && !media.ended;
    // The icons are <svg>: SVGElement has no `hidden` property, so assigning
    // `.hidden` would never reach the attribute the CSS reads.
    iconPlay.toggleAttribute("hidden", playing);
    iconPause.toggleAttribute("hidden", !playing);
    playPause.setAttribute("aria-label", playing ? "Pause" : "Lecture");
  }

  function setNowPlaying(row) {
    if (!row) {
      nowTitle.textContent = "Aucune piste lisible";
      nowSub.textContent = `Aucune vidéo de la playlist n'a de fichier ${mode === "audio" ? "audio" : "vidéo"}.`;
      artImg.hidden = true;
      return;
    }
    const all = rows();
    nowTitle.textContent = row.dataset.title;
    const channel = row.dataset.channel ? `${row.dataset.channel} · ` : "";
    nowSub.textContent = `${channel}${all.indexOf(row) + 1} sur ${all.length}`;
    if (row.dataset.thumb === "1") {
      artImg.src = `/api/videos/${row.dataset.videoId}/thumbnail`;
      artImg.hidden = false;
    } else {
      artImg.hidden = true;
    }
  }

  function applyMode() {
    media.hidden = mode === "audio";
    art.hidden = mode === "video";
    fullscreenButton.hidden = mode === "audio";
    modeButtons.forEach((button) => button.setAttribute("aria-pressed", String(button.dataset.mode === mode)));
  }

  function load(row, autoplay, startAt) {
    current = row;
    if (!row) {
      media.removeAttribute("src");
      media.load();
      seek.value = "0";
      window.ratonPaintSeekRange?.(seek, media);
      timeCurrent.textContent = formatTime(0);
      timeTotal.textContent = formatTime(0);
      setNowPlaying(null);
      refreshRows();
      updatePlayIcon();
      return;
    }
    if (viaMini()) {
      setNowPlaying(row);
      refreshRows();
      // A paused pick still moves a queue that is already this playlist's.
      if (autoplay || ownsMini()) startQueue(row, startAt || 0, autoplay);
      else pendingStartAt = startAt || 0;
      updatePlayIcon();
      return;
    }
    media.src = `/api/videos/${row.dataset.videoId}/${mode}`;
    if (row.dataset.thumb === "1" && mode === "video") {
      media.poster = `/api/videos/${row.dataset.videoId}/thumbnail`;
    } else {
      media.removeAttribute("poster");
    }
    if (startAt) {
      media.addEventListener("loadedmetadata", () => { media.currentTime = startAt; }, { once: true });
    }
    setNowPlaying(row);
    refreshRows();
    if (autoplay) {
      media.play().catch(() => {});
    }
    updatePlayIcon();
  }

  function eligibleRows() {
    return rows().filter(eligible);
  }

  function pickNext() {
    const candidates = eligibleRows();
    if (!candidates.length) return null;
    if (shuffle) {
      let pool = candidates.filter((row) => !shuffleSeen.has(row) && row !== current);
      if (!pool.length) {
        if (!loop) return null;
        shuffleSeen = new Set(current ? [current] : []);
        pool = candidates.filter((row) => row !== current);
        if (!pool.length) pool = candidates;
      }
      return pool[Math.floor(Math.random() * pool.length)];
    }
    const index = candidates.indexOf(current);
    if (index === -1) {
      const all = rows();
      const start = current ? all.indexOf(current) : -1;
      return candidates.find((row) => all.indexOf(row) > start) || (loop ? candidates[0] : null);
    }
    if (index + 1 < candidates.length) return candidates[index + 1];
    return loop ? candidates[0] : null;
  }

  function goNext() {
    if (viaMini() && ownsMini()) {
      mini().next();
      return;
    }
    const next = pickNext();
    if (!next) {
      media.pause();
      return;
    }
    if (current) history.push(current);
    shuffleSeen.add(next);
    load(next, true);
  }

  function goPrevious() {
    if (viaMini() && ownsMini()) {
      mini().previous();
      return;
    }
    if (media.currentTime > 3) {
      media.currentTime = 0;
      return;
    }
    let previous = null;
    if (shuffle) {
      while (history.length && !previous) {
        const candidate = history.pop();
        if (rows().includes(candidate) && eligible(candidate)) previous = candidate;
      }
    } else {
      const candidates = eligibleRows();
      const index = candidates.indexOf(current);
      previous = index > 0 ? candidates[index - 1] : loop ? candidates[candidates.length - 1] : null;
    }
    if (previous) load(previous, true);
    else media.currentTime = 0;
  }

  function playRow(row) {
    if (!eligible(row)) {
      nowSub.textContent = `« ${row.dataset.title} » n'a pas de fichier ${mode === "audio" ? "audio" : "vidéo"} : télécharge-le pour le lire.`;
      return;
    }
    if (current && current !== row) history.push(current);
    shuffleSeen.add(row);
    load(row, true);
  }

  // ---- Playback activity (history, screen time, 90% watched rule) --------
  // Skipped entirely in free-listening mode: that mode exists so replaying
  // music never counts as watching.
  let watchedAccum = 0;
  let lastTick = null;
  let lastPost = 0;

  function postActivity() {
    if (isFree() || !current || !Number.isFinite(media.duration) || media.duration <= 0) return;
    const watched = watchedAccum;
    watchedAccum = 0;
    lastPost = Date.now();
    if (media.currentTime / media.duration >= 0.9 && !flag(current, "seen")) {
      current.dataset.seen = "1";
      refreshRows();
    }
    window.ratonReportPlayback?.(`/api/videos/${current.dataset.videoId}/activity`, mode, media, watched);
  }

  // Fill and buffer layers of the seek bar; the helper lives in app.js.
  function paintSeek() {
    window.ratonPaintSeekRange?.(seek, media);
  }

  // Seek bar and times of the element playing: this page's <video>, or the
  // mini player's <audio> in Audio mode.
  function showProgress(element) {
    if (!seeking && Number.isFinite(element.duration) && element.duration > 0) {
      seek.value = String((element.currentTime / element.duration) * 100);
    }
    window.ratonPaintSeekRange?.(seek, element);
    timeCurrent.textContent = formatTime(element.currentTime);
    timeTotal.textContent = formatTime(element.duration);
  }

  media.addEventListener("timeupdate", () => {
    if (viaMini()) return;
    showProgress(media);
    const now = Date.now();
    if (lastTick !== null && !media.paused) watchedAccum += Math.min((now - lastTick) / 1000, 2);
    lastTick = now;
    if (now - lastPost > 15000) postActivity();
  });
  media.addEventListener("loadedmetadata", () => {
    timeTotal.textContent = formatTime(media.duration);
  });
  media.addEventListener("progress", paintSeek);
  // On a full page load app.js (the helper) runs after this script.
  const bindMediaSession = () =>
    window.ratonClaimMediaSession(
      media,
      () =>
        current && {
          title: current.dataset.title,
          artist: current.dataset.channel,
          artwork: current.dataset.thumb === "1" ? `/api/videos/${current.dataset.videoId}/thumbnail` : "",
        },
      { previous: goPrevious, next: goNext }
    );
  if (window.ratonClaimMediaSession) bindMediaSession();
  else document.addEventListener("DOMContentLoaded", bindMediaSession, { once: true });
  media.addEventListener("play", () => { lastTick = Date.now(); updatePlayIcon(); });
  media.addEventListener("pause", () => { lastTick = null; postActivity(); updatePlayIcon(); });
  media.addEventListener("ended", () => { postActivity(); goNext(); });
  media.addEventListener("error", () => {
    if (current) nowSub.textContent = "Lecture impossible pour ce fichier.";
  });
  window.addEventListener("pagehide", postActivity);

  let seeking = false;
  seek.addEventListener("input", () => {
    seeking = true;
    if (viaMini()) {
      const audio = miniAudio();
      if (ownsMini() && Number.isFinite(audio.duration)) {
        const seconds = (Number(seek.value) / 100) * audio.duration;
        mini().seekTo(mini().currentId(), seconds);
        timeCurrent.textContent = formatTime(seconds);
      }
      window.ratonPaintSeekRange?.(seek, audio);
      return;
    }
    if (Number.isFinite(media.duration)) {
      media.currentTime = (Number(seek.value) / 100) * media.duration;
      timeCurrent.textContent = formatTime(media.currentTime);
    }
    paintSeek();
  });
  seek.addEventListener("change", () => { seeking = false; });

  playPause.addEventListener("click", () => {
    if (viaMini()) {
      if (ownsMini()) {
        mini().toggle(mini().currentId());
        return;
      }
      const row = current && eligible(current) ? current : eligibleRows()[0];
      if (row) startQueue(row, pendingStartAt);
      pendingStartAt = 0;
      return;
    }
    if (!current) {
      const first = eligibleRows()[0];
      if (first) load(first, true);
      return;
    }
    if (media.paused) media.play().catch(() => {});
    else media.pause();
  });
  root.querySelector("[data-next]").addEventListener("click", goNext);
  root.querySelector("[data-prev]").addEventListener("click", goPrevious);
  media.addEventListener("click", () => playPause.click());
  // Safari's own fullscreen player (native controls) wins over the standard
  // API: on iPhone it is the only way, and on macOS it gives the same player as
  // a `<video controls>` page instead of a bare controls-less fullscreen.
  fullscreenButton.addEventListener("click", () => {
    if (media.webkitEnterFullscreen) media.webkitEnterFullscreen();
    else media.requestFullscreen?.();
  });

  function syncToggles() {
    shuffleButton.setAttribute("aria-pressed", String(shuffle));
    loopButton.setAttribute("aria-pressed", String(loop));
  }
  shuffleButton.addEventListener("click", () => {
    shuffle = !shuffle;
    shuffleSeen = new Set(current ? [current] : []);
    history = [];
    store.set(SHUFFLE_KEY, shuffle ? "1" : "0");
    syncToggles();
    syncQueue();
  });
  loopButton.addEventListener("click", () => {
    loop = !loop;
    store.set(LOOP_KEY, loop ? "1" : "0");
    syncToggles();
    syncQueue();
  });

  modeButtons.forEach((button) => {
    button.addEventListener("click", () => {
      if (button.dataset.mode === mode) return;
      // The track and position carry over from one player to the other.
      const fromMini = viaMini() && ownsMini();
      const playing = fromMini ? miniAudio() : media;
      const wasPlaying = (fromMini || !viaMini()) && !playing.paused;
      const position = fromMini || !viaMini() ? playing.currentTime : pendingStartAt;
      postActivity();
      if (fromMini) {
        if (wasPlaying) mini().toggle(mini().currentId());
      } else if (!viaMini()) {
        media.pause();
        media.removeAttribute("src");
        media.load();
      }
      pendingStartAt = 0;
      mode = button.dataset.mode;
      store.set(MODE_KEY, mode);
      applyMode();
      const keep = current && eligible(current) ? current : null;
      if (viaMini() && ownsMini() && !current) {
        // Nothing new from Video mode: show where the mini player is.
        current = null;
        mirrorMini();
        if (wasPlaying) mini().toggle(mini().currentId());
      } else if (keep) {
        load(keep, wasPlaying, position);
      } else {
        const all = rows();
        const start = current ? all.indexOf(current) : -1;
        const target = eligibleRows().find((row) => all.indexOf(row) > start) || eligibleRows()[0] || null;
        load(target, wasPlaying && Boolean(target));
      }
    });
  });

  list.addEventListener("click", (event) => {
    const row = event.target.closest("[data-row]");
    if (!row) return;
    // A touch long-press that started a drag ends with a click: it must not play the row.
    if (suppressClick) return;
    const more = event.target.closest("[data-more]");
    if (more) {
      toggleRowMenu(row);
      return;
    }
    const move = event.target.closest("[data-move]");
    closeRowMenus();
    if (move) {
      moveRow(row, move.dataset.move === "up" ? -1 : 1);
    } else if (event.target.closest("[data-ask-remove]")) {
      row.classList.add("is-confirming");
      row.querySelector(".pld-confirm").hidden = false;
      row.querySelector(".pld-confirm-cancel").focus();
    } else if (event.target.closest("[data-cancel-remove]")) {
      row.classList.remove("is-confirming");
      row.querySelector(".pld-confirm").hidden = true;
    } else if (event.target.closest("[data-dl]")) {
      startDownload(row, event.target.closest("[data-dl]"));
    } else if (event.target.closest("[data-play-row]")) {
      playRow(row);
    } else if (!event.target.closest("a, button, form, input, [data-row-actions]") && !row.classList.contains("is-confirming")) {
      // The whole row plays the track; the title link and the controls keep their own action,
      // and the menu padding or a row waiting for its removal confirmation does nothing.
      playRow(row);
    }
  });

  // Phone: the row actions live in a popover opened by the "⋯" button.
  function closeRowMenus() {
    list.querySelectorAll("[data-row].is-menu-open").forEach((row) => {
      row.classList.remove("is-menu-open");
      row.querySelector("[data-more]").setAttribute("aria-expanded", "false");
    });
  }

  function toggleRowMenu(row) {
    const open = !row.classList.contains("is-menu-open");
    closeRowMenus();
    row.classList.toggle("is-menu-open", open);
    row.querySelector("[data-more]").setAttribute("aria-expanded", String(open));
  }

  document.addEventListener("click", (event) => {
    if (!event.target.closest("[data-row]")) closeRowMenus();
  });
  list.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      const menuRow = event.target.closest("[data-row].is-menu-open");
      if (menuRow) {
        closeRowMenus();
        menuRow.querySelector("[data-more]").focus();
        return;
      }
      const row = event.target.closest("[data-row].is-confirming");
      if (row) {
        row.classList.remove("is-confirming");
        row.querySelector(".pld-confirm").hidden = true;
      }
    }
  });

  // ---- Downloads from the queue ---------------------------------------------
  async function startDownload(row, button) {
    const kind = button.dataset.dl;
    const key = `${row.dataset.videoId}:${kind}`;
    if (hasFile(row, kind) || pendingDownloads.has(key)) return;
    pendingDownloads.add(key);
    refreshRows();
    try {
      // The helpers live in app.js.
      const job = await window.ratonApi("POST", button.dataset.url);
      await window.ratonWaitForJob(job.status_url, { interval: 3000, failure: "Le téléchargement a échoué." });
      row.dataset[kind === "audio" ? "hasAudio" : "hasVideo"] = "1";
      syncQueue();
    } catch (error) {
      nowSub.textContent = error.message;
    }
    pendingDownloads.delete(key);
    refreshRows();
  }

  // ---- Free listening switch -----------------------------------------------
  const freeForm = root.querySelector("[data-free-form]");
  if (freeForm) {
    freeForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const input = freeForm.querySelector("[data-free-input]");
      const next = input.value === "1";
      try {
        await window.ratonApi("PUT", `/api/playlists/${playlistId}/free-listening`, { enabled: next });
      } catch {
        // The form's own action (no-JS fallback) saves it with a page load.
        freeForm.submit();
        return;
      }
      root.dataset.free = next ? "1" : "0";
      input.value = next ? "0" : "1";
      freeForm.querySelector("[data-free-switch]").setAttribute("aria-checked", String(next));
      refreshRows();
      syncQueue();
    });
  }

  // ---- Filter ------------------------------------------------------------------
  const filter = root.querySelector("[data-filter]");
  if (filter) {
    filter.addEventListener("input", () => {
      const needle = filter.value.trim().toLowerCase();
      rows().forEach((row) => {
        row.hidden = Boolean(needle) && !row.dataset.title.toLowerCase().includes(needle);
      });
    });
  }

  // ---- Reorder (pointer drag on the grip, or arrow keys on it) ----------------
  function renumber() {
    refreshRows();
    if (current) setNowPlaying(current);
    syncQueue();
  }

  async function saveOrder() {
    try {
      await window.ratonApi("PUT", `/api/playlists/${playlistId}/order`, {
        item_ids: rows().map((row) => Number(row.dataset.itemId)),
      });
    } catch {
      // 409: the list changed elsewhere since this page loaded; any other failure, same remedy.
      window.location.reload();
    }
  }

  // Drag starts from the grip (mouse, pen, touch) or, on touch screens, from a
  // press-and-hold anywhere on the row (the grip is hidden on a phone).
  const LONG_PRESS_MS = 450;
  const LONG_PRESS_SLOP = 8;
  let suppressClick = false;
  let dragging = false;

  // A non-passive touchmove is the only way to stop iOS from scrolling the page
  // once the drag has begun.
  list.addEventListener("touchmove", (event) => {
    if (dragging && event.cancelable) event.preventDefault();
  }, { passive: false });
  list.addEventListener("contextmenu", (event) => {
    if (event.target.closest("[data-row]") && window.matchMedia("(pointer: coarse)").matches) event.preventDefault();
  });

  list.addEventListener("pointerdown", (event) => {
    const grip = event.target.closest("[data-grip]");
    if (grip && !(event.pointerType === "mouse" && event.button !== 0)) {
      event.preventDefault();
      startDrag(grip.closest("[data-row]"), event);
      return;
    }
    const row = event.target.closest("[data-row]");
    // Only the first finger can start a press: a second one must not start another drag.
    if (!row || event.pointerType === "mouse" || !event.isPrimary || dragging || row.classList.contains("is-confirming")) return;
    if (event.target.closest("button:not([data-play-row]), form, summary, input")) return;
    const startX = event.clientX;
    const startY = event.clientY;
    const timer = window.setTimeout(() => {
      cleanup();
      if (navigator.vibrate) navigator.vibrate(12);
      suppressClick = true;
      startDrag(row, event);
    }, LONG_PRESS_MS);
    const onMove = (moveEvent) => {
      if (moveEvent.pointerId !== event.pointerId) return;
      if (Math.hypot(moveEvent.clientX - startX, moveEvent.clientY - startY) > LONG_PRESS_SLOP) cleanup();
    };
    const onRelease = (releaseEvent) => {
      if (releaseEvent.pointerId === event.pointerId) cleanup();
    };
    const cleanup = () => {
      window.clearTimeout(timer);
      document.removeEventListener("pointermove", onMove);
      document.removeEventListener("pointerup", onRelease);
      document.removeEventListener("pointercancel", onRelease);
    };
    document.addEventListener("pointermove", onMove);
    document.addEventListener("pointerup", onRelease);
    document.addEventListener("pointercancel", onRelease);
  });

  function startDrag(row, event) {
    if (dragging) return;
    dragging = true;
    const before = rows().map((r) => r.dataset.itemId).join(",");
    row.classList.add("is-dragging");

    // Listeners live on the document, not on the grip: moving the row in the
    // DOM releases any pointer capture held by an element inside it.
    const onMove = (moveEvent) => {
      if (moveEvent.pointerId !== event.pointerId) return;
      const target = document.elementFromPoint(moveEvent.clientX, moveEvent.clientY);
      const over = target && target.closest("[data-row]");
      if (over && over !== row && list.contains(over)) {
        const box = over.getBoundingClientRect();
        list.insertBefore(row, moveEvent.clientY > box.top + box.height / 2 ? over.nextSibling : over);
      }
      if (moveEvent.clientY < 70) window.scrollBy(0, -14);
      else if (moveEvent.clientY > window.innerHeight - 70) window.scrollBy(0, 14);
    };
    const onEnd = (endEvent) => {
      if (endEvent.pointerId !== event.pointerId) return;
      document.removeEventListener("pointermove", onMove);
      document.removeEventListener("pointerup", onEnd);
      document.removeEventListener("pointercancel", onEnd);
      row.classList.remove("is-dragging");
      dragging = false;
      // The click that follows a long-press release is synthesized after pointerup (on iOS
      // after touchend, in a later task): a 0 ms timer can run before it.
      window.setTimeout(() => { suppressClick = false; }, 400);
      renumber();
      if (rows().map((r) => r.dataset.itemId).join(",") !== before) saveOrder();
    };
    document.addEventListener("pointermove", onMove);
    document.addEventListener("pointerup", onEnd);
    document.addEventListener("pointercancel", onEnd);
  }

  // Shared by the grip's arrow keys and the "Monter"/"Descendre" entries of the phone menu
  // (the grip is hidden there). Returns false when the row is already at that end.
  function moveRow(row, direction) {
    const sibling = direction < 0 ? row.previousElementSibling : row.nextElementSibling;
    if (!sibling || !sibling.matches("[data-row]")) return false;
    list.insertBefore(row, direction < 0 ? sibling : sibling.nextSibling);
    renumber();
    saveOrder();
    return true;
  }

  list.addEventListener("keydown", (event) => {
    const grip = event.target.closest("[data-grip]");
    if (!grip || (event.key !== "ArrowUp" && event.key !== "ArrowDown")) return;
    event.preventDefault();
    if (moveRow(grip.closest("[data-row]"), event.key === "ArrowUp" ? -1 : 1)) grip.focus();
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      root.querySelectorAll("details.pl-menu[open]").forEach((menu) => { menu.open = false; });
    }
  });
  if (!window.__plMenuCloser) {
    window.__plMenuCloser = true;
    document.addEventListener("click", (event) => {
      document.querySelectorAll("details.pl-menu[open]").forEach((menu) => {
        if (!menu.contains(event.target)) menu.open = false;
      });
    });
  }

  // ---- Mini player (Audio mode) ----------------------------------------------------
  // Mirrors the mini player while it plays this playlist: current row, seek
  // bar, play/pause. Its <audio> outlives this page (Turbo permanent node), so
  // the listeners go once the page has been swapped out.
  function followMini() {
    const audio = miniAudio();
    if (!audio) return;
    const events = ["play", "pause", "ended", "emptied", "timeupdate", "loadedmetadata", "progress", "raton:queue-change"];
    const sync = () => {
      if (!root.isConnected) {
        events.forEach((name) => audio.removeEventListener(name, sync));
        return;
      }
      if (viaMini()) mirrorMini();
    };
    events.forEach((name) => audio.addEventListener(name, sync));
    sync();
  }

  function mirrorMini() {
    const audio = miniAudio();
    if (ownsMini()) {
      const row = rows().find((candidate) => candidate.dataset.videoId === mini().currentId()) || null;
      if (row && row !== current) {
        current = row;
        setNowPlaying(row);
        refreshRows();
      }
      showProgress(audio);
      // Same 90% rule as the server, so the ✓ shows without a reload.
      if (current && !isFree() && !flag(current, "seen") && audio.duration > 0 && audio.currentTime / audio.duration >= 0.9) {
        current.dataset.seen = "1";
        refreshRows();
      }
    }
    updatePlayIcon();
  }

  // ---- Boot -----------------------------------------------------------------------
  applyMode();
  syncToggles();
  function boot() {
    if (viaMini() && ownsMini()) {
      // Back on the playlist that is playing: show its track, not the first one.
      syncQueue();
    } else {
      const first = eligibleRows()[0] || null;
      if (first) shuffleSeen.add(first);
      load(first, false);
    }
    followMini();
  }
  // On a full page load app.js (the mini player) runs after this script.
  if (window.ratonMiniPlayer) boot();
  else document.addEventListener("DOMContentLoaded", boot, { once: true });
})();
