#!/usr/bin/env node
/**
 * update_data.mjs (v2.5)
 * - 목적: 공공/공식 원자료(가격/환율/곡물 등)를 수집/정규화하여
 *        app/data/aggregated/species_summary.json 생성
 * - 원칙: AI/예측 없음, 룰 기반 비교(전주/전월/전년동월)만 산출
 *
 * 운영 방식:
 * 1) app/data/sources/sources.json 의 url을 채우면 그걸 사용
 * 2) url이 비어있으면 샘플 데이터로 species_summary.json을 생성(앱 UI 검증용)
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const REPO = path.resolve(__dirname, "..");
const DATA = path.join(REPO, "app", "data");
const SOURCES_JSON = path.join(DATA, "sources", "sources.json");
const OUT_SUMMARY = path.join(DATA, "aggregated", "species_summary.json");

function readJSON(p, fallback=null){
  try { return JSON.parse(fs.readFileSync(p, "utf-8")); } catch(e){ return fallback; }
}
function writeJSON(p, obj){
  fs.mkdirSync(path.dirname(p), { recursive:true });
  fs.writeFileSync(p, JSON.stringify(obj, null, 2), "utf-8");
}

async function fetchText(url){
  const r = await fetch(url, { headers: { "User-Agent":"data-bot/1.0" } });
  if (!r.ok) throw new Error(`HTTP ${r.status} ${r.statusText}: ${url}`);
  return await r.text();
}
function parseCSV(text){
  const lines = text.split(/\r?\n/).filter(Boolean);
  if (!lines.length) return [];
  const head = lines[0].split(",").map(s=>s.trim());
  return lines.slice(1).map(line=>{
    const cols = line.split(",");
    const o = {};
    head.forEach((h,i)=> o[h]= (cols[i] ?? "").trim());
    return o;
  });
}
function pctChange(cur, base){
  if (cur==null || base==null || base===0) return null;
  return ((cur - base) / base) * 100;
}
function memoRule(wow, mom, yoy){
  const parts = [];
  const s = (v)=> (v==null? null : (v>=0? `+${v.toFixed(1)}%` : `${v.toFixed(1)}%`));
  if (wow!=null){
    if (Math.abs(wow) < 1) parts.push(`전주 대비 보합(${s(wow)})`);
    else if (wow > 0) parts.push(`전주 대비 상승(${s(wow)})`);
    else parts.push(`전주 대비 하락(${s(wow)})`);
  }
  if (mom!=null){
    if (mom > 2) parts.push(`전월 대비 강세(${s(mom)})`);
    else if (mom < -2) parts.push(`전월 대비 약세(${s(mom)})`);
  }
  if (yoy!=null){
    if (yoy > 5) parts.push(`전년 동월 대비 상회(${s(yoy)})`);
    else if (yoy < -5) parts.push(`전년 동월 대비 하회(${s(yoy)})`);
  }
  return parts.join(" · ") || "데이터 축적 중";
}
function makeSampleSeries(base, weeks=12){
  const arr = [];
  let v = base;
  for (let i=0;i<weeks;i++){
    v = v * (1 + ((i%3)-1) * 0.003);
    arr.push(Math.round(v));
  }
  return arr;
}
function buildSampleSummary(){
  const now = new Date().toISOString();
  const items = [
    { species:"돈육", metric:"지육경락가", unit:"원/kg", current: 5100, series_12w: makeSampleSeries(5050) },
    { species:"우육", metric:"한우지육경락가", unit:"원/kg", current: 17400, series_12w: makeSampleSeries(17600) },
    { species:"계란", metric:"특란산지가", unit:"원/개", current: 180, series_12w: makeSampleSeries(185) },
    { species:"계육", metric:"닭도체가격", unit:"원/kg", current: 2900, series_12w: makeSampleSeries(2850) },
  ].map(it=>{
    const s = it.series_12w;
    const cur = it.current;
    const wowBase = s.length>=2 ? s[s.length-2] : null;
    const momBase = s.length>=5 ? s[s.length-5] : null;
    const yoyBase = null;
    const wow = pctChange(cur, wowBase);
    const mom = pctChange(cur, momBase);
    const yoy = null;
    return { ...it, wow, mom, yoy, memo: memoRule(wow, mom, yoy) };
  });
  return {
    updated_at: now,
    basis: { week:"전주 대비", month:"전월 대비", yoy:"전년 동월 대비" },
    mode: "sample",
    items
  };
}

async function main(){
  const cfg = readJSON(SOURCES_JSON, null);
  if (!cfg || !Array.isArray(cfg.sources)){
    console.error("sources.json missing or invalid:", SOURCES_JSON);
    process.exit(1);
  }

  const urls = cfg.sources.filter(s=>s.url && String(s.url).trim().length>0);
  if (urls.length === 0){
    const out = buildSampleSummary();
    writeJSON(OUT_SUMMARY, out);
    cfg.updated_at = new Date().toISOString();
    writeJSON(SOURCES_JSON, cfg);
    console.log("[OK] Generated sample species_summary.json (no source urls configured).");
    return;
  }

  const status = {};
  for (const s of cfg.sources){
    if (!s.url) continue;
    try{
      const txt = await fetchText(s.url);
      const rows = s.url.toLowerCase().includes(".csv") ? parseCSV(txt) : JSON.parse(txt);
      status[s.id] = { ok:true, count: Array.isArray(rows)? rows.length : null };
    }catch(e){
      status[s.id] = { ok:false, error: String(e?.message || e) };
    }
  }

  const out = buildSampleSummary();
  out.mode = "sample_with_fetch_status";
  out.fetch_status = status;
  writeJSON(OUT_SUMMARY, out);

  cfg.updated_at = new Date().toISOString();
  writeJSON(SOURCES_JSON, cfg);
  console.log("[OK] update_data finished (placeholder summary). Configure urls + parsers to go live.");
}

main().catch(e=>{
  console.error(e);
  process.exit(1);
});
