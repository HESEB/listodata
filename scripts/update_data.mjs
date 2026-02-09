#!/usr/bin/env node
/**
 * update_data.mjs (v2.6.0)
 * 목표: "공식 OpenAPI(JSON/XML)" 기반으로 원천 데이터를 수집하고,
 *       app/data/aggregated/species_summary.json 생성.
 * 원칙: 예측/AI 없음. 전주/전월/전년동월 비교는 룰 기반.
 *
 * v2.6 핵심:
 * - sources.json의 url/params 템플릿을 확장하여 요청 (Secrets로 키 주입)
 * - JSON/XML 자동 감지 + 최소 XML 파서(태그 기반)로 값 추출
 * - 실패 사유(fetch_status) 기록 + URL 미설정 시 샘플 생성 유지
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

async function fetchText(url){
  const controller = new AbortController();
  const t = setTimeout(()=>controller.abort(), 20000);
  try{
    const r = await fetch(url, { headers: { "User-Agent":"data-bot/2.6" }, signal: controller.signal });
    const ct = r.headers.get("content-type") || "";
    const txt = await r.text();
    if (!r.ok) throw new Error(`HTTP ${r.status} ${r.statusText}`);
    return { txt, contentType: ct };
  } finally {
    clearTimeout(t);
  }
}

function looksLikeXML(txt){ return /^\s*<\?xml|\s*<!DOCTYPE|\s*<\w+/i.test(txt); }
function looksLikeJSON(txt){ return /^\s*[\{\[]/.test(txt); }

/**
 * 최소 XML 텍스트 추출(태그 단위)
 * - 복잡한 중첩 XML 전체 파싱 대신, MVP로 "필요 태그 값"만 안전하게 뽑는 용도
 */
function xmlGetAll(txt, tag){
  const re = new RegExp(`<${tag}[^>]*>([\\s\\S]*?)<\\/${tag}>`, "gi");
  const out = [];
  let m;
  while ((m = re.exec(txt)) !== null){
    out.push(m[1].trim());
  }
  return out;
}

function buildURL(base, params, ctx){
  if (!base) return "";
  const u = new URL(base);
  for (const [k,v0] of Object.entries(params || {})){
    let v = String(v0);
    v = v.replaceAll("{{DATA_GO_KR_SERVICE_KEY}}", ctx.DATA_GO_KR_SERVICE_KEY || "")
         .replaceAll("{{KAMIS_CERT_KEY}}", ctx.KAMIS_CERT_KEY || "")
         .replaceAll("{{KAMIS_CERT_ID}}", ctx.KAMIS_CERT_ID || "")
         .replaceAll("{{EXIM_AUTHKEY}}", ctx.EXIM_AUTHKEY || "")
         .replaceAll("{{START_YMD}}", ctx.START_YMD)
         .replaceAll("{{END_YMD}}", ctx.END_YMD)
         .replaceAll("{{YYYYMMDD}}", ctx.YYYYMMDD);
    if (v) u.searchParams.set(k, v);
  }
  return u.toString();
}

function ymd(d){
  const y = d.getFullYear();
  const m = String(d.getMonth()+1).padStart(2,"0");
  const dd = String(d.getDate()).padStart(2,"0");
  return `${y}${m}${dd}`;
}

async function main(){
  const cfg = readJSON(SOURCES_JSON, null);
  if (!cfg || !Array.isArray(cfg.sources)){
    console.error("sources.json missing or invalid:", SOURCES_JSON);
    process.exit(1);
  }

  // ctx from env (GitHub Secrets)
  const now = new Date();
  const ctx = {
    DATA_GO_KR_SERVICE_KEY: process.env.DATA_GO_KR_SERVICE_KEY || "",
    KAMIS_CERT_KEY: process.env.KAMIS_CERT_KEY || "",
    KAMIS_CERT_ID: process.env.KAMIS_CERT_ID || "",
    EXIM_AUTHKEY: process.env.EXIM_AUTHKEY || "",
    YYYYMMDD: ymd(now),
    END_YMD: ymd(now),
    START_YMD: ymd(new Date(now.getTime() - 7*24*3600*1000))
  };

  const configured = cfg.sources.filter(s=>s.url && String(s.url).trim().length>0);
  if (configured.length === 0){
    const out = buildSampleSummary();
    out.mode = "sample";
    writeJSON(OUT_SUMMARY, out);
    cfg.updated_at = new Date().toISOString();
    writeJSON(SOURCES_JSON, cfg);
    console.log("[OK] Generated sample species_summary.json (no API urls configured).");
    return;
  }

  const fetch_status = {};
  for (const s of cfg.sources){
    if (!s.url) continue;
    const url = buildURL(s.url, s.params, ctx);
    try{
      const { txt, contentType } = await fetchText(url);
      // Determine format
      let kind = s.format || "";
      if (!kind){
        kind = looksLikeJSON(txt) ? "json" : (looksLikeXML(txt) ? "xml" : "text");
      }

      // MVP: 이 단계에서는 "값 추출 파서"를 소스별로 추가 연결해야 함.
      // 지금은 정상 수집 여부 + 응답 형태만 기록하고,
      // UI 안정화를 위해 샘플 요약을 유지한다.
      const preview = txt.slice(0, 60).replace(/\s+/g," ");
      fetch_status[s.id] = { ok:true, kind, contentType, url, preview };

      // (선택) XML에서 에러메시지 태그가 있으면 기록
      if (kind === "xml"){
        const errs = xmlGetAll(txt, "resultMsg");
        if (errs.length) fetch_status[s.id].resultMsg = errs[0];
      }
    } catch(e){
      fetch_status[s.id] = { ok:false, url, error: String(e?.message || e) };
    }
  }

  const out = buildSampleSummary();
  out.mode = "sample_with_fetch_status";
  out.fetch_status = fetch_status;
  out.updated_at = new Date().toISOString();
  writeJSON(OUT_SUMMARY, out);

  cfg.updated_at = new Date().toISOString();
  writeJSON(SOURCES_JSON, cfg);

  console.log("[OK] update_data finished. (Parser hookup is next: map source responses -> current/series)");
}

main().catch(e=>{
  console.error(e);
  process.exit(1);
});
