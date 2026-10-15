const paths = {
  prediction: "/reports/next_race_prediction.json",
  top10: "/reports/next_race_top10_prediction.csv",
  weather: "/reports/prediction_weather.csv",
};

const teamLabels = {
  red_bull: "Red Bull",
  ferrari: "Ferrari",
  mercedes: "Mercedes",
  mclaren: "McLaren",
  alpine: "Alpine",
  audi: "Audi",
  aston_martin: "Aston Martin",
  williams: "Williams",
  haas: "Haas",
  rb: "RB"
};

const githubTrackBase = "https://raw.githubusercontent.com/MasterPlay007/F1-Track-Layouts-SVG/main";

const trackAssets = {
  albert_park: githubAsset("albert_park"),
  shanghai: githubAsset("shanghai"),
  suzuka: githubAsset("suzuka"),
  miami: githubAsset("miami"),
  villeneuve: githubAsset("villeneuve"),
  monaco: githubAsset("monaco"),
  catalunya: githubAsset("catalunya"),
  red_bull_ring: githubAsset("red_bull_ring"),
  silverstone: githubAsset("silverstone"),
  spa: githubAsset("spa"),
  hungaroring: githubAsset("hungaroring"),
  zandvoort: githubAsset("zandvoort"),
  monza: githubAsset("monza"),
  baku: githubAsset("baku"),
  marina_bay: githubAsset("marina_bay"),
  americas: githubAsset("americas"),
  rodriguez: githubAsset("rodriguez"),
  interlagos: githubAsset("interlagos"),
  vegas: githubAsset("vegas"),
  losail: githubAsset("losail"),
  yas_marina: githubAsset("yas_marina"),
  sepang: {
    url: "https://commons.wikimedia.org/wiki/Special:FilePath/Sepang.svg",
    sourceUrl: "https://commons.wikimedia.org/wiki/File:Sepang.svg",
    label: "Wikimedia Commons, CC BY-SA 3.0"
  },
  madring: {
    url: "https://commons.wikimedia.org/wiki/Special:FilePath/Madring%20%282026%29.svg",
    sourceUrl: "https://commons.wikimedia.org/wiki/File:Madring_(2026).svg",
    label: "Wikimedia Commons, CC BY-SA 3.0"
  }
};

function githubAsset(circuitId) {
  return {
    url: `${githubTrackBase}/${circuitId}.svg`,
    sourceUrl: "https://github.com/MasterPlay007/F1-Track-Layouts-SVG",
    label: "F1 Track Layouts SVG, CC0"
  };
}

const els = {
  updateStatus: document.querySelector("#updateStatus"),
  sprintCallout: document.querySelector("#sprintCallout"),
  sprintTime: document.querySelector("#sprintTime"),
  sprintModelStatus: document.querySelector("#sprintModelStatus"),
  sprintQualifyingStatus: document.querySelector("#sprintQualifyingStatus"),
  sprintTitle: document.querySelector("#sprintTitle"),
  sprintRaceStatus: document.querySelector("#sprintRaceStatus"),
  lastUpdated: document.querySelector("#lastUpdated"),
  raceRound: document.querySelector("#raceRound"),
  raceName: document.querySelector("#raceName"),
  raceLocation: document.querySelector("#raceLocation"),
  raceTime: document.querySelector("#raceTime"),
  qualifyingTime: document.querySelector("#qualifyingTime"),
  trackName: document.querySelector("#trackName"),
  rainProbability: document.querySelector("#rainProbability"),
  rainLabel: document.querySelector("#rainLabel"),
  airTemp: document.querySelector("#airTemp"),
  windSpeed: document.querySelector("#windSpeed"),
  windLabel: document.querySelector("#windLabel"),
  podium: document.querySelector("#podium"),
  predictionRows: document.querySelector("#predictionRows"),
  trackMap: document.querySelector("#trackMap"),
  trackCredit: document.querySelector("#trackCredit"),
  refreshButton: document.querySelector("#refreshButton")
};

async function fetchJson(path) {
  const response = await fetch(`${path}?v=${Date.now()}`);
  if (!response.ok) throw new Error(`Could not load ${path}`);
  return response.json();
}

async function fetchText(path) {
  const response = await fetch(`${path}?v=${Date.now()}`);
  if (!response.ok) throw new Error(`Could not load ${path}`);
  return response.text();
}

async function fetchJsonOrNull(path) {
  try {
    return await fetchJson(path);
  } catch {
    return null;
  }
}

function parseCsv(text) {
  const lines = text.trim().split(/\r?\n/);
  const headers = lines.shift().split(",");
  return lines.map((line) => {
    const values = line.split(",");
    return headers.reduce((row, header, index) => {
      row[header] = values[index] ?? "";
      return row;
    }, {});
  });
}

function formatDateTime(date, time) {
  if (!date) return "--";
  const iso = time ? `${date}T${time}` : `${date}T00:00:00Z`;
  const value = new Date(iso);
  if (Number.isNaN(value.getTime())) return date;
  return new Intl.DateTimeFormat(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: time ? "numeric" : undefined,
    minute: time ? "2-digit" : undefined,
    timeZoneName: time ? "short" : undefined
  }).format(value);
}

function percent(value, digits = 0) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "--";
  return `${(numeric * 100).toFixed(digits)}%`;
}

function number(value, digits = 1) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "--";
  return numeric.toFixed(digits);
}

function titleTeam(teamId) {
  return teamLabels[teamId] || String(teamId || "Unknown").replaceAll("_", " ");
}

function titleDriver(driverId, code, driverRegistry = {}) {
  if (driverRegistry[driverId]) return driverRegistry[driverId];
  if (driverRegistry[code]) return driverRegistry[code];
  if (!driverId) return code ? `${code} driver` : "Driver";
  return String(driverId)
    .split("_")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function addDriverToRegistry(registry, driver) {
  if (!driver?.driverId) return;
  const fullName = [driver.givenName, driver.familyName].filter(Boolean).join(" ");
  if (!fullName) return;
  registry[driver.driverId] = fullName;
  if (driver.code) registry[driver.code] = fullName;
}

function buildDriverRegistry(...documents) {
  const registry = {};
  documents.forEach((document) => {
    const races = document?.MRData?.RaceTable?.Races || [];
    races.forEach((race) => {
      ["Results", "QualifyingResults", "SprintResults", "SprintQualifyingResults"].forEach((key) => {
        (race[key] || []).forEach((row) => addDriverToRegistry(registry, row.Driver));
      });
    });
  });
  return registry;
}

function setBar(el, value) {
  el.style.setProperty("--value", `${Math.max(0, Math.min(100, Number(value) * 100))}%`);
}

function findRace(schedule, prediction) {
  const races = schedule?.MRData?.RaceTable?.Races || [];
  return races.find((race) => {
    return Number(race.round) === Number(prediction.round) && Number(race.season) === Number(prediction.season);
  });
}

function renderBanner(prediction, race, weather) {
  const circuit = race?.Circuit;
  const location = circuit?.Location;
  els.raceRound.textContent = `${prediction.season} Round ${prediction.round}`;
  els.raceName.textContent = prediction.race_name || race?.raceName || "Next Grand Prix";
  els.raceLocation.textContent = [
    circuit?.circuitName,
    location?.locality,
    location?.country
  ].filter(Boolean).join(" · ");
  els.raceTime.textContent = formatDateTime(race?.date || prediction.date, race?.time);
  els.qualifyingTime.textContent = formatDateTime(race?.Qualifying?.date, race?.Qualifying?.time);
  els.trackName.textContent = circuit?.circuitName || "Track TBD";

  els.rainProbability.textContent = percent(weather?.rain_probability);
  const rainValue = Number(weather?.rain_probability);
  els.rainLabel.textContent = Number.isFinite(rainValue)
    ? rainValue >= 0.5 ? "Wet-race risk elevated" : "Mostly dry outlook"
    : "Forecast unavailable";
  els.airTemp.textContent = weather?.air_temp_c ? `${number(weather.air_temp_c)} C` : "--";
  els.windSpeed.textContent = weather?.wind_kph ? `${number(weather.wind_kph)} kph` : "--";
  els.windLabel.textContent = weather?.track_temp_c ? `Track temp ${number(weather.track_temp_c)} C` : "Weather model input";
  renderTrackMap(circuit);
}

function renderSprintCallout(prediction, race) {
  const sprint = race?.Sprint;
  els.sprintCallout.hidden = !sprint?.date;
  if (els.sprintCallout.hidden) return;

  els.sprintTime.textContent = `Sprint start · ${formatDateTime(sprint.date, sprint.time)}`;
  const qualifyingUsed = prediction.sprint_qualifying_results_used;
  const raceUsed = prediction.sprint_race_results_used;
  els.sprintTitle.textContent = raceUsed === true ? "Sprint race completed" : "Sprint race scheduled";
  const status = (value) => value === true ? "Used in prediction"
    : value === false ? "Not used in prediction" : "Usage unavailable in this report";
  els.sprintQualifyingStatus.textContent = `Sprint qualifying · ${status(qualifyingUsed)}`;
  els.sprintRaceStatus.textContent = `Sprint race · ${status(raceUsed)}`;
  els.sprintModelStatus.textContent = qualifyingUsed === true || raceUsed === true
    ? "These predictions include available results from this weekend’s sprint sessions."
    : qualifyingUsed === false && raceUsed === false
      ? "These predictions do not yet include sprint results. Completed session results can be used when predictions are regenerated."
      : "This prediction report does not fully record sprint input usage. Regenerate predictions to update the status.";
}

function renderPodium(rows) {
  els.podium.innerHTML = "";
  rows.slice(0, 3).forEach((row) => {
    const card = document.createElement("article");
    card.className = "driver-card";
    card.innerHTML = `
      <div>
        <div class="rank-pill">${row.predicted_rank || row.rank}</div>
        <div class="driver-code">${row.driver_code}</div>
        <div class="team-name">${titleTeam(row.constructor_id)}</div>
      </div>
      <div class="prob-row">
        <div><span>Top-10 probability</span><strong>${percent(row.predicted_top10_probability || row.top10_probability, 1)}</strong></div>
        <div class="bar"><span></span></div>
      </div>
    `;
    setBar(card.querySelector(".bar span"), row.predicted_top10_probability || row.top10_probability);
    els.podium.appendChild(card);
  });
}

function renderRows(rows, driverRegistry) {
  els.predictionRows.innerHTML = rows.map((row) => {
    const rank = row.predicted_rank || row.rank;
    const top10 = Number(row.predicted_top10_probability || row.top10_probability || 0);
    const win = Number(row.predicted_win_probability || 0);
    return `
      <tr>
        <td class="rank-cell">${rank}</td>
        <td>
          <div class="driver-line">
            <strong>${row.driver_code}</strong>
            <span>${titleDriver(row.driver_id, row.driver_code, driverRegistry)}</span>
          </div>
        </td>
        <td>${titleTeam(row.constructor_id)}</td>
        <td class="table-prob">
          <strong>${percent(top10, 1)}</strong>
          <div class="bar"><span style="--value:${top10 * 100}%"></span></div>
        </td>
        <td class="table-prob">
          <strong>${percent(win, 1)}</strong>
          <div class="bar win-bar"><span style="--value:${win * 100}%"></span></div>
        </td>
        <td class="score">${number(row.score, 4)}</td>
      </tr>
    `;
  }).join("");
}

function renderTrackMap(circuit) {
  const asset = trackAssets[circuit?.circuitId];
  if (!asset) {
    els.trackMap.removeAttribute("src");
    els.trackMap.alt = "Circuit map unavailable";
    els.trackCredit.textContent = "Track map unavailable";
    els.trackCredit.removeAttribute("href");
    return;
  }

  els.trackMap.src = asset.url;
  els.trackMap.alt = `${circuit.circuitName} track map`;
  els.trackCredit.textContent = asset.label;
  els.trackCredit.href = asset.sourceUrl;
}

async function loadDashboard() {
  try {
    const status = await fetchJsonOrNull("/reports/update_status.json");
    els.updateStatus.textContent = status
      ? `${status.message || "Checking for new inputs…"} Last checked: ${formatDateTime(status.checked_at.slice(0, 10), status.checked_at.slice(11))}`
      : "Automatic updater is not connected. Showing saved predictions.";
    const prediction = await fetchJson(paths.prediction);
    if (status?.status === "off_season" || (status?.race &&
        (Number(status.race.season) !== Number(prediction.season) || Number(status.race.round) !== Number(prediction.round)))) {
      els.raceName.textContent = status.race?.raceName || "Season complete";
      els.raceRound.textContent = status.race ? `${status.race.season} Round ${status.race.round}` : "Off season";
      els.raceLocation.textContent = "Predictions pending";
      els.raceTime.textContent = formatDateTime(status.race?.date, status.race?.time);
      els.qualifyingTime.textContent = formatDateTime(status.race?.Qualifying?.date, status.race?.Qualifying?.time);
      els.trackName.textContent = status.race?.Circuit?.circuitName || "--";
      renderTrackMap(status.race?.Circuit);
      renderSprintCallout({}, status.race);
      els.podium.textContent = "Waiting for updated predictions.";
      els.predictionRows.innerHTML = '<tr><td colspan="6" class="empty-state">Predictions for this race are pending.</td></tr>';
      for (const key of ["rainProbability", "airTemp", "windSpeed", "lastUpdated"]) els[key].textContent = "--";
      return;
    }
    const season = Number(prediction.season);
    const round = Number(prediction.round);
    const [top10Text, weatherText, schedule, seasonResults, raceQualifying] = await Promise.all([
      fetchText(prediction.top10_path || paths.top10),
      prediction.weather_path ? fetchText(prediction.weather_path) : prediction.generated_at ? Promise.resolve("") : fetchText(paths.weather),
      fetchJsonOrNull("/reports/current_schedule.json").then((value) => value?.MRData?.RaceTable?.season === String(season) ? value : fetchJson(`/data/cache/${season}.json_limit=100.json`)),
      fetchJsonOrNull(`/data/cache/${season}__results.json_limit=2000.json`),
      fetchJsonOrNull(`/data/cache/${season}__${round}__qualifying.json_limit=100.json`)
    ]);

    const rows = parseCsv(top10Text);
    const weatherRows = parseCsv(weatherText);
    const driverRegistry = buildDriverRegistry(seasonResults, raceQualifying);
    const race = findRace(schedule, prediction);
    const weather = weatherRows.find((row) => {
      return Number(row.season) === Number(prediction.season) && Number(row.round) === Number(prediction.round);
    });

    renderBanner(prediction, race, weather);
    renderSprintCallout(prediction, race);
    renderPodium(rows.length ? rows : prediction.predicted_top10);
    renderRows(rows.length ? rows : prediction.predicted_top10, driverRegistry);
    els.lastUpdated.textContent = new Intl.DateTimeFormat(undefined, {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit"
    }).format(new Date(prediction.generated_at || prediction.date));
    els.lastUpdated.title = prediction.stage || "Saved prediction";
    els.updateStatus.textContent += prediction.generated_at ? ` Forecast: ${prediction.stage}${prediction.final_weather_update ? " · Final weather update" : ""}.` : " Forecast generation time unavailable.";
  } catch (error) {
    els.sprintCallout.hidden = true;
    els.raceName.textContent = "Dashboard data unavailable";
    els.raceLocation.textContent = error.message;
    els.podium.innerHTML = `<p class="empty-state">Start a local server at the project root so the dashboard can read reports.</p>`;
    els.predictionRows.innerHTML = `<tr><td colspan="6" class="empty-state">${error.message}</td></tr>`;
  }
}

els.refreshButton.addEventListener("click", loadDashboard);
loadDashboard();

setInterval(loadDashboard, 60000);
