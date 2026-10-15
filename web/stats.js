const paths = {
  backtest: "/reports/backtest_predictions.csv",
  summary: "/reports/backtest_summary.json"
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
  rb: "RB",
  cadillac: "Cadillac"
};

const els = {
  lastUpdated: document.querySelector("#lastUpdated"),
  refreshButton: document.querySelector("#refreshButton"),
  seasonSelect: document.querySelector("#seasonSelect"),
  driverSelect: document.querySelector("#driverSelect"),
  trackSelect: document.querySelector("#trackSelect"),
  raceSelect: document.querySelector("#raceSelect"),
  pointsCapture: document.querySelector("#pointsCapture"),
  top10Precision: document.querySelector("#top10Precision"),
  avgRankDelta: document.querySelector("#avgRankDelta"),
  driverTitle: document.querySelector("#driverTitle"),
  driverSummary: document.querySelector("#driverSummary"),
  driverRows: document.querySelector("#driverRows"),
  trackTitle: document.querySelector("#trackTitle"),
  trackRows: document.querySelector("#trackRows"),
  modelTitle: document.querySelector("#modelTitle"),
  raceAccuracy: document.querySelector("#raceAccuracy"),
  modelRows: document.querySelector("#modelRows")
};

let allRows = [];
let summary = null;

async function fetchText(path) {
  const response = await fetch(`${path}?v=${Date.now()}`);
  if (!response.ok) throw new Error(`Could not load ${path}`);
  return response.text();
}

async function fetchJsonOrNull(path) {
  try {
    const response = await fetch(`${path}?v=${Date.now()}`);
    if (!response.ok) return null;
    return response.json();
  } catch {
    return null;
  }
}

function splitCsvLine(line) {
  const values = [];
  let value = "";
  let quoted = false;
  for (let index = 0; index < line.length; index += 1) {
    const character = line[index];
    if (character === '"' && line[index + 1] === '"') {
      value += '"';
      index += 1;
    } else if (character === '"') {
      quoted = !quoted;
    } else if (character === "," && !quoted) {
      values.push(value);
      value = "";
    } else {
      value += character;
    }
  }
  values.push(value);
  return values;
}

function parseCsv(text) {
  const lines = text.trim().split(/\r?\n/);
  const headers = splitCsvLine(lines.shift());
  return lines.map((line) => {
    const values = splitCsvLine(line);
    return headers.reduce((row, header, index) => {
      row[header] = values[index] ?? "";
      return row;
    }, {});
  });
}

function normalizeRow(row) {
  return {
    ...row,
    season: Number(row.season),
    round: Number(row.round),
    predicted_rank: Number(row.predicted_rank),
    predicted_win_probability: Number(row.predicted_win_probability),
    predicted_top10_probability: Number(row.predicted_top10_probability),
    predicted_top10: row.predicted_top10 === "True",
    actual_top10: row.actual_top10 === "True",
    actual_finish: Number(row.actual_finish),
    actual_points: Number(row.actual_points),
    score: Number(row.score)
  };
}

function titleTeam(teamId) {
  return teamLabels[teamId] || String(teamId || "Unknown").replaceAll("_", " ");
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

function signed(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "--";
  return numeric > 0 ? `+${numeric}` : String(numeric);
}

function uniqueBy(rows, getter) {
  return [...new Map(rows.map((row) => [getter(row), row])).values()];
}

function raceKey(row) {
  return `${row.season}-${row.round}`;
}

function raceLabel(row) {
  return `${row.season} R${row.round} · ${row.race_name}`;
}

function populateSelect(select, options, selectedValue) {
  select.innerHTML = options.map((option) => {
    const selected = String(option.value) === String(selectedValue) ? " selected" : "";
    return `<option value="${option.value}"${selected}>${option.label}</option>`;
  }).join("");
}

function setupFilters() {
  const seasons = [...new Set(allRows.map((row) => row.season))].sort((a, b) => b - a);
  populateSelect(els.seasonSelect, seasons.map((season) => ({ value: season, label: season })), seasons[0]);
  refreshSeasonOptions();
}

function refreshSeasonOptions() {
  const season = Number(els.seasonSelect.value);
  const seasonRows = allRows.filter((row) => row.season === season);
  const drivers = uniqueBy(
    [...seasonRows].sort((a, b) => a.driver_code.localeCompare(b.driver_code)),
    (row) => row.driver_code
  );
  const tracks = uniqueBy(
    [...allRows].sort((a, b) => a.race_name.localeCompare(b.race_name)),
    (row) => row.race_name
  );
  const races = uniqueBy(
    [...seasonRows].sort((a, b) => a.round - b.round),
    raceKey
  );

  populateSelect(
    els.driverSelect,
    drivers.map((row) => ({ value: row.driver_code, label: row.driver_code })),
    els.driverSelect.value || drivers[0]?.driver_code
  );
  populateSelect(
    els.trackSelect,
    tracks.map((row) => ({ value: row.race_name, label: row.race_name.replace(" Grand Prix", "") })),
    els.trackSelect.value || tracks[0]?.race_name
  );
  populateSelect(
    els.raceSelect,
    races.map((row) => ({ value: raceKey(row), label: `R${row.round} · ${row.race_name.replace(" Grand Prix", "")}` })),
    els.raceSelect.value || raceKey(races[races.length - 1])
  );
}

function updateDashboard() {
  const season = Number(els.seasonSelect.value);
  const driver = els.driverSelect.value;
  const track = els.trackSelect.value;
  const race = els.raceSelect.value;
  const seasonRows = allRows.filter((row) => row.season === season);
  const raceRows = seasonRows.filter((row) => raceKey(row) === race);

  renderMetrics(seasonRows);
  renderDriver(seasonRows, driver);
  renderTrack(track);
  renderModel(raceRows);
  els.lastUpdated.textContent = new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit"
  }).format(new Date());
}

function renderMetrics(rows) {
  const totalPoints = rows.reduce((sum, row) => sum + row.actual_points, 0);
  const predictedPoints = rows.filter((row) => row.predicted_top10).reduce((sum, row) => sum + row.actual_points, 0);
  const predictedTop10 = rows.filter((row) => row.predicted_top10);
  const correctTop10 = predictedTop10.filter((row) => row.actual_top10);
  const deltas = rows
    .filter((row) => Number.isFinite(row.actual_finish) && Number.isFinite(row.predicted_rank))
    .map((row) => Math.abs(row.actual_finish - row.predicted_rank));

  els.pointsCapture.textContent = totalPoints ? percent(predictedPoints / totalPoints, 1) : percent(summary?.points_capture, 1);
  els.top10Precision.textContent = predictedTop10.length ? percent(correctTop10.length / predictedTop10.length, 1) : percent(summary?.top10_precision, 1);
  els.avgRankDelta.textContent = deltas.length ? number(deltas.reduce((sum, delta) => sum + delta, 0) / deltas.length, 1) : "--";
}

function renderDriver(rows, driverCode) {
  const driverRows = rows.filter((row) => row.driver_code === driverCode).sort((a, b) => a.round - b.round);
  const points = driverRows.reduce((sum, row) => sum + row.actual_points, 0);
  const top10s = driverRows.filter((row) => row.actual_top10).length;
  const avgFinish = driverRows.reduce((sum, row) => sum + row.actual_finish, 0) / Math.max(driverRows.length, 1);
  const avgModel = driverRows.reduce((sum, row) => sum + row.predicted_rank, 0) / Math.max(driverRows.length, 1);

  els.driverTitle.textContent = `${driverCode} season results`;
  els.driverSummary.innerHTML = [
    ["Points", number(points, 0)],
    ["Top-10s", top10s],
    ["Avg Finish", number(avgFinish, 1)],
    ["Avg Model Rank", number(avgModel, 1)]
  ].map(([label, value]) => `<div><span>${label}</span><strong>${value}</strong></div>`).join("");

  els.driverRows.innerHTML = driverRows.map((row) => {
    const delta = row.actual_finish - row.predicted_rank;
    return `
      <tr>
        <td class="rank-cell">${row.round}</td>
        <td>${row.race_name}</td>
        <td>${titleTeam(row.constructor_id)}</td>
        <td>${row.actual_finish}</td>
        <td>${number(row.actual_points, 0)}</td>
        <td>${row.predicted_rank}</td>
        <td class="${delta === 0 ? "" : delta > 0 ? "negative" : "positive"}">${signed(delta)}</td>
        <td><span class="result-pill ${row.actual_top10 ? "is-hit" : "is-miss"}">${row.actual_top10 ? "Scored" : "Miss"}</span></td>
      </tr>
    `;
  }).join("") || `<tr><td colspan="8" class="empty-state">No driver rows found for this season.</td></tr>`;
}

function renderTrack(trackName) {
  const races = uniqueBy(allRows.filter((row) => row.race_name === trackName).sort((a, b) => b.season - a.season), raceKey);
  els.trackTitle.textContent = trackName.replace(" Grand Prix", " GP");
  els.trackRows.innerHTML = races.map((race) => {
    const rows = allRows.filter((row) => raceKey(row) === raceKey(race));
    const winner = rows.find((row) => row.actual_finish === 1);
    const podium = rows
      .filter((row) => row.actual_finish <= 3)
      .sort((a, b) => a.actual_finish - b.actual_finish)
      .map((row) => row.driver_code)
      .join(" / ");
    const modelPick = [...rows].sort((a, b) => a.predicted_rank - b.predicted_rank)[0];
    const winnerDelta = winner ? winner.actual_finish - winner.predicted_rank : null;
    return `
      <tr>
        <td class="rank-cell">${race.season}</td>
        <td>${race.race_name}</td>
        <td><strong>${winner?.driver_code || "--"}</strong></td>
        <td>${podium || "--"}</td>
        <td>${modelPick?.driver_code || "--"}</td>
        <td class="${winnerDelta === 0 ? "" : winnerDelta > 0 ? "negative" : "positive"}">${winnerDelta === null ? "--" : signed(winnerDelta)}</td>
      </tr>
    `;
  }).join("") || `<tr><td colspan="6" class="empty-state">No historical results found for this track.</td></tr>`;
}

function renderModel(rows) {
  const sortedRows = [...rows].sort((a, b) => a.predicted_rank - b.predicted_rank);
  const race = sortedRows[0];
  const predictedTop10 = sortedRows.filter((row) => row.predicted_top10);
  const hits = predictedTop10.filter((row) => row.actual_top10).length;
  els.modelTitle.textContent = race ? raceLabel(race) : "Race comparison";
  els.raceAccuracy.textContent = predictedTop10.length ? `${hits}/${predictedTop10.length} top-10 hits` : "--";

  els.modelRows.innerHTML = sortedRows.map((row) => {
    const delta = row.actual_finish - row.predicted_rank;
    return `
      <tr>
        <td class="rank-cell">${row.predicted_rank}</td>
        <td>
          <div class="driver-line">
            <strong>${row.driver_code}</strong>
            <span>${row.driver_id.replaceAll("_", " ")}</span>
          </div>
        </td>
        <td>${titleTeam(row.constructor_id)}</td>
        <td>${row.actual_finish}</td>
        <td class="${delta === 0 ? "" : delta > 0 ? "negative" : "positive"}">${signed(delta)}</td>
        <td class="table-prob">
          <strong>${percent(row.predicted_top10_probability, 1)}</strong>
          <div class="bar ${row.actual_top10 ? "" : "miss-bar"}"><span style="--value:${row.predicted_top10_probability * 100}%"></span></div>
        </td>
        <td>${percent(row.predicted_win_probability, 1)}</td>
        <td>${number(row.actual_points, 0)}</td>
      </tr>
    `;
  }).join("") || `<tr><td colspan="8" class="empty-state">No model rows found for this race.</td></tr>`;
}

async function loadStats() {
  try {
    const [csvText, summaryJson] = await Promise.all([
      fetchText(paths.backtest),
      fetchJsonOrNull(paths.summary)
    ]);
    allRows = parseCsv(csvText).map(normalizeRow);
    summary = summaryJson;
    setupFilters();
    updateDashboard();
  } catch (error) {
    els.modelTitle.textContent = "Stats data unavailable";
    els.modelRows.innerHTML = `<tr><td colspan="8" class="empty-state">${error.message}</td></tr>`;
  }
}

els.seasonSelect.addEventListener("change", () => {
  refreshSeasonOptions();
  updateDashboard();
});
els.driverSelect.addEventListener("change", updateDashboard);
els.trackSelect.addEventListener("change", updateDashboard);
els.raceSelect.addEventListener("change", updateDashboard);
els.refreshButton.addEventListener("click", loadStats);
loadStats();
