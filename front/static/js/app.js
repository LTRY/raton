// Turbo Drive (see base.html) re-executes this file's <script> tag on every
// visit, so top-level `const`/`let` must live inside this closure — otherwise
// the second visit to any page throws "Identifier has already been declared".
(function () {

// Calls to the JSON API (/api): the body goes as JSON, and an error answer's `detail` (a French
// message, see docs/spec/12-api-et-routes.md) becomes the thrown Error's message, its HTTP code
// the Error's `status`.
async function apiRequest(method, url, body, { keepalive = false } = {}) {
  const options = { method, headers: { Accept: "application/json" }, keepalive };
  if (body instanceof FormData) {
    options.body = body; // A form with a file goes as multipart.
  } else if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  const response = await fetch(url, options);
  const payload = response.status === 204 ? null : await response.json().catch(() => null);
  if (!response.ok) {
    const error = new Error(payload?.detail || `HTTP ${response.status}`);
    error.status = response.status;
    throw error;
  }
  return payload;
}
window.ratonApi = apiRequest;

// Polls a job's `status_url` (/api/jobs/{id}) until it is done; a failed job throws its message.
async function waitForJob(statusUrl, { interval = 2000, onProgress, failure = "Le traitement a échoué." } = {}) {
  for (;;) {
    const job = await apiRequest("GET", statusUrl);
    onProgress?.(job);
    if (job.status === "failed") throw new Error(job.message || failure);
    if (job.done) return job;
    await new Promise((resolve) => window.setTimeout(resolve, interval));
  }
}
window.ratonWaitForJob = waitForJob;

// The JSON body of a form's /api twin, named by its `data-api-body`; without one the form goes
// as multipart (it carries a file). The form's own field names serve its no-JS fallback.
function splitLabels(text) {
  return (text || "")
    .split(/[,\n]/)
    .map((label) => label.trim())
    .filter(Boolean);
}
const API_BODIES = {
  manualDownload: (data) => ({
    url: data.get("url"),
    media_types: data.getAll("media_type"),
    download_transcript: data.get("download_transcript") === "true",
    video_quality: data.get("video_quality") || "1080",
    categories: [...data.getAll("preset_categories"), ...splitLabels(data.get("custom_categories"))],
  }),
  mediaDownload: (data) => ({ video_quality: data.get("video_quality") || "1080" }),
  channelImport: (data) => ({
    page: Number.parseInt(data.get("page"), 10) || 1,
    section: data.get("section") || "videos",
  }),
  playlistUrl: (data) => ({ url: data.get("url"), title: data.get("title") || "" }),
};
function apiFormBody(form) {
  const data = new FormData(form);
  const build = API_BODIES[form.dataset.apiBody];
  return build ? build(data) : data;
}

// A player's report to POST /api/videos/{id}/activity; it must never interrupt playback.
function reportPlayback(url, mediaType, media, watchedSeconds) {
  const seconds = (value) => (Number.isFinite(value) ? value : 0);
  apiRequest(
    "POST",
    url,
    {
      media_type: mediaType,
      position_seconds: seconds(media.currentTime),
      duration_seconds: seconds(media.duration),
      watched_seconds: Math.round(watchedSeconds),
    },
    { keepalive: true },
  ).catch(() => {});
}
window.ratonReportPlayback = reportPlayback;

function setAsyncFormState(form, message, level) {
  let status = form.querySelector(".async-form-status");
  if (!status) {
    status = document.createElement("p");
    status.className = "async-form-status";
    status.setAttribute("aria-live", "polite");
    form.append(status);
  }
  status.textContent = message;
  status.dataset.level = level;
}

function setAsyncFormDisabled(form, disabled) {
  form.querySelectorAll("button, input, select").forEach((control) => {
    control.disabled = disabled;
  });
}

function redirectWithMessage(path, level, message) {
  const url = new URL(path, window.location.origin);
  url.searchParams.set("level", level);
  url.searchParams.set("message", message);
  window.location.assign(url.pathname + url.search + url.hash);
}

const mobileViewport = window.matchMedia("(max-width: 800px)");

document.querySelectorAll("details[data-mobile-collapsible]").forEach((details) => {
  details.open = false;
});

function filterScrollStorageKey(pathname = window.location.pathname) {
  return `raton:auto-filter-scroll:${pathname}`;
}

function restoreFilterScrollPosition() {
  let value = null;
  try {
    const key = filterScrollStorageKey();
    value = window.sessionStorage.getItem(key);
    window.sessionStorage.removeItem(key);
  } catch {
    return;
  }
  const position = Number.parseInt(value || "", 10);
  if (!Number.isFinite(position)) return;
  window.requestAnimationFrame(() => {
    window.scrollTo({ top: position, left: 0, behavior: "auto" });
  });
}

async function pollAsyncJob(form, statusUrl, returnTo) {
  const job = await waitForJob(statusUrl, {
    onProgress: (current) => setAsyncFormState(form, current.message || "Traitement en cours...", "loading"),
  });
  redirectWithMessage(returnTo, "success", job.message || "Traitement terminé.");
}

function bindAsyncJobForm(form) {
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    // Read before disabling: a disabled field is left out of FormData.
    const next = new FormData(form).get("next");
    const body = apiFormBody(form);
    setAsyncFormDisabled(form, true);
    setAsyncFormState(form, form.dataset.pendingMessage || "Traitement en file d'attente...", "loading");

    try {
      const payload = await apiRequest("POST", form.dataset.apiAction, body);
      // A playlist import answers {playlist, job}; the other imports answer the job itself.
      const job = payload.job || payload;
      const returnTo = payload.playlist ? `/playlists/${payload.playlist.id}` : next || window.location.pathname;
      setAsyncFormState(form, job.message || "Traitement lancé.", "loading");
      await pollAsyncJob(form, job.status_url, returnTo);
    } catch (error) {
      setAsyncFormDisabled(form, false);
      setAsyncFormState(form, error.message, "error");
    }
  });
}

document.querySelectorAll("form[data-async-download], form[data-async-job]").forEach(bindAsyncJobForm);

// Local file import: the drop (or the file picker) starts the upload at once, with a progress bar.
document.querySelectorAll("form[data-local-upload]").forEach((form) => {
  const zone = form.querySelector("[data-dropzone]");
  const input = form.querySelector("input[type=file]");
  const hint = form.querySelector("[data-dropzone-hint]");
  const progress = form.querySelector("[data-dropzone-progress]");

  function fail(message) {
    zone.classList.remove("is-uploading");
    progress.hidden = true;
    hint.textContent = message;
    zone.dataset.level = "error";
  }

  function upload(file) {
    const data = new FormData();
    data.append("file", file);
    zone.classList.add("is-uploading");
    zone.dataset.level = "";
    progress.hidden = false;
    progress.value = 0;
    hint.textContent = `Envoi de ${file.name}...`;
    // XMLHttpRequest rather than apiRequest: it reports the upload's progress.
    const request = new XMLHttpRequest();
    request.open("POST", form.dataset.apiAction);
    request.setRequestHeader("Accept", "application/json");
    request.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable) progress.value = (event.loaded / event.total) * 100;
    });
    request.addEventListener("error", () => fail("L'envoi a échoué."));
    request.addEventListener("load", () => {
      let payload = {};
      try {
        payload = JSON.parse(request.responseText);
      } catch {
        // Falls through to the generic error below.
      }
      if (request.status >= 200 && request.status < 300 && payload.video_id) {
        const message = payload.created ? "Fichier importé." : "Ce fichier est déjà dans la bibliothèque.";
        redirectWithMessage(`/videos/${payload.video_id}`, "success", message);
      } else {
        fail(payload.detail || "L'envoi a échoué.");
      }
    });
    request.send(data);
  }

  input.addEventListener("change", () => {
    if (input.files.length) upload(input.files[0]);
  });
  ["dragenter", "dragover"].forEach((name) =>
    zone.addEventListener(name, (event) => {
      event.preventDefault();
      zone.classList.add("is-dragover");
    })
  );
  ["dragleave", "drop"].forEach((name) =>
    zone.addEventListener(name, () => zone.classList.remove("is-dragover"))
  );
  zone.addEventListener("drop", (event) => {
    event.preventDefault();
    const file = event.dataTransfer && event.dataTransfer.files[0];
    if (file) upload(file);
  });
});
// form[data-explore] has its own binder (initExplorer), it is not an async-job form.

restoreFilterScrollPosition();

document.querySelectorAll("form[data-auto-submit-filter]").forEach((form) => {
  form.addEventListener("submit", () => {
    try {
      const target = new URL(form.getAttribute("action") || window.location.href, window.location.origin);
      window.sessionStorage.setItem(filterScrollStorageKey(target.pathname), String(window.scrollY));
    } catch {
      return;
    }
  });
  form.querySelectorAll("input, select").forEach((control) => {
    if (control.type === "hidden") return;
    // A live search field already refreshed the results while typing; its
    // `change` fires on blur, and a full submit there would race the click
    // that caused the blur (e.g. on a result link).
    if (control.type === "search" && form.dataset.liveSearch) return;
    control.addEventListener("change", () => {
      form.requestSubmit();
    });
  });
});

// Live search: typing reloads only the results <turbo-frame> named by
// `data-live-search`, so the field keeps focus and caret. Enter still does a
// regular full submit.
document.querySelectorAll("form[data-live-search]").forEach((form) => {
  const input = form.querySelector('input[type="search"]');
  const frame = document.getElementById(form.dataset.liveSearch);
  if (!input || !frame) return;
  let timer = null;
  let lastQuery = input.value.trim();
  form.addEventListener("submit", () => window.clearTimeout(timer));
  input.addEventListener("input", () => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => {
      const query = input.value.trim();
      if (query === lastQuery) return;
      lastQuery = query;
      const url = new URL(form.getAttribute("action") || window.location.href, window.location.origin);
      url.search = new URLSearchParams(new FormData(form)).toString();
      const target = url.pathname + url.search;
      frame.src = target;
      // Keep the address bar in sync so a reload or a card's `next` return
      // path lands on the same search.
      window.history.replaceState(window.history.state, "", target);
    }, 200);
  });
});

document.querySelectorAll("[data-chip3]").forEach((button) => {
  const wrap = button.closest(".chip3-wrap");
  if (!wrap) return;
  const [includeInput, excludeInput] = wrap.querySelectorAll(".chip3-input");
  if (!includeInput || !excludeInput) return;

  button.addEventListener("click", () => {
    const nextState =
      button.dataset.state === "neutral" ? "include" : button.dataset.state === "include" ? "exclude" : "neutral";
    includeInput.checked = nextState === "include";
    excludeInput.checked = nextState === "exclude";
    button.dataset.state = nextState;
    button.setAttribute("aria-pressed", nextState === "neutral" ? "false" : "true");
    const icon = button.querySelector(".chip3-ic");
    if (icon) icon.textContent = nextState === "include" ? "✓" : nextState === "exclude" ? "✕" : "";
    const form = button.closest("form");
    if (form) form.requestSubmit();
  });
});

// Position de reprise. Elle vit à deux endroits : le `localStorage` (écrit
// toutes les 5 s, donc précis même si l'onglet est tué) et le serveur (journal
// d'activité, écrit à la pause et à la sortie de page). Le `localStorage` seul
// ne suffit pas : il est propre à chaque appareil, et Safari iOS le purge après
// 7 jours sans visite. La clé `<clé>:at` horodate la copie locale pour pouvoir
// la départager de celle du serveur — la plus récente gagne.
const RESUME_MINIMUM_SECONDS = 3;
const RESUME_END_BUFFER_SECONDS = 5;

function readStoredResume(storageKey) {
  try {
    const position = Number.parseFloat(window.localStorage.getItem(storageKey) || "");
    if (!Number.isFinite(position)) return null;
    const at = Number.parseFloat(window.localStorage.getItem(`${storageKey}:at`) || "");
    return { position, at: Number.isFinite(at) ? at : 0 };
  } catch {
    return null;
  }
}

function writeStoredResume(storageKey, position) {
  try {
    window.localStorage.setItem(storageKey, position.toString());
    window.localStorage.setItem(`${storageKey}:at`, Date.now().toString());
  } catch {
    // Playback should continue even when storage is unavailable.
  }
}

// Fin de lecture : on écrit 0 horodaté plutôt que de supprimer la clé, sinon
// une position serveur plus ancienne reprendrait la main au prochain chargement.
function resetStoredResume(storageKey) {
  writeStoredResume(storageKey, 0);
}

function resolveResumePosition(storageKey, serverPosition, serverAt) {
  const local = storageKey ? readStoredResume(storageKey) : null;
  const remotePosition = Number.parseFloat(serverPosition || "");
  const remoteAt = Number.parseFloat(serverAt || "");
  if (Number.isFinite(remotePosition) && Number.isFinite(remoteAt) && (!local || remoteAt > local.at)) {
    return remotePosition;
  }
  return local ? local.position : null;
}

function bindResumableMedia(media) {
  const storageKey = media.dataset.resumeKey;
  if (!storageKey) return;

  const saveIntervalSeconds = 5;
  const minimumResumeSeconds = RESUME_MINIMUM_SECONDS;
  const endBufferSeconds = RESUME_END_BUFFER_SECONDS;
  let lastSavedAt = 0;
  let watchedSeconds = 0;
  let lastTrackedTime = null;
  // Position de reprise tant qu'elle n'est pas confirmée par une lecture
  // effective : Safari iOS peut ignorer un `currentTime` posé avant que le média
  // soit jouable, il faut donc pouvoir le reposer.
  let pendingResume = null;

  function writePosition() {
    if (pendingResume !== null) return;
    if (!Number.isFinite(media.currentTime) || media.currentTime < minimumResumeSeconds) return;
    writeStoredResume(storageKey, media.currentTime);
    lastSavedAt = media.currentTime;
  }

  function clearPosition() {
    resetStoredResume(storageKey);
  }

  function seekToPendingResume() {
    if (pendingResume === null || Math.abs(media.currentTime - pendingResume) < 1) return;
    // Reprise automatique : ce n'est pas un rembobinage utilisateur, le segment
    // qui contient la position doit rester armé.
    media.sponsorSkipController?.markInternalSeek();
    media.currentTime = pendingResume;
    lastSavedAt = pendingResume;
  }

  function applyResume() {
    const position = resolveResumePosition(
      storageKey,
      media.dataset.resumeServerPosition,
      media.dataset.resumeServerAt
    );
    if (position === null || position < minimumResumeSeconds) return;
    if (Number.isFinite(media.duration) && position > media.duration - endBufferSeconds) {
      clearPosition();
      return;
    }
    pendingResume = position;
    seekToPendingResume();
  }

  // app.js est chargé en fin de <body> : les métadonnées peuvent déjà être là
  // (cache, réseau local rapide) et `loadedmetadata` ne se redéclenchera pas.
  if (media.readyState >= 1) applyResume();
  else media.addEventListener("loadedmetadata", applyResume, { once: true });

  function retryResumeIfStillAtStart() {
    if (pendingResume !== null && media.currentTime < minimumResumeSeconds) seekToPendingResume();
  }
  media.addEventListener("canplay", retryResumeIfStillAtStart);
  media.addEventListener("play", retryResumeIfStillAtStart);

  // Clic sur un timestamp (transcript, segment) : même à 0:00, c'est un choix
  // explicite qui annule la reprise.
  media.addEventListener("raton:user-seek", () => {
    pendingResume = null;
  });

  media.addEventListener("seeking", () => {
    // Un seek ailleurs qu'au début et ailleurs qu'à la position de reprise est
    // un geste de l'utilisateur : la reprise n'a plus à s'imposer.
    if (pendingResume === null) return;
    if (media.currentTime >= minimumResumeSeconds && Math.abs(media.currentTime - pendingResume) >= 1) {
      pendingResume = null;
    }
  });

  media.addEventListener("timeupdate", () => {
    if (pendingResume !== null) {
      if (media.paused || media.seeking) return;
      if (media.currentTime < minimumResumeSeconds) {
        // La lecture a démarré à 0 : le seek de reprise a été ignoré.
        seekToPendingResume();
        return;
      }
      pendingResume = null;
    }
    trackWatchedTime();
    if (Math.abs(media.currentTime - lastSavedAt) >= saveIntervalSeconds) {
      writePosition();
    }
  });

  function trackWatchedTime(force = false) {
    if ((!force && media.paused) || media.seeking || !Number.isFinite(media.currentTime)) {
      lastTrackedTime = Number.isFinite(media.currentTime) ? media.currentTime : null;
      return;
    }
    if (lastTrackedTime !== null) {
      const delta = media.currentTime - lastTrackedTime;
      if (delta > 0 && delta < 5) {
        watchedSeconds += delta;
      }
    }
    lastTrackedTime = media.currentTime;
  }

  function logActivity() {
    trackWatchedTime(true);
    if (!media.dataset.activityUrl || watchedSeconds < 1) return;
    reportPlayback(media.dataset.activityUrl, media.dataset.mediaKind || "video", media, watchedSeconds);
    watchedSeconds = 0;
  }

  media.addEventListener("play", () => {
    lastTrackedTime = Number.isFinite(media.currentTime) ? media.currentTime : null;
  });

  media.addEventListener("pause", () => {
    writePosition();
    logActivity();
  });
  media.addEventListener("ended", () => {
    clearPosition();
    logActivity();
  });
  // `media` is torn down when Turbo swaps in the next page's body, so these
  // must be one-shot: without { once: true } every past page's media element
  // would keep a dangling "leave" listener attached to window/document for
  // the rest of the session (Turbo navigation never fires a real pagehide).
  function handleLeave() {
    writePosition();
    logActivity();
  }
  window.addEventListener("pagehide", handleLeave, { once: true });
  document.addEventListener("turbo:before-cache", handleLeave, { once: true });
}

document.querySelectorAll("[data-resumable-media]").forEach(bindResumableMedia);

document.querySelectorAll("[data-seek-time]").forEach((trigger) => {
  trigger.addEventListener("click", () => {
    const seconds = Number.parseFloat(trigger.dataset.seekTime);
    if (!Number.isFinite(seconds)) return;
    // A segment tapped in the phone popover would leave it covering the player.
    trigger.closest("details[data-pop]")?.removeAttribute("open");

    const media = document.querySelector("[data-resumable-media]");
    if (media) {
      media.dispatchEvent(new CustomEvent("raton:user-seek"));
      media.currentTime = seconds;
      media.play().catch(() => {});
      return;
    }

    // Audio-only videos have no inline [data-resumable-media] element — the
    // track plays through the persistent mini-player instead (see
    // initMiniPlayer/bindPlayTrackButtons below, and the audio element at
    // base.html's [data-mini-player-audio]). Fall back to that player: load
    // this page's track into it first (via its [data-play-track] trigger)
    // if it isn't already the one playing, then seek once ready.
    const miniAudio = document.querySelector("[data-mini-player-audio]");
    const playTrigger = document.querySelector("[data-play-track]");
    if (!miniAudio || !playTrigger) return;

    if (miniAudio.dataset.trackId === String(playTrigger.dataset.trackId)) {
      miniAudio.dispatchEvent(new CustomEvent("raton:user-seek"));
      miniAudio.currentTime = seconds;
      miniAudio.play().catch(() => {});
      return;
    }

    miniAudio.addEventListener(
      "loadedmetadata",
      () => {
        miniAudio.dispatchEvent(new CustomEvent("raton:user-seek"));
        miniAudio.currentTime = seconds;
      },
      { once: true }
    );
    playTrigger.click();
  });
});

// Saut automatique des segments sponsors. Les segments arrivent déjà triés,
// fusionnés et filtrés par normalize_skip_segments (app/services/sponsor_segments.py) :
// ce moteur ne fait que comparer des bornes.
const SPONSOR_FADE_MS = 250;
const SPONSOR_SEEK_TIMEOUT_MS = 2000;

function rampVolume(media, from, to, durationMs) {
  return new Promise((resolve) => {
    // requestAnimationFrame est suspendu tant que l'onglet est masqué, alors que
    // le média continue de jouer — et le mini-lecteur sert précisément à écouter
    // en arrière-plan. Un fondu laissé en attente y bloquerait le volume à
    // mi-course et le moteur avec lui, jusqu'au retour de l'utilisateur. Dès que
    // l'onglet est masqué, à l'entrée comme en cours de fondu, on applique donc
    // la valeur cible d'un coup : l'onglet masqué rend le fondu impossible, pas
    // inutile — c'est justement là que l'utilisateur écoute.
    let settled = false;

    function finish() {
      if (settled) return;
      settled = true;
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      media.volume = to;
      resolve();
    }

    function handleVisibilityChange() {
      if (document.hidden) finish();
    }

    if (document.hidden) {
      finish();
      return;
    }
    document.addEventListener("visibilitychange", handleVisibilityChange);

    const start = performance.now();
    function step(now) {
      if (settled) return;
      const ratio = Math.min((now - start) / durationMs, 1);
      if (ratio < 1) {
        media.volume = from + (to - from) * ratio;
        window.requestAnimationFrame(step);
      } else {
        finish();
      }
    }
    window.requestAnimationFrame(step);
  });
}

function bindSponsorSkip(media, { visual = false } = {}) {
  // Le mini-lecteur est permanent et change de piste sans être recréé : les
  // écouteurs sont posés une seule fois, et setSegments réarme le contrôleur.
  if (media.sponsorSkipController) return media.sponsorSkipController;

  let segments = [];
  const disarmed = new Set();
  let skipping = false;
  let internalSeek = false;

  function segmentIndexAt(time) {
    return segments.findIndex((segment) => time >= segment.start && time < segment.end);
  }

  function runSkip(index) {
    const segment = segments[index];
    // Un segment qui va jusqu'au bout du média est sauté comme les autres : la
    // lecture atteint sa fin naturelle et l'`ended` qui suit est légitime (la
    // vidéo est bel et bien terminée, la position enregistrée doit être vidée).
    // Le refuser reviendrait à laisser passer un sponsor entier dès qu'un outro
    // le prolonge jusqu'à la fin — normalize_skip_segments fusionne les deux en
    // un seul bloc, et c'est tout le bloc qui cessait alors d'être sauté.
    skipping = true;
    const targetVolume = media.volume;
    if (visual) media.classList.add("sponsor-skip-fading");

    rampVolume(media, targetVolume, 0, SPONSOR_FADE_MS).then(() => {
      // Le fondu sortant a duré au moins 250 ms, et bien plus si l'onglet a été
      // masqué. Entre-temps l'utilisateur a pu chercher ailleurs (scrubber, ±30 s,
      // timestamp de transcription), changer de piste dans le mini-lecteur, ou
      // simplement écouter le segment en entier. Sans cette revalidation le seek
      // différé ci-dessous écraserait son action — voire, après un changement de
      // piste, ferait démarrer la nouvelle piste à la fin d'un segment de
      // l'ancienne. On revérifie donc exactement la condition d'admission de
      // `timeupdate`, plus l'identité du segment (setSegments a pu remplacer le
      // tableau sous le même index).
      const stillInSegment =
        segments[index] === segment && segmentIndexAt(media.currentTime) === index && !disarmed.has(index);
      if (!stillInSegment) {
        // Restauration directe et non par un second fondu : rien ne garantit que
        // l'onglet soit redevenu visible, et on ne veut pas rouvrir l'attente.
        if (visual) media.classList.remove("sponsor-skip-fading");
        media.volume = targetVolume;
        skipping = false;
        return;
      }

      let settled = false;

      function restore(fade) {
        if (settled) return;
        settled = true;
        window.clearTimeout(guard);
        if (visual) media.classList.remove("sponsor-skip-fading");
        if (!fade) {
          media.volume = targetVolume;
          skipping = false;
          return;
        }
        rampVolume(media, media.volume, targetVolume, SPONSOR_FADE_MS).then(() => {
          skipping = false;
        });
      }

      // Le fondu entrant attend `seeked`, pas un timer : sur un média mal
      // bufferisé, un délai fixe rendrait le son à plein volume sur une image
      // encore figée. Le garde-fou évite de rester muet si `seeked` ne vient
      // jamais (fichier corrompu, coupure réseau).
      const guard = window.setTimeout(() => restore(false), SPONSOR_SEEK_TIMEOUT_MS);
      media.addEventListener("seeked", () => restore(true), { once: true });

      internalSeek = true;
      media.currentTime = segment.end;
    });
  }

  media.addEventListener("timeupdate", () => {
    if (skipping || media.seeking || segments.length === 0) return;
    const index = segmentIndexAt(media.currentTime);
    if (index !== -1 && !disarmed.has(index)) runSkip(index);
  });

  media.addEventListener("seeking", () => {
    // Notre propre seek : consommé ici, pas un rembobinage utilisateur.
    if (internalSeek) {
      internalSeek = false;
      return;
    }
    // Sans bandeau « Annuler », c'est ce désarmement qui évite le piège : sinon
    // rembobiner dans un segment le ferait resauter en boucle.
    const index = segmentIndexAt(media.currentTime);
    if (index !== -1) disarmed.add(index);
  });

  const controller = {
    setSegments(list) {
      segments = Array.isArray(list) ? list : [];
      disarmed.clear();
    },
    // À appeler juste avant un `currentTime = …` posé par l'application (reprise
    // de la position enregistrée, par exemple) : sans ça le `seeking` qui suit
    // passerait pour un rembobinage utilisateur et désarmerait le segment
    // d'atterrissage, alors que le désarmement doit rester un geste délibéré.
    markInternalSeek() {
      internalSeek = true;
    },
  };
  media.sponsorSkipController = controller;
  return controller;
}

function initSponsorSkip() {
  const payloadElement = document.querySelector("script[data-sponsor-skip]");
  if (!payloadElement) return;
  let payload;
  try {
    payload = JSON.parse(payloadElement.textContent || "{}");
  } catch {
    return;
  }
  if (!payload.enabled || !Array.isArray(payload.segments) || payload.segments.length === 0) return;
  document.querySelectorAll("[data-resumable-media]").forEach((media) => {
    bindSponsorSkip(media, { visual: media.tagName === "VIDEO" }).setSegments(payload.segments);
  });
}

initSponsorSkip();

document.querySelectorAll("form[data-download-format-form]").forEach((form) => {
  const mediaFormats = Array.from(form.querySelectorAll("[data-media-format]"));
  const videoFormat = form.querySelector('[data-media-format][value="video"]');
  const qualityField = form.querySelector("[data-video-quality]");
  const hint = form.querySelector("[data-formats-hint]");
  // The server-rendered text is the "nothing ticked" message.
  const hintNone = hint ? hint.textContent : "";

  // The metadata and the transcript are posted as hidden fields: only the
  // audio/video tiles are a choice, and neither is required.
  function syncFormats() {
    if (qualityField && videoFormat) {
      qualityField.hidden = !videoFormat.checked;
    }
    if (hint) {
      hint.textContent = mediaFormats.some((input) => input.checked)
        ? hint.dataset.hintFiles
        : hintNone;
    }
  }

  mediaFormats.forEach((input) => {
    input.addEventListener("change", syncFormats);
  });

  syncFormats();
});

function normalizeCategoryLabel(label) {
  return label.trim().toLowerCase().replace(/\s+/g, " ");
}

function normalizeCategoryColor(color, fallback = "#16a34a") {
  return /^#[0-9a-f]{6}$/i.test(color || "") ? color.toLowerCase() : fallback;
}

function contrastTextColor(color) {
  const normalized = normalizeCategoryColor(color);
  const red = Number.parseInt(normalized.slice(1, 3), 16);
  const green = Number.parseInt(normalized.slice(3, 5), 16);
  const blue = Number.parseInt(normalized.slice(5, 7), 16);
  const brightness = (red * 299 + green * 587 + blue * 114) / 1000;
  return brightness > 150 ? "#0f172a" : "#ffffff";
}

function bindCategoryLabelEditor(editor) {
  const source = editor.querySelector("[data-category-source]");
  const list = editor.querySelector("[data-category-list]");
  const input = editor.querySelector("[data-category-input]");
  const newColor = editor.querySelector("[data-category-new-color]");
  const addButton = editor.querySelector("[data-category-add]");
  const count = editor.querySelector("[data-category-count]");
  if (!source || !list || !input || !addButton) return;

  function readInitialLabels() {
    try {
      const parsed = JSON.parse(editor.dataset.initialLabels || "[]");
      if (Array.isArray(parsed)) return parsed;
    } catch {
      // Fall back to the textarea value below.
    }
    return source.value.split(/[\n,]/);
  }

  let labels = [];

  function normalizeLabelItem(item, fallbackColor = "#16a34a") {
    if (typeof item === "string") {
      return { label: normalizeCategoryLabel(item), color: normalizeCategoryColor(fallbackColor) };
    }
    if (item && typeof item === "object") {
      return {
        label: normalizeCategoryLabel(String(item.label || "")),
        color: normalizeCategoryColor(item.color, fallbackColor),
      };
    }
    return { label: "", color: normalizeCategoryColor(fallbackColor) };
  }

  function setLabels(nextLabels) {
    labels = [];
    nextLabels.forEach((item) => {
      const normalized = normalizeLabelItem(item, newColor ? newColor.value : "#16a34a");
      if (normalized.label && !labels.some((existing) => existing.label === normalized.label)) {
        labels.push(normalized);
      }
    });
    render();
  }

  function render() {
    list.replaceChildren();
    labels.forEach((item, index) => {
      const chip = document.createElement("span");
      chip.className = "settings-category-chip";
      chip.style.setProperty("--category-bg", item.color);
      chip.style.setProperty("--category-border", item.color);
      chip.style.setProperty("--category-text", contrastTextColor(item.color));

      const text = document.createElement("span");
      text.textContent = item.label;

      const color = document.createElement("input");
      color.type = "color";
      color.className = "settings-category-chip-color";
      color.value = item.color;
      color.setAttribute("aria-label", `Couleur ${item.label}`);
      color.addEventListener("input", () => {
        labels[index].color = normalizeCategoryColor(color.value, labels[index].color);
        render();
      });

      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "settings-category-remove";
      remove.setAttribute("aria-label", `Supprimer ${item.label}`);
      remove.textContent = "×";
      remove.addEventListener("click", () => {
        labels.splice(index, 1);
        render();
        input.focus();
      });

      chip.append(color, text, remove);
      list.append(chip);
    });
    source.value = JSON.stringify(labels);
    if (count) {
      count.textContent = `${labels.length} label${labels.length > 1 ? "s" : ""}`;
    }
  }

  function addFromInput() {
    const chunks = input.value.split(",");
    const color = newColor ? newColor.value : "#16a34a";
    setLabels([...labels, ...chunks.map((label) => ({ label, color }))]);
    input.value = "";
    input.focus();
  }

  addButton.addEventListener("click", addFromInput);
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      addFromInput();
    }
    if (event.key === "," && input.value.trim()) {
      event.preventDefault();
      addFromInput();
    }
  });

  setLabels(readInitialLabels());
}

document.querySelectorAll("[data-category-label-editor]").forEach(bindCategoryLabelEditor);

function bindLibraryViewEditor(editor) {
  const source = editor.querySelector("[data-library-view-source]");
  const list = editor.querySelector("[data-library-view-list]");
  const addButton = editor.querySelector("[data-library-view-add]");
  const count = editor.querySelector("[data-library-view-count]");
  if (!source || !list || !addButton) return;

  function readJsonAttribute(name, fallback) {
    try {
      const parsed = JSON.parse(editor.dataset[name] || "null");
      return Array.isArray(parsed) ? parsed : fallback;
    } catch {
      return fallback;
    }
  }

  const assetOptions = readJsonAttribute("assetOptions", []);
  const categoryOptions = readJsonAttribute("categoryOptions", []);
  let views = [];

  function normalizeMode(mode) {
    return ["or", "and"].includes(mode) ? mode : "or";
  }

  function normalizeView(view) {
    return {
      name: String(view && view.name ? view.name : "").trim(),
      asset_filter_mode: normalizeMode(view && view.asset_filter_mode),
      category_filter_mode: normalizeMode(view && view.category_filter_mode),
      assets: Array.isArray(view && view.assets) ? view.assets.map(String) : [],
      categories: Array.isArray(view && view.categories) ? view.categories.map(normalizeCategoryLabel).filter(Boolean) : [],
      excluded_assets: Array.isArray(view && view.excluded_assets) ? view.excluded_assets.map(String) : [],
      excluded_categories: Array.isArray(view && view.excluded_categories)
        ? view.excluded_categories.map(normalizeCategoryLabel).filter(Boolean)
        : [],
      rated: Boolean(view && view.rated),
    };
  }

  function checkedSet(values) {
    return new Set(Array.isArray(values) ? values : []);
  }

  function syncSource() {
    source.value = JSON.stringify(views);
    if (count) {
      count.textContent = `${views.length} sous-bibliothèque${views.length > 1 ? "s" : ""}`;
    }
  }

  function buildModeSelect(value, onChange) {
    const select = document.createElement("select");
    [
      ["or", "||"],
      ["and", "&&"],
    ].forEach(([mode, label]) => {
      const option = document.createElement("option");
      option.value = mode;
      option.textContent = label;
      option.selected = value === mode;
      select.append(option);
    });
    select.addEventListener("change", () => {
      onChange(select.value);
      syncSource();
    });
    return select;
  }

  function categoryStyleFromOption(option) {
    const color = normalizeCategoryColor(option && option.color);
    return `--category-bg: ${color}; --category-border: ${color}; --category-text: ${contrastTextColor(color)};`;
  }

  function buildCheckbox(name, checked, text, onChange, options = {}) {
    const label = document.createElement("label");
    label.className = "asset-filter-chip";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.name = name;
    input.checked = checked;
    input.addEventListener("change", () => {
      onChange(input.checked);
      syncSource();
    });
    const span = document.createElement("span");
    span.className = options.labelClassName || "asset-label";
    if (options.style) {
      span.setAttribute("style", options.style);
    }
    span.textContent = text;
    label.append(input, span);
    return label;
  }

  function render() {
    list.replaceChildren();
    views.forEach((view, index) => {
      const card = document.createElement("div");
      card.className = "settings-library-card";

      const header = document.createElement("div");
      header.className = "settings-library-card-header";
      const name = document.createElement("input");
      name.type = "text";
      name.value = view.name;
      name.placeholder = "Nom";
      name.addEventListener("input", () => {
        views[index].name = name.value.trim();
        syncSource();
      });
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "settings-category-remove";
      remove.setAttribute("aria-label", `Supprimer ${view.name || "la sous-bibliothèque"}`);
      remove.textContent = "×";
      remove.addEventListener("click", () => {
        views.splice(index, 1);
        render();
      });
      const positionControls = document.createElement("span");
      positionControls.className = "settings-library-position-controls";
      const moveUp = document.createElement("button");
      moveUp.type = "button";
      moveUp.className = "secondary";
      moveUp.setAttribute("aria-label", `Monter ${view.name || "la sous-bibliothèque"}`);
      moveUp.textContent = "↑";
      moveUp.disabled = index === 0;
      moveUp.addEventListener("click", () => {
        if (index === 0) return;
        [views[index - 1], views[index]] = [views[index], views[index - 1]];
        render();
      });
      const moveDown = document.createElement("button");
      moveDown.type = "button";
      moveDown.className = "secondary";
      moveDown.setAttribute("aria-label", `Descendre ${view.name || "la sous-bibliothèque"}`);
      moveDown.textContent = "↓";
      moveDown.disabled = index === views.length - 1;
      moveDown.addEventListener("click", () => {
        if (index === views.length - 1) return;
        [views[index], views[index + 1]] = [views[index + 1], views[index]];
        render();
      });
      positionControls.append(moveUp, moveDown, remove);
      header.append(name, positionControls);

      const technical = document.createElement("div");
      technical.className = "settings-library-filter-row";
      technical.append(buildModeSelect(view.asset_filter_mode, (mode) => {
        views[index].asset_filter_mode = normalizeMode(mode);
      }));
      const selectedAssets = checkedSet(view.assets);
      const technicalOptions = document.createElement("span");
      technicalOptions.className = "asset-filter-options";
      assetOptions.forEach((option) => {
        technicalOptions.append(buildCheckbox(
          `library_asset_${index}`,
          selectedAssets.has(option.kind),
          option.text,
          (checked) => {
            views[index].assets = checked
              ? [...checkedSet(views[index].assets), option.kind]
              : views[index].assets.filter((asset) => asset !== option.kind);
          },
          { labelClassName: `asset-label asset-label-${option.kind}` },
        ));
      });
      technicalOptions.append(buildCheckbox(
        `library_rated_${index}`,
        view.rated,
        "★ Notées",
        (checked) => {
          views[index].rated = checked;
        },
        { labelClassName: "asset-label asset-label-rating" },
      ));
      technical.append(technicalOptions);

      const excludedTechnical = document.createElement("div");
      excludedTechnical.className = "settings-library-filter-row";
      const technicalExcludeMarker = document.createElement("span");
      technicalExcludeMarker.className = "filter-exclude-marker";
      technicalExcludeMarker.textContent = "!!";
      excludedTechnical.append(technicalExcludeMarker);
      const excludedAssets = checkedSet(view.excluded_assets);
      const excludedTechnicalOptions = document.createElement("span");
      excludedTechnicalOptions.className = "asset-filter-options";
      assetOptions.forEach((option) => {
        excludedTechnicalOptions.append(buildCheckbox(
          `library_excluded_asset_${index}`,
          excludedAssets.has(option.kind),
          option.text,
          (checked) => {
            views[index].excluded_assets = checked
              ? [...checkedSet(views[index].excluded_assets), option.kind]
              : views[index].excluded_assets.filter((asset) => asset !== option.kind);
          },
          { labelClassName: `asset-label asset-label-${option.kind}` },
        ));
      });
      excludedTechnical.append(excludedTechnicalOptions);

      const categories = document.createElement("div");
      categories.className = "settings-library-filter-row";
      categories.append(buildModeSelect(view.category_filter_mode, (mode) => {
        views[index].category_filter_mode = normalizeMode(mode);
      }));
      const selectedCategories = checkedSet(view.categories);
      const categoryList = document.createElement("span");
      categoryList.className = "category-filter-options";
      categoryOptions.forEach((option) => {
        const label = normalizeCategoryLabel(String(option.label || ""));
        if (!label) return;
        categoryList.append(buildCheckbox(
          `library_category_${index}`,
          selectedCategories.has(label),
          label,
          (checked) => {
            views[index].categories = checked
              ? [...checkedSet(views[index].categories), label]
              : views[index].categories.filter((category) => category !== label);
          },
          { labelClassName: "category-label", style: categoryStyleFromOption(option) },
        ));
      });
      categories.append(categoryList);

      const excludedCategories = document.createElement("div");
      excludedCategories.className = "settings-library-filter-row";
      const categoryExcludeMarker = document.createElement("span");
      categoryExcludeMarker.className = "filter-exclude-marker";
      categoryExcludeMarker.textContent = "!!";
      excludedCategories.append(categoryExcludeMarker);
      const selectedExcludedCategories = checkedSet(view.excluded_categories);
      const excludedCategoryList = document.createElement("span");
      excludedCategoryList.className = "category-filter-options";
      categoryOptions.forEach((option) => {
        const label = normalizeCategoryLabel(String(option.label || ""));
        if (!label) return;
        excludedCategoryList.append(buildCheckbox(
          `library_excluded_category_${index}`,
          selectedExcludedCategories.has(label),
          label,
          (checked) => {
            views[index].excluded_categories = checked
              ? [...checkedSet(views[index].excluded_categories), label]
              : views[index].excluded_categories.filter((category) => category !== label);
          },
          { labelClassName: "category-label", style: categoryStyleFromOption(option) },
        ));
      });
      excludedCategories.append(excludedCategoryList);

      card.append(header, technical, excludedTechnical, categories, excludedCategories);
      list.append(card);
    });
    syncSource();
  }

  views = readJsonAttribute("initialViews", []).map(normalizeView).filter((view) => view.name);
  if (views.length === 0) {
    views = [normalizeView({ name: "Notés", rated: true })];
  }
  addButton.addEventListener("click", () => {
    views.push(normalizeView({ name: "Nouvelle sous-bibliothèque" }));
    render();
  });
  render();
}

document.querySelectorAll("[data-library-view-editor]").forEach(bindLibraryViewEditor);

document.querySelectorAll("[data-screen-time-carousel]").forEach((carousel) => {
  const slides = Array.from(carousel.querySelectorAll(".screen-time-slide"));
  const container = carousel.closest(".screen-time-variant");
  const previous = container?.querySelector("[data-screen-time-previous]");
  const next = container?.querySelector("[data-screen-time-next]");
  let activeIndex = 0;

  function updateControls() {
    if (previous) previous.disabled = activeIndex === 0;
    if (next) next.disabled = activeIndex === slides.length - 1;
  }

  function goTo(index) {
    activeIndex = Math.max(0, Math.min(index, slides.length - 1));
    carousel.scrollTo({ left: activeIndex * carousel.clientWidth, behavior: "smooth" });
    updateControls();
  }

  previous?.addEventListener("click", () => goTo(activeIndex - 1));
  next?.addEventListener("click", () => goTo(activeIndex + 1));
  carousel.addEventListener("scroll", () => {
    if (!carousel.clientWidth) return;
    activeIndex = Math.max(0, Math.min(Math.round(carousel.scrollLeft / carousel.clientWidth), slides.length - 1));
    updateControls();
  }, { passive: true });
  updateControls();
});

document.querySelectorAll("[data-video-stack-carousel]").forEach((carousel) => {
  const slides = Array.from(carousel.querySelectorAll(".video-stack-slide"));
  const container = carousel.closest(".video-stack");
  const previous = container?.querySelector("[data-video-stack-previous]");
  const next = container?.querySelector("[data-video-stack-next]");
  let activeIndex = 0;

  function updateControls() {
    if (previous) previous.disabled = activeIndex === 0;
    if (next) next.disabled = activeIndex === slides.length - 1;
  }

  function goTo(index) {
    activeIndex = Math.max(0, Math.min(index, slides.length - 1));
    carousel.scrollTo({ left: activeIndex * carousel.clientWidth, behavior: "smooth" });
    updateControls();
  }

  previous?.addEventListener("click", () => goTo(activeIndex - 1));
  next?.addEventListener("click", () => goTo(activeIndex + 1));
  carousel.addEventListener("scroll", () => {
    if (!carousel.clientWidth) return;
    activeIndex = Math.max(0, Math.min(Math.round(carousel.scrollLeft / carousel.clientWidth), slides.length - 1));
    updateControls();
  }, { passive: true });
  updateControls();
});

function bindSettingsNav(nav) {
  const links = Array.from(nav.querySelectorAll(".settings-nav-link"));
  const sections = links
    .map((link) => document.querySelector(link.getAttribute("href")))
    .filter(Boolean);
  if (sections.length === 0) return;
  const visible = new Set();

  function setActive() {
    const activeId = sections.find((section) => visible.has(section.id))?.id ?? sections[0].id;
    links.forEach((link) => {
      link.classList.toggle("active", link.getAttribute("href") === `#${activeId}`);
    });
  }

  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          visible.add(entry.target.id);
        } else {
          visible.delete(entry.target.id);
        }
      });
      setActive();
    },
    { rootMargin: "-96px 0px -70% 0px" }
  );
  sections.forEach((section) => observer.observe(section));
  setActive();
}

document.querySelectorAll("[data-settings-nav]").forEach(bindSettingsNav);

document.querySelectorAll("[data-csv-dropzone-form]").forEach((form) => {
  const dropzone = form.querySelector("[data-csv-dropzone]");
  const input = form.querySelector("[data-csv-dropzone-input]");
  const text = form.querySelector("[data-csv-dropzone-text]");
  if (!dropzone || !input) return;
  const defaultText = text ? text.textContent : "";

  function updateText() {
    if (!text) return;
    text.textContent = input.files && input.files[0] ? input.files[0].name : defaultText;
  }

  input.addEventListener("change", () => {
    updateText();
    if (input.files && input.files[0]) form.requestSubmit();
  });

  ["dragenter", "dragover"].forEach((eventName) => {
    dropzone.addEventListener(eventName, (event) => {
      event.preventDefault();
      dropzone.classList.add("csv-dropzone-active");
    });
  });

  ["dragleave", "dragend", "drop"].forEach((eventName) => {
    dropzone.addEventListener(eventName, () => {
      dropzone.classList.remove("csv-dropzone-active");
    });
  });

  dropzone.addEventListener("drop", (event) => {
    event.preventDefault();
    const file = event.dataTransfer?.files?.[0];
    if (!file) return;
    input.files = event.dataTransfer.files;
    updateText();
    form.requestSubmit();
  });
});

document.querySelectorAll(".csv-import-list").forEach((list) => {
  const panel = list.closest(".csv-import-panel");
  const selectAll = panel?.querySelector("[data-csv-select-all]");
  const selectNone = panel?.querySelector("[data-csv-select-none]");
  const checkboxes = () => Array.from(list.querySelectorAll('input[type="checkbox"]:not(:disabled)'));

  selectAll?.addEventListener("click", () => {
    checkboxes().forEach((checkbox) => { checkbox.checked = true; });
  });
  selectNone?.addEventListener("click", () => {
    checkboxes().forEach((checkbox) => { checkbox.checked = false; });
  });
});

const formatDownloadQueue = [];
let formatDownloadRunning = false;

function pumpFormatDownloadQueue() {
  if (formatDownloadRunning) return;
  const task = formatDownloadQueue.shift();
  if (!task) return;
  formatDownloadRunning = true;
  runFormatQueueTask(task).finally(() => {
    formatDownloadRunning = false;
    pumpFormatDownloadQueue();
  });
}

function enqueueFormatDownload(task) {
  formatDownloadQueue.push(task);
  pumpFormatDownloadQueue();
}

async function requestFormatDownload(task) {
  const body = task.quality ? { video_quality: task.quality } : undefined;
  const job = await apiRequest("POST", `/api/videos/${task.videoId}/media/${task.format}/download`, body);
  await waitForJob(job.status_url, { failure: "Le téléchargement a échoué." });
}

async function requestFormatDelete(task) {
  await apiRequest("DELETE", `/api/videos/${task.videoId}/media/${task.format}`);
}

async function runFormatQueueTask(task) {
  const { button } = task;
  try {
    if (task.action === "delete") {
      await requestFormatDelete(task);
      button.classList.remove("format-toggle-loading", "format-toggle-active");
      button.title = task.format === "audio" ? "Télécharger l’audio" : "Télécharger la vidéo";
      button.disabled = false;
    } else {
      await requestFormatDownload(task);
      button.classList.remove("format-toggle-loading");
      button.classList.add("format-toggle-active");
      button.title =
        task.format === "audio"
          ? task.allowDelete
            ? "Cliquer pour supprimer l’audio"
            : "Audio déjà téléchargé"
          : task.allowDelete
            ? "Cliquer pour supprimer la vidéo"
            : "Vidéo déjà téléchargée";
      if (task.allowDelete) button.disabled = false;
    }
  } catch (error) {
    button.classList.remove("format-toggle-loading");
    button.disabled = false;
    button.classList.add("format-toggle-error");
    button.title = error.message;
    window.setTimeout(() => button.classList.remove("format-toggle-error"), 4000);
  } finally {
    delete button.dataset.formatBusy;
  }
}

function startFormatDownload(button, videoId, quality, allowDelete) {
  button.dataset.formatBusy = "1";
  button.disabled = true;
  button.classList.add("format-toggle-loading");
  enqueueFormatDownload({ button, format: button.dataset.format, videoId, quality, allowDelete, action: "download" });
}

function startFormatDelete(button, videoId) {
  button.dataset.formatBusy = "1";
  button.disabled = true;
  button.classList.add("format-toggle-loading");
  enqueueFormatDownload({ button, format: button.dataset.format, videoId, action: "delete" });
}

function closeFormatPopovers() {
  document.querySelectorAll("[data-format-quality-popover], [data-format-delete-popover]").forEach((popover) => {
    popover.hidden = true;
  });
}

// The popovers live inside a row, which sits in a clipping carousel
// (overflow + container-type) and, for watched/hidden rows, in its own
// stacking context (opacity). Neither can be escaped with z-index, so an open
// popover is moved to <body> and placed from the toggle's viewport rect.
function openFormatPopover(popover, anchor) {
  document.body.appendChild(popover);
  popover.hidden = false;
  const rect = anchor.getBoundingClientRect();
  popover.style.position = "fixed";
  popover.style.right = "auto";
  popover.style.top = `${rect.bottom + 4}px`;
  const left = Math.min(rect.right - popover.offsetWidth, window.innerWidth - popover.offsetWidth - 8);
  popover.style.left = `${Math.max(8, left)}px`;
  if (rect.bottom + 4 + popover.offsetHeight > window.innerHeight) {
    popover.style.top = `${Math.max(8, rect.top - 4 - popover.offsetHeight)}px`;
  }
}

document.addEventListener("click", closeFormatPopovers);
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeFormatPopovers();
});

// Light that follows the finger (or the pointer) over a glass control (Raton's
// call to action). The position and the intensity are eased here and handed to
// CSS as custom properties, so the light trails the contact point instead of
// snapping to it. The chat composer has its own, richer version below.
function initGlassLight(composer) {
  if (!composer) return;
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  let tx = 0;
  let ty = 0;
  let tg = 0;
  let x = 0;
  let y = 0;
  let g = 0;
  let frame = 0;

  function paint() {
    frame = 0;
    const follow = reduced ? 1 : 0.24;
    x += (tx - x) * follow;
    y += (ty - y) * follow;
    g += (tg - g) * (reduced ? 1 : tg > g ? 0.35 : 0.09);
    composer.style.setProperty("--gx", `${x.toFixed(1)}px`);
    composer.style.setProperty("--gy", `${y.toFixed(1)}px`);
    composer.style.setProperty("--glow", g.toFixed(3));
    if (Math.abs(tx - x) > 0.4 || Math.abs(ty - y) > 0.4 || Math.abs(tg - g) > 0.004) {
      frame = requestAnimationFrame(paint);
    }
  }

  function aim(event) {
    const rect = composer.getBoundingClientRect();
    tx = event.clientX - rect.left;
    ty = event.clientY - rect.top;
    // Light that was off appears under the finger instead of sliding in from the last spot.
    if (g < 0.02) {
      x = tx;
      y = ty;
    }
    tg = 1;
    if (!frame) frame = requestAnimationFrame(paint);
  }

  function release() {
    tg = 0;
    composer.classList.remove("is-pressed");
    if (!frame) frame = requestAnimationFrame(paint);
  }

  composer.addEventListener("pointerenter", aim);
  composer.addEventListener("pointermove", aim);
  composer.addEventListener("pointerdown", (event) => {
    aim(event);
    composer.classList.add("is-pressed");
  });
  composer.addEventListener("pointerup", (event) => {
    composer.classList.remove("is-pressed");
    // A mouse stays over the card after the click; a finger is gone.
    if (event.pointerType !== "mouse") release();
  });
  composer.addEventListener("pointerleave", release);
  composer.addEventListener("pointercancel", release);
}

// Liquid-glass light of the chat composer. Two halos follow the pointer with
// inertia (also from outside the card: they fade over --glass-fade), a spot
// runs along the border, and the "+" button reflects the pointer. Everything is
// written as custom properties on the layers of `.chat-glass`, which CSS moves
// with transform/opacity only. Touch screens and prefers-reduced-motion get a
// fixed halo (no pointer tracking, no inertia). Knobs: `--glass-*` in the CSS.
function initGlassComposer(composer) {
  if (!composer) return;
  const layer = (name) => composer.querySelector(`.chat-glass-${name}`);
  const halo = layer("halo");
  const halo2 = layer("halo2");
  const spot = layer("spot");
  const plus = composer.querySelector(".chat-suggest-toggle");
  const send = composer.querySelector(".chat-send");
  const input = composer.querySelector("[data-chat-editor]");
  if (!halo || !halo2 || !spot) return;

  const style = getComputedStyle(composer);
  const knob = (name, fallback) => {
    const value = parseFloat(style.getPropertyValue(name));
    return Number.isFinite(value) ? value : fallback;
  };
  const inertia = knob("--glass-inertia", 0.15);
  const intensity = knob("--glass-intensity", 0.6);
  const fade = knob("--glass-fade", 150);
  const magnet = knob("--glass-magnet", 0.1);
  const pulseGain = knob("--glass-pulse", 0.18);

  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)");
  const fine = window.matchMedia("(hover: hover) and (pointer: fine)");
  const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
  const pointer = { x: 0, y: 0, has: false };
  const s = { x: 0, y: 0, x2: 0, y2: 0, o: 0, pr: 0, eo: 0, so: 0, sx: 0, sy: 0, pulse: 0, init: false };
  let focused = false;
  let frame = 0;
  let last = 0;

  const isStatic = () => reduce.matches || !fine.matches;

  function kick() {
    if (frame) return;
    composer.classList.add("is-live");
    last = 0;
    frame = requestAnimationFrame(paint);
  }

  function set(el, name, value) {
    el.style.setProperty(name, value.toFixed(3));
  }

  function paint(now) {
    frame = 0;
    const f = (last ? Math.min(48, now - last) : 16.67) / 16.67;
    last = now;
    const rect = composer.getBoundingClientRect();
    const w = composer.offsetWidth || rect.width;
    const h = composer.offsetHeight || rect.height;
    if (!s.init) {
      s.x = s.x2 = w / 2;
      s.y = s.y2 = h / 2;
      s.init = true;
    }
    const still = isStatic();

    // Target: the pointer brought back onto the card, so outside of it the
    // halo rests on the nearest point.
    let tx = s.x;
    let ty = s.y;
    let prox = 0;
    if (still) {
      tx = w * 0.5;
      ty = h * 0.25;
      prox = 0.55;
    } else if (pointer.has) {
      const lx = pointer.x - rect.left;
      const ly = pointer.y - rect.top;
      tx = clamp(lx, 0, w);
      ty = clamp(ly, 0, h);
      const dx = lx < 0 ? -lx : lx > w ? lx - w : 0;
      const dy = ly < 0 ? -ly : ly > h ? ly - h : 0;
      prox = clamp(1 - Math.hypot(dx, dy) / fade, 0, 1);
    }

    const follow = still ? 1 : 1 - Math.pow(1 - inertia, f);
    const slow = still ? 1 : 1 - Math.pow(1 - inertia * 0.5, f);
    const ease = still ? 1 : 1 - Math.pow(1 - 0.14, f);
    s.x += (tx - s.x) * follow;
    s.y += (ty - s.y) * follow;
    s.x2 += (tx - s.x2) * slow;
    s.y2 += (ty - s.y2) * slow;
    s.pr += (prox - s.pr) * ease;
    let target = s.pr * intensity;
    if (focused) target = Math.min(1.15, target + 0.35 * intensity);
    s.o += (target - s.o) * ease;
    s.pulse = still ? 0 : s.pulse * Math.pow(0.88, f);

    // Magnetism: the halo leans toward the nearest button.
    let hx = s.x;
    let hy = s.y;
    if (!still) {
      let best = null;
      let bestDistance = Infinity;
      for (const button of [plus, send]) {
        if (!button) continue;
        const b = button.getBoundingClientRect();
        const cx = b.left + b.width / 2 - rect.left;
        const cy = b.top + b.height / 2 - rect.top;
        const d = Math.hypot(cx - s.x, cy - s.y);
        if (d < bestDistance) {
          bestDistance = d;
          best = { x: cx, y: cy };
        }
      }
      if (best) {
        hx += (best.x - s.x) * magnet;
        hy += (best.y - s.y) * magnet;
      }
    }

    const scale = (0.55 + 0.45 * s.pr) * (focused ? 1.12 : 1) * (1 + s.pulse * 0.08);
    const opacity = clamp(s.o * (1 + s.pulse * pulseGain * 5), 0, 1);
    set(halo, "--mx", hx);
    set(halo, "--my", hy);
    set(halo, "--ho", opacity);
    set(halo, "--hs", scale);
    set(halo2, "--mx2", s.x2 - 26);
    set(halo2, "--my2", s.y2 + 10);
    set(halo2, "--h2o", opacity * 0.5);
    set(halo2, "--h2s", scale * 0.95);

    const edgeTarget = still ? 0.3 : clamp(s.pr * 1.15, 0, 1);
    s.eo += (edgeTarget - s.eo) * ease;
    set(spot, "--ex", s.x);
    set(spot, "--ey", s.y);
    set(spot, "--eo", s.eo);

    let shineTarget = 0;
    let shineX = 0;
    let shineY = 0;
    if (!still && pointer.has && plus) {
      const b = plus.getBoundingClientRect();
      const dx = pointer.x - (b.left + b.width / 2);
      const dy = pointer.y - (b.top + b.height / 2);
      shineTarget = clamp(1 - Math.hypot(dx, dy) / 200, 0, 1);
      shineX = clamp(dx / 120, -1, 1);
      shineY = clamp(dy / 120, -1, 1);
    }
    s.so += (shineTarget - s.so) * ease;
    s.sx += (shineX - s.sx) * ease;
    s.sy += (shineY - s.sy) * ease;
    if (plus) {
      set(plus, "--so", s.so);
      set(plus, "--sx", s.sx);
      set(plus, "--sy", s.sy);
    }

    const settled =
      Math.abs(tx - s.x) < 0.1 && Math.abs(ty - s.y) < 0.1 &&
      Math.abs(tx - s.x2) < 0.1 && Math.abs(ty - s.y2) < 0.1 &&
      Math.abs(target - s.o) < 0.002 && Math.abs(prox - s.pr) < 0.002 &&
      s.pulse < 0.002 && Math.abs(edgeTarget - s.eo) < 0.002 &&
      Math.abs(shineTarget - s.so) < 0.002 &&
      Math.abs(shineX - s.sx) < 0.002 && Math.abs(shineY - s.sy) < 0.002;
    if (settled) composer.classList.remove("is-live");
    else frame = requestAnimationFrame(paint);
  }

  window.addEventListener(
    "pointermove",
    (event) => {
      if (event.pointerType !== "mouse") return;
      pointer.x = event.clientX;
      pointer.y = event.clientY;
      pointer.has = true;
      if (!isStatic()) kick();
    },
    { passive: true }
  );
  document.documentElement.addEventListener("mouseleave", () => {
    pointer.has = false;
    kick();
  });
  window.addEventListener("scroll", () => {
    if (pointer.has) kick();
  }, { passive: true });
  reduce.addEventListener("change", kick);
  fine.addEventListener("change", kick);

  // The halo intensifies while the field has the focus and pulses on each key.
  if (input) {
    input.addEventListener("focus", () => {
      focused = true;
      kick();
    });
    input.addEventListener("blur", () => {
      focused = false;
      kick();
    });
    input.addEventListener("input", () => {
      s.pulse = 1;
      kick();
    });
  }

  // Press: the card squishes (CSS, `.is-pressed`) and a wave leaves the contact point.
  function ripple(x, y) {
    if (reduce.matches || !composer.querySelector(".chat-glass")) return;
    const wave = document.createElement("i");
    wave.className = "chat-glass-ripple";
    composer.querySelector(".chat-glass").appendChild(wave);
    const reach = (Math.hypot(composer.offsetWidth, composer.offsetHeight) * 2) / 40;
    const animation = wave.animate(
      [
        { transform: `translate(${x - 20}px, ${y - 20}px) scale(0)`, opacity: 0.6 },
        { transform: `translate(${x - 20}px, ${y - 20}px) scale(${reach})`, opacity: 0 },
      ],
      { duration: 700, easing: "cubic-bezier(0.2, 0.7, 0.2, 1)" }
    );
    animation.onfinish = () => wave.remove();
  }

  composer.addEventListener("pointerdown", (event) => {
    composer.classList.add("is-pressed");
    const rect = composer.getBoundingClientRect();
    ripple(event.clientX - rect.left, event.clientY - rect.top);
  });
  const release = () => composer.classList.remove("is-pressed");
  window.addEventListener("pointerup", release);
  window.addEventListener("pointercancel", release);

  kick();
}

// Shared chat widget: powers both the per-video chat (video_detail.html) and
// the cross-video ("whole library") chat (dashboard bar), which differ only
// in which endpoints/messages they read from — see app/templates/_macros.html
// chat_widget() for the data-chat-config shape this expects.
function initChatWidget(root) {
  root.querySelectorAll(".chat-composer").forEach(initGlassComposer);
  let config;
  try {
    config = JSON.parse(root.dataset.chatConfig || "{}");
  } catch {
    return;
  }
  if (!config.scopes || !Object.keys(config.scopes).length) return;

  const messagesEl = root.querySelector("[data-chat-messages]");
  const statusEl = root.querySelector("[data-chat-status]");
  const coverageEl = root.querySelector("[data-chat-coverage]");
  const form = root.querySelector("[data-chat-form]");
  const clearForm = root.querySelector("[data-chat-clear]");
  const scopeButtons = root.querySelectorAll("[data-chat-scope]");
  // The visible field is a contenteditable (no iOS form accessory bar); the
  // hidden textarea only carries its text into FormData.
  const input = form ? form.querySelector("[data-chat-editor]") : null;
  const field = form ? form.querySelector("textarea[name='question']") : null;
  const defaultPlaceholder = input ? input.dataset.placeholder : "";
  const readInput = () => (input ? input.innerText.replace(/\u00a0/g, " ") : "");
  function syncField() {
    if (!input) return;
    // A fully erased contenteditable keeps a <br>, which defeats :empty (placeholder).
    if (!input.textContent) input.replaceChildren();
    if (field) field.value = readInput();
  }
  function writeInput(text) {
    if (!input) return;
    input.textContent = text;
    syncField();
  }
  function focusInputAtEnd() {
    if (!input) return;
    input.focus();
    const range = document.createRange();
    range.selectNodeContents(input);
    range.collapse(false);
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
  }
  const suggestEl = root.querySelector("[data-chat-suggest]");
  const suggestToggle = root.querySelector("[data-chat-suggest-toggle]");
  const suggestMenu = root.querySelector("[data-chat-suggest-menu]");
  const suggestList = root.querySelector("[data-chat-suggest-list]");
  const suggestClose = root.querySelector("[data-chat-suggest-close]");
  const suggestBackdrop = root.querySelector("[data-chat-suggest-backdrop]");
  let currentScope = config.scopes[config.defaultScope] ? config.defaultScope : Object.keys(config.scopes)[0];
  let statusTimer;

  function scopeConfig() {
    return config.scopes[currentScope];
  }

  function setStatus(message, level) {
    if (!statusEl) return;
    window.clearTimeout(statusTimer);
    statusEl.hidden = false;
    statusEl.textContent = message;
    statusEl.dataset.level = level;
    if (level === "success") {
      statusTimer = window.setTimeout(() => {
        statusEl.hidden = true;
      }, 2200);
    }
  }

  // The model writes `[[chaine:12|Name]]` / `[[video:34|Title]]` inside its
  // answer (app/services/library_chat/tools.py, which owns the syntax: keep this
  // pattern in step with its `_REFERENCE_PATTERN`). Only the ones the server
  // still lists in `channels`/`citations` become links, and the link text is
  // the name stored in the database, not the model's label: a deleted item
  // stays plain text under the label.
  const REFERENCE_PATTERN = /\[\[(chaine|video)\s*:\s*(\d+)\s*(?:\|\s*([^\n]*?)\s*)?\]\](?!\])/g;

  function appendAnswerText(paragraph, content, targets, mentioned) {
    let last = 0;
    for (const match of content.matchAll(REFERENCE_PATTERN)) {
      paragraph.append(content.slice(last, match.index));
      last = match.index + match[0].length;
      const [, kind, id, label] = match;
      const target = targets[kind].get(Number(id));
      if (!target) {
        paragraph.append(label || "");
        continue;
      }
      const link = document.createElement("a");
      link.className = "chat-ref";
      link.dataset.kind = kind;
      link.href = target.href;
      link.textContent = target.name;
      paragraph.append(link);
      mentioned[kind].add(Number(id));
    }
    paragraph.append(content.slice(last));
  }

  function buildMessageNode(message) {
    const article = document.createElement("article");
    article.className = `chat-message ${message.role}`;
    const strong = document.createElement("strong");
    strong.className = "chat-role";
    strong.textContent = message.role === "user" ? "Vous" : "Assistant";
    const paragraph = document.createElement("p");
    const targets = {
      chaine: new Map((message.channels || []).map((channel) => [channel.channel_id, { href: `/videos?channel_id=${channel.channel_id}`, name: channel.name }])),
      video: new Map((message.citations || []).map((citation) => [citation.video_id, { href: `/videos/${citation.video_id}`, name: citation.title }])),
    };
    const mentioned = { chaine: new Set(), video: new Set() };
    if (message.role === "user") {
      paragraph.textContent = message.content;
    } else {
      appendAnswerText(paragraph, message.content, targets, mentioned);
    }
    article.append(strong, paragraph);
    // What the answer did not mention inline (older answers) stays a chip row
    // under the text. Channels first: when the question was about a channel,
    // that is the answer.
    const chips = [
      ...(message.channels || [])
        .filter((channel) => !mentioned.chaine.has(channel.channel_id))
        .map((channel) => ({
          href: `/videos?channel_id=${channel.channel_id}`,
          text: channel.name,
          className: "chat-citation-chip chat-channel-chip",
        })),
      ...(message.citations || [])
        .filter((citation) => !mentioned.video.has(citation.video_id))
        .map((citation) => ({
          href: `/videos/${citation.video_id}`,
          text: citation.title,
          className: "chat-citation-chip",
        })),
    ];
    if (chips.length) {
      const citations = document.createElement("div");
      citations.className = "chat-citations";
      chips.forEach((chip) => {
        const link = document.createElement("a");
        link.className = chip.className;
        link.href = chip.href;
        link.textContent = chip.text;
        citations.append(link);
      });
      article.append(citations);
    }
    return article;
  }

  // The conversation flows in the page (no inner scroll box): bring the latest
  // message to the top of the screen while an answer is being written, so a
  // long answer is read from its first line, not from its end. Not called when
  // the page first loads.
  function revealLatest() {
    messagesEl?.lastElementChild?.scrollIntoView({ block: "start", behavior: "smooth" });
  }

  function renderMessages() {
    if (!messagesEl) return;
    const scope = scopeConfig();
    const messages = scope.messages || [];
    messagesEl.replaceChildren();
    // An empty scope renders nothing: the messages area collapses
    // (`.chat-messages:empty`) and only the composer is left.
    messages.forEach((message) => messagesEl.append(buildMessageNode(message)));
    root.dataset.chatEmpty = messages.length ? "false" : "true";
    if (clearForm) clearForm.hidden = !messages.length;
    if (coverageEl) {
      coverageEl.hidden = !scope.coverageNote || !messages.length;
      coverageEl.textContent = scope.coverageNote || "";
    }
  }

  // The tool calls the model makes while it works (search a channel, search
  // the notes...), shown above the typing bubble so the wait is not silent.
  function renderToolSteps(steps) {
    if (!messagesEl) return;
    let list = messagesEl.querySelector("[data-chat-tool-steps]");
    if (!steps || !steps.length) {
      list?.remove();
      return;
    }
    if (!list) {
      list = document.createElement("div");
      list.className = "chat-message assistant chat-tool-steps";
      list.dataset.chatToolSteps = "1";
      list.setAttribute("role", "status");
      messagesEl.querySelector("[data-chat-typing]")?.before(list);
      if (!list.isConnected) messagesEl.append(list);
    }
    list.replaceChildren(
      ...steps.map((step) => {
        const item = document.createElement("div");
        item.className = "chat-tool-step";
        item.dataset.done = step.result ? "true" : "false";
        const label = document.createElement("span");
        label.textContent = step.label;
        item.append(label);
        if (step.result) {
          const result = document.createElement("span");
          result.className = "chat-tool-step-result";
          result.textContent = step.result;
          item.append(result);
        }
        return item;
      }),
    );
    revealLatest();
  }

  function closeSuggestions() {
    if (!suggestMenu || suggestMenu.hidden) return;
    suggestMenu.hidden = true;
    suggestToggle.setAttribute("aria-expanded", "false");
  }

  function renderSuggestions() {
    if (!suggestEl || !suggestMenu || !input) return;
    const suggestions = scopeConfig().suggestions || [];
    closeSuggestions();
    suggestEl.hidden = !suggestions.length;
    suggestList.replaceChildren(
      ...suggestions.map((suggestion) => {
        const item = document.createElement("button");
        item.type = "button";
        item.className = "chat-suggest-item";
        item.setAttribute("role", "menuitem");
        item.textContent = suggestion.label;
        item.addEventListener("click", () => {
          closeSuggestions();
          writeInput(suggestion.prompt);
          input.dispatchEvent(new Event("input"));
          focusInputAtEnd();
        });
        return item;
      }),
    );
  }

  if (suggestToggle && suggestMenu) {
    suggestToggle.addEventListener("click", () => {
      if (!suggestMenu.hidden) {
        closeSuggestions();
        return;
      }
      // The menu is a bottom sheet: the keyboard goes away before it slides up.
      if (input) input.blur();
      suggestMenu.hidden = false;
      suggestToggle.setAttribute("aria-expanded", "true");
      const first = suggestList.querySelector("button");
      if (first) first.focus({ preventScroll: true });
    });
    if (suggestBackdrop) suggestBackdrop.addEventListener("click", closeSuggestions);
    if (suggestClose) {
      suggestClose.addEventListener("click", () => {
        closeSuggestions();
        suggestToggle.focus({ preventScroll: true });
      });
    }
    suggestEl.addEventListener("keydown", (event) => {
      if (suggestMenu.hidden) return;
      if (event.key === "Escape") {
        closeSuggestions();
        suggestToggle.focus();
        return;
      }
      if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
      event.preventDefault();
      const items = [...suggestList.querySelectorAll("button")];
      const index = items.indexOf(document.activeElement) + (event.key === "ArrowDown" ? 1 : -1);
      items[(index + items.length) % items.length].focus();
    });
    document.addEventListener("click", (event) => {
      if (!suggestEl.contains(event.target)) closeSuggestions();
    });
  }

  function setTyping(active) {
    if (!messagesEl) return;
    const existing = messagesEl.querySelector("[data-chat-typing]");
    if (!active) {
      if (existing) existing.remove();
      messagesEl.querySelector("[data-chat-tool-steps]")?.remove();
      return;
    }
    if (existing) return;
    const bubble = document.createElement("div");
    bubble.className = "chat-message assistant chat-typing";
    bubble.dataset.chatTyping = "1";
    bubble.setAttribute("aria-hidden", "true");
    bubble.append(document.createElement("span"), document.createElement("span"), document.createElement("span"));
    messagesEl.append(bubble);
    revealLatest();
  }

  function setScope(scope) {
    if (!config.scopes[scope]) return;
    currentScope = scope;
    scopeButtons.forEach((button) => {
      const active = button.dataset.chatScope === scope;
      button.classList.toggle("active", active);
      button.setAttribute("aria-selected", active ? "true" : "false");
    });
    if (input) input.dataset.placeholder = scopeConfig().placeholder || defaultPlaceholder;
    renderSuggestions();
    renderMessages();
  }

  scopeButtons.forEach((button) => {
    button.addEventListener("click", () => setScope(button.dataset.chatScope));
  });

  // Polls /api/llm-jobs/{id} until the answer is written; returns the conversation with it.
  async function waitForAnswer(statusUrl, onProgress) {
    for (;;) {
      const job = await apiRequest("GET", statusUrl);
      if (job.status === "failed") throw new Error(job.message || "Réponse impossible.");
      if (job.status === "done") return job.chat_messages || job.library_chat.messages;
      onProgress(job.tool_calls);
      await new Promise((resolve) => window.setTimeout(resolve, 2000));
    }
  }

  if (form) {
    const sendButton = form.querySelector("button[type='submit']");

    function syncSendState() {
      if (!sendButton || !input) return;
      sendButton.disabled = input.contentEditable === "false" || !readInput().trim();
    }

    if (input) {
      input.addEventListener("input", () => {
        syncField();
        syncSendState();
      });
      input.addEventListener("keydown", (event) => {
        if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
          event.preventDefault();
          if (readInput().trim()) form.requestSubmit();
        }
      });
    }
    syncSendState();

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const button = form.querySelector("button");
      const submittedScope = currentScope;
      syncField();
      const question = readInput().trim();
      button.disabled = true;
      if (input) input.contentEditable = "false";
      // Show the question and a typing bubble right away; both are replaced by
      // the server's own message list once the answer lands (or dropped again
      // by renderMessages() if the request fails).
      if (messagesEl && question) {
        messagesEl.append(buildMessageNode({ role: "user", content: question }));
        root.dataset.chatEmpty = "false";
      }
      setTyping(true);
      setStatus("Préparation de la réponse...", "loading");

      try {
        const job = await apiRequest("POST", scopeConfig().chatUrl, { question });
        form.reset();
        writeInput("");
        setStatus("Préparation de la réponse, cela peut prendre un moment...", "loading");
        config.scopes[submittedScope].messages = await waitForAnswer(job.status_url, renderToolSteps);
        if (submittedScope === currentScope) {
          renderMessages();
          revealLatest();
        }
        setStatus("Réponse ajoutée.", "success");
      } catch (error) {
        setStatus(error.message, "error");
        renderMessages();
        // The question is cleared as soon as the job is queued, so put it back
        // when the job ends up failing rather than making the user retype it.
        if (!readInput().trim()) writeInput(question);
      } finally {
        setTyping(false);
        button.disabled = false;
        if (input) input.contentEditable = "plaintext-only";
        syncSendState();
        focusInputAtEnd();
      }
    });
  }

  if (clearForm) {
    clearForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const button = clearForm.querySelector("button");
      const clearedScope = currentScope;
      button.disabled = true;
      setStatus("Effacement en cours...", "loading");
      try {
        await apiRequest("DELETE", scopeConfig().chatUrl);
        config.scopes[clearedScope].messages = [];
        if (clearedScope === currentScope) renderMessages();
        setStatus("Discussion effacée.", "success");
      } catch (error) {
        setStatus(error.message, "error");
      } finally {
        button.disabled = false;
      }
    });
  }

  setScope(currentScope);
}

document.querySelectorAll("[data-chat-widget]").forEach(initChatWidget);
// Raton's call to action on the home page gets the same pointer-following light.
// Also re-run for fragments swapped in later (turbo-frame), hence the guard.
function bindGlassLight(root) {
  root.querySelectorAll(".raton-cta, [data-glass-light]").forEach((el) => {
    if (el.dataset.glassLightBound) return;
    el.dataset.glassLightBound = "1";
    initGlassLight(el);
  });
}
bindGlassLight(document);
document.addEventListener("turbo:frame-load", (event) => bindGlassLight(event.target));

function bindFormatActionContainer(container) {
  if (container.dataset.formatActionsBound) return;
  container.dataset.formatActionsBound = "true";
  const videoId = container.dataset.videoId;
  const allowDelete = container.dataset.allowDelete === "true";
  container.querySelectorAll("[data-format-toggle]").forEach((button) => {
    const qualityPopover = button.parentElement.querySelector(":scope > [data-format-quality-popover]");
    const deletePopover = button.parentElement.querySelector(":scope > [data-format-delete-popover]");
    button.addEventListener("click", (event) => {
      if (button.disabled || button.dataset.formatBusy) return;
      if (allowDelete && button.classList.contains("format-toggle-active") && deletePopover) {
        event.stopPropagation();
        const wasOpen = !deletePopover.hidden;
        closeFormatPopovers();
        if (!wasOpen) openFormatPopover(deletePopover, button);
        return;
      }
      if (qualityPopover) {
        event.stopPropagation();
        const wasOpen = !qualityPopover.hidden;
        closeFormatPopovers();
        if (!wasOpen) openFormatPopover(qualityPopover, button);
        return;
      }
      startFormatDownload(button, videoId, null, allowDelete);
    });
    qualityPopover?.querySelectorAll("[data-format-quality-option]").forEach((option) => {
      option.addEventListener("click", (event) => {
        event.stopPropagation();
        qualityPopover.hidden = true;
        startFormatDownload(button, videoId, option.dataset.quality, allowDelete);
      });
    });
    deletePopover?.querySelector("[data-format-delete-cancel]")?.addEventListener("click", (event) => {
      event.stopPropagation();
      deletePopover.hidden = true;
    });
    deletePopover?.querySelector("[data-format-delete-confirm]")?.addEventListener("click", (event) => {
      event.stopPropagation();
      deletePopover.hidden = true;
      startFormatDelete(button, videoId);
    });
  });
}

document.querySelectorAll("[data-video-format-actions]").forEach(bindFormatActionContainer);

// A form that redirects back to the page it was posted from (bell, playlist
// order, notes...) must not send the reader back to the top. Turbo
// keeps the scroll position (turbo-refresh-scroll in base.html) only for a
// "page refresh": a `replace` visit to the current pathname. It picks
// `replace` by itself only when the redirect URL is identical to the current
// one, which a `?message=` suffix defeats, so the action is forced here.
if (!window.__sameFormRedirectBound) {
  window.__sameFormRedirectBound = true;
  document.addEventListener("turbo:before-fetch-response", (event) => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement) || form.method !== "post") return;
    if (form.dataset.turboAction) return;
    // A submission rendered inside a frame must stay there: data-turbo-action
    // would promote it to a full page visit. Frames with target="_top" (the
    // live result lists) already navigate the whole page.
    const frame = form.closest("turbo-frame");
    const frameTarget = form.dataset.turboFrame || frame?.getAttribute("target") || frame?.id;
    if (frameTarget && frameTarget !== "_top") return;
    const response = event.detail.fetchResponse;
    if (!response.redirected) return;
    const target = response.location;
    if (target.pathname !== window.location.pathname) return;
    form.dataset.turboAction = "replace";
  });
}

// Rating stars. The forms carry data-turbo="false": the note is saved with
// PUT on `data-rating-url` (/api) and the stars repainted in place, so the page
// neither reloads nor scrolls back to the top; `action` is the no-JS fallback. Delegated to the document because Turbo replaces
// the lists; bound once because this file runs again on every visit.
function ratingFormValue(form) {
  const tier = [...form.classList].find((name) => name.startsWith("rating-tier-"));
  return tier ? Number.parseInt(tier.slice("rating-tier-".length), 10) || 0 : 0;
}

// A light glint crosses the filled stars of a channel-page rating (hero or card) when
// its value changes; `.rating-fx` carries the animation and is dropped once it ends.
function flashRatingFx(form) {
  if (!form.closest(".channel-actions, .channel-video-grid")) return;
  form.classList.remove("rating-fx");
  // Force a reflow so a second change within the animation restarts it.
  void form.offsetWidth;
  form.classList.add("rating-fx");
  window.setTimeout(() => form.classList.remove("rating-fx"), 1400);
}

function paintRating(action, rating, animate = true) {
  // The same video or channel can be rated from several cards of one page.
  document.querySelectorAll("form.rating-control").forEach((form) => {
    if (form.getAttribute("action") !== action) return;
    // The optimistic paint already played the glint: the server echo (same tier) must not restart it.
    const changed = !form.classList.contains(`rating-tier-${rating}`);
    [...form.classList]
      .filter((name) => name.startsWith("rating-tier-"))
      .forEach((name) => form.classList.remove(name));
    form.classList.add(`rating-tier-${rating}`);
    if (animate && changed) flashRatingFx(form);
    form.querySelectorAll('button[name="rating"]').forEach((button) => {
      const value = Number.parseInt(button.value, 10);
      const filled = value > 0 && rating >= value;
      button.classList.toggle("rating-star-filled", filled);
      button.classList.toggle("rating-star-empty", !filled);
    });
  });
  document.querySelectorAll("[data-rating-value]").forEach((label) => {
    if (label.dataset.ratingValue === action) label.textContent = String(rating);
  });
}

async function submitRating(form, requested) {
  const action = form.getAttribute("action");
  const previous = ratingFormValue(form);
  paintRating(action, requested);
  try {
    const payload = await apiRequest("PUT", form.dataset.ratingUrl, { rating: requested });
    paintRating(action, payload.rating);
  } catch (error) {
    paintRating(action, previous, false);
  }
}

if (!window.__ratingFormsBound) {
  window.__ratingFormsBound = true;
  document.addEventListener("submit", (event) => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement) || !form.classList.contains("rating-control")) return;
    const requested = Number.parseInt(event.submitter?.value ?? "", 10);
    // Without a submitter there is no note to send: let the form post normally.
    if (!Number.isFinite(requested)) return;
    event.preventDefault();
    submitRating(form, requested);
  });
}

// Boutons « Vu » / « Écartée » des cartes vidéo. Écouteur délégué au document :
// les listes sont remplacées par Turbo, il n'y a donc rien à relier après coup.
function paintListState(container, state) {
  // Les classes de grisage different selon le contexte (carte de liste vs ligne
  // « A reprendre ») : la macro les passe en data-*, le JS n'a rien a savoir.
  const row = container.closest("article");
  container.dataset.listState = state;
  if (row) {
    row.classList.toggle(container.dataset.rowWatchedClass, state === "watched");
    row.classList.toggle(container.dataset.rowHiddenClass, state === "hidden");
  }
  container.querySelectorAll("[data-list-state-target]").forEach((button) => {
    const active =
      button.dataset.listStateTarget === "hidden" ? state === "hidden" : state !== "normal";
    button.classList.toggle("list-state-toggle-active", active);
    button.setAttribute("aria-pressed", active ? "true" : "false");
  });
}

async function submitListState(container, requested) {
  const buttons = [...container.querySelectorAll("[data-list-state-target]")];
  buttons.forEach((button) => {
    button.disabled = true;
  });
  try {
    const payload = await apiRequest("PUT", `/api/videos/${container.dataset.videoId}/list-state`, {
      state: requested,
    });
    // `unwatched` forces the normal look; `null` hands back to the automatic state, which only
    // the server knows when rendering: it is read back from the attribute the macro sets.
    let painted = payload.list_state;
    if (painted === "unwatched") painted = "normal";
    if (!painted) painted = container.dataset.listStateAuto || "normal";
    paintListState(container, painted);
  } catch (error) {
    paintListState(container, container.dataset.listState);
  } finally {
    buttons.forEach((button) => {
      button.disabled = false;
    });
  }
}

document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-list-state-target]");
  if (!button || button.disabled) return;
  const container = button.closest("[data-list-state-toggle]");
  if (!container) return;
  event.preventDefault();
  const current = container.dataset.listState || "normal";
  const requested =
    button.dataset.listStateTarget === "hidden"
      ? current === "hidden"
        ? "clear"
        : "hidden"
      : current === "watched"
        ? "unwatched"
        : "watched";
  submitListState(container, requested);
});

// Left/right swipe on a video card (touch screens, where the "vu"/"écartée"
// buttons above are hidden): same toggle logic and same endpoint, through
// submitListState. Délégué au document comme
// le pull-to-refresh plus bas : les listes sont remplacées par Turbo, rien à
// relier après coup.
if (!window.__videoSwipeBound) {
  window.__videoSwipeBound = true;

  const SWIPE_THRESHOLD = 90; // px de glissement pour déclencher l'action au relâchement
  const SWIPE_MAX = 130; // butée visuelle : la carte ne suit pas le doigt au-delà
  const SWIPE_CLICK_GUARD_MS = 400;

  const HIDE_ICON =
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M10.6 5.2A9.7 9.7 0 0 1 12 5c6.5 0 10 7 10 7a17 17 0 0 1-3 3.9M6.2 6.2A17 17 0 0 0 2 12s3.5 7 10 7a9.6 9.6 0 0 0 4.3-1"/><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2"/><path d="M3 3l18 18"/></svg>';
  const WATCHED_ICON =
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="3"/></svg>';

  let swipeIndicator = null;
  let swipeRow = null;
  let swipeContainer = null;
  let swipeStartX = null;
  let swipeStartY = null;
  let swipeBaseRect = null;
  let swipeDeltaX = 0;
  let swipeDragging = false; // glissement horizontal confirmé (au-delà du seuil de désambiguation)
  let swipeDirection = null; // "hidden" | "watched" — direction du dernier rendu de l'indicateur
  let lastSwipeEndedAt = 0;

  function resetSwipe() {
    if (swipeRow) {
      swipeRow.classList.remove("swipe-dragging");
      swipeRow.style.transform = "";
    }
    swipeIndicator?.remove();
    swipeIndicator = null;
    swipeRow = null;
    swipeContainer = null;
    swipeStartX = null;
    swipeStartY = null;
    swipeBaseRect = null;
    swipeDeltaX = 0;
    swipeDragging = false;
    swipeDirection = null;
  }

  function updateSwipeIndicator() {
    const direction = swipeDeltaX < 0 ? "hidden" : "watched";
    if (!swipeIndicator) {
      swipeIndicator = document.createElement("div");
      swipeIndicator.style.position = "fixed";
      swipeIndicator.style.top = `${swipeBaseRect.top}px`;
      swipeIndicator.style.left = `${swipeBaseRect.left}px`;
      swipeIndicator.style.width = `${swipeBaseRect.width}px`;
      swipeIndicator.style.height = `${swipeBaseRect.height}px`;
      document.body.appendChild(swipeIndicator);
    }
    if (direction !== swipeDirection) {
      swipeDirection = direction;
      const current = swipeContainer.dataset.listState || "normal";
      if (direction === "hidden") {
        swipeIndicator.className = "swipe-action-indicator swipe-action-hidden";
        const label = current === "hidden" ? "Réafficher" : "Masquer";
        swipeIndicator.innerHTML = `<span>${label}</span>${HIDE_ICON}`;
      } else {
        swipeIndicator.className = "swipe-action-indicator swipe-action-watched";
        const label = current === "watched" ? "Marquer non vu" : "Marquer vu";
        swipeIndicator.innerHTML = `${WATCHED_ICON}<span>${label}</span>`;
      }
    }
    swipeIndicator.style.opacity = String(Math.min(Math.abs(swipeDeltaX) / SWIPE_THRESHOLD, 1));
  }

  document.addEventListener("touchstart", (event) => {
    if (event.touches.length !== 1) return;
    // A swipe may start anywhere on the card, links and buttons included
    // (thumbnail and title cover most of it). A plain tap still reaches them:
    // nothing is cancelled until the gesture is confirmed horizontal. Form
    // fields keep their own touch handling.
    if (event.target.closest("input, select, textarea")) return;
    const row = event.target.closest(".video-row, .dashboard-media-row");
    if (!row) return;
    const toggle = row.querySelector("[data-list-state-toggle]");
    if (!toggle) return;
    swipeRow = row;
    swipeContainer = toggle;
    swipeStartX = event.touches[0].clientX;
    swipeStartY = event.touches[0].clientY;
    swipeDragging = false;
    swipeDeltaX = 0;
  }, { passive: true });

  document.addEventListener("touchmove", (event) => {
    if (!swipeRow || swipeStartX === null) return;
    const deltaX = event.touches[0].clientX - swipeStartX;
    const deltaY = event.touches[0].clientY - swipeStartY;
    if (!swipeDragging) {
      // Meme desambiguation que le pull-to-refresh : un glissement surtout
      // vertical reste un scroll normal, on abandonne le geste de swipe.
      if (Math.abs(deltaY) > Math.abs(deltaX)) {
        if (Math.abs(deltaY) > 10) resetSwipe();
        return;
      }
      if (Math.abs(deltaX) < 10) return;
      swipeDragging = true;
      swipeRow.classList.add("swipe-dragging");
      // Capturé avant la première translation : sert de repère fixe à
      // l'indicateur pendant tout le geste (la carte, elle, continue de bouger).
      swipeBaseRect = swipeRow.getBoundingClientRect();
    }
    event.preventDefault();
    swipeDeltaX = Math.max(-SWIPE_MAX, Math.min(SWIPE_MAX, deltaX));
    swipeRow.style.transform = `translateX(${swipeDeltaX}px)`;
    updateSwipeIndicator();
  }, { passive: false });

  document.addEventListener("touchend", () => {
    if (!swipeRow) return;
    if (swipeDragging) lastSwipeEndedAt = Date.now();
    if (swipeDragging && Math.abs(swipeDeltaX) >= SWIPE_THRESHOLD) {
      const current = swipeContainer.dataset.listState || "normal";
      const requested =
        swipeDeltaX < 0
          ? current === "hidden" ? "clear" : "hidden"
          : current === "watched" ? "unwatched" : "watched";
      submitListState(swipeContainer, requested);
    }
    resetSwipe();
  });

  document.addEventListener("touchcancel", resetSwipe);

  // A swipe that started on a link or button must not also activate it when
  // the finger lifts: swallow the click that may follow a confirmed drag.
  document.addEventListener("click", (event) => {
    if (Date.now() - lastSwipeEndedAt > SWIPE_CLICK_GUARD_MS) return;
    if (!event.target.closest(".video-row, .dashboard-media-row")) return;
    event.preventDefault();
    event.stopPropagation();
  }, true);
}

// Persistent audio mini-player (Spotify-style): the bar in base.html carries
// data-turbo-permanent, so Turbo Drive moves the same live <audio> element
// across every visit instead of destroying it — this is what lets audio-only
// tracks (podcasts etc.) keep playing while the user browses other pages.
function formatMiniPlayerTime(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00";
  const total = Math.floor(seconds);
  const minutes = Math.floor(total / 60);
  const secs = total % 60;
  return `${minutes}:${secs.toString().padStart(2, "0")}`;
}

// Percent (0-100) of the media buffered around the playhead, for the seek bars'
// buffer layer; 0 until the duration is known.
function bufferedPercent(media) {
  const duration = media.duration;
  if (!Number.isFinite(duration) || duration <= 0) return 0;
  const ranges = media.buffered;
  const time = media.currentTime;
  for (let i = 0; i < ranges.length; i += 1) {
    if (ranges.start(i) <= time + 0.5 && time <= ranges.end(i)) return (ranges.end(i) / duration) * 100;
  }
  return 0;
}

// Paints a native range input's fill and buffer layers (see the shared seek-bar
// CSS). Also used by playlist-player.js.
function paintSeekRange(input, media) {
  input.style.setProperty("--seek-progress", String(Number(input.value) || 0));
  input.style.setProperty("--seek-buffered", String(bufferedPercent(media)));
}
window.ratonPaintSeekRange = paintSeekRange;

function initMiniPlayer() {
  const bar = document.querySelector("[data-mini-player]");
  // `bar` is permanent (never recreated by Turbo), so without this guard
  // every visit's re-execution of app.js would rebind the same node again.
  if (!bar || bar.dataset.bound) return;
  bar.dataset.bound = "1";

  const audio = bar.querySelector("[data-mini-player-audio]");
  const playPauseButton = bar.querySelector("[data-mini-player-playpause]");
  const seek = bar.querySelector("[data-mini-player-seek]");
  const currentTimeEl = bar.querySelector("[data-mini-player-current]");
  const durationEl = bar.querySelector("[data-mini-player-duration]");
  const titleEl = bar.querySelector("[data-mini-player-title]");
  const channelEl = bar.querySelector("[data-mini-player-channel]");
  const metaTimeEl = bar.querySelector("[data-mini-player-meta-time]");
  const openLink = bar.querySelector("[data-mini-player-open]");
  const thumbEl = bar.querySelector("[data-mini-player-thumb]");
  const closeButton = bar.querySelector("[data-mini-player-close]");
  if (!audio || !playPauseButton || !seek) return;

  const saveIntervalSeconds = 5;
  const minimumResumeSeconds = RESUME_MINIMUM_SECONDS;
  const endBufferSeconds = RESUME_END_BUFFER_SECONDS;
  let lastSavedAt = 0;
  let watchedSeconds = 0;
  let lastTrackedTime = null;
  let seeking = false;
  // The phone layout has no seek bar: its time text sits after the channel name.
  let hasChannel = false;
  let detailPath = "";
  // Même rôle que dans bindResumableMedia : reprise à reposer tant que la
  // lecture n'a pas effectivement démarré au bon endroit.
  let pendingResume = null;

  function writePosition() {
    const storageKey = audio.dataset.resumeKey;
    if (pendingResume !== null) return;
    if (!storageKey || !Number.isFinite(audio.currentTime) || audio.currentTime < minimumResumeSeconds) return;
    writeStoredResume(storageKey, audio.currentTime);
    lastSavedAt = audio.currentTime;
  }

  function seekToPendingResume() {
    if (pendingResume === null || Math.abs(audio.currentTime - pendingResume) < 1) return;
    // Même raison que dans bindResumableMedia : la reprise ne doit pas
    // désarmer le segment dans lequel elle atterrit.
    audio.sponsorSkipController?.markInternalSeek();
    audio.currentTime = pendingResume;
    lastSavedAt = pendingResume;
  }

  function trackWatchedTime(force = false) {
    if ((!force && audio.paused) || audio.seeking || !Number.isFinite(audio.currentTime)) {
      lastTrackedTime = Number.isFinite(audio.currentTime) ? audio.currentTime : null;
      return;
    }
    if (lastTrackedTime !== null) {
      const delta = audio.currentTime - lastTrackedTime;
      if (delta > 0 && delta < 5) watchedSeconds += delta;
    }
    lastTrackedTime = audio.currentTime;
  }

  function logActivity() {
    trackWatchedTime(true);
    const activityUrl = audio.dataset.activityUrl;
    if (!activityUrl || watchedSeconds < 1) return;
    reportPlayback(activityUrl, "audio", audio, watchedSeconds);
    watchedSeconds = 0;
  }

  function updatePlayPauseUI() {
    playPauseButton.textContent = audio.paused ? "▶" : "⏸";
    playPauseButton.setAttribute("aria-label", audio.paused ? "Lecture" : "Pause");
  }

  let lastMetaTime = "";
  function updateMetaTime() {
    if (!metaTimeEl) return;
    const text =
      (hasChannel ? " · " : "") +
      `${formatMiniPlayerTime(audio.currentTime)} / ${formatMiniPlayerTime(audio.duration)}`;
    // timeupdate fires several times a second but the text changes once a second.
    if (text === lastMetaTime) return;
    lastMetaTime = text;
    metaTimeEl.textContent = text;
  }

  function updateProgressUI() {
    updateMetaTime();
    if (!seeking) {
      if (Number.isFinite(audio.duration) && audio.duration > 0) {
        seek.value = String((audio.currentTime / audio.duration) * 100);
      }
      currentTimeEl.textContent = formatMiniPlayerTime(audio.currentTime);
      durationEl.textContent = formatMiniPlayerTime(audio.duration);
    }
    paintSeekRange(seek, audio);
  }

  audio.addEventListener("loadedmetadata", () => {
    const position = resolveResumePosition(
      audio.dataset.resumeKey,
      audio.dataset.resumeServerPosition,
      audio.dataset.resumeServerAt
    );
    if (position !== null && position >= minimumResumeSeconds) {
      const nearEnd = Number.isFinite(audio.duration) && position > audio.duration - endBufferSeconds;
      if (!nearEnd) {
        pendingResume = position;
        seekToPendingResume();
      }
    }
    updateProgressUI();
  });

  audio.addEventListener("raton:user-seek", () => {
    pendingResume = null;
  });

  audio.addEventListener("seeking", () => {
    if (pendingResume === null) return;
    if (audio.currentTime >= minimumResumeSeconds && Math.abs(audio.currentTime - pendingResume) >= 1) {
      pendingResume = null;
    }
  });

  audio.addEventListener("timeupdate", () => {
    if (pendingResume !== null) {
      if (audio.paused || audio.seeking) return;
      if (audio.currentTime < minimumResumeSeconds) {
        // La lecture a démarré à 0 : le seek de reprise a été ignoré.
        seekToPendingResume();
        return;
      }
      pendingResume = null;
    }
    trackWatchedTime();
    updateProgressUI();
    if (Math.abs(audio.currentTime - lastSavedAt) >= saveIntervalSeconds) writePosition();
  });

  audio.addEventListener("play", () => {
    lastTrackedTime = Number.isFinite(audio.currentTime) ? audio.currentTime : null;
    updatePlayPauseUI();
  });

  audio.addEventListener("pause", () => {
    writePosition();
    logActivity();
    updatePlayPauseUI();
  });

  audio.addEventListener("ended", () => {
    const storageKey = audio.dataset.resumeKey;
    if (storageKey) resetStoredResume(storageKey);
    logActivity();
    updatePlayPauseUI();
  });

  playPauseButton.addEventListener("click", () => {
    if (audio.paused) audio.play();
    else audio.pause();
  });

  bar.querySelectorAll("[data-mini-player-skip]").forEach((button) => {
    button.addEventListener("click", () => {
      const delta = Number.parseFloat(button.dataset.miniPlayerSkip || "0");
      const upperBound = Number.isFinite(audio.duration) ? audio.duration : Infinity;
      audio.currentTime = Math.min(Math.max(audio.currentTime + delta, 0), upperBound);
    });
  });

  seek.addEventListener("input", () => {
    seeking = true;
    if (Number.isFinite(audio.duration)) {
      currentTimeEl.textContent = formatMiniPlayerTime((Number(seek.value) / 100) * audio.duration);
    }
    paintSeekRange(seek, audio);
  });
  seek.addEventListener("change", () => {
    if (Number.isFinite(audio.duration)) {
      audio.currentTime = (Number(seek.value) / 100) * audio.duration;
    }
    seeking = false;
  });

  // The link goes to the audio slide of the playing video. When that page is
  // already open, Turbo would only treat the hash as an anchor jump, so the
  // pager is asked to show its audio slide instead.
  openLink?.addEventListener("click", (event) => {
    if (!detailPath) {
      event.preventDefault();
      return;
    }
    if (new URL(detailPath, window.location.href).pathname === window.location.pathname) {
      event.preventDefault();
      document.dispatchEvent(new CustomEvent("raton:show-audio-slide"));
    }
  });

  closeButton?.addEventListener("click", () => {
    audio.pause();
    writePosition();
    logActivity();
    audio.removeAttribute("src");
    // Sans ça les segments de la piste fermée resteraient armés sur un élément
    // sans source : un `timeupdate` à 0 s pourrait entrer dans un segment
    // commençant à 0 et laisser un seek interne en attente indéfiniment.
    audio.sponsorSkipController?.setSegments([]);
    delete audio.dataset.trackId;
    bar.hidden = true;
    document.body.classList.remove("has-mini-player");
  });

  // Bound once (this element is never destroyed), so no { once: true }/leak
  // concern here the way there is in bindResumableMedia for per-page media.
  window.addEventListener("pagehide", () => {
    writePosition();
    logActivity();
  });

  window.ratonMiniPlayer = {
    load(track) {
      if (audio.dataset.trackId === String(track.id)) {
        if (audio.paused) audio.play().catch(() => {});
        return;
      }
      if (audio.dataset.trackId) {
        writePosition();
        logActivity();
      }
      audio.dataset.trackId = track.id;
      audio.dataset.resumeKey = track.resumeKey || "";
      audio.dataset.resumeServerPosition = track.resumeServerPosition || "";
      audio.dataset.resumeServerAt = track.resumeServerAt || "";
      pendingResume = null;
      audio.dataset.activityUrl = track.activityUrl || "";
      audio.src = track.src;
      // Le mini-lecteur se lance depuis n'importe quelle liste : les segments ne
      // sont pas dans le DOM de la page courante, il faut les demander.
      const sponsorSkip = bindSponsorSkip(audio, { visual: false });
      sponsorSkip.setSegments([]);
      fetch(`/api/videos/${track.id}/sponsor-segments`, { headers: { Accept: "application/json" } })
        .then((response) => (response.ok ? response.json() : null))
        .then((payload) => {
          if (!payload || !payload.skip_enabled) return;
          // Une réponse lente ne doit pas armer les segments d'une piste que
          // l'utilisateur a déjà quittée.
          if (audio.dataset.trackId !== String(track.id)) return;
          sponsorSkip.setSegments(payload.segments || []);
        })
        .catch(() => {});
      watchedSeconds = 0;
      lastTrackedTime = null;
      lastSavedAt = 0;
      if (titleEl) titleEl.textContent = track.title || "";
      if (openLink) {
        // A video with both formats opens on its video slide by default: the
        // fragment makes the pager open on the audio one.
        detailPath = (track.detailUrl || "").split("#")[0];
        openLink.setAttribute("href", detailPath ? `${detailPath}#audio` : "#");
      }
      hasChannel = Boolean(track.channel);
      if (channelEl) channelEl.textContent = track.channel || "";
      updateMetaTime();
      if (thumbEl) {
        if (track.thumb) {
          thumbEl.src = track.thumb;
          thumbEl.hidden = false;
        } else {
          thumbEl.removeAttribute("src");
          thumbEl.hidden = true;
        }
      }
      bar.hidden = false;
      document.body.classList.add("has-mini-player");
      audio.play().catch(() => {});
    },
    isCurrent(id) {
      return audio.dataset.trackId === String(id);
    },
    // Relative seek for the page-level controls (video_detail media pager).
    skip(id, seconds) {
      if (audio.dataset.trackId !== String(id)) return false;
      const upperBound = Number.isFinite(audio.duration) ? audio.duration : Infinity;
      audio.currentTime = Math.min(Math.max(audio.currentTime + seconds, 0), upperBound);
      audio.dispatchEvent(new CustomEvent("raton:user-seek"));
      return true;
    },
    // Absolute seek for the page-level slider (video_detail media pager).
    seekTo(id, seconds) {
      if (audio.dataset.trackId !== String(id)) return false;
      const upperBound = Number.isFinite(audio.duration) ? audio.duration : Infinity;
      audio.currentTime = Math.min(Math.max(seconds, 0), upperBound);
      audio.dispatchEvent(new CustomEvent("raton:user-seek"));
      return true;
    },
    audioElement() {
      return audio;
    },
    isPlaying(id) {
      return audio.dataset.trackId === String(id) && !audio.paused;
    },
    toggle(id) {
      if (audio.dataset.trackId !== String(id)) return false;
      if (audio.paused) audio.play().catch(() => {});
      else audio.pause();
      return true;
    },
  };
}

// Video/audio pager of /videos/{id} (phone layout, see .media-pager in the CSS).
// The slides never download anything themselves: their buttons drive the
// Audio/Video toggles of the (hidden on phones) format action bar, so the
// download queue, the polling and the delete route stay in one place. Each
// slide's data-state (idle, busy, ok, ready) is derived from the state
// classes those toggles end up with.
function bindMediaPager(pager) {
  if (pager.dataset.mediaPagerBound) return;
  pager.dataset.mediaPagerBound = "true";
  const videoId = pager.dataset.videoId;
  const track = pager.querySelector("[data-media-pager-track]");
  const slides = [...pager.querySelectorAll("[data-media-slide]")];
  const dots = [...pager.querySelectorAll("[data-media-dot]")];
  const actions = pager.closest(".video-detail-card")?.querySelector("[data-video-format-actions]");
  const allowDelete = actions?.dataset.allowDelete === "true";
  if (!track || slides.length === 0) return;

  function scrollToSlide(index, smooth) {
    const slide = slides[index];
    if (!slide) return;
    // The track is not a positioned element, so offsetLeft would be measured
    // from some ancestor: work from bounding boxes instead.
    const trackRect = track.getBoundingClientRect();
    const slideRect = slide.getBoundingClientRect();
    const delta = slideRect.left + slideRect.width / 2 - (trackRect.left + trackRect.width / 2);
    track.scrollTo({ left: Math.max(0, track.scrollLeft + delta), behavior: smooth ? "smooth" : "auto" });
  }

  function syncDots() {
    const trackRect = track.getBoundingClientRect();
    const center = trackRect.left + trackRect.width / 2;
    let active = 0;
    let best = Infinity;
    slides.forEach((slide, index) => {
      const rect = slide.getBoundingClientRect();
      const distance = Math.abs(rect.left + rect.width / 2 - center);
      if (distance < best) {
        best = distance;
        active = index;
      }
    });
    dots.forEach((dot, index) => dot.classList.toggle("media-pager-dot-active", index === active));
  }

  track.addEventListener("scroll", () => window.requestAnimationFrame(syncDots), { passive: true });
  dots.forEach((dot, index) => dot.addEventListener("click", () => scrollToSlide(index, true)));
  // An audio-only video opens on its audio slide.
  const slideMemoryKey = `raton:pager-slide:${videoId}`;
  let remembered = null;
  try {
    remembered = window.sessionStorage.getItem(slideMemoryKey);
    window.sessionStorage.removeItem(slideMemoryKey);
  } catch (error) {
    // Storage unavailable: fall back to data-initial.
  }
  window.requestAnimationFrame(() => {
    // An explicit #audio (mini-player link) beats the remembered slide; the
    // post-download reload strips the hash so that it does not override it.
    if (window.location.hash === "#audio") scrollToSlide(1, false);
    else if (remembered !== null) scrollToSlide(Number.parseInt(remembered, 10) || 0, false);
    else if (pager.dataset.initial === "audio") scrollToSlide(1, false);
    syncDots();
  });

  function activeSlideIndex() {
    return dots.findIndex((dot) => dot.classList.contains("media-pager-dot-active"));
  }

  // Asked by the mini-player link when this video's page is already open. The
  // listener lives on `document`, which outlives the page: drop it as soon as
  // Turbo swaps the page out.
  function showAudioSlide() {
    const audioSlide = slides.find((slide) => slide.dataset.mediaSlide === "audio");
    audioSlide?.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "center" });
  }
  function unbindShowAudioSlide() {
    document.removeEventListener("raton:show-audio-slide", showAudioSlide);
    document.removeEventListener("turbo:before-render", unbindShowAudioSlide);
  }
  document.addEventListener("raton:show-audio-slide", showAudioSlide);
  document.addEventListener("turbo:before-render", unbindShowAudioSlide);

  // A reload swaps in the server-rendered player. It waits for the other slide's
  // download (the reload would drop its tracking) and reopens on the slide the
  // reader is looking at.
  function refreshPage() {
    if (slides.some((slide) => slide.dataset.state === "busy")) {
      pager.dataset.refreshPending = "true";
      return;
    }
    delete pager.dataset.refreshPending;
    try {
      window.sessionStorage.setItem(slideMemoryKey, String(activeSlideIndex()));
    } catch (error) {
      // Private mode: the page then reopens on its default slide.
    }
    if (window.Turbo) window.Turbo.visit(window.location.href.split("#")[0], { action: "replace" });
    else window.location.reload();
  }

  slides.forEach((slide) => {
    const format = slide.dataset.mediaSlide;
    const toggle = actions?.querySelector(`[data-format-toggle][data-format="${format}"]`);
    if (!toggle) return;

    let settleTimer = null;
    function begin(kind, quality) {
      // Same guards as the action bar's own click handler.
      if (toggle.disabled || toggle.dataset.formatBusy) return;
      if (kind === "delete" && !allowDelete) return;
      window.clearTimeout(settleTimer);
      slide.dataset.pending = kind;
      if (kind === "delete") startFormatDelete(toggle, videoId);
      else startFormatDownload(toggle, videoId, quality, allowDelete);
    }

    slide.querySelector("[data-media-download]")?.addEventListener("click", () => {
      if (format === "video") {
        // The quality picker is the same list as the toggle's popover.
        const picker = slide.querySelector("[data-media-quality]");
        if (picker) picker.hidden = !picker.hidden;
        return;
      }
      begin("download", null);
    });
    slide.querySelectorAll("[data-media-quality-option]").forEach((option) => {
      option.addEventListener("click", () => {
        slide.querySelector("[data-media-quality]").hidden = true;
        begin("download", option.dataset.quality);
      });
    });
    if (!allowDelete) slide.querySelector("[data-media-delete]")?.remove();
    slide.querySelector("[data-media-delete]")?.addEventListener("click", () => {
      const noun = format === "audio" ? "l’audio" : "la vidéo";
      if (!window.confirm(`Supprimer ${noun} ?`)) return;
      begin("delete");
    });

    let wasLoading = toggle.classList.contains("format-toggle-loading");
    new MutationObserver(() => {
      const loading = toggle.classList.contains("format-toggle-loading");
      const active = toggle.classList.contains("format-toggle-active");
      const failed = toggle.classList.contains("format-toggle-error");
      const pending = slide.dataset.pending || "download";
      if (loading) {
        slide.dataset.state = "busy";
      } else if (wasLoading && failed) {
        slide.dataset.state = pending === "delete" ? "ready" : "idle";
        if (window.showToast) window.showToast(toggle.title, "error");
      } else if (wasLoading && pending === "delete" && !active) {
        slide.dataset.state = "idle";
        slide.classList.remove("is-revealing");
        // The player of a removed video is still in the page: reload it away.
        if (format === "video") settleTimer = window.setTimeout(refreshPage, 300);
      } else if (wasLoading && active) {
        slide.dataset.state = "ok";
        if (format === "video") {
          // The <video> element only exists server-side: show the check, then reload.
          settleTimer = window.setTimeout(refreshPage, 1400);
        } else {
          settleTimer = window.setTimeout(() => {
            slide.classList.add("is-revealing");
            slide.dataset.state = "ready";
          }, 900);
        }
      }
      wasLoading = loading;
      if (!loading && pager.dataset.refreshPending) window.setTimeout(refreshPage, 0);
    }).observe(toggle, { attributes: true, attributeFilter: ["class"] });
  });

  bindPagerAudioControls(pager);
}

function bindPagerAudioControls(pager) {
  const panel = pager.querySelector("[data-media-panel='audio']");
  const player = window.ratonMiniPlayer;
  if (!panel || !player) return;
  const id = panel.dataset.trackId;
  const playButton = panel.querySelector("[data-audio-play]");
  const seekEl = panel.querySelector("[data-media-seek]");
  const bubbleEl = panel.querySelector("[data-media-seek-bubble]");
  const currentEl = panel.querySelector("[data-media-time-current]");
  const durationEl = panel.querySelector("[data-media-time-duration]");
  const audio = player.audioElement();

  playButton?.addEventListener("click", () => {
    if (player.toggle(id)) return;
    player.load(trackFromDataset(panel));
  });
  panel.querySelectorAll("[data-audio-skip]").forEach((button) => {
    button.addEventListener("click", () => {
      player.skip(id, Number.parseFloat(button.dataset.audioSkip || "0"));
    });
  });

  // The slider is only live once this video is the loaded track: before that
  // there is nothing to seek in.
  let dragging = false;
  let dragFraction = 0;
  const SEEK_PADDING = 16; // keep in sync with .media-seek-track in the CSS

  function seekable() {
    return player.isCurrent(id) && Number.isFinite(audio.duration) && audio.duration > 0;
  }

  function renderSeek(fraction) {
    if (!seekEl) return;
    const percent = Math.min(1, Math.max(0, fraction)) * 100;
    const seconds = (percent / 100) * (Number.isFinite(audio.duration) ? audio.duration : 0);
    seekEl.style.setProperty("--seek-progress", String(percent));
    seekEl.style.setProperty("--seek-buffered", String(player.isCurrent(id) ? bufferedPercent(audio) : 0));
    seekEl.setAttribute("aria-valuenow", String(Math.round(percent)));
    seekEl.setAttribute("aria-valuetext", formatMiniPlayerTime(seconds));
    if (bubbleEl) bubbleEl.textContent = formatMiniPlayerTime(seconds);
    if (currentEl) currentEl.textContent = formatMiniPlayerTime(seconds);
  }

  function fractionFromPointer(event) {
    const rect = seekEl.getBoundingClientRect();
    const usable = Math.max(1, rect.width - 2 * SEEK_PADDING);
    return Math.min(1, Math.max(0, (event.clientX - rect.left - SEEK_PADDING) / usable));
  }

  function endDrag(commit) {
    if (!dragging) return;
    dragging = false;
    seekEl.classList.remove("is-dragging");
    if (bubbleEl) bubbleEl.hidden = true;
    // Seek once, on release: seeking a streamed file on every move is jerky.
    if (commit && seekable()) player.seekTo(id, dragFraction * audio.duration);
    sync();
  }

  if (seekEl) {
    seekEl.addEventListener("pointerdown", (event) => {
      // Primary button / touch / pen only: a right click would open a context
      // menu and never deliver the pointerup.
      if (event.button > 0 || !seekable()) return;
      dragging = true;
      seekEl.classList.add("is-dragging");
      if (bubbleEl) bubbleEl.hidden = false;
      try {
        seekEl.setPointerCapture(event.pointerId);
      } catch (error) {
        // Capture is a convenience: the slider still follows the pointer without it.
      }
      dragFraction = fractionFromPointer(event);
      renderSeek(dragFraction);
    });
    seekEl.addEventListener("pointermove", (event) => {
      if (!dragging) return;
      dragFraction = fractionFromPointer(event);
      renderSeek(dragFraction);
    });
    seekEl.addEventListener("pointerup", () => endDrag(true));
    seekEl.addEventListener("pointercancel", () => endDrag(false));
    // Capture lost without pointerup (released outside the window, ...). After
    // a normal pointerup this is a no-op: endDrag already ran.
    seekEl.addEventListener("lostpointercapture", () => endDrag(false));
    seekEl.addEventListener("keydown", (event) => {
      const step = { ArrowLeft: -5, ArrowDown: -5, ArrowRight: 5, ArrowUp: 5, PageDown: -30, PageUp: 30 }[event.key];
      if (step !== undefined) {
        event.preventDefault();
        player.skip(id, step);
      } else if ((event.key === "Home" || event.key === "End") && seekable()) {
        event.preventDefault();
        player.seekTo(id, event.key === "Home" ? 0 : audio.duration);
      }
    });
  }

  const events = ["play", "pause", "ended", "timeupdate", "progress", "loadedmetadata", "durationchange", "emptied"];
  function sync() {
    // The mini player's <audio> outlives this page (Turbo permanent node):
    // stop listening once the panel has been swapped out.
    if (!panel.isConnected) {
      events.forEach((name) => audio.removeEventListener(name, sync));
      return;
    }
    const current = player.isCurrent(id);
    panel.classList.toggle("is-playing", player.isPlaying(id));
    seekEl?.classList.toggle("is-inert", !seekable());
    const position = current && Number.isFinite(audio.currentTime) ? audio.currentTime : 0;
    const duration = current && Number.isFinite(audio.duration) ? audio.duration : 0;
    if (durationEl) durationEl.textContent = duration > 0 ? formatMiniPlayerTime(duration) : "--:--";
    // While the thumb is being dragged it shows the target, not the playback position.
    if (dragging) return;
    if (currentEl) currentEl.textContent = formatMiniPlayerTime(position);
    renderSeek(duration > 0 ? position / duration : 0);
  }
  events.forEach((name) => audio.addEventListener(name, sync));
  sync();
}

// Mini-player track description carried by data-track-* attributes (the
// "Écouter" trigger and the media pager's audio panel use the same set).
function trackFromDataset(element) {
  const data = element.dataset;
  return {
    id: data.trackId,
    title: data.trackTitle,
    channel: data.trackChannel,
    src: data.trackSrc,
    thumb: data.trackThumb,
    resumeKey: data.trackResumeKey,
    resumeServerPosition: data.trackResumeServerPosition,
    resumeServerAt: data.trackResumeServerAt,
    activityUrl: data.trackActivityUrl,
    detailUrl: data.trackDetailUrl,
  };
}

// Unlike initMiniPlayer, these trigger buttons live on ordinary (non-permanent)
// pages, so a full Turbo Drive visit gives fresh elements automatically. A
// <turbo-frame> swap does NOT re-run this script, though, so `turbo:frame-load`
// below re-binds just the swapped-in frame's buttons (dataset guards make both
// binders idempotent).
function bindPlayTrackButtons(root = document) {
  root.querySelectorAll("[data-play-track]").forEach((button) => {
    if (button.dataset.playTrackBound) return;
    button.dataset.playTrackBound = "true";
    const icon = button.querySelector("[data-play-track-icon]");
    const label = button.querySelector("[data-play-track-label]");

    function syncState() {
      const player = window.ratonMiniPlayer;
      const id = button.dataset.trackId;
      const playing = Boolean(player && player.isPlaying(id));
      const current = Boolean(player && player.isCurrent(id));
      if (icon) icon.textContent = playing ? "⏸" : "▶";
      if (label) label.textContent = current ? (playing ? "En cours de lecture" : "En pause") : "Écouter";
    }

    syncState();
    button.addEventListener("click", (event) => {
      event.preventDefault();
      const player = window.ratonMiniPlayer;
      if (!player) return;
      const id = button.dataset.trackId;
      if (!player.toggle(id)) {
        player.load(trackFromDataset(button));
      }
      syncState();
    });
  });
}

// One-shot toasts: closed by hand or after a delay, and their trigger query
// parameters (space-separated in data-toast-param) are dropped from the URL
// so a reload does not show them again.
function initToasts() {
  document.querySelectorAll("[data-toast]").forEach((toast) => {
    const params = (toast.dataset.toastParam || "").split(" ").filter(Boolean);
    const url = new URL(window.location.href);
    if (params.some((param) => url.searchParams.has(param))) {
      params.forEach((param) => url.searchParams.delete(param));
      window.history.replaceState(window.history.state, "", url.pathname + url.search + url.hash);
    }
    const close = () => toast.remove();
    toast.querySelector("[data-toast-close]")?.addEventListener("click", close);
    window.setTimeout(close, 8000);
  });
}

// For results that arrive without a page load (the server-rendered toasts in
// base.html only exist after one).
window.showToast = function (message, level, href) {
  const stack = document.querySelector(".toast-stack");
  if (!stack) return;
  const toast = document.createElement("div");
  toast.className = level === "error" ? "toast error" : "toast";
  toast.setAttribute("role", level === "error" ? "alert" : "status");
  toast.dataset.turboTemporary = "";
  const text = document.createElement("p");
  text.className = "toast-text";
  text.textContent = message;
  const closeButton = document.createElement("button");
  closeButton.className = "toast-close";
  closeButton.type = "button";
  closeButton.setAttribute("aria-label", "Fermer la notification");
  closeButton.textContent = "×";
  closeButton.addEventListener("click", () => toast.remove());
  toast.append(text);
  if (href) {
    const link = document.createElement("a");
    link.className = "toast-link";
    link.href = href;
    link.textContent = "Voir";
    toast.append(link);
  }
  toast.append(closeButton);
  stack.append(toast);
  // A scan can emit dozens of events: keep the newest few readable instead of filling the screen.
  while (stack.children.length > 5) stack.firstElementChild.remove();
  window.setTimeout(() => toast.remove(), 8000);
};

// "Lancer le scan maintenant" (settings): starts the scan, then shows each event of its feed as a
// toast until the final one. Also follows a scan already running when the page opens (3am cron).
function initScanRunner() {
  const button = document.querySelector("[data-scan-run]");
  if (!button) return;
  let after = Number.parseInt(button.dataset.scanAfter || "0", 10) || 0;
  let polling = false;

  const setBusy = (busy) => {
    button.disabled = busy;
    button.textContent = busy ? "Scan en cours…" : "Lancer le scan maintenant";
  };

  async function poll() {
    if (polling) return;
    polling = true;
    setBusy(true);
    let quiet = 0;
    try {
      while (true) {
        const feed = await apiRequest("GET", `${button.dataset.scanFeedUrl}?after=${after}`).catch(() => {
          throw new Error("Impossible de lire la progression du scan.");
        });
        after = feed.last_id;
        let finished = false;
        feed.events.forEach((event) => {
          window.showToast(event.message, event.level === "error" ? "error" : "info");
          if (event.final) finished = true;
        });
        // The cron or another tab may have finished between two polls: stop once nothing runs.
        quiet = feed.events.length ? 0 : quiet + 1;
        if (finished || (!feed.running && quiet >= 3)) break;
        await new Promise((resolve) => window.setTimeout(resolve, 1500));
      }
    } catch (error) {
      window.showToast(error.message, "error");
    } finally {
      polling = false;
      setBusy(false);
    }
  }

  button.addEventListener("click", async () => {
    setBusy(true);
    try {
      ({ after } = await apiRequest("POST", button.dataset.scanUrl));
      poll();
    } catch (error) {
      window.showToast(error.message || "Le scan n'a pas pu démarrer.", "error");
      // 409: a scan already runs, follow it instead.
      if (error.status === 409) poll();
      else setBusy(false);
    }
  });

  if (button.dataset.scanRunning === "true") poll();
}

initScanRunner();

// "Commencer l'exploration" / "Explorer la suite" (channel page): the import runs in the background
// while Raton, fixed at the bottom of the page, keeps count. Each fiche is added to the grid as soon
// as its metadata is imported. The state lives on `window` because this file runs again on every
// Turbo visit while the import goes on; the single polling chain started by the first run keeps going
// across pages; Raton is only shown on the channel's page, and the end of the exploration gives one
// toast (plus one system notification when the tab is hidden) elsewhere. The state is also kept in
// sessionStorage so a page reload picks the exploration up again, and Raton's X cancels the job.
function initExplorer() {
  const raton = () => document.querySelector("[data-explorer-raton]");
  const plural = (count) => `${count} fiche${count > 1 ? "s" : ""}`;
  const STORAGE_KEY = "raton:explorer";
  const MAX_AGE_MS = 30 * 60 * 1000;

  function saveState(state) {
    try {
      if (!state) {
        window.sessionStorage.removeItem(STORAGE_KEY);
        return;
      }
      const { seen, ...rest } = state;
      window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(rest));
    } catch {
      // Private mode or blocked storage: the exploration just does not survive a reload.
    }
  }

  function restoreState() {
    try {
      const stored = JSON.parse(window.sessionStorage.getItem(STORAGE_KEY) || "null");
      if (!stored || !stored.running || Date.now() - stored.startedAt > MAX_AGE_MS) {
        saveState(null);
        return null;
      }
      return { ...stored, seen: new Set() };
    } catch {
      return null;
    }
  }

  function setRunning(running) {
    const element = raton();
    if (element) element.dataset.running = running ? "true" : "false";
  }

  function say(text) {
    const element = raton();
    if (!element) return;
    element.querySelector("[data-explorer-raton-text]").textContent = text;
    const state = window.__ptExplorer;
    // Raton belongs to the channel page being explored: on any other page he stays out of sight.
    element.hidden = Boolean(state && !matchingGrid(state));
  }

  // Run on every page load: Raton follows the exploration only while its channel page is shown.
  function syncRaton() {
    const element = raton();
    const state = window.__ptExplorer;
    if (!element || !state || !state.running) return;
    element.hidden = !matchingGrid(state);
    setRunning(true);
  }

  function hideLater(delay) {
    window.setTimeout(() => {
      const element = raton();
      if (element && !(window.__ptExplorer && window.__ptExplorer.running)) element.hidden = true;
    }, delay);
  }

  function setFormLocked(form, locked) {
    form.querySelectorAll("button").forEach((button) => {
      button.disabled = locked;
    });
    const hint = form.querySelector("[data-explore-hint]");
    if (hint) hint.hidden = locked;
  }

  function matchingGrid(state) {
    const grid = document.querySelector("[data-explore-grid]");
    if (grid && grid.dataset.channelId === state.channelId && grid.dataset.section === state.section) return grid;
    return null;
  }

  async function insertCards(state, grid, videos) {
    // After a reload the page already shows the fiches imported meanwhile.
    videos = videos.filter((video) => !grid.querySelector(`article[data-video-id="${video.id}"]`));
    if (!videos.length) return;
    const params = new URLSearchParams({
      ids: videos.map((video) => video.id).join(","),
      section: state.section,
      next: `${window.location.pathname}${window.location.search}`,
    });
    const response = await fetch(`/videos/cards?${params}`, { headers: { Accept: "text/html" } });
    if (!response.ok) return;
    const template = document.createElement("template");
    template.innerHTML = await response.text();
    template.content
      .querySelectorAll("form[data-async-download], form[data-async-job]")
      .forEach(bindAsyncJobForm);
    // The page must not move when a card arrives (the reader may be looking at the button below).
    const scrollY = window.scrollY;
    grid.querySelector(".channel-empty")?.remove();
    grid.append(template.content);
    window.scrollTo(window.scrollX, scrollY);
    const counter = document.querySelector("[data-explore-count]");
    if (counter) {
      const total = Number.parseInt(counter.dataset.exploreCount || "0", 10) + videos.length;
      counter.dataset.exploreCount = String(total);
      counter.textContent = plural(total);
    }
  }

  // One system notification for the whole exploration (not one per fiche), only when the tab is hidden.
  function notifyDone(state, summary) {
    if (!document.hidden || !("Notification" in window) || Notification.permission !== "granted") return;
    const notification = new Notification("Raton a fini l'exploration", {
      body: state.channelName ? `${summary} (${state.channelName})` : summary,
      tag: "raton-explore-done",
      icon: "/static/img/apple-touch-icon.png",
    });
    notification.onclick = () => {
      window.focus();
      window.location.assign(state.returnTo);
      notification.close();
    };
  }

  function finish(state, job, failed) {
    state.running = false;
    saveState(null);
    setRunning(false);
    document.documentElement.classList.remove("explore-running");
    const grid = matchingGrid(state);
    if (failed) {
      const message = job.message || "L'exploration a échoué.";
      say(`Aïe, ça n'a pas marché. ${message}`);
      window.showToast(message, "error");
      document.querySelectorAll("form[data-explore]").forEach((form) => setFormLocked(form, false));
      hideLater(8000);
      return;
    }
    const cancelled = job.status === "cancelled";
    const summary = cancelled
      ? state.count
        ? `Exploration arrêtée, ${plural(state.count)} récupérée${state.count > 1 ? "s" : ""}.`
        : "Exploration arrêtée."
      : state.count
        ? `Voilà, ${plural(state.count)} récupérée${state.count > 1 ? "s" : ""} !`
        : "Rien de nouveau à récupérer.";
    say(summary);
    hideLater(4000);
    if (state.count && !cancelled) notifyDone(state, summary);
    if (grid) {
      // Reload the page quietly: order, pagination, count and the button label come back from the server.
      const scrollY = window.scrollY;
      document.addEventListener("turbo:load", () => window.scrollTo(0, scrollY), { once: true });
      if (window.Turbo) window.Turbo.visit(window.location.href, { action: "replace" });
      else window.location.reload();
    } else {
      window.showToast(summary, "info", state.returnTo);
    }
  }

  async function tick() {
    const state = window.__ptExplorer;
    if (!state || !state.running) return;
    try {
      const job = await apiRequest("GET", state.statusUrl);
      const fresh = (job.videos || []).filter((video) => !state.seen.has(video.id));
      if (fresh.length) {
        fresh.forEach((video) => state.seen.add(video.id));
        state.count = state.seen.size;
        const grid = matchingGrid(state);
        if (grid) await insertCards(state, grid, fresh);
        say(`Je m'en occupe ! ${state.count}/${state.expected}`);
      }
      if (job.status === "failed") finish(state, job, true);
      else if (job.done) finish(state, job, false);
      else window.setTimeout(tick, 1500);
    } catch (error) {
      finish(state, { message: error.message }, true);
    }
  }

  function bindExploreForm(form) {
    const running = window.__ptExplorer && window.__ptExplorer.running;
    if (running && window.__ptExplorer.channelId === form.dataset.channelId) setFormLocked(form, true);

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (window.__ptExplorer && window.__ptExplorer.running) return;
      setFormLocked(form, true);
      // Asked on the click itself (a user gesture), not awaited: the import must not wait for the answer.
      if ("Notification" in window && Notification.permission === "default") {
        try {
          Notification.requestPermission();
        } catch {
          // Some browsers refuse outside a gesture or do not support it: toasts still work.
        }
      }
      // Forget the previous exploration so Raton is judged against this page only.
      window.__ptExplorer = null;
      setRunning(true);
      say("Je m'en occupe !");
      try {
        const data = new FormData(form);
        const payload = await apiRequest("POST", form.dataset.apiAction, {
          page: Number.parseInt(data.get("page"), 10) || 1,
          section: data.get("section") || "videos",
        });
        window.__ptExplorer = {
          running: true,
          statusUrl: payload.status_url,
          returnTo: data.get("next") || `${window.location.pathname}${window.location.search}`,
          channelId: form.dataset.channelId,
          channelName: form.dataset.channelName || "",
          section: form.dataset.section,
          expected: Number.parseInt(form.dataset.expected || "25", 10) || 25,
          startedAt: Date.now(),
          seen: new Set(),
          count: 0,
        };
        saveState(window.__ptExplorer);
        document.documentElement.classList.add("explore-running");
        tick();
      } catch (error) {
        setFormLocked(form, false);
        setRunning(false);
        say(`Aïe, ça n'a pas marché. ${error.message}`);
        hideLater(6000);
      }
    });
  }

  const stopButton = document.querySelector("[data-explorer-raton-stop]");
  if (stopButton && !stopButton.dataset.bound) {
    // The button lives in the permanent Raton: bound once, it works on every page.
    stopButton.dataset.bound = "true";
    stopButton.addEventListener("click", async () => {
      const state = window.__ptExplorer;
      if (!state || !state.running) return;
      stopButton.disabled = true;
      say("J'arrête là…");
      try {
        await apiRequest("POST", `${state.statusUrl}/cancel`);
      } catch {
        // The polling reports the real state; the button comes back below.
      }
      stopButton.disabled = false;
    });
  }

  // Full page load (reload, new tab navigation) while an exploration runs: pick it up again.
  if (!window.__ptExplorer) {
    const restored = restoreState();
    if (restored) {
      window.__ptExplorer = restored;
      document.documentElement.classList.add("explore-running");
      say(`Je m'en occupe ! ${restored.count || 0}/${restored.expected}`);
      setRunning(true);
      tick();
    }
  }

  document.querySelectorAll("form[data-explore]").forEach(bindExploreForm);
  syncRaton();
  // A Turbo visit swaps the body; the permanent Raton must follow the page that is now shown.
  if (!window.__ptExplorerLoadBound) {
    window.__ptExplorerLoadBound = true;
    document.addEventListener("turbo:load", () => window.__ptExplorerSyncRaton && window.__ptExplorerSyncRaton());
  }
  window.__ptExplorerSyncRaton = syncRaton;
}

initExplorer();

// Import sheet (_import_sheet.html): a <details> closed by Escape, a click outside or its close button.
// The sheet's own form (video, playlist or subscriptions, depending on the page) is bound like any page form; the two
// playlist helpers just below used to live in playlists.html.
{
  const form = document.querySelector("[data-playlist-csv-form]");
  if (form) {
    const input = form.querySelector("[data-playlist-csv-input]");
    const titleField = form.querySelector("[data-playlist-csv-title]");
    const label = form.querySelector("[data-playlist-csv-label]");
    if (input && titleField) {
      input.addEventListener("change", () => {
        const file = input.files && input.files[0];
        if (!file) return;
        if (label) label.textContent = file.name;
        if (titleField.value.trim()) return;
        const stem = file.name.replace(/\.csv$/i, "");
        titleField.value = stem.replace(/^(vid[ée]os de|videos de|videos from)\s+/i, "");
      });
    }
  }

  // Preview step of the URL import: nothing is created until "Importer".
  const urlForm = document.querySelector('form[action="/playlists/import-url"]');
  if (urlForm) {
    const urlField = urlForm.querySelector('input[name="url"]');
    const previewButton = urlForm.querySelector("[data-playlist-preview-button]");
    const status = urlForm.querySelector("[data-playlist-preview-status]");
    const card = urlForm.querySelector("[data-playlist-preview]");
    const field = (name) => card.querySelector(`[data-preview-${name}]`);
    const plural = (n, one, many) => `${n} ${n > 1 ? many : one}`;
    // "21 h 40 min" or "40 min", like the playlist header (format_long_duration).
    const longDuration = (seconds) => {
      const minutes = Math.floor((seconds || 0) / 60);
      if (minutes <= 0) return null;
      const hours = Math.floor(minutes / 60);
      return hours ? `${hours} h ${String(minutes % 60).padStart(2, "0")} min` : `${minutes} min`;
    };

    const reset = () => {
      card.hidden = true;
      status.hidden = true;
    };
    const showStatus = (text) => {
      status.textContent = text;
      status.hidden = false;
    };

    const preview = async () => {
      const url = urlField.value.trim();
      if (!url) {
        urlField.focus();
        return;
      }
      card.hidden = true;
      previewButton.disabled = true;
      showStatus("Analyse de la playlist…");
      try {
        // The helper lives in app.js.
        const data = await window.ratonApi("POST", "/api/playlists/preview", { url });

        field("title").textContent = data.title;
        field("channel").textContent = data.channel_name || "";
        field("count").textContent = data.truncated ? `${data.video_count}+` : String(data.video_count);
        const label = longDuration(data.duration_seconds);
        field("duration").textContent = data.unknown_duration_count && label ? `≥ ${label}` : label || "—";
        field("known").textContent = `${data.known_in_library_count} / ${data.video_count}`;
        const notes = [];
        if (data.unavailable_count) notes.push(plural(data.unavailable_count, "vidéo indisponible ou privée", "vidéos indisponibles ou privées"));
        if (data.unknown_duration_count) notes.push(plural(data.unknown_duration_count, "vidéo sans durée connue", "vidéos sans durée connue"));
        if (data.truncated) notes.push("Aperçu limité aux 2000 premières vidéos.");
        field("notes").textContent = notes.join(" · ");
        field("notes").hidden = !notes.length;
        const list = field("titles");
        list.replaceChildren(...data.sample_titles.map((title) => {
          const item = document.createElement("li");
          item.textContent = title;
          return item;
        }));
        status.hidden = true;
        card.hidden = false;
      } catch (error) {
        showStatus(error.message);
      } finally {
        previewButton.disabled = false;
      }
    };

    previewButton.addEventListener("click", preview);
    urlField.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        preview();
      }
    });
    urlField.addEventListener("input", reset);
    urlForm.querySelector("[data-playlist-preview-cancel]").addEventListener("click", reset);
  }
}

document.querySelectorAll("[data-import-fab]").forEach((fab) => {
  // `?import=` opens the sheet server-side (redirects, other pages): drop it so a reload does not reopen it.
  const url = new URL(window.location.href);
  if (fab.open && url.searchParams.has("import")) {
    url.searchParams.delete("import");
    window.history.replaceState(window.history.state, "", url.pathname + url.search + url.hash);
  }
});

// Closes the sheet once its closing animation (`.is-closing`, see the CSS) has played.
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
function closeImportFab(fab) {
  if (!fab.open || fab.classList.contains("is-closing")) return;
  const sheet = fab.querySelector(".import-sheet");
  const finish = () => {
    if (!fab.classList.contains("is-closing")) return; // Reopened meanwhile.
    fab.classList.remove("is-closing");
    fab.removeAttribute("open");
    sheet.style.transform = "";
  };
  if (reducedMotion.matches) {
    fab.classList.add("is-closing");
    finish();
    return;
  }
  fab.classList.add("is-closing");
  sheet.addEventListener("animationend", function onEnd(event) {
    if (event.target !== sheet) return;
    sheet.removeEventListener("animationend", onEnd);
    finish();
  });
  // In case the animation never runs (hidden tab, style not loaded).
  setTimeout(finish, 600);
}

// Phone sheet: pulled down by its grip or title, it follows the finger and closes past a threshold.
document.querySelectorAll("[data-import-fab]").forEach((fab) => {
  const sheet = fab.querySelector(".import-sheet");
  let startY = null;
  let delta = 0;
  fab.querySelectorAll(".import-grip, .import-head").forEach((handle) => {
    handle.addEventListener("pointerdown", (event) => {
      if (!mobileViewport.matches || event.target.closest("[data-import-close]")) return;
      startY = event.clientY;
      delta = 0;
      handle.setPointerCapture(event.pointerId);
    });
    handle.addEventListener("pointermove", (event) => {
      if (startY === null) return;
      delta = Math.max(0, event.clientY - startY);
      sheet.style.transform = `translateY(${delta}px)`;
    });
    const release = () => {
      if (startY === null) return;
      startY = null;
      // Past the threshold the closing animation starts from where the finger left the sheet.
      if (delta > 110) closeImportFab(fab);
      else sheet.style.transform = "";
    };
    handle.addEventListener("pointerup", release);
    handle.addEventListener("pointercancel", release);
  });
});

if (!window.__importFabBound) {
  // Bound once on `document` (see the pull-to-refresh note below); Turbo swaps the <details> itself.
  window.__importFabBound = true;
  const closeAll = () => document.querySelectorAll("[data-import-fab][open]").forEach(closeImportFab);
  document.addEventListener("click", (event) => {
    // A link elsewhere on the page that opens the sheet (empty Playlists page); its href is the no-JS fallback.
    const opener = event.target.closest("[data-import-open]");
    const importFab = opener && document.querySelector("[data-import-fab]");
    if (importFab) {
      event.preventDefault();
      importFab.classList.remove("is-closing");
      importFab.open = true;
      return;
    }
    const button = event.target.closest(".import-fab-button");
    const fab = button && button.closest("[data-import-fab]");
    if (fab && fab.open) {
      // The button closes an open sheet: animated, instead of the <details> default toggle. During the closing
      // animation, it keeps the sheet open.
      event.preventDefault();
      if (fab.classList.contains("is-closing")) {
        fab.classList.remove("is-closing");
        fab.querySelector(".import-sheet").style.transform = "";
      } else {
        closeImportFab(fab);
      }
    } else if (!event.target.closest("[data-import-fab]") || event.target.closest("[data-import-close]")) {
      closeAll();
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeAll();
  });
}

initToasts();
initMiniPlayer();
bindPlayTrackButtons();
document.querySelectorAll("[data-media-pager]").forEach(bindMediaPager);

document.addEventListener("turbo:frame-load", (event) => {
  const frame = event.target;
  frame.querySelectorAll("[data-video-format-actions]").forEach(bindFormatActionContainer);
  bindPlayTrackButtons(frame);
});

// document.body may be a brand new element after a Turbo visit (the mini
// player bar itself survives as a permanent node, but this class doesn't),
// so it has to be re-applied every visit based on the bar's actual state.
const miniPlayerBar = document.querySelector("[data-mini-player]");
if (miniPlayerBar && !miniPlayerBar.hidden) {
  document.body.classList.add("has-mini-player");
}

// Pull-to-refresh: dragging down while already scrolled to the top reloads
// the page. Bound once via a window flag (not the usual per-run re-binding
// pattern) because these are plain `document` listeners with no idempotency
// guard of their own — re-running this on every Turbo visit would stack a
// new set each time. The indicator element is data-turbo-permanent, so it
// survives every navigation including the one this gesture triggers.
if (!window.__pullToRefreshBound) {
  window.__pullToRefreshBound = true;

  const PULL_THRESHOLD = 70;
  const PULL_RESISTANCE = 0.4;
  const PULL_MAX = 90;

  const indicator = document.getElementById("pull-refresh-indicator");

  let startX = null;
  let startY = null;
  let pulling = false;
  let refreshing = false;
  let lastPull = 0;

  function setPull(distance) {
    lastPull = distance;
    if (!indicator) return;
    indicator.style.setProperty("--pull-progress", String(Math.min(distance / PULL_THRESHOLD, 1)));
    indicator.classList.toggle("pull-refresh-ready", distance >= PULL_THRESHOLD);
  }

  function resetPull() {
    startX = null;
    startY = null;
    pulling = false;
    if (refreshing) return;
    setPull(0);
  }

  function startRefresh() {
    refreshing = true;
    pulling = false;
    startX = null;
    startY = null;
    indicator?.classList.add("pull-refresh-loading");
    if (window.Turbo) {
      window.Turbo.visit(window.location.href, { action: "replace" });
    } else {
      window.location.reload();
    }
  }

  document.addEventListener("touchstart", (event) => {
    if (refreshing || event.touches.length !== 1 || window.scrollY > 0) return;
    // Letting the gesture start on a range input (the mini-player seek bar)
    // or a form control would fight the browser's own touch handling for
    // those elements once preventDefault() below kicks in.
    if (event.target.closest("input, textarea, select, [data-mini-player]")) return;
    startX = event.touches[0].clientX;
    startY = event.touches[0].clientY;
    pulling = true;
  }, { passive: true });

  document.addEventListener("touchmove", (event) => {
    if (!pulling || startY === null || refreshing) return;
    if (window.scrollY > 0) {
      resetPull();
      return;
    }
    const deltaX = event.touches[0].clientX - startX;
    const deltaY = event.touches[0].clientY - startY;
    if (deltaY <= 0) {
      setPull(0);
      return;
    }
    // A mostly-horizontal drag (e.g. the screen-time carousel) shouldn't be
    // hijacked into a pull gesture just because it drifts slightly downward.
    if (Math.abs(deltaX) > Math.abs(deltaY)) {
      resetPull();
      return;
    }
    event.preventDefault();
    setPull(Math.min(deltaY * PULL_RESISTANCE, PULL_MAX));
  }, { passive: false });

  document.addEventListener("touchend", () => {
    if (!pulling) return;
    if (lastPull >= PULL_THRESHOLD) {
      startRefresh();
    } else {
      resetPull();
    }
  });

  document.addEventListener("touchcancel", resetPull);

  // Fires after the Turbo navigation this gesture triggers (and after every
  // other Turbo navigation, harmlessly) - resets the permanent indicator
  // since a fresh script evaluation never re-enters this once-only block.
  document.addEventListener("turbo:load", () => {
    refreshing = false;
    indicator?.classList.remove("pull-refresh-loading");
    setPull(0);
  });
}

// `html.keyboard-open`: a text field is active or the on-screen keyboard has
// shrunk the visual viewport. The CSS hides the tab bar and its reserved space
// then. Not a pure :has(:focus) rule because iOS does not always report focus
// the way the CSS expects (see docs/spec/11-interface-html.md, tab bar).
if (!window.__keyboardOpenBound) {
  window.__keyboardOpenBound = true;
  const NON_TEXT = new Set(["checkbox", "radio", "range", "button", "submit", "reset", "file", "hidden", "image", "color"]);
  const isTextField = (el) =>
    el instanceof HTMLElement &&
    (el.isContentEditable || el.tagName === "TEXTAREA" || (el.tagName === "INPUT" && !NON_TEXT.has(el.type)));
  const update = () => {
    const vv = window.visualViewport;
    const shrunk = vv ? window.innerHeight - vv.height > 120 : false;
    document.documentElement.classList.toggle("keyboard-open", isTextField(document.activeElement) || shrunk);
  };
  document.addEventListener("focusin", update);
  // Focus is already on the next element when focusout fires: read it after.
  document.addEventListener("focusout", () => setTimeout(update, 0));
  window.visualViewport?.addEventListener("resize", update);
  document.addEventListener("turbo:load", update);
}

// Bottom tab bar: replay the clicked icon's animation right away (an already
// active tab included). The tab bar is re-rendered by every Turbo visit, so the
// destination page's active icon animates by itself via CSS on load.
if (!window.__tabbarBound) {
  window.__tabbarBound = true;
  document.addEventListener("click", (event) => {
    const tab = event.target.closest?.("[data-tabbar] a");
    if (!tab) return;
    tab.classList.remove("play");
    void tab.offsetWidth;
    tab.classList.add("play");
  });
}

// Bound once: the closure runs again on every Turbo visit but the listener lives on window.
if (!window.__formatPopoverScrollBound) {
  window.__formatPopoverScrollBound = true;
  window.addEventListener("scroll", closeFormatPopovers, { passive: true });
}
})();

// Channel page. Popovers are <details data-pop>: only one stays open, an outside click or
// Escape closes it, and the "Fermer" button (`data-pop-close`) too. Bound once: this file
// runs again on every Turbo visit but the listeners live on the document.
if (!window.__channelPopsBound) {
  window.__channelPopsBound = true;
  const openPops = () => [...document.querySelectorAll("details[data-pop][open]")];
  document.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof Element)) return;
    if (target.closest("[data-pop-close]")) {
      target.closest("details[data-pop]")?.removeAttribute("open");
      return;
    }
    const inside = target.closest("details[data-pop]");
    openPops().forEach((pop) => {
      // A click on the details element itself is the backdrop (its ::before).
      if (pop !== inside || target === pop) pop.removeAttribute("open");
    });
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") openPops().forEach((pop) => pop.removeAttribute("open"));
  });

  // The filters panel submits the toolbar form on every change, which reloads the page:
  // remember at submit time (not on the click/change that precedes it) that the panel was
  // open, so the flag only exists when a navigation actually follows.
  const FILTERS_OPEN_KEY = "raton:channel-filters-open";
  document.addEventListener("submit", (event) => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement) || !form.matches(".channel-toolbar-form")) return;
    if (!form.querySelector('details[data-pop-persist="filters"][open]')) return;
    try {
      window.sessionStorage.setItem(FILTERS_OPEN_KEY, "1");
    } catch {
      return;
    }
  });

  // A bell switched on rings after the redirect brings the page back.
  document.addEventListener("submit", (event) => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement) || !form.hasAttribute("data-bell-form")) return;
    try {
      const section = form.querySelector('input[name="section"]')?.value;
      const wasActive = form.querySelector(".channel-bell-btn")?.classList.contains("active");
      if (section && !wasActive) window.sessionStorage.setItem("raton:bell-ring", section);
    } catch {
      return;
    }
  });
}

(() => {
  try {
    if (window.sessionStorage.getItem("raton:channel-filters-open")) {
      window.sessionStorage.removeItem("raton:channel-filters-open");
      document.querySelector('details[data-pop-persist="filters"]')?.setAttribute("open", "");
    }
    const ringSection = window.sessionStorage.getItem("raton:bell-ring");
    if (ringSection) {
      window.sessionStorage.removeItem("raton:bell-ring");
      document.querySelectorAll("[data-bell-form]").forEach((form) => {
        if (form.querySelector('input[name="section"]')?.value === ringSection) {
          form.querySelector(".channel-bell-btn.active")?.classList.add("is-ringing");
        }
      });
    }
  } catch {
    return;
  }
})();

// `data-click-proxy="<selector>"`: a button that only forwards its click to the
// element the selector names (a control that must keep a single id, shown
// elsewhere on phones). Delegated, so Turbo visits need no rebinding.
if (!window.__clickProxyBound) {
  window.__clickProxyBound = true;
  document.addEventListener("click", (event) => {
    const proxy = event.target instanceof Element ? event.target.closest("[data-click-proxy]") : null;
    if (!proxy) return;
    const target = document.querySelector(proxy.dataset.clickProxy);
    if (target && !target.disabled) target.click();
  });
}
