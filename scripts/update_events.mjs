// scripts/update_events.mjs
// Node 20+
// Generates:
//  - app/data/events/events_official.json
//  - app/data/events/events_news.json
//
// Policy:
// - NEWS: title + link only (no body, no summary, no excerpts)
// - OFFICIAL: title + link + minimal classification (template_id) only

import fs from "fs";
import path from "path";
import crypto from "crypto";

const ROOT = process.cwd();
const SOURCES_PATH = path.join(ROOT, "app", "data", "sources_events.json");
const OUT_DIR = path.join(ROOT, "app", "data", "events");
const OFFICIAL_OUT = path.join(OUT_DIR, "events_official.json");
const NEWS_OUT = path.join(OUT_DIR, "events_news.json");

function readJSON(p) {
  return JSON.parse(fs.readFileSync(p, "utf-8"));
}
function writeJSON(p, obj) {
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, JSON.stringify(obj, null, 2), "utf-8");
}
function sha1(s) {
  return crypto.createHash("sha1").update(s).digest("hex");
}
function toYMD(dateLike) {
  if (!dateLike) return "";
  const d = new Date(dateLike);
  if (Number.isNaN(d.getTime())) return "";
  return d.toISOString().slice(0, 10);
}
function decodeEntities(s = "") {
  return s
    .replace(/<!\[CDATA\[([\s\S]*?)\]\]>/g, "$1")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'");
}
function extractTag(block, tag) {
  const re = new RegExp(`<${tag}[^>]*>([\\s\\S]*?)<\\/${tag}>`, "i");
  const m = block.match(re);
  return m ? decodeEntities(m[1].trim()) : "";
}
function extractAtomLink(block) {
  const m = block.match(/<link[^>]*href=["']([^"']+)["'][^>]*\/?>/i);
  if (m) return decodeEntities(m[1].trim());
  const link = extractTag(block, "link");
  return link || "";
}
function parseFeed(xml) {
  const items = [];
  const itemBlocks = xml.match(/<item[\s\S]*?<\/item>/gi) || [];
  for (const block of itemBlocks) {
    const title = extractTag(block, "title");
    const link = extractTag(block, "link");
    const pubDate = extractTag(block, "pubDate") || extractTag(block, "dc:date");
    if (title && link) items.push({ title, link, pubDate });
  }
  if (items.length === 0) {
    const entryBlocks = xml.match(/<entry[\s\S]*?<\/entry>/gi) || [];
    for (const block of entryBlocks) {
      const title = extractTag(block, "title");
      const link = extractAtomLink(block);
      const updated = extractTag(block, "updated") || extractTag(block, "published");
      if (title && link) items.push({ title, link, pubDate: updated });
    }
  }
  return items;
}
async function fetchText(url) {
  const res = await fetch(url, {
    headers: { "user-agent": "Mozilla/5.0 (GitHubActions; MarketDigestBot/1.0)" }
  });
  if (!res.ok) throw new Error(`Fetch failed ${res.status}: ${url}`);
  return await res.text();
}
function classifySpeciesFromTitle(title) {
  const t = (title || "").toLowerCase();
  const species = new Set();
  if (t.includes("한우") || t.includes("소고기") || t.includes("우육") || t.includes("beef")) species.add("BEEF");
  if (t.includes("돼지") || t.includes("돈육") || t.includes("삼겹") || t.includes("pork")) species.add("PORK");
  if (t.includes("닭") || t.includes("계육") || t.includes("가금") || t.includes("chicken")) species.add("POULTRY");
  if (t.includes("오리") || t.includes("duck")) species.add("DUCK");
  if (t.includes("계란") || t.includes("달걀") || t.includes("egg")) species.add("EGG");
  return [...species];
}
function severityFromTitle(title, defaultSev = "MID") {
  const t = (title || "").toLowerCase();
  if (t.includes("확진") || t.includes("발생") || t.includes("긴급") || t.includes("살처분") || t.includes("경보")) return "HIGH";
  if (t.includes("주의") || t.includes("우려") || t.includes("확대")) return "MID";
  return defaultSev;
}
function buildOfficialTemplateId(title) {
  const t = (title || "").toLowerCase();
  if (t.includes("asf") || t.includes("돼지열병") || t.includes("고병원성") || t.includes(" ai") || t.includes("구제역")) {
    return "OFFICIAL_DISEASE_UPDATE";
  }
  return "OFFICIAL_NOTICE";
}
function loadExisting(pathOut) {
  if (!fs.existsSync(pathOut)) return { generated_at: "", items: [] };
  try { return JSON.parse(fs.readFileSync(pathOut, "utf-8")); }
  catch { return { generated_at: "", items: [] }; }
}
function dedupeAndKeep(items, daysKeep) {
  const byId = new Map();
  for (const it of items) byId.set(it.event_id, it);

  const cutoff = Date.now() - daysKeep * 24 * 60 * 60 * 1000;
  const kept = [...byId.values()].filter((it) => {
    const d = new Date(it.published_at || it.date);
    if (Number.isNaN(d.getTime())) return true;
    return d.getTime() >= cutoff;
  });

  kept.sort((a, b) => {
    const da = new Date(a.published_at || a.date).getTime() || 0;
    const db = new Date(b.published_at || b.date).getTime() || 0;
    return db - da;
  });

  return kept;
}

async function main() {
  const sources = readJSON(SOURCES_PATH);
  const rules = sources.rules || {};
  const maxItems = rules.max_items_per_feed ?? 30;
  const daysKeep = rules.days_keep ?? 45;

  const existingOfficial = loadExisting(OFFICIAL_OUT);
  const existingNews = loadExisting(NEWS_OUT);

  let officialItems = [...(existingOfficial.items || [])];
  let newsItems = [...(existingNews.items || [])];

  const officialSourcesStatus = [];
  const newsSourcesStatus = [];

  for (const feed of sources.official_rss || []) {
    const st = { id: feed.id, name: feed.name, url: feed.url, ok: false, count: 0, status: null, error: null };
    try {
      const xml = await fetchText(feed.url);
      const parsed = parseFeed(xml).slice(0, maxItems);
      st.ok = true;
      st.count = parsed.length;
      for (const it of parsed) {
        const url = it.link;
        const eventId = `OFF_${sha1(url).slice(0, 10)}`;
        officialItems.push({
          event_id: eventId,
          date: toYMD(it.pubDate) || toYMD(new Date()),
          category: "OFFICIAL",
          subcategory: feed.category,
          severity: severityFromTitle(it.title, feed.severity_default || "MID"),
          species: classifySpeciesFromTitle(it.title),
          region: "KR",
          facts: {},
          template_id: buildOfficialTemplateId(it.title),
          title: it.title,
          source_title: feed.name,
          source_url: url,
          published_at: it.pubDate ? new Date(it.pubDate).toISOString() : ""
        });
      }
    } catch (e) {
      st.error = String(e?.message || e);
    }
    officialSourcesStatus.push(st);
  }

  for (const feed of sources.news_rss || []) {
    const st = { id: feed.id, name: feed.name, url: feed.url, ok: false, count: 0, status: null, error: null };
    try {
      const xml = await fetchText(feed.url);
      const parsed = parseFeed(xml).slice(0, maxItems);
      st.ok = true;
      st.count = parsed.length;
      for (const it of parsed) {
        const url = it.link;
        const eventId = `NEWS_${sha1(url).slice(0, 10)}`;
        const species = (feed.species_tags && feed.species_tags.length)
          ? feed.species_tags
          : classifySpeciesFromTitle(it.title);
        newsItems.push({
          event_id: eventId,
          date: toYMD(it.pubDate) || toYMD(new Date()),
          category: "NEWS",
          severity: severityFromTitle(it.title, rules.default_news_severity || "MID"),
          species,
          tags: feed.tags || [],
          title: it.title,
          publisher: "",
          url,
          published_at: it.pubDate ? new Date(it.pubDate).toISOString() : ""
        });
      }
    } catch (e) {
      st.error = String(e?.message || e);
    }
    officialSourcesStatus.push(st);
  }

  officialItems = dedupeAndKeep(officialItems, daysKeep);
  newsItems = dedupeAndKeep(newsItems, daysKeep);

  writeJSON(OFFICIAL_OUT, { generated_at: new Date().toISOString(), items: officialItems, _sources: officialSourcesStatus });
  writeJSON(NEWS_OUT, { generated_at: new Date().toISOString(), items: newsItems, _sources: newsSourcesStatus, disclaimer: "민간 뉴스는 제목/링크만 제공합니다. 본문 요약·발췌는 하지 않습니다." });

  console.log(`official: ${officialItems.length}, news: ${newsItems.length}`);
}

main().catch((e) => { console.error(e); process.exit(1); });
