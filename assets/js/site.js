/*
 * Progressive WebMCP enhancement for the static GitHub profile explorer.
 * All user-facing data is read from a fixed, same-origin export allowlist.
 */

const PAGE_SIZE = 25;
const MAX_TOOL_SEARCH_RESULTS = 5;
const MAX_TOOL_PAGE_RESULTS = 10;
const MAX_OUTPUT_STRING_LENGTH = 420;
const MAX_EXPORT_BYTES = 10_000_000;
const MAX_EXPORT_CHUNKS = 4096;
const SITE_ROOT = typeof window !== "undefined" ? new URL("./", window.location.href) : null;
const DATA_CACHE = new Map();
const DATA_PENDING = new Map();
let metadataPromise = null;
let metadataValue = null;
let registrationController = null;
let registrationState = "idle";

const DATASETS = [
  {
    id: "repos",
    label: "Repositories",
    description: "Public repositories in the profile report, with summary statistics.",
    columns: [
      { key: "name", label: "Repository", link: "url" },
      { key: "description", label: "Description" },
      { key: "language", label: "Language" },
      { key: "stars", label: "Stars" },
      { key: "forks", label: "Forks" },
      { key: "updated_at", label: "Updated" },
    ],
  },
  {
    id: "branches",
    label: "Branches",
    description: "Tracked branch names, head commits, and default-branch flags.",
    columns: [
      { key: "repo", label: "Repository" },
      { key: "name", label: "Branch", link: "url" },
      { key: "head_sha_short", label: "Head commit" },
      { key: "is_default", label: "Default" },
    ],
  },
  {
    id: "commits",
    label: "Commits",
    description: "Commit summaries collected for tracked repository branches.",
    columns: [
      { key: "repo", label: "Repository" },
      { key: "branch", label: "Branch" },
      { key: "sha_short", label: "Commit", link: "url" },
      { key: "message", label: "Message" },
      { key: "author", label: "Author" },
      { key: "date", label: "Date" },
    ],
  },
  {
    id: "issues",
    label: "Issues",
    description: "Sampled open and closed issue records, excluding pull requests.",
    columns: [
      { key: "repo", label: "Repository" },
      { key: "number", label: "Issue", link: "url" },
      { key: "state", label: "State" },
      { key: "title", label: "Title" },
      { key: "user", label: "Author" },
      { key: "created_at", label: "Created" },
    ],
  },
  {
    id: "pull_requests",
    label: "Pull requests",
    description: "Sampled pull-request state, author, branches, and commit counts.",
    columns: [
      { key: "repo", label: "Repository" },
      { key: "number", label: "Pull request", link: "url" },
      { key: "status", label: "Status" },
      { key: "title", label: "Title" },
      { key: "user", label: "Author" },
      { key: "created_at", label: "Created" },
    ],
  },
  {
    id: "pull_request_commits",
    label: "Pull request commits",
    description: "Commit summaries associated with sampled pull requests.",
    columns: [
      { key: "repo", label: "Repository" },
      { key: "pr_number", label: "PR #" },
      { key: "sha_short", label: "Commit", link: "url" },
      { key: "message", label: "Message" },
    ],
  },
  {
    id: "forks",
    label: "Forks",
    description: "Fork repositories returned by the public GitHub API.",
    columns: [
      { key: "repo", label: "Source repository" },
      { key: "fork_owner", label: "Fork owner" },
      { key: "fork_name", label: "Fork", link: "url" },
      { key: "stars", label: "Stars" },
      { key: "created_at", label: "Created" },
    ],
  },
  {
    id: "stargazers",
    label: "Stargazers",
    description: "Public accounts returned for sampled repository stargazer lists.",
    columns: [
      { key: "repo", label: "Repository" },
      { key: "login", label: "Account", link: "profile_url" },
      { key: "starred_at", label: "Starred" },
    ],
  },
  {
    id: "watchers",
    label: "Watchers",
    description: "Public accounts returned for sampled repository watcher lists.",
    columns: [
      { key: "repo", label: "Repository" },
      { key: "login", label: "Account", link: "profile_url" },
    ],
  },
  {
    id: "contributors",
    label: "Contributors",
    description: "Public contributor accounts and contribution totals.",
    columns: [
      { key: "repo", label: "Repository" },
      { key: "login", label: "Account", link: "profile_url" },
      { key: "contributions", label: "Contributions" },
    ],
  },
  {
    id: "releases",
    label: "Releases",
    description: "Release names, publication dates, and prerelease or draft flags.",
    columns: [
      { key: "repo", label: "Repository" },
      { key: "name", label: "Release", link: "url" },
      { key: "published_at", label: "Published" },
      { key: "prerelease", label: "Prerelease" },
      { key: "draft", label: "Draft" },
    ],
  },
  {
    id: "release_assets",
    label: "Release assets",
    description: "Release asset names, sizes, and download counts.",
    columns: [
      { key: "repo", label: "Repository" },
      { key: "release_name", label: "Release" },
      { key: "asset_name", label: "Asset", link: "url" },
      { key: "size_mb", label: "Size (MB)" },
      { key: "downloads", label: "Downloads" },
    ],
  },
  {
    id: "languages",
    label: "Languages",
    description: "Language byte counts and percentages for public repositories.",
    columns: [
      { key: "repo", label: "Repository" },
      { key: "language", label: "Language" },
      { key: "bytes", label: "Bytes" },
      { key: "percent", label: "Share (%)" },
    ],
  },
  {
    id: "followers",
    label: "Followers",
    description: "Public follower account summaries from the report snapshot.",
    columns: [
      { key: "login", label: "Account", link: "profile_url" },
      { key: "public_repos", label: "Public repositories" },
      { key: "following_count", label: "Following" },
    ],
  },
  {
    id: "following",
    label: "Following",
    description: "Public accounts followed by the profile owner.",
    columns: [
      { key: "login", label: "Account", link: "profile_url" },
    ],
  },
  {
    id: "starred_by_user",
    label: "Repositories starred by the owner",
    description: "Public repositories starred by the profile owner.",
    columns: [
      { key: "full_name", label: "Repository", link: "url" },
      { key: "description", label: "Description" },
    ],
  },
];

const DATASET_BY_ID = new Map(DATASETS.map((dataset) => [dataset.id, dataset]));
const RELATED_DATASET_IDS = [
  "branches",
  "commits",
  "issues",
  "pull_requests",
  "pull_request_commits",
  "forks",
  "stargazers",
  "watchers",
  "contributors",
  "releases",
  "release_assets",
  "languages",
];
const SAMPLE_DATASET_IDS = ["branches", "commits", "issues", "pull_requests", "releases"];

const state = {
  dataset: "repos",
  query: "",
  offset: 0,
  limit: PAGE_SIZE,
  repoLanguage: "",
  repoMinStars: 0,
  includeForks: true,
  renderSequence: 0,
};

class ToolInputError extends Error {}
class ToolNotFoundError extends Error {}
class DataIntegrityError extends Error {}
class ToolCancelledError extends Error {}

function byId(id) {
  return typeof document === "undefined" ? null : document.getElementById(id);
}

function isPlainRecord(value) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function normalizeText(value) {
  return String(value ?? "").normalize("NFKC").toLocaleLowerCase("en-US").trim();
}

function compactString(value, stateRef) {
  const text = String(value);
  if (text.length <= MAX_OUTPUT_STRING_LENGTH) return text;
  stateRef.truncated = true;
  return `${text.slice(0, MAX_OUTPUT_STRING_LENGTH)}… [truncated]`;
}

function compactValue(value, stateRef, depth = 0) {
  if (typeof value === "string") return compactString(value, stateRef);
  if (typeof value === "boolean" || value === null) return value;
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (Array.isArray(value)) {
    if (depth >= 4) {
      stateRef.truncated = true;
      return "[nested data omitted]";
    }
    const sliced = value.slice(0, 16);
    if (value.length > sliced.length) stateRef.truncated = true;
    return sliced.map((item) => compactValue(item, stateRef, depth + 1));
  }
  if (isPlainRecord(value) && depth < 4) {
    const result = {};
    const entries = Object.entries(value).slice(0, 32);
    if (Object.keys(value).length > entries.length) stateRef.truncated = true;
    for (const [key, item] of entries) {
      if (!/^[A-Za-z][A-Za-z0-9_]{0,63}$/.test(key)) continue;
      result[key] = compactValue(item, stateRef, depth + 1);
    }
    return result;
  }
  if (value === undefined) return null;
  stateRef.truncated = true;
  return "[unsupported value omitted]";
}

function compactRows(rows) {
  const stateRef = { truncated: false };
  const compacted = compactValue(rows, stateRef);
  return { value: compacted, truncated: stateRef.truncated };
}

function makeSuccess(result) {
  const bounded = compactRows(result.data);
  return {
    ok: true,
    data: bounded.value,
    meta: {
      ...(result.meta || {}),
      schemaVersion: 1,
      source: "committed-public-github-export",
      generatedAt: typeof metadataValue?.generatedAt === "string" ? metadataValue.generatedAt : null,
      untrustedContent: true,
      truncated: Boolean(result.meta?.truncated || bounded.truncated),
    },
  };
}

function makeFailure(code, message, extras = {}) {
  return {
    ok: false,
    error: { code, message, ...extras },
    meta: {
      schemaVersion: 1,
      source: "committed-public-github-export",
      generatedAt: typeof metadataValue?.generatedAt === "string" ? metadataValue.generatedAt : null,
      untrustedContent: true,
    },
  };
}

function throwIfAborted(signal) {
  if (signal?.aborted) throw new ToolCancelledError("Tool execution cancelled.");
}

function awaitWithSignal(promise, signal) {
  if (!signal || typeof signal.addEventListener !== "function") return promise;
  if (signal.aborted) return Promise.reject(new ToolCancelledError("Tool execution cancelled."));
  return new Promise((resolve, reject) => {
    const cleanup = () => signal.removeEventListener("abort", onAbort);
    const onAbort = () => {
      cleanup();
      reject(new ToolCancelledError("Tool execution cancelled."));
    };
    signal.addEventListener("abort", onAbort, { once: true });
    promise.then(
      (value) => { cleanup(); resolve(value); },
      (error) => { cleanup(); reject(error); },
    );
  });
}

function parseArgs(input, allowedKeys) {
  if (input === undefined) input = {};
  if (!isPlainRecord(input)) throw new ToolInputError("Arguments must be a JSON object.");
  const allowed = new Set(allowedKeys);
  if (Object.keys(input).some((key) => !allowed.has(key))) {
    throw new ToolInputError("Remove unsupported fields from the arguments.");
  }
  return input;
}

function optionalString(args, key, { required = false, maxLength = 100, defaultValue = "" } = {}) {
  if (!Object.prototype.hasOwnProperty.call(args, key)) {
    if (required) throw new ToolInputError(`The ${key} field is required.`);
    return defaultValue;
  }
  if (typeof args[key] !== "string") throw new ToolInputError(`The ${key} field must be a string.`);
  if (args[key].length > maxLength * 4 + 8) throw new ToolInputError(`The ${key} field is too long (maximum ${maxLength} characters).`);
  const value = args[key].trim().normalize("NFKC");
  if (required && value.length === 0) throw new ToolInputError(`The ${key} field must not be empty.`);
  if (Array.from(value).length > maxLength) throw new ToolInputError(`The ${key} field is too long (maximum ${maxLength} characters).`);
  return value;
}

function optionalBoolean(args, key, defaultValue) {
  if (!Object.prototype.hasOwnProperty.call(args, key)) return defaultValue;
  if (typeof args[key] !== "boolean") throw new ToolInputError(`The ${key} field must be a boolean.`);
  return args[key];
}

function optionalInteger(args, key, { defaultValue, min = 0, max = 100000 } = {}) {
  if (!Object.prototype.hasOwnProperty.call(args, key)) return defaultValue;
  if (!Number.isInteger(args[key]) || args[key] < min || args[key] > max) {
    throw new ToolInputError(`The ${key} field must be a whole number from ${min} to ${max}.`);
  }
  return args[key];
}

function datasetField(args, key = "dataset") {
  const value = optionalString(args, key, { required: true, maxLength: 40 });
  if (!DATASET_BY_ID.has(value)) throw new ToolInputError(`Choose one of the supported dataset identifiers.`);
  return value;
}

function getStaticUrl(relativePath) {
  if (!SITE_ROOT || typeof window === "undefined") throw new DataIntegrityError("Browser location is unavailable.");
  const url = new URL(relativePath, SITE_ROOT);
  if (url.origin !== window.location.origin || !url.pathname.startsWith(SITE_ROOT.pathname)) {
    throw new DataIntegrityError("Report file is outside this website.");
  }
  return url;
}

async function readBoundedJson(response) {
  if (response.body && typeof response.body.getReader === "function" && typeof TextDecoder === "function") {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    const chunks = [];
    let totalBytes = 0;
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        totalBytes += value.byteLength;
        if (totalBytes > MAX_EXPORT_BYTES || chunks.length >= MAX_EXPORT_CHUNKS) {
          try { await reader.cancel(); } catch { /* Best-effort cancellation for an oversized response. */ }
          throw new DataIntegrityError("The report export is larger than the supported size.");
        }
        chunks.push(decoder.decode(value, { stream: true }));
      }
      chunks.push(decoder.decode());
      return JSON.parse(chunks.join(""));
    } finally {
      reader.releaseLock?.();
    }
  }

  if (typeof response.text === "function") {
    const text = await response.text();
    if (new TextEncoder().encode(text).byteLength > MAX_EXPORT_BYTES) {
      throw new DataIntegrityError("The report export is larger than the supported size.");
    }
    return JSON.parse(text);
  }

  // Compatibility fallback for minimal test doubles and older host implementations.
  return response.json();
}

async function fetchStaticJson(relativePath, signal) {
  const url = getStaticUrl(relativePath);
  const response = await fetch(url.href, {
    method: "GET",
    mode: "same-origin",
    credentials: "omit",
    redirect: "error",
    referrerPolicy: "no-referrer",
    cache: "no-cache",
    signal,
    headers: { Accept: "application/json" },
  });
  if (!response.ok) throw new DataIntegrityError("A report export could not be loaded.");
  const length = Number(response.headers.get("content-length"));
  if (Number.isFinite(length) && length > MAX_EXPORT_BYTES) throw new DataIntegrityError("The report export is larger than the supported size.");
  return readBoundedJson(response);
}

function loadDataset(datasetId, signal) {
  const dataset = DATASET_BY_ID.get(datasetId);
  if (!dataset) return Promise.reject(new DataIntegrityError("Unknown report dataset."));
  if (signal?.aborted) return Promise.reject(new ToolCancelledError("Tool execution cancelled."));
  if (DATA_CACHE.has(datasetId)) return awaitWithSignal(Promise.resolve(DATA_CACHE.get(datasetId)), signal);

  let entry = DATA_PENDING.get(datasetId);
  if (!entry) {
    const controller = new AbortController();
    entry = { controller, consumers: 0, settled: false, promise: null };
    entry.promise = fetchStaticJson(`reports/${dataset.id}.json`, controller.signal).then((records) => {
      if (controller.signal.aborted) throw new ToolCancelledError("Tool execution cancelled.");
      if (!Array.isArray(records) || !records.every(isPlainRecord)) throw new DataIntegrityError("The report export has an unexpected shape.");
      DATA_CACHE.set(datasetId, records);
      return records;
    }).finally(() => {
      entry.settled = true;
      if (DATA_PENDING.get(datasetId) === entry) DATA_PENDING.delete(datasetId);
    });
    DATA_PENDING.set(datasetId, entry);
  }

  entry.consumers += 1;
  return awaitWithSignal(entry.promise, signal).finally(() => {
    entry.consumers -= 1;
    if (entry.consumers === 0 && !entry.settled) {
      entry.controller.abort();
      if (DATA_PENDING.get(datasetId) === entry) DATA_PENDING.delete(datasetId);
    }
  });
}

function loadMetadata() {
  if (metadataValue) return Promise.resolve(metadataValue);
  if (metadataPromise) return metadataPromise;
  metadataPromise = fetchStaticJson("reports/metadata.json").then((value) => {
    if (!isPlainRecord(value) || value.schemaVersion !== 1 || !isPlainRecord(value.counts)) {
      throw new DataIntegrityError("The report metadata has an unexpected shape.");
    }
    metadataValue = value;
    return value;
  }).catch((error) => {
    metadataPromise = null;
    throw error;
  });
  return metadataPromise;
}

async function optionalMetadata() {
  try {
    return await loadMetadata();
  } catch {
    return null;
  }
}

function searchableText(record) {
  const parts = [];
  const stack = [{ value: record, depth: 0 }];
  let visited = 0;
  while (stack.length && visited < 512) {
    const current = stack.pop();
    visited += 1;
    if (typeof current.value === "string") {
      parts.push(current.value);
    } else if (typeof current.value === "number" || typeof current.value === "boolean") {
      parts.push(String(current.value));
    } else if (Array.isArray(current.value) && current.depth < 4) {
      for (let index = Math.min(current.value.length, 16) - 1; index >= 0; index -= 1) {
        stack.push({ value: current.value[index], depth: current.depth + 1 });
      }
    } else if (isPlainRecord(current.value) && current.depth < 4) {
      let count = 0;
      for (const key in current.value) {
        if (!Object.prototype.hasOwnProperty.call(current.value, key)) continue;
        if (count >= 32) break;
        count += 1;
        parts.push(key);
        stack.push({ value: current.value[key], depth: current.depth + 1 });
      }
    }
  }
  return parts.join(" ");
}

function recordMatchesQuery(record, query) {
  if (!query) return true;
  return normalizeText(searchableText(record)).includes(normalizeText(query));
}

function filterRepositoryRows(rows, filters) {
  const query = normalizeText(filters.query || "");
  const language = normalizeText(filters.language || "");
  const minStars = Number.isInteger(filters.minStars) ? filters.minStars : 0;
  const includeForks = filters.includeForks !== false;
  return rows.filter((row) => {
    if (!includeForks && row.is_fork !== false) return false;
    if (language && normalizeText(row.language) !== language) return false;
    if (minStars > 0 && (!Number.isFinite(row.stars) || row.stars < minStars)) return false;
    return recordMatchesQuery(row, query);
  });
}

function filterDatasetRows(rows, query) {
  return rows.filter((row) => recordMatchesQuery(row, query));
}

function safeGitHubUrl(value) {
  if (typeof value !== "string" || value.length > 2048) return null;
  try {
    const url = new URL(value);
    if (url.protocol !== "https:" || url.hostname.toLowerCase() !== "github.com" || url.username || url.password) return null;
    if (url.port && url.port !== "443") return null;
    return url.href;
  } catch {
    return null;
  }
}

function displayValue(value, depth = 0) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "number") return Number.isFinite(value) ? new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(value) : "—";
  if (typeof value === "string") return value.length > MAX_OUTPUT_STRING_LENGTH ? `${value.slice(0, MAX_OUTPUT_STRING_LENGTH)}… [truncated]` : value;
  if (depth >= 4 && (Array.isArray(value) || isPlainRecord(value))) return "[nested data omitted]";
  if (Array.isArray(value)) {
    const items = value.slice(0, 16).map((item) => displayValue(item, depth + 1));
    if (value.length > 16) items.push(`… ${value.length - 16} more`);
    return items.join(", ");
  }
  if (isPlainRecord(value)) {
    const parts = [];
    let count = 0;
    let hasMore = false;
    for (const key in value) {
      if (!Object.prototype.hasOwnProperty.call(value, key)) continue;
      if (count >= 16) {
        hasMore = true;
        break;
      }
      count += 1;
      parts.push(`${key}: ${displayValue(value[key], depth + 1)}`);
    }
    if (hasMore) parts.push("… more fields");
    return parts.join("; ");
  }
  return String(value);
}

function setExplorerStatus(message, kind = "info", retry = false) {
  const status = byId("explorer-status");
  if (!status) return;
  status.dataset.kind = kind;
  status.replaceChildren(document.createTextNode(message));
  if (retry) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "text-link retry-link";
    button.textContent = "Retry";
    button.addEventListener("click", () => { void renderDataset(); });
    status.append(document.createTextNode(" "), button);
  }
}

function renderHeader(dataset) {
  const head = byId("table-head");
  if (!head) return;
  const row = document.createElement("tr");
  for (const column of dataset.columns) {
    const cell = document.createElement("th");
    cell.scope = "col";
    cell.textContent = column.label;
    row.append(cell);
  }
  head.replaceChildren(row);
  const caption = byId("table-caption");
  if (caption) caption.textContent = `${dataset.label} records from the current public GitHub report export`;
}

function renderRows(dataset, rows) {
  const body = byId("table-body");
  if (!body) return;
  if (rows.length === 0) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = Math.max(dataset.columns.length, 1);
    cell.className = "empty-state";
    cell.textContent = "No records match these filters in this report snapshot.";
    row.append(cell);
    body.replaceChildren(row);
    return;
  }

  const fragment = document.createDocumentFragment();
  for (const record of rows) {
    const row = document.createElement("tr");
    for (const column of dataset.columns) {
      const cell = document.createElement("td");
      const rawValue = record[column.key];
      const text = displayValue(rawValue);
      if (column.link) {
        const href = safeGitHubUrl(record[column.link]);
        if (href && text !== "—") {
          const link = document.createElement("a");
          link.href = href;
          link.target = "_blank";
          link.rel = "noopener noreferrer";
          link.textContent = text;
          cell.append(link);
        } else {
          cell.textContent = text;
        }
      } else {
        cell.textContent = text;
      }
      row.append(cell);
    }
    fragment.append(row);
  }
  body.replaceChildren(fragment);
}

function formatNumber(value) {
  if (!Number.isFinite(value)) return "—";
  return new Intl.NumberFormat("en-US", { notation: value >= 10000 ? "compact" : "standard", maximumFractionDigits: 1 }).format(value);
}

function renderStats(metadata) {
  const counts = metadata && isPlainRecord(metadata.counts) ? metadata.counts : null;
  if (!counts) return;
  const total = DATASETS.reduce((sum, dataset) => {
    const count = counts[dataset.id];
    return sum + (Number.isInteger(count) && count >= 0 ? count : 0);
  }, 0);
  const setText = (id, value) => { const element = byId(id); if (element) element.textContent = value; };
  setText("stat-repositories", formatNumber(counts.repos));
  setText("stat-commits", formatNumber(counts.commits));
  setText("stat-branches", formatNumber(counts.branches));
  setText("stat-records", formatNumber(total));
  setText("generated-at", typeof metadata.generatedAt === "string" ? metadata.generatedAt.replace("T", " ").replace(/Z$/, " UTC") : "Timestamp unavailable");

  const login = typeof metadata.profile?.login === "string" ? metadata.profile.login : "";
  const profileLink = byId("profile-link");
  const profileLogin = byId("profile-login");
  if (login && /^[A-Za-z0-9-]{1,39}$/.test(login)) {
    if (profileLogin) profileLogin.textContent = `@${login}`;
    if (profileLink) profileLink.href = `https://github.com/${encodeURIComponent(login)}`;
  }
}

function buildDatasetOptions() {
  const select = byId("dataset-select");
  if (!select) return;
  const fragment = document.createDocumentFragment();
  for (const dataset of DATASETS) {
    const option = document.createElement("option");
    option.value = dataset.id;
    option.textContent = dataset.label;
    fragment.append(option);
  }
  select.replaceChildren(fragment);
  select.value = state.dataset;
}

function buildDownloadLinks(dataset) {
  const container = byId("download-links");
  if (!container) return;
  const fragment = document.createDocumentFragment();
  for (const format of ["json", "jsonl", "csv"]) {
    const link = document.createElement("a");
    link.href = new URL(`reports/${dataset.id}.${format}`, SITE_ROOT).href;
    link.download = `${dataset.id}.${format}`;
    link.textContent = format.toUpperCase();
    link.setAttribute("aria-label", `Download ${dataset.label} as ${format.toUpperCase()}`);
    fragment.append(link);
  }
  container.replaceChildren(fragment);
}

function populateLanguages(rows) {
  const select = byId("repo-language");
  if (!select) return;
  const languages = [...new Set(rows.map((row) => typeof row.language === "string" ? row.language.trim() : "").filter(Boolean))]
    .sort((a, b) => a.localeCompare(b, "en", { sensitivity: "base" }));
  const current = state.repoLanguage;
  const fragment = document.createDocumentFragment();
  const anyOption = document.createElement("option");
  anyOption.value = "";
  anyOption.textContent = "Any language";
  fragment.append(anyOption);
  for (const language of languages) {
    const option = document.createElement("option");
    option.value = language;
    option.textContent = language;
    fragment.append(option);
  }
  select.replaceChildren(fragment);
  select.value = languages.some((language) => normalizeText(language) === normalizeText(current)) ? current : "";
}

function currentFilters() {
  if (state.dataset === "repos") {
    return {
      query: state.query,
      language: state.repoLanguage,
      minStars: state.repoMinStars,
      includeForks: state.includeForks,
    };
  }
  return { query: state.query };
}

async function renderDataset() {
  const dataset = DATASET_BY_ID.get(state.dataset);
  if (!dataset || !byId("table-body")) return false;
  const renderId = ++state.renderSequence;
  const repoFilters = byId("repo-filter-options");
  if (repoFilters) repoFilters.hidden = dataset.id !== "repos";
  const description = byId("dataset-description");
  if (description) description.textContent = dataset.description;
  const selector = byId("dataset-select");
  if (selector && selector.value !== dataset.id) selector.value = dataset.id;
  const query = byId("filter-input");
  if (query && query.value !== state.query) query.value = state.query;
  const languageSelect = byId("repo-language");
  if (languageSelect && languageSelect.value !== state.repoLanguage) languageSelect.value = state.repoLanguage;
  const minimumStars = byId("repo-min-stars");
  if (minimumStars && minimumStars.value !== String(state.repoMinStars)) minimumStars.value = String(state.repoMinStars);
  const includeForks = byId("repo-include-forks");
  if (includeForks && includeForks.checked !== state.includeForks) includeForks.checked = state.includeForks;
  buildDownloadLinks(dataset);
  renderHeader(dataset);
  setExplorerStatus(`Loading ${dataset.label.toLocaleLowerCase("en-US")}…`);

  try {
    const records = await loadDataset(dataset.id);
    if (renderId !== state.renderSequence) return false;
    if (dataset.id === "repos") populateLanguages(records);
    const matching = dataset.id === "repos" ? filterRepositoryRows(records, currentFilters()) : filterDatasetRows(records, state.query);
    const total = matching.length;
    const start = Math.min(state.offset, total);
    const page = matching.slice(start, start + state.limit);
    renderRows(dataset, page);
    const countText = byId("dataset-result-count");
    if (countText) countText.textContent = `${formatNumber(total)} matching record${total === 1 ? "" : "s"}`;
    const pageLabel = byId("page-label");
    if (pageLabel) pageLabel.textContent = total === 0 ? "0 records" : page.length === 0 ? `No records at offset ${state.offset}` : `${formatNumber(start + 1)}–${formatNumber(start + page.length)} of ${formatNumber(total)}`;
    const previous = byId("previous-page");
    const next = byId("next-page");
    if (previous) previous.disabled = start <= 0;
    if (next) next.disabled = start + page.length >= total;
    const q = state.query ? ` for “${state.query.slice(0, 70)}${state.query.length > 70 ? "…" : ""}”` : "";
    setExplorerStatus(`Showing ${page.length} of ${formatNumber(total)} matching ${dataset.label.toLocaleLowerCase("en-US")}${q}.`);
    return true;
  } catch {
    if (renderId !== state.renderSequence) return false;
    const body = byId("table-body");
    if (body) {
      const row = document.createElement("tr");
      const cell = document.createElement("td");
      cell.colSpan = Math.max(dataset.columns.length, 1);
      cell.className = "empty-state";
      cell.textContent = "This report export could not be loaded.";
      row.append(cell);
      body.replaceChildren(row);
    }
    const countText = byId("dataset-result-count");
    if (countText) countText.textContent = "Report data unavailable";
    setExplorerStatus("Could not load this local report export. Check your connection and retry, or use a download link.", "error", true);
    const pageLabel = byId("page-label");
    if (pageLabel) pageLabel.textContent = "Unavailable";
    return false;
  }
}

async function setExplorerView({ dataset, query = "", offset = 0, limit = PAGE_SIZE, repoLanguage = "", repoMinStars = 0, includeForks = true }) {
  if (!byId("table-body")) return false;
  if (!DATASET_BY_ID.has(dataset)) return false;
  state.dataset = dataset;
  state.query = query;
  state.offset = offset;
  state.limit = limit;
  state.repoLanguage = repoLanguage;
  state.repoMinStars = repoMinStars;
  state.includeForks = includeForks;
  return renderDataset();
}

function initExplorer() {
  if (!byId("table-body")) return;
  buildDatasetOptions();
  const datasetSelect = byId("dataset-select");
  datasetSelect?.addEventListener("change", () => {
    const selected = DATASET_BY_ID.has(datasetSelect.value) ? datasetSelect.value : "repos";
    state.dataset = selected;
    state.query = "";
    state.offset = 0;
    if (selected !== "repos") {
      state.repoLanguage = "";
      state.repoMinStars = 0;
      state.includeForks = true;
    }
    void renderDataset();
  });

  const filterInput = byId("filter-input");
  let queryTimer = 0;
  filterInput?.addEventListener("input", () => {
    state.query = filterInput.value.slice(0, 100);
    state.offset = 0;
    window.clearTimeout(queryTimer);
    queryTimer = window.setTimeout(() => { void renderDataset(); }, 100);
  });

  const languageSelect = byId("repo-language");
  languageSelect?.addEventListener("change", () => {
    state.repoLanguage = languageSelect.value;
    state.offset = 0;
    void renderDataset();
  });
  const minimumStars = byId("repo-min-stars");
  minimumStars?.addEventListener("input", () => {
    const value = Number(minimumStars.value);
    state.repoMinStars = Number.isInteger(value) && value >= 0 && value <= 100000 ? value : 0;
    state.offset = 0;
    void renderDataset();
  });
  const includeForks = byId("repo-include-forks");
  includeForks?.addEventListener("change", () => {
    state.includeForks = includeForks.checked;
    state.offset = 0;
    void renderDataset();
  });
  byId("clear-filters")?.addEventListener("click", () => {
    state.query = "";
    state.repoLanguage = "";
    state.repoMinStars = 0;
    state.includeForks = true;
    state.offset = 0;
    if (filterInput) filterInput.value = "";
    if (languageSelect) languageSelect.value = "";
    if (minimumStars) minimumStars.value = "0";
    if (includeForks) includeForks.checked = true;
    void renderDataset();
  });
  byId("previous-page")?.addEventListener("click", () => {
    state.offset = Math.max(0, state.offset - state.limit);
    void renderDataset();
  });
  byId("next-page")?.addEventListener("click", () => {
    state.offset += state.limit;
    void renderDataset();
  });
  void renderDataset();
}

async function overviewData(signal) {
  throwIfAborted(signal);
  const metadata = await awaitWithSignal(optionalMetadata(), signal);
  throwIfAborted(signal);
  const counts = metadata && isPlainRecord(metadata.counts) ? metadata.counts : {};
  const generatedAt = typeof metadata?.generatedAt === "string" ? metadata.generatedAt : null;
  const login = typeof metadata?.profile?.login === "string" ? metadata.profile.login : null;
  const datasets = DATASETS.map((dataset) => ({
    id: dataset.id,
    name: dataset.label,
    description: dataset.description,
    count: Number.isInteger(counts[dataset.id]) && counts[dataset.id] >= 0 ? counts[dataset.id] : null,
    formats: ["json", "jsonl", "csv"],
  }));
  const totalRecords = datasets.every((dataset) => dataset.count !== null)
    ? datasets.reduce((sum, dataset) => sum + dataset.count, 0)
    : null;
  const safeLogin = typeof login === "string" && /^[A-Za-z0-9-]{1,39}$/.test(login) ? login : null;
  return {
    data: {
      profile: safeLogin ? { login: safeLogin, url: `https://github.com/${encodeURIComponent(safeLogin)}` } : null,
      generatedAt,
      datasetCount: DATASETS.length,
      totalRecords,
      datasets,
      capabilities: { reportDataReadOnly: true, liveGithubRequests: false, persistentWrites: false, temporaryViewChanges: true },
    },
    meta: { truncated: false },
  };
}

async function searchRepositories(args, signal) {
  throwIfAborted(signal);
  const rows = await loadDataset("repos", signal);
  throwIfAborted(signal);
  const matching = filterRepositoryRows(rows, {
    query: args.query,
    language: args.language,
    minStars: args.min_stars,
    includeForks: args.include_forks,
  });
  if (args.offset > 0 && args.offset >= matching.length) {
    throw new ToolInputError("The offset is beyond the matching repository results. Choose a smaller offset.");
  }
  const items = matching.slice(args.offset, args.offset + args.limit).map((row) => ({
    name: row.name,
    owner: row.owner,
    url: row.url,
    description: row.description || "",
    language: row.language || "unknown",
    stars: row.stars,
    forks: row.forks,
    watchers: row.watchers,
    open_issues: row.open_issues,
    updated_at: row.updated_at,
    is_fork: Boolean(row.is_fork),
  }));
  const nextOffset = args.offset + items.length < matching.length ? args.offset + items.length : null;
  await setExplorerView({
    dataset: "repos",
    query: args.query,
    offset: args.offset,
    limit: args.limit,
    repoLanguage: args.language,
    repoMinStars: args.min_stars,
    includeForks: args.include_forks,
  });
  return {
    data: {
      total: matching.length,
      offset: args.offset,
      limit: args.limit,
      returned: items.length,
      items,
      hasMore: nextOffset !== null,
      nextOffset,
      appliedFilters: {
        query: args.query || null,
        language: args.language || null,
        min_stars: args.min_stars,
        include_forks: args.include_forks,
      },
    },
    meta: { truncated: nextOffset !== null },
  };
}

async function getRepositoryDetails(args, signal) {
  throwIfAborted(signal);
  const repositories = await loadDataset("repos", signal);
  throwIfAborted(signal);
  const requested = normalizeText(args.repository);
  const slash = requested.lastIndexOf("/");
  const shortName = slash >= 0 ? requested.slice(slash + 1) : requested;
  const requestedOwner = slash >= 0 ? requested.slice(0, slash) : "";
  const repo = repositories.find((record) => normalizeText(record.name) === shortName && (!requestedOwner || normalizeText(record.owner) === requestedOwner));
  if (!repo) throw new ToolNotFoundError("No exact repository match was found. Search repositories to find a valid name.");

  const related = await Promise.all(RELATED_DATASET_IDS.map(async (datasetId) => {
    const records = await loadDataset(datasetId, signal);
    const matches = records.filter((record) => normalizeText(record.repo) === normalizeText(repo.name));
    return [datasetId, matches];
  }));
  throwIfAborted(signal);
  const relatedCounts = Object.fromEntries(related.map(([datasetId, matches]) => [datasetId, matches.length]));
  const data = {
    repository: repo,
    relatedCounts,
  };
  if (args.include_samples) {
    data.samples = Object.fromEntries(SAMPLE_DATASET_IDS.map((datasetId) => {
      const matches = related.find(([id]) => id === datasetId)?.[1] || [];
      return [datasetId, matches.slice(0, 1)];
    }));
  }
  await setExplorerView({ dataset: "repos", query: `${repo.owner}/${repo.name}`, offset: 0, limit: PAGE_SIZE, includeForks: true });
  return { data, meta: { truncated: false } };
}

async function searchReport(args, signal) {
  throwIfAborted(signal);
  const rows = await loadDataset(args.dataset, signal);
  throwIfAborted(signal);
  const matching = filterDatasetRows(rows, args.query);
  const dataset = DATASET_BY_ID.get(args.dataset);
  if (args.offset > 0 && args.offset >= matching.length) {
    throw new ToolInputError("The offset is beyond the matching records. Choose a smaller offset.");
  }
  const items = matching.slice(args.offset, args.offset + args.limit);
  const nextOffset = args.offset + items.length < matching.length ? args.offset + items.length : null;
  await setExplorerView({ dataset: args.dataset, query: args.query, offset: args.offset, limit: args.limit });
  return {
    data: {
      dataset: args.dataset,
      datasetName: dataset.label,
      total: matching.length,
      offset: args.offset,
      limit: args.limit,
      returned: items.length,
      items,
      hasMore: nextOffset !== null,
      nextOffset,
    },
    meta: { truncated: nextOffset !== null },
  };
}

async function getDatasetPage(args, signal) {
  throwIfAborted(signal);
  const rows = await loadDataset(args.dataset, signal);
  throwIfAborted(signal);
  if (args.offset >= rows.length && rows.length > 0) {
    throw new ToolInputError("The offset is at or beyond the end of this dataset. Choose an offset below its total record count.");
  }
  if (rows.length === 0 && args.offset > 0) {
    throw new ToolInputError("The empty dataset only has offset 0.");
  }
  const items = rows.slice(args.offset, args.offset + args.limit);
  const nextOffset = args.offset + items.length < rows.length ? args.offset + items.length : null;
  const dataset = DATASET_BY_ID.get(args.dataset);
  await setExplorerView({ dataset: args.dataset, query: "", offset: args.offset, limit: args.limit });
  return {
    data: {
      dataset: args.dataset,
      datasetName: dataset.label,
      total: rows.length,
      offset: args.offset,
      limit: args.limit,
      returned: items.length,
      items,
      hasMore: nextOffset !== null,
      nextOffset,
    },
    meta: { truncated: nextOffset !== null },
  };
}

function makeTool({ name, title, description, inputSchema, allowedKeys, validate, run, readOnlyHint = false }) {
  return {
    name,
    title,
    description,
    inputSchema,
    annotations: {
      readOnlyHint,
      untrustedContentHint: true,
      consequentialHint: false,
    },
    execute: async (input = {}, options = {}) => {
      let args;
      try {
        const object = parseArgs(input, allowedKeys);
        args = validate(object);
      } catch (error) {
        if (error instanceof ToolInputError) return makeFailure("invalid_input", error.message);
        return makeFailure("invalid_input", "Tool arguments are invalid. Check the tool schema and try again.");
      }
      const signal = options && typeof options === "object" ? options.signal : undefined;
      if (signal?.aborted) return makeFailure("cancelled", "The tool call was cancelled.");
      try {
        const result = await run(args, signal);
        if (signal?.aborted) return makeFailure("cancelled", "The tool call was cancelled.");
        return makeSuccess(result);
      } catch (error) {
        if (signal?.aborted || error instanceof ToolCancelledError) return makeFailure("cancelled", "The tool call was cancelled.");
        if (error instanceof ToolInputError) return makeFailure("invalid_input", error.message);
        if (error instanceof ToolNotFoundError) return makeFailure("not_found", error.message);
        if (error instanceof DataIntegrityError) return makeFailure("data_unavailable", "The local report export is unavailable or malformed. Retry later or use the dataset download links.", { retryable: true });
        return makeFailure("data_unavailable", "The local report export could not be read. Retry later or use the dataset download links.", { retryable: true });
      }
    },
  };
}

const DATASET_ENUM = DATASETS.map((dataset) => dataset.id);
const TOOL_DEFINITIONS = [
  makeTool({
    name: "get_site_overview",
    title: "Get report overview",
    description: "Read the profile, export timestamp, record totals, and available public-report datasets and download formats.",
    inputSchema: { type: "object", properties: {}, additionalProperties: false },
    allowedKeys: [],
    validate: () => ({}),
    run: overviewData,
    readOnlyHint: true,
  }),
  makeTool({
    name: "search_repositories",
    title: "Search repositories",
    description: "Search public repository records by text, language, minimum stars, and fork status. Returns bounded results and applies the same filters to the visible repository table; this changes only the temporary view, never report data.",
    inputSchema: {
      type: "object",
      properties: {
        query: { type: "string", description: "Text in repository name, owner, description, or language.", maxLength: 100 },
        language: { type: "string", description: "Exact programming-language filter.", maxLength: 50 },
        min_stars: { type: "integer", description: "Minimum star count, from 0 to 100000.", minimum: 0, maximum: 100000 },
        include_forks: { type: "boolean", description: "Whether forked repositories are included." },
        offset: { type: "integer", description: "Zero-based result offset, from 0 to 100000.", minimum: 0, maximum: 100000 },
        limit: { type: "integer", description: "Maximum number of compact matches to return, from 1 to 5.", minimum: 1, maximum: 5 },
      },
      additionalProperties: false,
    },
    allowedKeys: ["query", "language", "min_stars", "include_forks", "offset", "limit"],
    validate: (args) => ({
      query: optionalString(args, "query", { maxLength: 100 }),
      language: optionalString(args, "language", { maxLength: 50 }),
      min_stars: optionalInteger(args, "min_stars", { defaultValue: 0, min: 0, max: 100000 }),
      include_forks: optionalBoolean(args, "include_forks", true),
      offset: optionalInteger(args, "offset", { defaultValue: 0, min: 0, max: 100000 }),
      limit: optionalInteger(args, "limit", { defaultValue: MAX_TOOL_SEARCH_RESULTS, min: 1, max: MAX_TOOL_SEARCH_RESULTS }),
    }),
    run: searchRepositories,
  }),
  makeTool({
    name: "get_repository_details",
    title: "Get repository details",
    description: "Read one exact repository record and counts from related public datasets, then select that repository in the visible explorer. This changes only the temporary view, never report data.",
    inputSchema: {
      type: "object",
      properties: {
        repository: { type: "string", description: "Exact repository name, optionally prefixed with its owner.", minLength: 1, maxLength: 100 },
        include_samples: { type: "boolean", description: "Include one bounded sample from selected activity categories." },
      },
      required: ["repository"],
      additionalProperties: false,
    },
    allowedKeys: ["repository", "include_samples"],
    validate: (args) => ({
      repository: optionalString(args, "repository", { required: true, maxLength: 100 }),
      include_samples: optionalBoolean(args, "include_samples", false),
    }),
    run: getRepositoryDetails,
  }),
  makeTool({
    name: "search_report",
    title: "Search a report dataset",
    description: "Search text and scalar values in one public-report dataset and show the same filtered dataset in the explorer; this updates only the temporary view, never report data.",
    inputSchema: {
      type: "object",
      properties: {
        dataset: { type: "string", description: "Dataset identifier from the site's dataset catalog.", enum: DATASET_ENUM },
        query: { type: "string", description: "Text to find in records in the selected dataset.", minLength: 1, maxLength: 100 },
        offset: { type: "integer", description: "Zero-based result offset, from 0 to 100000.", minimum: 0, maximum: 100000 },
        limit: { type: "integer", description: "Maximum matching records to return, from 1 to 5.", minimum: 1, maximum: 5 },
      },
      required: ["dataset", "query"],
      additionalProperties: false,
    },
    allowedKeys: ["dataset", "query", "offset", "limit"],
    validate: (args) => ({
      dataset: datasetField(args),
      query: optionalString(args, "query", { required: true, maxLength: 100 }),
      offset: optionalInteger(args, "offset", { defaultValue: 0, min: 0, max: 100000 }),
      limit: optionalInteger(args, "limit", { defaultValue: MAX_TOOL_SEARCH_RESULTS, min: 1, max: MAX_TOOL_SEARCH_RESULTS }),
    }),
    run: searchReport,
  }),
  makeTool({
    name: "get_dataset_page",
    title: "Read a dataset page",
    description: "Read a bounded page of records from one public-report dataset and select that page in the explorer; this updates only the temporary view, never report data.",
    inputSchema: {
      type: "object",
      properties: {
        dataset: { type: "string", description: "Dataset identifier from the site's dataset catalog.", enum: DATASET_ENUM },
        offset: { type: "integer", description: "Zero-based record offset, from 0 to 100000.", minimum: 0, maximum: 100000 },
        limit: { type: "integer", description: "Maximum records to return, from 1 to 10.", minimum: 1, maximum: 10 },
      },
      required: ["dataset"],
      additionalProperties: false,
    },
    allowedKeys: ["dataset", "offset", "limit"],
    validate: (args) => ({
      dataset: datasetField(args),
      offset: optionalInteger(args, "offset", { defaultValue: 0, min: 0, max: 100000 }),
      limit: optionalInteger(args, "limit", { defaultValue: MAX_TOOL_PAGE_RESULTS, min: 1, max: MAX_TOOL_PAGE_RESULTS }),
    }),
    run: getDatasetPage,
  }),
];

function renderWebMcpStatus(message, names = []) {
  const status = byId("webmcp-status-text");
  if (status) status.textContent = message;
  const list = byId("webmcp-tool-list");
  if (!list) return;
  const fragment = document.createDocumentFragment();
  for (const name of names) {
    const item = document.createElement("li");
    item.textContent = name;
    fragment.append(item);
  }
  list.replaceChildren(fragment);
}

function getModelContext() {
  if (typeof document === "undefined") return null;
  const contexts = [document.modelContext, globalThis.navigator?.modelContext];
  return contexts.find((context) => context && typeof context.registerTool === "function") || null;
}

async function registerWebMcpTools() {
  if (registrationState === "registering" || registrationState === "ready") return;
  const modelContext = getModelContext();
  if (!modelContext) {
    registrationState = "unsupported";
    renderWebMcpStatus("Not detected in this browser. The report explorer still works normally.");
    return;
  }

  registrationState = "registering";
  const controller = new AbortController();
  registrationController = controller;
  const registered = [];
  try {
    for (const definition of TOOL_DEFINITIONS) {
      if (controller.signal.aborted) throw new ToolCancelledError("Registration cancelled.");
      await modelContext.registerTool(definition, { signal: controller.signal });
      registered.push(definition.name);
    }
    if (registrationController !== controller || controller.signal.aborted) return;
    registrationState = "ready";
    renderWebMcpStatus(`WebMCP ready · ${registered.length} tools registered. Search and page tools may change only this temporary view; report data is never modified.`, registered);
  } catch {
    controller.abort();
    if (registrationController !== controller) return;
    registrationState = "failed";
    renderWebMcpStatus("WebMCP was detected, but tool registration was blocked or unavailable. The human-facing site remains available.");
  }
}

function init() {
  if (typeof document === "undefined") return;
  initExplorer();
  void optionalMetadata().then((metadata) => renderStats(metadata));
  void registerWebMcpTools();

  window.addEventListener("pagehide", () => {
    if (registrationController) registrationController.abort();
    registrationController = null;
    registrationState = "idle";
  }, { once: true });
  window.addEventListener("pageshow", (event) => {
    if (event.persisted) void registerWebMcpTools();
  });
}

init();
