import React, { useState, useEffect, useRef, useCallback } from "react";
import { createRoot } from "react-dom/client";
import { createPortal } from "react-dom";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { captureReturnState, loadReaderPage, pageDeltaForGesture, pageOffset, restoreReturnState, revealLearningTarget, saveReaderPage } from "./reader_logic.mjs";
import { hasDirectListingLink, leadAddressLine, redfinLookupUrl } from "./scout_logic.mjs";

/* ============================================================
   HOMESTEAD — Stage 0
   A private first-home tracker for a two-person household.
   Design language: a county property record annotated by a careful buyer.
   ============================================================ */

const STORAGE_KEY = "homestead:state:v1";

const storage = {
  async get(key) {
    const response = await fetch(`/api/state?key=${encodeURIComponent(key)}`, { cache: "no-store" });
    if (!response.ok) throw new Error("state unavailable");
    return response.json();
  },
  async set(key, value) {
    const response = await fetch("/api/state", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key, value }),
    });
    if (!response.ok) throw new Error("state unavailable");
    return response.json();
  },
};

const CSS = `
@import url('https://fonts.googleapis.com/css2?family=Zilla+Slab:wght@400;500;600;700&family=Karla:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap');

.hs {
  /* County Record — archival paper, clerk's ink, and survey teal. */
  --county-paper: #F4EFE5;
  --record:       #FFFDF8;
  --record-high:  #E9E0D2;
  --rule:         #C8BAA9;
  --record-edge:  #8A7A6D;
  --ink:          #28211B;
  --reading-ink:  #433A33;
  --file-note:    #746A60;
  --county-teal:  #315F66;
  --red-clay:     #9E4D3A;
  --ochre:        #80631F;

  /* Compatibility aliases while the single-file app is split into components. */
  --blackland: var(--county-paper);
  --clay:      var(--record);
  --clay-hi:   var(--record-high);
  --fenceline: var(--rule);
  --boundary:  var(--record-edge);
  --caliche:   var(--ink);
  --parchment: var(--reading-ink);
  --dust:      var(--file-note);
  --bluestem:  var(--county-teal);
  --mesquite:  var(--red-clay);
  --wheat:     var(--ochre);

  background: var(--blackland);
  color: var(--caliche);
  color-scheme: light;
  font-family: 'Karla', system-ui, sans-serif;
  min-height: 100vh;
  width: 100%;
  -webkit-font-smoothing: antialiased;
}
.hs *, .hs *::before, .hs *::after { box-sizing: border-box; }

.hs-wrap { max-width: 1080px; margin: 0 auto; padding: 0 20px 80px; }

/* ---- plat masthead ---- */
.hs-plat {
  border-bottom: 1px solid var(--fenceline);
  padding: 28px 0 20px;
  margin-bottom: 26px;
}
.hs-plat-row { display: flex; align-items: center; justify-content: space-between; gap: 16px; flex-wrap: wrap; }
.hs-brand { display: flex; align-items: center; gap: 12px; }
.hs-brand-icon { width: 42px; height: 42px; flex: 0 0 auto; }
.hs-mark {
  font-family: 'Zilla Slab', Georgia, serif;
  font-weight: 700; font-size: 30px; letter-spacing: 0.015em;
  margin: 0; line-height: 1;
}
.hs-mark span { color: var(--bluestem); }
.hs-mark-sub {
  color: var(--dust); font-family: 'IBM Plex Mono', monospace;
  font-size: 8.5px; letter-spacing: .15em; text-transform: uppercase; margin-top: 6px;
}
.hs-legend {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 10.5px; letter-spacing: 0.14em; text-transform: uppercase;
  color: var(--dust);
}

/* ---- nav ---- */
.hs-nav { display: flex; gap: 4px; flex-wrap: wrap; margin-top: 18px; }
.hs-tab {
  background: none; border: 1px solid transparent; border-radius: 2px;
  color: var(--dust); font-family: 'Karla', sans-serif;
  font-size: 13.5px; font-weight: 600; letter-spacing: 0.04em;
  padding: 7px 13px; cursor: pointer; transition: color .15s, border-color .15s;
}
.hs-tab:hover { color: var(--caliche); }
.hs-tab[aria-selected="true"] { color: var(--blackland); background: var(--bluestem); border-color: var(--bluestem); }
.hs-tab:focus-visible { outline: 2px solid var(--bluestem); outline-offset: 2px; }

/* ---- section headings ---- */
.hs-h {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 10.5px; letter-spacing: 0.16em; text-transform: uppercase;
  color: var(--dust); margin: 30px 0 12px; display: flex; align-items: center; gap: 10px;
}
.hs-h::after { content: ""; flex: 1; height: 1px; background: var(--fenceline); }
.hs-h:first-child { margin-top: 0; }

/* ---- panels ---- */
.hs-panel {
  background: var(--clay); border: 1px solid var(--fenceline);
  border-radius: 3px; padding: 20px;
}
.hs-grid { display: grid; gap: 12px; }
.hs-g2 { grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); }
.hs-g4 { grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); }

/* ---- the fence line (signature) ---- */
.hs-fence { padding: 4px 0 2px; }
.hs-fence-rail { position: relative; height: 58px; }
.hs-fence-wire {
  position: absolute; left: 0; right: 0; height: 1px; background: var(--fenceline);
}
.hs-fence-wire.w1 { top: 17px; }
.hs-fence-wire.w2 { top: 31px; }
.hs-fence-wire-fill { position: absolute; height: 1px; background: var(--bluestem); transition: width .6s ease; }
.hs-posts { position: absolute; inset: 0; display: flex; justify-content: space-between; }
.hs-post { width: 2px; height: 44px; background: var(--fenceline); border-radius: 1px; }
.hs-post.set { background: var(--bluestem); }
.hs-post.now { background: var(--caliche); height: 52px; }
.hs-fence-labels {
  display: flex; justify-content: space-between;
  font-family: 'IBM Plex Mono', monospace; font-size: 10px;
  letter-spacing: 0.1em; color: var(--dust); margin-top: 6px;
}

/* ---- numbers ---- */
.hs-num {
  font-family: 'Zilla Slab', Georgia, serif; font-weight: 600;
  font-size: 26px; line-height: 1.1; letter-spacing: -0.01em;
}
.hs-num.sm { font-size: 19px; }
.hs-lab {
  font-family: 'IBM Plex Mono', monospace; font-size: 10px;
  letter-spacing: 0.13em; text-transform: uppercase; color: var(--dust); margin-top: 5px;
}
.hs-accent { color: var(--bluestem); }
.hs-warn { color: var(--mesquite); }

/* ---- stat cell ---- */
.hs-cell { background: var(--clay); border: 1px solid var(--fenceline); border-radius: 3px; padding: 15px 16px; }

/* ---- tasks ---- */
.hs-task {
  display: flex; gap: 11px; align-items: flex-start;
  padding: 9px 0; border-bottom: 1px solid color-mix(in srgb, var(--fenceline) 65%, transparent);
}
.hs-task:last-child { border-bottom: none; }
.hs-check {
  flex: 0 0 auto; width: 15px; height: 15px; margin-top: 3px;
  border: 1px solid var(--dust); border-radius: 2px; background: none;
  cursor: pointer; position: relative; padding: 0;
}
.hs-check[aria-checked="true"] { background: var(--bluestem); border-color: var(--bluestem); }
.hs-check[aria-checked="true"]::after {
  content: ""; position: absolute; left: 4px; top: 1px; width: 4px; height: 8px;
  border: solid var(--blackland); border-width: 0 2px 2px 0; transform: rotate(42deg);
}
.hs-check:focus-visible { outline: 2px solid var(--bluestem); outline-offset: 2px; }
.hs-task-txt { font-size: 14.5px; line-height: 1.45; flex: 1; }
.hs-task.done .hs-task-txt { color: var(--dust); text-decoration: line-through; }
.hs-note { font-size: 12.5px; color: var(--dust); line-height: 1.5; margin-top: 3px; }

/* ---- phase block ---- */
.hs-phase { margin-bottom: 26px; }
.hs-phase-hd { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; margin-bottom: 6px; }
.hs-phase-name { font-family: 'Zilla Slab', serif; font-weight: 600; font-size: 17px; }
.hs-phase-when { font-family: 'IBM Plex Mono', monospace; font-size: 10.5px; letter-spacing: 0.1em; color: var(--dust); }

/* ---- forms ---- */
.hs-in, .hs-sel {
  width: 100%; background: var(--blackland); border: 1px solid var(--boundary);
  border-radius: 2px; color: var(--caliche); padding: 8px 10px;
  font-family: 'Karla', sans-serif; font-size: 14px;
}
.hs-in:focus-visible, .hs-sel:focus-visible { outline: 2px solid var(--bluestem); outline-offset: 2px; border-color: var(--bluestem); }
.hs-field { display: block; }
.hs-field-lab {
  display: block; font-family: 'IBM Plex Mono', monospace; font-size: 9.5px;
  letter-spacing: 0.13em; text-transform: uppercase; color: var(--dust); margin-bottom: 5px;
}
.hs-btn {
  background: var(--bluestem); color: var(--blackland); border: none; border-radius: 2px;
  font-family: 'Karla', sans-serif; font-weight: 700; font-size: 13.5px;
  letter-spacing: 0.03em; padding: 9px 18px; cursor: pointer;
}
.hs-btn:hover { filter: brightness(1.08); }
.hs-btn.ghost { background: none; border: 1px solid var(--boundary); color: var(--dust); font-weight: 600; }
.hs-btn.ghost:hover { color: var(--caliche); border-color: var(--dust); filter: none; }
.hs-btn.small { padding: 6px 10px; font-size: 12px; }
.hs-btn.warn { color: var(--mesquite); border-color: var(--mesquite); }
.hs-btn.warn:hover { color: var(--caliche); border-color: var(--mesquite); }
.hs-btn:focus-visible { outline: 2px solid var(--caliche); outline-offset: 2px; }
.hs-btn:disabled { cursor: not-allowed; opacity: .45; filter: none; }
.hs-filing-activity {
  width: 100%; max-width: 520px; margin-top: 2px; padding: 11px 12px;
  border: 1px solid var(--fenceline); background: var(--blackland);
}
.hs-filing-head { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; }
.hs-filing-title {
  font-family: 'IBM Plex Mono', monospace; font-size: 10px; font-weight: 500;
  letter-spacing: .11em; text-transform: uppercase; color: var(--bluestem);
}
.hs-filing-time { font-family: 'IBM Plex Mono', monospace; font-size: 10px; color: var(--dust); white-space: nowrap; }
.hs-filing-rail { position: relative; height: 4px; margin: 8px 0; overflow: hidden; background: var(--record-high); }
.hs-filing-rail::after {
  content: ""; position: absolute; inset: 0 auto 0 0; width: 38%; background: var(--bluestem);
  animation: hs-filing-sweep 1.25s ease-in-out infinite;
}
.hs-filing-copy { color: var(--reading-ink); font-size: 12px; line-height: 1.45; }
.hs-filing-note { color: var(--dust); font-size: 11px; margin-top: 2px; }
@keyframes hs-filing-sweep {
  from { transform: translateX(-110%); }
  to { transform: translateX(365%); }
}

/* ---- scout lead card ---- */
.hs-lead {
  background: var(--clay); border: 1px solid var(--fenceline); border-radius: 3px;
  padding: 15px 16px;
}
.hs-lead.dismissed { opacity: .58; }
.hs-lead-hd { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.hs-lead-addr { font-family: 'Zilla Slab', Georgia, serif; font-weight: 600; font-size: 16.5px; line-height: 1.25; }
.hs-lead-src {
  font-family: 'IBM Plex Mono', monospace; font-size: 9.5px; letter-spacing: .13em;
  text-transform: uppercase; color: var(--dust); border: 1px solid var(--boundary);
  border-radius: 2px; padding: 2px 7px; white-space: nowrap;
}
.hs-lead-facts {
  display: flex; flex-wrap: wrap; gap: 6px 14px; margin-top: 8px;
  font-size: 13px; color: var(--reading-ink);
}
.hs-lead-seen {
  font-family: 'IBM Plex Mono', monospace; font-size: 10px; letter-spacing: .08em;
  color: var(--dust); margin-top: 9px;
}
.hs-lead-fit { margin-top: 10px; border-top: 1px solid var(--fenceline); padding-top: 9px; }
.hs-lead-fit-lab {
  font-family: 'IBM Plex Mono', monospace; font-size: 10px; letter-spacing: .12em;
  text-transform: uppercase;
}
.hs-lead-why { font-size: 12.5px; line-height: 1.5; color: var(--dust); margin-top: 4px; }
.hs-lead-mark { font-family: 'IBM Plex Mono', monospace; font-weight: 700; }
.hs-lead-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
.hs-lead-manual { display: block; margin-top: 10px; }
.hs-lead-manual .hs-in { margin-bottom: 4px; }
.hs-lead-filters { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 16px; }
.hs-lead-filter[aria-pressed="true"] { background: var(--bluestem); color: var(--blackland); border-color: var(--bluestem); font-weight: 700; }

/* ---- property card ---- */
.hs-prop { background: var(--clay); border: 1px solid var(--fenceline); border-radius: 3px; padding: 16px 17px; }
.hs-prop-hd { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; }
.hs-prop-addr { font-family: 'Zilla Slab', serif; font-weight: 600; font-size: 16.5px; line-height: 1.25; }
.hs-prop-meta { font-family: 'IBM Plex Mono', monospace; font-size: 11px; color: var(--dust); margin-top: 3px; letter-spacing: 0.04em; }
.hs-dossier { margin: 16px 0; }
.hs-dossier-summary { display: grid; grid-template-columns: repeat(auto-fit, minmax(105px, 1fr)); gap: 8px; margin: 12px 0 18px; }
.hs-dossier-summary > div { border: 1px solid var(--fenceline); padding: 10px 11px; background: var(--blackland); }
.hs-dossier-value { font-family: 'Zilla Slab', serif; font-weight: 600; font-size: 18px; }
.hs-dossier-label { font-family: 'IBM Plex Mono', monospace; color: var(--dust); text-transform: uppercase; letter-spacing: .09em; font-size: 8.5px; margin-top: 3px; }
.hs-media-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(145px, 1fr)); gap: 8px; }
.hs-media-card { margin: 0; border: 1px solid var(--fenceline); background: var(--blackland); overflow: hidden; }
.hs-media-card img { width: 100%; height: 115px; object-fit: cover; display: block; background: var(--record-high); }
.hs-media-card figcaption { padding: 5px 7px; color: var(--dust); font-size: 10px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.hs-floorplan-card { margin: 0; border: 1px solid var(--fenceline); background: white; max-width: 900px; }
.hs-floorplan-card button { display: block; width: 100%; padding: 12px; border: 0; background: white; cursor: zoom-in; }
.hs-floorplan-card img { display: block; width: 100%; height: min(62vh, 640px); object-fit: contain; }
.hs-floorplan-card figcaption { padding: 8px 11px; border-top: 1px solid var(--fenceline); color: var(--dust); font-size: 11px; }
.hs-dossier-subhead { font-family: 'Zilla Slab', serif; font-size: 18px; font-weight: 600; margin: 20px 0 9px; }
.hs-fact-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); border: 1px solid var(--fenceline); }
.hs-fact { padding: 8px 10px; border-bottom: 1px solid var(--fenceline); min-width: 0; }
.hs-fact:nth-child(odd) { background: color-mix(in srgb, var(--blackland) 55%, transparent); }
.hs-fact-key { font-family: 'IBM Plex Mono', monospace; color: var(--dust); text-transform: uppercase; letter-spacing: .07em; font-size: 8.5px; }
.hs-fact-value { font-size: 12px; line-height: 1.45; margin-top: 3px; overflow-wrap: anywhere; }
.hs-data-table { width: 100%; border-collapse: collapse; font-size: 11.5px; }
.hs-data-table th, .hs-data-table td { padding: 7px 8px; text-align: left; vertical-align: top; border-bottom: 1px solid var(--fenceline); }
.hs-data-table th { color: var(--dust); font-family: 'IBM Plex Mono', monospace; text-transform: uppercase; letter-spacing: .06em; font-size: 8.5px; }
.hs-dossier-description { font-family: 'Zilla Slab', Georgia, serif; font-size: 15px; line-height: 1.6; color: var(--reading-ink); }
.hs-dossier-links { display: flex; flex-wrap: wrap; gap: 8px; margin: 10px 0; }
.hs-dossier details { border-top: 1px solid var(--fenceline); padding: 9px 0; }
.hs-dossier summary { cursor: pointer; font-weight: 600; }
.hs-property-list { display: grid; gap: 16px; }
.hs-property-card { display: grid; grid-template-columns: minmax(260px, 38%) 1fr; padding: 0; overflow: hidden; }
.hs-property-cover { position: relative; min-height: 255px; background: var(--record-high); }
.hs-property-cover img { width: 100%; height: 100%; object-fit: cover; display: block; position: absolute; inset: 0; }
.hs-property-cover-empty { height: 100%; display: grid; place-items: center; color: var(--dust); font-family: 'IBM Plex Mono', monospace; font-size: 10px; text-transform: uppercase; letter-spacing: .1em; }
.hs-photo-count { position: absolute; right: 10px; bottom: 10px; z-index: 1; background: rgba(40,33,27,.82); color: white; padding: 5px 8px; font: 500 10px 'IBM Plex Mono',monospace; letter-spacing: .05em; }
.hs-property-body { padding: 19px 20px; min-width: 0; }
.hs-property-title { font-family: 'Zilla Slab', serif; font-size: 25px; line-height: 1.1; font-weight: 600; }
.hs-property-price { font-family: 'Zilla Slab', serif; font-size: 23px; font-weight: 600; margin-top: 16px; }
.hs-property-quick { display: flex; flex-wrap: wrap; gap: 6px 14px; color: var(--dust); font-size: 12px; margin-top: 5px; }
.hs-capture-meta { margin-top: 12px; padding-top: 10px; border-top: 1px solid var(--fenceline); color: var(--dust); font: 10px 'IBM Plex Mono',monospace; }
.hs-map { height: 385px; border: 1px solid var(--fenceline); background: var(--record-high); z-index: 0; }
.hs-map,
.hs-map.leaflet-grab,
.hs-map .leaflet-map-pane,
.hs-map .leaflet-pane,
.hs-map .leaflet-layer,
.hs-map .leaflet-tile-container,
.hs-map .leaflet-tile { cursor: grab !important; }
.hs-map.leaflet-dragging,
.hs-map.leaflet-dragging .leaflet-map-pane,
.hs-map.leaflet-dragging .leaflet-pane,
.hs-map.leaflet-dragging .leaflet-tile { cursor: grabbing !important; }
.hs-map .leaflet-marker-icon.leaflet-interactive,
.hs-map .leaflet-control,
.hs-map .leaflet-control a { cursor: pointer !important; }
.hs-map-pin { background: var(--county-teal); border: 3px solid var(--record); border-radius: 50% 50% 50% 0; width: 25px; height: 25px; transform: rotate(-45deg); box-shadow: 0 2px 7px rgba(40,33,27,.3); }
.hs-map-popup { min-width: 205px; font-family: 'Karla', sans-serif; }
.hs-map-popup img { width: 100%; height: 105px; object-fit: cover; margin-bottom: 6px; }
.hs-map-popup strong { font-family: 'Zilla Slab', serif; font-size: 15px; }
.hs-modal-backdrop { position: fixed; inset: 0; z-index: 1000; background: rgba(40,33,27,.72); display: grid; place-items: center; padding: 24px; }
.hs-property-modal { background: var(--record); width: min(1180px, 96vw); max-height: 92vh; overflow: auto; border: 1px solid var(--record-edge); box-shadow: 0 20px 70px rgba(0,0,0,.35); }
.hs-modal-head { position: sticky; top: 0; z-index: 3; background: var(--record); border-bottom: 1px solid var(--fenceline); padding: 15px 20px 0; }
.hs-modal-title-row { display: flex; justify-content: space-between; gap: 15px; align-items: flex-start; }
.hs-modal-tabs { display: flex; gap: 3px; margin-top: 12px; overflow-x: auto; }
.hs-modal-tab { border: 0; border-bottom: 3px solid transparent; background: transparent; padding: 9px 12px; font: 600 12px 'Karla',sans-serif; color: var(--dust); cursor: pointer; }
.hs-modal-tab[aria-selected="true"] { color: var(--county-teal); border-color: var(--county-teal); }
.hs-modal-body { padding: 4px 22px 28px; }
.hs-lightbox { position: fixed; inset: 0; z-index: 1200; background: rgba(18,15,13,.94); display: grid; grid-template-columns: 60px 1fr 60px; align-items: center; }
.hs-lightbox-stage { display: grid; place-items: center; min-width: 0; }
.hs-lightbox img { max-width: 100%; max-height: 86vh; object-fit: contain; }
.hs-lightbox button { background: rgba(255,255,255,.1); color: white; border: 1px solid rgba(255,255,255,.35); font-size: 28px; height: 58px; cursor: pointer; }
.hs-lightbox-close { position: absolute; top: 16px; right: 18px; width: 46px; height: 46px !important; }
.hs-lightbox-caption { color: white; text-align: center; font-size: 12px; margin-top: 8px; }
.hs-specs { display: flex; flex-wrap: wrap; gap: 14px; margin-top: 13px; padding-top: 12px; border-top: 1px solid color-mix(in srgb, var(--fenceline) 70%, transparent); }
.hs-spec-v { font-family: 'Zilla Slab', serif; font-weight: 600; font-size: 15px; }
.hs-spec-l { font-family: 'IBM Plex Mono', monospace; font-size: 9px; letter-spacing: 0.11em; text-transform: uppercase; color: var(--dust); margin-top: 2px; }
.hs-flags { margin-top: 13px; display: flex; flex-direction: column; gap: 6px; }
.hs-flag {
  display: flex; gap: 8px; font-size: 12.5px; line-height: 1.4;
  color: var(--mesquite); align-items: flex-start;
}
.hs-flag::before { content: "▲"; font-size: 8px; margin-top: 4px; flex: 0 0 auto; }
.hs-status {
  font-family: 'IBM Plex Mono', monospace; font-size: 9.5px; letter-spacing: 0.12em;
  text-transform: uppercase; padding: 3px 8px; border: 1px solid var(--fenceline);
  border-radius: 2px; color: var(--dust); white-space: nowrap;
}
.hs-status.live { color: var(--bluestem); border-color: var(--bluestem); }

/* ---- journey workspace ---- */
.hs-stagebar { display: grid; grid-template-columns: repeat(7, minmax(105px, 1fr)); gap: 6px; overflow-x: auto; padding-bottom: 4px; }
.hs-stage {
  min-width: 105px; background: var(--blackland); border: 1px solid var(--boundary);
  border-radius: 2px; color: var(--dust); padding: 10px 11px; text-align: left; cursor: pointer;
}
.hs-stage:hover { color: var(--caliche); border-color: var(--dust); }
.hs-stage[aria-current="step"] { color: var(--blackland); background: var(--bluestem); border-color: var(--bluestem); }
.hs-stage-n { font-family: 'IBM Plex Mono', monospace; font-size: 9px; letter-spacing: .12em; text-transform: uppercase; }
.hs-stage-t { font-family: 'Zilla Slab', serif; font-size: 14px; font-weight: 600; margin-top: 4px; }
.hs-item { padding: 13px 0; border-bottom: 1px solid color-mix(in srgb, var(--fenceline) 65%, transparent); }
.hs-item:first-child { padding-top: 0; }
.hs-item:last-child { padding-bottom: 0; border-bottom: none; }
.hs-item-main { display: flex; gap: 11px; align-items: flex-start; }
.hs-item-copy { flex: 1; min-width: 0; }
.hs-item-title { font-size: 14.5px; line-height: 1.4; }
.hs-item.done .hs-item-title { color: var(--dust); text-decoration: line-through; }
.hs-item-meta { display: flex; flex-wrap: wrap; gap: 7px; margin-top: 6px; align-items: center; }
.hs-kind {
  font-family: 'IBM Plex Mono', monospace; font-size: 9px; letter-spacing: .11em;
  text-transform: uppercase; color: var(--bluestem); border: 1px solid color-mix(in srgb, var(--bluestem) 45%, transparent);
  border-radius: 2px; padding: 3px 7px;
}
.hs-date { font-family: 'IBM Plex Mono', monospace; font-size: 10px; color: var(--dust); }
.hs-item-actions { display: flex; flex-wrap: wrap; gap: 7px; margin-top: 10px; }
.hs-attention { display: flex; gap: 12px; align-items: flex-start; padding: 12px 0; border-bottom: 1px solid color-mix(in srgb, var(--fenceline) 65%, transparent); }
.hs-attention:first-child { padding-top: 0; }
.hs-attention:last-child { padding-bottom: 0; border-bottom: none; }
.hs-attention-copy { flex: 1; min-width: 0; }
.hs-attention-title { font-size: 14.5px; line-height: 1.4; }
.hs-overdue { color: var(--mesquite); }
.hs-removed { opacity: .78; }

/* ---- brief: a paragraph of the contract, where it bites ---- */
.hs-brief { border-left: 2px solid var(--mesquite); padding: 2px 0 2px 15px; margin-bottom: 18px; }
.hs-brief:last-child { margin-bottom: 0; }
.hs-brief-hd { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }
.hs-brief-code {
  font-family: 'IBM Plex Mono', monospace; font-size: 10px;
  letter-spacing: 0.12em; color: var(--mesquite); white-space: nowrap;
}
.hs-brief-t { font-family: 'Zilla Slab', serif; font-weight: 600; font-size: 15.5px; line-height: 1.3; }
.hs-brief-b { font-size: 13.5px; line-height: 1.55; margin-top: 7px; }
.hs-brief-b strong { color: var(--caliche); }
.hs-brief-do { font-size: 13px; line-height: 1.5; color: var(--bluestem); margin-top: 8px; display: flex; gap: 7px; }
.hs-brief-do::before { content: "→"; flex: 0 0 auto; }
.hs-tagrow { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 9px; }
.hs-tag {
  font-family: 'IBM Plex Mono', monospace; font-size: 9px; letter-spacing: 0.11em;
  text-transform: uppercase; padding: 3px 7px; border: 1px solid var(--fenceline);
  border-radius: 2px; color: var(--dust);
}
.hs-tag.gap { color: var(--mesquite); border-color: color-mix(in srgb, var(--mesquite) 45%, transparent); }

/* ---- coverage bar ---- */
.hs-cov { display: flex; height: 6px; border-radius: 2px; overflow: hidden; margin: 14px 0 8px; }
.hs-cov-seg { height: 100%; }
.hs-cov-key { display: flex; flex-wrap: wrap; gap: 14px; }
.hs-cov-k { display: flex; align-items: center; gap: 6px; font-family: 'IBM Plex Mono', monospace;
  font-size: 9.5px; letter-spacing: 0.1em; text-transform: uppercase; color: var(--dust); }
.hs-cov-dot { width: 7px; height: 7px; border-radius: 1px; flex: 0 0 auto; }

/* ---- learning workspace ---- */
.hs-learn-hero { display: grid; grid-template-columns: minmax(0, 1.6fr) minmax(240px, .8fr); gap: 20px; align-items: end; }
.hs-learn-title { font-family: 'Zilla Slab', serif; font-size: clamp(27px, 4vw, 42px); line-height: 1.04; margin: 4px 0 10px; }
.hs-learn-kicker { font-family: 'IBM Plex Mono', monospace; font-size: 10px; letter-spacing: .15em; text-transform: uppercase; color: var(--bluestem); }
.hs-learn-progress { height: 7px; background: var(--blackland); border: 1px solid var(--boundary); border-radius: 2px; overflow: hidden; margin: 12px 0 7px; }
.hs-learn-progress > i { display: block; height: 100%; background: var(--bluestem); }
.hs-learn-layout { display: grid; grid-template-columns: minmax(270px, .85fr) minmax(0, 1.5fr); gap: 14px; align-items: start; }
.hs-learn-sidebar { position: sticky; top: 12px; max-height: calc(100vh - 24px); overflow: auto; }
.hs-trackbar { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 6px; margin-bottom: 12px; }
.hs-track { text-align: left; background: var(--blackland); border: 1px solid var(--boundary); color: var(--dust); border-radius: 2px; padding: 9px 10px; cursor: pointer; }
.hs-track[aria-pressed="true"] { border-color: var(--bluestem); color: var(--caliche); }
.hs-track-code { font-family: 'IBM Plex Mono', monospace; font-size: 9px; letter-spacing: .12em; text-transform: uppercase; color: var(--bluestem); }
.hs-track-name { font-family: 'Zilla Slab', serif; font-size: 13.5px; font-weight: 600; margin-top: 3px; }
.hs-group-when { font-family: 'IBM Plex Mono', monospace; font-size: 9px; letter-spacing: .06em; color: var(--dust); margin: -5px 0 8px 24px; }
.hs-learn-group { border-top: 1px solid color-mix(in srgb, var(--fenceline) 75%, transparent); }
.hs-learn-group:first-of-type { border-top: none; }
.hs-learn-group-btn { width: 100%; display: flex; gap: 8px; align-items: baseline; text-align: left; padding: 11px 0; background: none; border: none; color: var(--caliche); cursor: pointer; }
.hs-learn-group-code { font-family: 'IBM Plex Mono', monospace; font-size: 9px; letter-spacing: .1em; color: var(--dust); flex: 0 0 auto; }
.hs-learn-group-title { font-family: 'Zilla Slab', serif; font-size: 14px; font-weight: 600; flex: 1; }
.hs-learn-count { font-family: 'IBM Plex Mono', monospace; font-size: 9px; color: var(--dust); }
.hs-learn-topic { width: 100%; text-align: left; display: grid; grid-template-columns: 16px 1fr auto; gap: 8px; align-items: start; padding: 8px 7px; margin-bottom: 3px; background: transparent; border: 1px solid transparent; border-radius: 2px; color: var(--dust); cursor: pointer; }
.hs-learn-topic:hover, .hs-learn-topic[aria-current="true"] { background: var(--blackland); border-color: var(--fenceline); color: var(--caliche); }
.hs-learn-topic-check { width: 12px; height: 12px; margin-top: 3px; border: 1px solid var(--dust); border-radius: 50%; }
.hs-learn-topic-check.done { background: var(--bluestem); border-color: var(--bluestem); box-shadow: inset 0 0 0 3px var(--blackland); }
.hs-learn-topic-name { font-size: 12.5px; line-height: 1.3; }
.hs-coverage { font-family: 'IBM Plex Mono', monospace; font-size: 9px; letter-spacing: .08em; text-transform: uppercase; border: 1px solid var(--fenceline); padding: 3px 5px; border-radius: 2px; white-space: nowrap; }
.hs-coverage.complete { color: var(--bluestem); border-color: color-mix(in srgb, var(--bluestem) 45%, transparent); }
.hs-coverage.partial, .hs-coverage.thin { color: var(--wheat); border-color: color-mix(in srgb, var(--wheat) 45%, transparent); }
.hs-coverage.coverage-gap { color: var(--mesquite); border-color: color-mix(in srgb, var(--mesquite) 50%, transparent); }
.hs-coverage.curated { color: var(--caliche); border-color: color-mix(in srgb, var(--caliche) 35%, transparent); }
.hs-lesson-head { padding-bottom: 18px; border-bottom: 1px solid var(--fenceline); }
.hs-selected-lesson { scroll-margin-top: 16px; }
.hs-selected-lesson:focus-visible { outline: 2px solid var(--survey); outline-offset: 4px; }
.hs-lesson-title { font-family: 'Zilla Slab', serif; font-size: clamp(24px, 3.2vw, 35px); line-height: 1.1; margin: 8px 0 10px; }
.hs-reading-card { margin-top: 14px; border: 1px solid var(--fenceline); background: var(--blackland); border-radius: 3px; overflow: hidden; }
.hs-reading-hd { padding: 13px 15px; border-bottom: 1px solid var(--fenceline); display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; }
.hs-reading-book { font-family: 'Zilla Slab', serif; font-size: 15px; font-weight: 600; }
.hs-reading-section { font-size: 11.5px; color: var(--dust); margin-top: 3px; }
.hs-reading-body { padding: 17px 18px; font-family: 'Zilla Slab', Georgia, serif; font-size: 15.5px; line-height: 1.72; white-space: pre-wrap; color: var(--parchment); }
.hs-source-note { padding: 10px 15px; border-top: 1px solid var(--fenceline); font-family: 'IBM Plex Mono', monospace; font-size: 9px; line-height: 1.5; letter-spacing: .05em; color: var(--dust); }
.hs-source-note.warn { color: var(--wheat); }
.hs-source-note.gap { color: var(--mesquite); }
.hs-read-full { margin: 0 15px 13px; }
.hs-lesson-nav { display: flex; justify-content: space-between; gap: 8px; margin-top: 18px; }

/* ---- full-section reader ---- */
.hs-reader-shell { position: fixed; inset: 0; z-index: 10000; background: var(--county-paper); color: var(--ink); display: grid; grid-template-rows: auto 1fr auto; overflow: hidden; overscroll-behavior: none; }
.hs-reader-bar { min-width: 0; padding: 12px clamp(12px,3vw,32px); border-bottom: 1px solid var(--rule); background: var(--record); display: grid; grid-template-columns: minmax(0,1fr) auto; gap: 14px; align-items: center; }
.hs-reader-kicker { font: 500 9px/1.3 'IBM Plex Mono',monospace; letter-spacing: .12em; text-transform: uppercase; color: var(--county-teal); }
.hs-reader-title { font: 600 clamp(17px,2.4vw,24px)/1.15 'Zilla Slab',Georgia,serif; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.hs-reader-bookline { font-size: 11px; color: var(--file-note); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.hs-reader-done { min-width: 76px; }
.hs-reader-stage { min-width: 0; min-height: 0; overflow: hidden; touch-action: pan-y; position: relative; }
.hs-reader-viewport { position: absolute; inset: clamp(14px,3vw,32px); overflow: hidden; }
.hs-reader-pages { height: 100%; min-width: 100%; column-fill: auto; column-gap: 40px; column-width: var(--reader-page-width); font: 400 clamp(16px,2vw,19px)/1.58 'Zilla Slab',Georgia,serif; color: var(--reading-ink); transition: transform 180ms ease-out; will-change: transform; overflow: visible; }
.hs-reader-pages > .epub-reader-content, .hs-reader-markdown { max-width: none; }
.hs-reader-pages h1,.hs-reader-pages h2,.hs-reader-pages h3,.hs-reader-pages h4 { break-after: avoid; font-family:'Zilla Slab',Georgia,serif; line-height:1.16; margin:0 0 .65em; }
.hs-reader-pages p,.hs-reader-pages ul,.hs-reader-pages ol,.hs-reader-pages blockquote,.hs-reader-pages figure,.hs-reader-pages table { margin:0 0 1em; }
.hs-reader-pages img { display:block; max-width:100%; max-height:65vh; width:auto; height:auto; object-fit:contain; margin:.5em auto; break-inside:avoid; }
.hs-reader-pages figure { max-width:100%; break-inside:avoid; }
.hs-reader-pages figcaption,.hs-reader-pages caption { font-size:.82em; line-height:1.35; color:var(--file-note); text-align:center; }
.hs-reader-pages table { display:table; table-layout:fixed; border-collapse:collapse; width:100%; max-width:100%; font-size:clamp(10px,2.7vw,14px); overflow-wrap:anywhere; break-inside:avoid; }
.hs-reader-pages th,.hs-reader-pages td { border:1px solid var(--rule); padding:.35em; vertical-align:top; }
.hs-reader-pages pre,.hs-reader-pages code { white-space:pre-wrap; overflow-wrap:anywhere; }
.hs-reader-pages a { color:inherit; text-decoration:none; }
.hs-reader-status { display:grid; grid-template-columns:1fr auto 1fr; align-items:center; gap:12px; padding:10px clamp(12px,3vw,32px); border-top:1px solid var(--rule); background:var(--record); }
.hs-reader-status .next { justify-self:end; }
.hs-reader-progress { font:500 10px/1.4 'IBM Plex Mono',monospace; letter-spacing:.06em; color:var(--file-note); text-align:center; white-space:nowrap; }
.hs-reader-meter { display:block; width:min(180px,35vw); height:3px; margin:5px auto 0; background:var(--record-high); }
.hs-reader-meter i { display:block; height:100%; background:var(--county-teal); }
.hs-reader-fallback { padding:7px 14px; border-bottom:1px solid var(--rule); background:#f5ead2; color:var(--ochre); font-size:11px; text-align:center; }
.hs-reader-loading { padding:10vh 20px; text-align:center; color:var(--file-note); }

/* ---- empty ---- */
.hs-empty { text-align: center; padding: 44px 20px; color: var(--dust); }
.hs-empty-t { font-family: 'Zilla Slab', serif; font-size: 17px; color: var(--caliche); margin-bottom: 7px; }

.hs-row { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
.hs-sp { height: 14px; }
.hs-link { color: var(--bluestem); text-decoration: none; border-bottom: 1px solid color-mix(in srgb, var(--bluestem) 40%, transparent); }
.hs-link:hover { border-bottom-color: var(--bluestem); }
.hs-record { padding: 14px 0; border-bottom: 1px solid color-mix(in srgb, var(--fenceline) 75%, transparent); }
.hs-record:first-child { padding-top: 0; }
.hs-record:last-child { padding-bottom: 0; border-bottom: none; }
.hs-record-hd { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; }
.hs-record-title { font-family: 'Zilla Slab', serif; font-size: 16px; font-weight: 600; }
.hs-record-meta { font-family: 'IBM Plex Mono', monospace; font-size: 9.5px; letter-spacing: .07em; color: var(--dust); margin-top: 3px; }
.hs-record-controls { display: grid; grid-template-columns: repeat(auto-fit, minmax(145px, 1fr)); gap: 9px; margin-top: 12px; }
.hs-section-note { border-left: 2px solid var(--bluestem); padding-left: 13px; }
.hs-history { margin: 8px 0 0; padding-left: 18px; color: var(--dust); font-size: 12.5px; }
.hs-cal-date { font-family: 'IBM Plex Mono', monospace; color: var(--wheat); font-size: 12px; margin-top: 7px; }
.hs-archived { opacity: .62; }
.hs-stage:focus-visible, .hs-track:focus-visible, .hs-learn-group-btn:focus-visible,
.hs-learn-topic:focus-visible, .hs-link:focus-visible {
  outline: 2px solid var(--bluestem); outline-offset: 2px;
}

@media (prefers-reduced-motion: reduce) {
  .hs *, .hs *::before { transition: none !important; }
  .hs-filing-rail::after { width: 100%; opacity: .55; animation: none; }
}
@media (max-width: 560px) {
  .hs-mark { font-size: 25px; }
  .hs-brand-icon { width: 36px; height: 36px; }
  .hs-num { font-size: 22px; }
  .hs-post { height: 34px; }
  .hs-post.now { height: 42px; }
  .hs-fence-rail { height: 46px; }
  .hs-fence-wire.w1 { top: 13px; }
  .hs-fence-wire.w2 { top: 25px; }
  .hs-learn-hero, .hs-learn-layout { grid-template-columns: 1fr; }
  .hs-learn-sidebar { position: static; max-height: none; }
  .hs-trackbar { grid-template-columns: 1fr; }
  .hs-reading-body { padding: 15px; font-size: 15px; }
  .hs-record-hd { flex-direction: column; }
  .hs-reader-bar { padding:9px 10px; }
  .hs-reader-viewport { inset:14px 13px; }
  .hs-reader-status { padding:8px 10px; }
  .hs-reader-status .hs-btn { padding:8px 10px; }
}
@media (max-width: 760px) {
  .hs-property-card { grid-template-columns: 1fr; }
  .hs-property-cover { min-height: 220px; }
  .hs-modal-backdrop { padding: 0; }
  .hs-property-modal { width: 100vw; max-height: 100vh; min-height: 100vh; }
}
`;

/* ---------------- seed data ---------------- */

const PHASES = [
  { id: "prepare", name: "Prepare", when: "Now → Nov 2026" },
  { id: "search", name: "Search", when: "Nov 2026 →" },
  { id: "offer", name: "Offer & option period", when: "At contract" },
  { id: "contract", name: "Under contract", when: "~30–45 days" },
  { id: "closing", name: "Closing", when: "Final week" },
  { id: "move", name: "Move & settle", when: "After funding" },
  { id: "ongoing", name: "Ongoing", when: "The household we keep" },
];

const ITEM_TYPES = [
  ["task", "Task"],
  ["decision", "Decision"],
  ["deadline", "Deadline"],
  ["document", "Document"],
  ["note", "Note"],
];

const ITEM_DONE_LABELS = {
  task: "Complete",
  decision: "Decided",
  deadline: "Met",
  document: "Received",
  note: "Filed",
};

const SEED_TASKS = [
  ["prepare", "Pull credit reports for both of us and dispute any errors", "annualcreditreport.com — free weekly. Do this early; disputes take 30+ days."],
  ["prepare", "Work through the CFPB \"Your Home Loan Toolkit\"", "Free. Teaches the Loan Estimate line by line — the main defense against padded fees."],
  ["prepare", "Talk to a Texas real-estate attorney", "Two documents: survivorship agreement (Estates Code §111.001) and a co-ownership agreement."],
  ["prepare", "Decide how you hold title with a co-buyer", "Texas does NOT presume survivorship. Silence on the deed = tenancy in common."],
  ["prepare", "Agree contributions, expense split, and a buyout mechanism in writing", "Any co-owner can force a partition sale. This is the document that prevents that."],
  ["prepare", "Reach the down payment target", "Track it against a real savings figure, not a feeling. A monthly contribution and a target date turn it into a date you can plan around."],
  ["prepare", "Start a separate closing-cost reserve", "2–5% of price ON TOP of the down payment. On a $375k purchase that is $7,500–$18,750. It is easy for the down payment to be on track while this is not, so track it separately."],
  ["prepare", "Read a blank TREC One-to-Four Family contract", "Free at trec.texas.gov. Don't let closing day be the first read."],
  ["prepare", "Interview three buyer's agents", "Since Aug 2024 you sign a written buyer agreement before touring. Negotiate that fee."],
  ["prepare", "Decide target areas and what proximity is worth", "Remote work makes the commute soft — the drives you actually make every week are the ones that matter."],

  ["search", "Get pre-approved by three lenders inside a 14-day window", "Multiple mortgage pulls in one window count as a single inquiry."],
  ["search", "Compare three Loan Estimates side by side", "Same CFPB form, same page numbers. Compare section by section."],
  ["search", "Log every house toured in Homestead the same day", "Memory blurs after the third house."],
  ["search", "For any new build: get an outside loan estimate anyway", "The builder incentive is often priced into the rate. RESPA bars them from requiring their lender."],
  ["search", "Confirm the MUD/PID disclosure on every new-build lot", "A missed notice is a statutory right to terminate."],

  ["offer", "Negotiate option period length and option fee", "This is the unrestricted right to walk. Buy enough days."],
  ["offer", "Book the general inspection for day 0–1 of the option period", "Deadlines are 5:00 p.m., time is of the essence."],
  ["offer", "Order a structural engineer if anything looks off", "North Texas clay. Foundation is the regional defect."],
  ["offer", "Read the seller's disclosure notice closely", "Prior repairs, foundation work, drainage, flooding."],

  ["contract", "Choose our own title company", "Premiums are set by the state — compare the add-on fees, not the premium."],
  ["contract", "Review the title commitment and survey", "Easements, deed restrictions, encroachments."],
  ["contract", "Review the appraisal", "If it comes in low, that's leverage, not a dead deal."],
  ["contract", "Decide when to lock the rate", "Confirm the lock length covers the closing date."],

  ["closing", "Compare the Closing Disclosure against the Loan Estimate", "Line by line. Question every number that moved."],
  ["closing", "Confirm wire instructions by phone using a known number", "Closing-day wire fraud is the single biggest money loss in this process."],
  ["closing", "Final walkthrough", "Verify repairs, appliances, and that nothing broke after the inspection."],
  ["closing", "Bring photo ID and confirmed funds", ""],

  ["move", "Give Josh and Jessica proper notice", ""],
  ["move", "Book movers for two households", "Two origins, likely on different dates."],
  ["move", "Storage unit if move-out and closing don't line up", ""],
  ["move", "Fence check and temporary containment before the dogs arrive", "Kumo, Levi, Atlas, and Ford — walk the whole line for gaps."],
  ["move", "Update microchip registrations and vet records to the new address", ""],
  ["move", "Transfer utilities", ""],
  ["move", "File the homestead exemption (Form 50-114)", "As soon as we own and occupy. Raised to $140,000 for school districts by Prop 13."],
  ["move", "Calendar the property-tax protest deadline", "May 15, or 30 days after the appraisal notice — whichever is later."],
];

const LEGACY_WHOLE_BOOK_TASK_TITLES = new Set([
  "Read Home Buying Kit For Dummies (8th ed., 2025)",
  "Read BiggerPockets First-Time Home Buyer",
]);

function isLegacyWholeBookTask(item) {
  const title = item?.title || item?.text || "";
  return (!item?.type || item.type === "task") && LEGACY_WHOLE_BOOK_TASK_TITLES.has(title);
}

function hasLegacyWholeBookTasks(state) {
  return [state?.items, state?.tasks, state?.trash]
    .some((items) => Array.isArray(items) && items.some(isLegacyWholeBookTask));
}

/* ---- from the knowledge base ----------------------------------------------
   Compiled 2026-08-06 against TREC 20-19 (64 codes) and TREC 40-11 (21 codes).
   A brief appears in the phase where the paragraph actually bites, not in a
   reference section you'd have to remember to open. `gap: true` means NO book
   in the corpus covers it — the brief is the only thing standing there.
   Full text: homestead-vault/library/. --------------------------------------- */

const COVERAGE = {
  contract: { spine: "TREC 20-19", total: 64, complete: 36, thin: 10, partial: 5, gap: 13 },
  financing: { spine: "TREC 40-11", total: 21, complete: 11, thin: 3, partial: 3, gap: 4 },
};

const BRIEFS = [
  {
    phase: "offer", code: "20-19 ¶5D", gap: true,
    t: "A blank option fee means no right to walk",
    b: "If no dollar amount is written as the option fee — not a late payment, just a blank — you do not have the unrestricted right to terminate. There is no notice and no cure period. The contract stays fully binding and nothing on the page tells you.",
    do: "Before signing, confirm ¶5B has BOTH a number of days and a dollar amount. Say the number out loud.",
  },
  {
    phase: "offer", code: "40-11 ¶2A", gap: false,
    t: "The financing contingency dies on its deadline",
    b: "If you don't terminate by the ¶2A day count, the contract is no longer subject to you getting loan approval. Only property-side reasons survive after that. A job loss or credit event afterwards leaves you bound, with earnest money exposed. Worse: one checkbox — \"not subject to Buyer Approval\" — removes the contingency from day one.",
    do: "Never check the second box. Negotiate a day count that survives real underwriting, not just pre-approval.",
  },
  {
    phase: "offer", code: "20-19 ¶21", gap: true,
    t: "A termination only counts if notice is valid",
    b: "Notice must be in writing, to the addresses filled in on page 9. Effective when sent, which helps against the 5:00 p.m. deadline — but a phone call is not a termination, and ¶21 is routinely left half-blank at offer time.",
    do: "Fill ¶21 in completely when the offer is written, emails included. Verify the seller agent's email by exchanging a message early.",
  },
  {
    phase: "offer", code: "40-11 ¶1", gap: false,
    t: "The origination cap is the anti-gouging blank",
    b: "Every financing type has a blank: Origination Charges as shown on your Loan Estimate, not to exceed ___% of the loan. It turns a federal disclosure into a contractual ceiling. Left blank, there is no cap.",
    do: "Fill it. Also set the interest-rate ceiling high enough to be real but low enough to protect you.",
  },
  {
    phase: "offer", code: "20-19 ¶4B", gap: true,
    t: "Ask about solar, propane, water softener, security",
    b: "A fixture lease files a UCC-1 the title company must clear, puts the payment into your debt-to-income, and can cost $10,000–$30,000 to buy out. An unchecked box is a seller representation that none exists — leverage, but only if you notice.",
    do: "Ask on every property with panels, a tank, a softener, or monitored security. Two of those are common on North Texas acreage.",
  },
  {
    phase: "contract", code: "20-19 ¶5C", gap: true,
    t: "Earnest money: three days, and wire it",
    b: "Due to the escrow agent within 3 days of the Effective Date. Time is of the essence, strict compliance required. A mailed check routinely misses it.",
    do: "Wire it. Get dated written confirmation from the escrow agent. Count the three days yourself.",
  },
  {
    phase: "contract", code: "20-19 ¶4B", gap: true,
    t: "Get the actual lease, day one of the option period",
    b: "Not a summary — the document. Send it to the lender before the financing addendum deadline. A lease found late, after ¶2A has expired, can break qualification when the contingency no longer exists.",
    do: "Day one, not day nine. Confirm with the title company who clears the UCC and who pays.",
  },
  {
    phase: "contract", code: "40-11 ¶2B", gap: false, thin: true,
    t: "Property Approval runs much later than you think",
    b: "Appraisal, insurability and lender-required repairs stay terminable until the 3rd day before closing — far longer than the ¶2A window. This is your remaining protection once the financing contingency is gone. No book in the corpus teaches this paragraph.",
    do: "Both ¶2A and ¶2B terminations need notice AND a written lender statement. Ask the lender early how fast they produce one.",
  },
  {
    phase: "closing", code: "20-19 ¶10B", gap: true,
    t: "Smart devices — codes, and the seller's access",
    b: "New in 20-19. The seller must hand over access codes, usernames and passwords, and remove their own access from their personal devices. Garage doors, locks, cameras, thermostat.",
    do: "Verify at the final walkthrough, not after. Change everything anyway once you own it.",
  },
];

const STATUSES = ["watching", "touring", "toured", "offer made", "under contract", "passed"];

const DOCUMENT_CATEGORIES = ["Closing", "Deed", "Survey", "Title policy", "Warranty", "Permit", "Manual", "Insurance", "Contractor", "Other"];
const MAINTENANCE_CADENCES = ["monthly", "quarterly", "semiannual", "annual", "as needed"];
const MAINTENANCE_SEED = [
  ["m-foundation", "Walk the slab, brick, doors, and drainage", "Foundation & drainage", "semiannual", "North Texas clay: photograph changes and keep the same observation points."],
  ["m-fence", "Walk the whole fence line", "Yard & dogs", "quarterly", "Check gates, dig points, loose boards, and gaps before they become escapes."],
  ["m-hvac", "Replace or inspect HVAC filters", "HVAC", "quarterly", "Adjust cadence to the installed system, filter, dogs, and actual dust load."],
  ["m-smoke", "Test smoke and carbon-monoxide alarms", "Safety", "semiannual", "Record device age and replace on the manufacturer's schedule."],
  ["m-gutters", "Clear roof drainage and inspect discharge", "Roof & drainage", "semiannual", "Confirm water moves away from the slab before spring storms and after leaf fall."],
].map(([id, title, area, cadence, notes]) => ({ id, title, area, cadence, notes, nextDue: "", history: [], archived: false }));

function makeSeedState() {
  const tasks = SEED_TASKS.map(([phase, text, note], i) => ({
    id: "t" + i, phase, text, note, done: false,
  }));
  return {
    // Demo figures. A real deployment supplies its own from the finance module.
    // The $2,750 previously seeded here was a MID-MONTH PARTIAL (5.5% of target
    // logged so far in August), not a rate. Monarch is the system of record.
    savings: { current: 40000, target: 75000, monthly: 5000 },
    money: { price: 375000, rate: 6.5, taxRate: 2.2, insurance: 2500 },
    journey: { currentPhase: "prepare" },
    items: tasks.map(taskToItem),
    trash: [],
    tasks,
    properties: [],
    reading: {},
    household: {
      billFacts: {},
      documents: [],
      maintenance: MAINTENANCE_SEED,
      tax: { exemptionFiled: false, appraisalNoticeDate: "", protestFiledYear: "", taxPaidYear: "" },
    },
  };
}

function taskToItem(task) {
  return {
    id: task.id,
    type: "task",
    phase: task.phase || "prepare",
    title: task.text || "Untitled task",
    detail: task.note || "",
    dueDate: "",
    done: !!task.done,
    createdAt: "",
  };
}

function normalizeJourneyItem(item, removed = false) {
  return {
    id: item.id || "i" + Date.now() + Math.random().toString(16).slice(2),
    type: ITEM_TYPES.some(([id]) => id === item.type) ? item.type : "note",
    phase: PHASES.some((phase) => phase.id === item.phase) ? item.phase : "prepare",
    title: item.title || item.text || "Untitled item",
    detail: item.detail || item.note || "",
    dueDate: item.dueDate || "",
    done: !!item.done,
    createdAt: item.createdAt || "",
    updatedAt: item.updatedAt || "",
    ...(removed ? { removedAt: item.removedAt || "" } : {}),
  };
}

function normalizeState(raw) {
  const seed = makeSeedState();
  const source = raw && typeof raw === "object" ? raw : {};
  const items = Array.isArray(source.items)
    ? source.items.filter((item) => !isLegacyWholeBookTask(item)).map((item) => normalizeJourneyItem(item))
    : (Array.isArray(source.tasks) ? source.tasks : seed.tasks)
      .filter((item) => !isLegacyWholeBookTask(item))
      .map(taskToItem);
  const trash = Array.isArray(source.trash)
    ? source.trash
      .filter((item) => !isLegacyWholeBookTask(item))
      .map((item) => normalizeJourneyItem(item, true))
    : [];
  const tasks = items.filter((item) => item.type === "task").map((item) => ({
    id: item.id,
    phase: item.phase,
    text: item.title,
    note: item.detail,
    done: item.done,
  }));
  const currentPhase = PHASES.some((phase) => phase.id === source.journey?.currentPhase)
    ? source.journey.currentPhase
    : "prepare";
  const household = source.household && typeof source.household === "object" ? source.household : {};
  const documents = Array.isArray(household.documents) ? household.documents.map((item) => ({
    id: item.id || "d" + Date.now() + Math.random().toString(16).slice(2),
    title: item.title || "Untitled document",
    category: DOCUMENT_CATEGORIES.includes(item.category) ? item.category : "Other",
    location: item.location || "",
    date: item.date || "",
    notes: item.notes || "",
    archived: !!item.archived,
  })) : [];
  const maintenance = Array.isArray(household.maintenance) ? household.maintenance.map((item) => ({
    id: item.id || "m" + Date.now() + Math.random().toString(16).slice(2),
    title: item.title || "Untitled maintenance item",
    area: item.area || "House",
    cadence: MAINTENANCE_CADENCES.includes(item.cadence) ? item.cadence : "as needed",
    nextDue: item.nextDue || "",
    notes: item.notes || "",
    history: Array.isArray(item.history) ? item.history.filter(Boolean) : [],
    archived: !!item.archived,
  })) : MAINTENANCE_SEED;
  return {
    ...seed,
    ...source,
    journey: { ...seed.journey, ...(source.journey || {}), currentPhase },
    items,
    trash,
    tasks,
    household: {
      billFacts: household.billFacts && typeof household.billFacts === "object" ? household.billFacts : {},
      documents,
      maintenance,
      tax: {
        exemptionFiled: !!household.tax?.exemptionFiled,
        appraisalNoticeDate: household.tax?.appraisalNoticeDate || "",
        protestFiledYear: household.tax?.protestFiledYear || "",
        taxPaidYear: household.tax?.taxPaidYear || "",
      },
    },
  };
}

/* ---------------- helpers ---------------- */

const money = (n) =>
  "$" + Number(n || 0).toLocaleString("en-US", { maximumFractionDigits: 0 });

const money2 = (n) =>
  "$" + Number(n || 0).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

function addCadence(dateText, cadence) {
  const base = dateText ? new Date(`${dateText}T12:00:00`) : new Date();
  if (cadence === "monthly") base.setMonth(base.getMonth() + 1);
  if (cadence === "quarterly") base.setMonth(base.getMonth() + 3);
  if (cadence === "semiannual") base.setMonth(base.getMonth() + 6);
  if (cadence === "annual") base.setFullYear(base.getFullYear() + 1);
  return cadence === "as needed" ? "" : base.toISOString().slice(0, 10);
}

function protestDeadline(noticeDate) {
  const year = Number((noticeDate || "").slice(0, 4)) || new Date().getFullYear();
  const may15 = new Date(year, 4, 15, 12);
  if (!noticeDate) return may15.toISOString().slice(0, 10);
  const afterNotice = new Date(`${noticeDate}T12:00:00`);
  afterNotice.setDate(afterNotice.getDate() + 30);
  return (afterNotice > may15 ? afterNotice : may15).toISOString().slice(0, 10);
}

function monthsUntilDec2026() {
  const now = new Date();
  const target = new Date(2026, 11, 31);
  return Math.max(0, Math.round((target - now) / (1000 * 60 * 60 * 24 * 30.44)));
}

function flagsFor(p) {
  const out = [];
  const price = Number(p.price) || 0;
  const yr = Number(p.yearBuilt) || 0;
  const tax = Number(p.taxRatePct) || 0;

  if (p.district === "unknown")
    out.push("MUD/PID status unconfirmed — ask for the disclosure before writing an offer.");
  if (p.district === "mud" || p.district === "both")
    out.push("In a MUD. The rate can change; it adds to the monthly cost the listing doesn't show.");
  if (p.district === "pid" || p.district === "both")
    out.push("In a PID. Fixed assessment on top of taxes.");
  if (p.buildType === "newbuild")
    out.push("New build — get an outside loan estimate and pick our own title company.");
  if (yr && yr < 1995)
    out.push("Pre-1995 slab. Budget a structural engineer on top of the general inspection.");
  if (tax > 2.2)
    out.push("Tax rate above 2.2% — run the real monthly number before falling for the price.");
  if (p.fencedYard === "no")
    out.push("No fenced yard. Four dogs — price the fence into the offer.");
  if (p.fencedYard === "unknown")
    out.push("Fence unconfirmed.");
  if (price > 0 && price > 425000)
    out.push("Above $425k — check that 20% down still clears with the closing reserve intact.");
  return out;
}

/* ---------------- app ---------------- */

export default function Homestead() {
  const [tab, setTab] = useState("overview");
  const [state, setState] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saveErr, setSaveErr] = useState(false);
  const [finance, setFinance] = useState(null);
  const [financeErr, setFinanceErr] = useState(false);
  const [bills, setBills] = useState(null);
  const [billsErr, setBillsErr] = useState(false);
  const [learning, setLearning] = useState(null);
  const [learningErr, setLearningErr] = useState(false);
  const [listingRecords, setListingRecords] = useState([]);
  const [listingErr, setListingErr] = useState(false);
  const [pendingListing, setPendingListing] = useState(null);
  const [listingSaving, setListingSaving] = useState(false);
  const [listingSaveErr, setListingSaveErr] = useState("");
  const [scout, setScout] = useState(null);
  const [scoutErr, setScoutErr] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const r = await storage.get(STORAGE_KEY);
        const raw = r ? JSON.parse(r.value) : makeSeedState();
        const normalized = normalizeState(raw);
        setState(normalized);
        if (hasLegacyWholeBookTasks(raw)) {
          try {
            await storage.set(STORAGE_KEY, JSON.stringify(normalized));
          } catch {
            setSaveErr(true);
          }
        }
      } catch {
        setState(normalizeState(makeSeedState()));
      }
      setLoading(false);
    })();
  }, []);

  useEffect(() => {
    fetch("/api/listings", { cache: "no-store" })
      .then((r) => {
        if (!r.ok) throw new Error("listings unavailable");
        return r.json();
      })
      .then((payload) => { setListingRecords(payload.listings || []); setListingErr(false); })
      .catch(() => setListingErr(true));
  }, []);

  useEffect(() => {
    const receive = () => {
      const encoded = document.documentElement.getAttribute("data-homestead-listing-import");
      if (!encoded) return;
      try {
        const payload = JSON.parse(encoded);
        if (payload?.capture?.schema_version === 1) {
          setPendingListing(payload.capture);
          setTab("properties");
        }
      } catch {}
    };
    document.addEventListener("homestead-listing-import-ready", receive);
    receive();
    return () => document.removeEventListener("homestead-listing-import-ready", receive);
  }, []);

  useEffect(() => {
    fetch("/api/bills", { cache: "no-store" })
      .then((r) => {
        if (!r.ok) throw new Error("bills unavailable");
        return r.json();
      })
      .then((payload) => { setBills(payload.bills || []); setBillsErr(false); })
      .catch(() => setBillsErr(true));
  }, []);

  useEffect(() => {
    fetch("/api/finance", { cache: "no-store" })
      .then((r) => {
        if (!r.ok) throw new Error("finance unavailable");
        return r.json();
      })
      .then((payload) => { setFinance(payload); setFinanceErr(false); })
      .catch(() => setFinanceErr(true));
  }, []);

  useEffect(() => {
    fetch("/api/learning", { cache: "no-store" })
      .then((r) => {
        if (!r.ok) throw new Error("learning unavailable");
        return r.json();
      })
      .then((payload) => { setLearning(payload); setLearningErr(false); })
      .catch(() => setLearningErr(true));
  }, []);

  const loadScout = useCallback(() => {
    return fetch("/api/scout", { cache: "no-store" })
      .then((r) => {
        if (!r.ok) throw new Error("scout unavailable");
        return r.json();
      })
      .then((payload) => { setScout(payload); setScoutErr(false); })
      .catch(() => setScoutErr(true));
  }, []);

  useEffect(() => { loadScout(); }, [loadScout]);

  const persist = async (next) => {
    const normalized = normalizeState(next);
    setState(normalized);
    try {
      await storage.set(STORAGE_KEY, JSON.stringify(normalized));
      setSaveErr(false);
    } catch {
      setSaveErr(true);
    }
  };

  const finishListingHandoff = () => {
    document.dispatchEvent(new Event("homestead-listing-import-consumed"));
    if (new URLSearchParams(window.location.search).has("listing-import")) {
      history.replaceState(null, "", window.location.pathname);
    }
    setPendingListing(null);
    setListingSaveErr("");
  };

  const saveListing = async (capture) => {
    setListingSaving(true);
    setListingSaveErr("");
    try {
      const response = await fetch("/api/listings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(capture),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.error || `Import failed (${response.status})`);
      const record = payload.listing;
      setListingRecords((current) => [record, ...current.filter((item) => item.listing_id !== record.listing_id)]);
      const fields = record.fields;
      const property = {
        id: "p-" + record.listing_id,
        address: fields.address || "",
        city: [fields.city, fields.state, fields.postal_code].filter(Boolean).join(", ").replace(", " + fields.postal_code, " " + fields.postal_code),
        price: fields.price || "",
        sqft: fields.living_area || "",
        beds: fields.bedrooms || "",
        baths: fields.bathrooms || "",
        lotAcres: fields.lot_sqft ? (Number(fields.lot_sqft) / 43560).toFixed(3).replace(/0+$/, "").replace(/\.$/, "") : "",
        yearBuilt: fields.year_built || "",
        hoaMonthly: fields.hoa_monthly || "",
        taxRatePct: "",
        buildType: "resale",
        district: "unknown",
        fencedYard: "unknown",
        status: "watching",
        notes: "",
        listingId: record.listing_id,
        source: record.source,
        sourceUrl: record.source_url,
      };
      const existing = state.properties.find((item) => item.listingId === record.listing_id);
      await persist({
        ...state,
        properties: existing
          ? state.properties.map((item) => item.listingId === record.listing_id ? { ...property, status: item.status, notes: item.notes, district: item.district, fencedYard: item.fencedYard, taxRatePct: item.taxRatePct } : item)
          : [property, ...state.properties],
      });
      finishListingHandoff();
    } catch (error) {
      setListingSaveErr(String(error?.message || error));
    } finally {
      setListingSaving(false);
    }
  };

  if (loading || !state) {
    return (
      <div className="hs">
        <style>{CSS}</style>
        <div className="hs-wrap">
          <div className="hs-empty" style={{ paddingTop: 90 }}>Opening the plat…</div>
        </div>
      </div>
    );
  }

  const tabs = [
    ["overview", "Overview"],
    ["journey", "Journey"],
    ["properties", "Properties"],
    ["scout", "Scout"],
    ["tasks", "Tasks"],
    ["money", "Money"],
    ["household", "Household"],
    ["reading", "Reading"],
  ];
  const moveTab = (event, currentId) => {
    const currentIndex = tabs.findIndex(([id]) => id === currentId);
    let nextIndex = null;
    if (event.key === "ArrowRight") nextIndex = (currentIndex + 1) % tabs.length;
    if (event.key === "ArrowLeft") nextIndex = (currentIndex - 1 + tabs.length) % tabs.length;
    if (event.key === "Home") nextIndex = 0;
    if (event.key === "End") nextIndex = tabs.length - 1;
    if (nextIndex === null) return;
    event.preventDefault();
    const nextId = tabs[nextIndex][0];
    setTab(nextId);
    requestAnimationFrame(() => document.getElementById(`hs-tab-${nextId}`)?.focus());
  };
  const currentPhase = PHASES.find((phase) => phase.id === state.journey.currentPhase) || PHASES[0];

  return (
    <div className="hs">
      <style>{CSS}</style>
      <div className="hs-wrap">
        <header className="hs-plat">
          <div className="hs-plat-row">
            <div className="hs-brand">
              <svg className="hs-brand-icon" viewBox="0 0 128 128" role="img" aria-label="Homestead">
                <path d="M20 28h76v84H20z" fill="none" stroke="var(--boundary)" strokeWidth="7" />
                <path d="M31 17h77v84H31z" fill="var(--county-paper)" stroke="var(--ink)" strokeWidth="8" />
                <path fill="var(--ink)" d="M47 37h12v22h21V37h12v45H80V70H59v12H47z" />
                <path d="M48 89h44" stroke="var(--county-teal)" strokeWidth="8" />
                <path d="M48 96h26" stroke="var(--record-edge)" strokeWidth="5" />
              </svg>
              <div>
                <h1 className="hs-mark">HOME<span>STEAD</span></h1>
                <div className="hs-mark-sub">Household record · North Texas</div>
              </div>
            </div>
            <div className="hs-legend">{currentPhase.name}</div>
          </div>
          <nav className="hs-nav" role="tablist" aria-label="Sections">
            {tabs.map(([id, label]) => (
              <button key={id} id={`hs-tab-${id}`} role="tab" aria-selected={tab === id}
                aria-controls={`hs-panel-${id}`} tabIndex={tab === id ? 0 : -1}
                className="hs-tab" onClick={() => setTab(id)} onKeyDown={(event) => moveTab(event, id)}>
                {label}
              </button>
            ))}
          </nav>
        </header>

        {saveErr && (
          <div className="hs-panel" style={{ borderColor: "var(--mesquite)", marginBottom: 18 }}>
            <div className="hs-flag">Changes aren't saving right now. Copy anything important before you close this.</div>
          </div>
        )}

        {pendingListing && (
          <ListingImport capture={pendingListing} saving={listingSaving} error={listingSaveErr}
            onSave={saveListing} onCancel={finishListingHandoff} />
        )}

        <main id={`hs-panel-${tab}`} role="tabpanel" aria-labelledby={`hs-tab-${tab}`}>
        {tab === "overview" && <Overview state={state} persist={persist} setTab={setTab} learning={learning} />}
        {tab === "journey" && <Journey state={state} persist={persist} />}
        {tab === "properties" && <Properties state={state} persist={persist} listingRecords={listingRecords} listingErr={listingErr} />}
        {tab === "scout" && <Scout scout={scout} scoutErr={scoutErr} reload={loadScout} />}
        {tab === "tasks" && <Tasks state={state} persist={persist} />}
        {tab === "money" && finance && <Money state={state} persist={persist} finance={finance} />}
        {tab === "money" && !finance && (
          <div className="hs-panel">
            <div className="hs-flag">
              {financeErr ? "Finance data is unavailable. The last known values are not displayed." : "Loading finance data…"}
            </div>
          </div>
        )}
        {tab === "household" && <Household state={state} persist={persist} bills={bills} billsErr={billsErr} />}
        {tab === "reading" && <Reading state={state} persist={persist} learning={learning} learningErr={learningErr} />}
        </main>
      </div>
    </div>
  );
}

/* ---------------- scout ----------------

   The lead inbox. Everything here is an EMAIL lead, which is a much weaker thing than a
   property: the alert carries a preview card, not a dossier, and Homestead has not seen
   the live page. So this view never offers a "save to Properties" action, and it repeats
   the boundary in plain words rather than assuming it is remembered.

   Remote email images are deliberately not rendered -- loading them would report back to
   the sender that David opened the alert, and would pull unverified media into the app. */

const SCOUT_FILTERS = [
  ["new", "New"],
  ["shortlisted", "Shortlisted"],
  ["dismissed", "Dismissed"],
  ["captured", "Captured"],
  ["all", "All"],
];

const SCOUT_SOURCE_LABEL = { zillow: "Zillow", redfin: "Redfin" };

const COPY_SHORTCUT = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform || "")
  ? "⌘C" : "Ctrl+C";

/* Synchronous clipboard write, reported honestly.
 *
 * `navigator.clipboard.writeText` returns a promise that, when the page lacks clipboard
 * permission or OS focus, can hang unresolved rather than reject -- which would leave the
 * button stuck mid-action. `execCommand` is deprecated but answers immediately, so the UI
 * always knows whether it worked. The async API is still fired as a best effort and never
 * awaited. Returns true only when the copy is known to have succeeded. */
function writeToClipboard(text) {
  let copied = false;
  try {
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.cssText = "position:fixed;top:0;left:0;opacity:0";
    document.body.appendChild(area);
    area.select();
    area.setSelectionRange(0, text.length);
    copied = document.execCommand("copy");
    document.body.removeChild(area);
  } catch {
    copied = false;
  }
  if (!copied) {
    try { navigator.clipboard?.writeText(text).catch(() => {}); } catch { /* best effort */ }
  }
  return copied;
}

function leadFacts(lead) {
  return [
    lead.price ? money(lead.price) : null,
    lead.bedrooms ? `${lead.bedrooms} bd` : null,
    lead.bathrooms ? `${lead.bathrooms} ba` : null,
    lead.living_area ? `${Number(lead.living_area).toLocaleString()} sf` : null,
    lead.lot_sqft ? `${Number(lead.lot_sqft).toLocaleString()} sf lot` : null,
    lead.property_type || null,
    lead.listing_status || null,
  ].filter(Boolean);
}

function shortDate(value) {
  if (!value) return "";
  const parsed = new Date(value);
  if (isNaN(parsed.getTime())) return String(value);
  return parsed.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function Scout({ scout, scoutErr, reload }) {
  const [filter, setFilter] = useState("new");
  const [busyId, setBusyId] = useState(null);
  const [actionErr, setActionErr] = useState("");
  const [manualCopyId, setManualCopyId] = useState(null);

  const copyAddress = (lead) => {
    const line = leadAddressLine(lead);
    if (!line) return;
    setActionErr("");
    // Deliberately no "Copied!" confirmation. Tested against the live site, both clipboard
    // routes lie: writeText() never settles its promise, and execCommand returns true
    // while the clipboard still holds its previous contents. A success message that can be
    // false is worse than none, so the write is fired as a silent best effort and the
    // reader is always handed a selected field that works regardless.
    writeToClipboard(line);
    setManualCopyId((current) => (current === lead.id ? null : lead.id));
  };

  if (scoutErr) {
    return (
      <div className="hs-panel">
        <div className="hs-flag">
          Scout is unavailable right now. No leads are shown rather than stale ones.
        </div>
      </div>
    );
  }
  if (!scout) return <div className="hs-panel"><div className="hs-note">Opening the lead book…</div></div>;

  const counts = scout.counts || {};
  const criteria = scout.profile ? scout.profile.profile : null;
  const leads = (scout.discoveries || []).filter(
    (lead) => filter === "all" || lead.status === filter
  );

  const review = async (id, status) => {
    setBusyId(id);
    setActionErr("");
    try {
      const response = await fetch("/api/scout/review", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id, status }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok || !payload.ok) throw new Error(payload.error || "Could not update this lead");
      await reload();
    } catch (error) {
      setActionErr(String(error?.message || error));
    } finally {
      setBusyId(null);
    }
  };

  return (
    <>
      <h2 className="hs-h">Scout — email leads</h2>

      <div className="hs-panel" style={{ marginBottom: 16 }}>
        <div className="hs-flag">{scout.boundary}</div>
        <div className="hs-note" style={{ marginTop: 10 }}>
          {criteria ? (
            <>
              Ranked against the criteria you approved:{" "}
              <strong>
                {[
                  criteria.max_price ? `${money(criteria.max_price)} maximum` : null,
                  criteria.cities && criteria.cities.length ? criteria.cities.join(" and ") : null,
                ].filter(Boolean).join(" · ")}
              </strong>
              . Everything else — bedrooms, bathrooms, property type, lot size, HOA, year
              built, schools, fenced yard — is not set, and was not considered.
            </>
          ) : (
            <>
              Leads are <strong>unranked</strong>. No buying criteria are stored yet, and a
              guessed score would read as an opinion this household never expressed.
            </>
          )}
        </div>
        <div className="hs-lead-seen" style={{ marginTop: 8 }}>
          Ingestion: {scout.ingestion?.last_accepted_at
            ? `last accepted alert ${shortDate(scout.ingestion.last_accepted_at)}`
            : "no alert mail accepted yet"}
          {scout.ingestion?.stale ? " · STALE" : ""}
        </div>
      </div>

      <div className="hs-lead-filters">
        {SCOUT_FILTERS.map(([id, label]) => (
          <button key={id} type="button" className="hs-btn ghost small hs-lead-filter"
            aria-pressed={filter === id} onClick={() => setFilter(id)}>
            {label} {counts[id] ?? 0}
          </button>
        ))}
      </div>

      {actionErr && (
        <div className="hs-panel" style={{ borderColor: "var(--mesquite)", marginBottom: 14 }}>
          <div className="hs-flag">{actionErr}</div>
        </div>
      )}

      {leads.length === 0 ? (
        <div className="hs-panel">
          <div className="hs-empty-t">No leads here yet</div>
          <div className="hs-note" style={{ marginTop: 6 }}>
            Scout reads the Zillow and Redfin saved-search alerts sent to Gmail. Nothing has
            been imported yet.
          </div>
        </div>
      ) : (
        <div className="hs-grid">
          {leads.map((lead) => {
            const facts = leadFacts(lead);
            const place = [lead.city, lead.state, lead.postal_code].filter(Boolean).join(" ");
            return (
              <article key={lead.id} className={`hs-lead${lead.status === "dismissed" ? " dismissed" : ""}`}>
                <div className="hs-lead-hd">
                  <div>
                    <div className="hs-lead-addr">{lead.address || "Address not in the alert"}</div>
                    {place && <div className="hs-note">{place}</div>}
                  </div>
                  <span className="hs-lead-src">
                    {SCOUT_SOURCE_LABEL[lead.source] || lead.source}
                    {lead.status === "captured" ? " · captured" : ""}
                  </span>
                </div>

                {facts.length > 0 && (
                  <div className="hs-lead-facts">
                    {facts.map((fact, index) => <span key={index}>{fact}</span>)}
                  </div>
                )}

                <div className="hs-lead-seen">
                  First seen {shortDate(lead.first_seen_at)} · last seen {shortDate(lead.last_seen_at)}
                  {" · "}{lead.sighting_count} alert{lead.sighting_count === 1 ? "" : "s"}
                </div>

                {lead.assessment && (
                  <div className="hs-lead-fit">
                    <div className={`hs-lead-fit-lab ${lead.fit_score >= 75 ? "hs-accent" : "hs-warn"}`}>
                      {lead.fit_label} · {lead.fit_score}
                    </div>
                    {(lead.assessment.reasons || []).map((line, index) => (
                      <div key={`r${index}`} className="hs-lead-why">
                        <span className="hs-lead-mark hs-accent">✓</span> {line}
                      </div>
                    ))}
                    {(lead.assessment.cautions || []).map((line, index) => (
                      <div key={`c${index}`} className="hs-lead-why">
                        <span className="hs-lead-mark hs-warn">!</span> {line}
                      </div>
                    ))}
                  </div>
                )}

                <div className="hs-lead-actions">
                  {hasDirectListingLink(lead) ? (
                    <a className="hs-btn ghost small" href={lead.source_url}
                      target="_blank" rel="noreferrer noopener">
                      Open on {SCOUT_SOURCE_LABEL[lead.source] || lead.source}
                    </a>
                  ) : (
                    <>
                      {/* Redfin's alert links are opaque trackers, so there is no listing
                          URL to open. The honest substitute is the ZIP browse page plus
                          the address ready to paste into Redfin's own search box. */}
                      <button type="button" className="hs-btn ghost small"
                        onClick={() => copyAddress(lead)}
                        aria-expanded={manualCopyId === lead.id}
                        disabled={!leadAddressLine(lead)}>
                        Copy address
                      </button>
                      <a className="hs-btn ghost small" href={redfinLookupUrl(lead)}
                        target="_blank" rel="noreferrer noopener"
                        title="Redfin's alert emails carry no direct listing link, so this opens the ZIP and you paste the address into its search box.">
                        Search Redfin{lead.postal_code ? ` · ${lead.postal_code}` : ""}
                      </a>
                    </>
                  )}
                  {lead.status !== "captured" && (
                    <>
                      <button type="button" className="hs-btn ghost small"
                        disabled={busyId === lead.id}
                        onClick={() => review(lead.id, lead.status === "shortlisted" ? "new" : "shortlisted")}>
                        {lead.status === "shortlisted" ? "Remove from shortlist" : "Shortlist"}
                      </button>
                      <button type="button" className="hs-btn ghost small warn"
                        disabled={busyId === lead.id}
                        onClick={() => review(lead.id, lead.status === "dismissed" ? "new" : "dismissed")}>
                        {lead.status === "dismissed" ? "Undismiss" : "Dismiss"}
                      </button>
                    </>
                  )}
                </div>

                {manualCopyId === lead.id && (
                  <label className="hs-lead-manual">
                    <span className="hs-field-lab">Copy this, then paste it into Redfin</span>
                    <input className="hs-in" readOnly autoFocus value={leadAddressLine(lead)}
                      onFocus={(event) => event.target.select()}
                      onClick={(event) => event.target.select()} />
                    <span className="hs-note">
                      Press {COPY_SHORTCUT}, then paste it into Redfin's search box.
                    </span>
                  </label>
                )}
              </article>
            );
          })}
        </div>
      )}

      <div className="hs-panel" style={{ marginTop: 16 }}>
        <div className="hs-note">
          Shortlisting and dismissing are review states. Neither saves a property nor
          downloads listing media. To file one of these in Properties, open the live page,
          use Homestead Capture, review the full capture, and save it there — Scout will
          then mark this lead captured.
        </div>
      </div>
    </>
  );
}

/* ---------------- overview ---------------- */

function Overview({ state, persist, setTab, learning }) {
  const [editing, setEditing] = useState(false);
  const { current, target, monthly } = state.savings;

  const POST = 2500;
  const posts = Math.round(target / POST);
  const set = Math.floor(current / POST);
  const pct = Math.min(100, (current / target) * 100);
  const left = Math.max(0, target - current);
  const months = monthsUntilDec2026();
  const needed = months > 0 ? left / months : left;

  const tasks = state.items.filter((item) => item.type === "task");
  const open = tasks.filter((t) => !t.done);
  const nextUp = open.filter((t) => t.phase === "prepare").slice(0, 4);
  const doneCount = tasks.length - open.length;
  const currentPhaseIndex = Math.max(0, PHASES.findIndex((phase) => phase.id === state.journey.currentPhase));
  const focusPhases = PHASES.slice(currentPhaseIndex, currentPhaseIndex + 2);
  const focusPhaseIds = new Set(focusPhases.map((phase) => phase.id));
  const followThrough = state.items
    .filter((item) => !item.done && (item.type === "decision" || item.type === "deadline") && focusPhaseIds.has(item.phase))
    .sort((a, b) => {
      const phaseDifference = PHASES.findIndex((phase) => phase.id === a.phase)
        - PHASES.findIndex((phase) => phase.id === b.phase);
      if (phaseDifference) return phaseDifference;
      if (a.type !== b.type) return a.type === "deadline" ? -1 : 1;
      return (a.dueDate || "9999-12-31").localeCompare(b.dueDate || "9999-12-31");
    });
  const now = new Date();
  const today = [now.getFullYear(), String(now.getMonth() + 1).padStart(2, "0"), String(now.getDate()).padStart(2, "0")].join("-");
  const openJourney = (phase) => {
    persist({ ...state, journey: { ...state.journey, currentPhase: phase } });
    setTab("journey");
  };
  const learnedCount = Object.entries(state.reading).filter(([key, value]) => key.startsWith("learn:") && value).length;
  const learningTotal = learning?.metadata?.objective_count || 85;

  return (
    <>
      <h2 className="hs-h">Down payment</h2>
      <div className="hs-panel">
        <div className="hs-row" style={{ justifyContent: "space-between", marginBottom: 16 }}>
          <div>
            <div className="hs-num hs-accent">{money2(current)}</div>
            <div className="hs-lab">of {money(target)} · {pct.toFixed(1)}%</div>
          </div>
          <button className="hs-btn ghost" onClick={() => setEditing(!editing)}>
            {editing ? "Done" : "Update"}
          </button>
        </div>

        <div className="hs-fence">
          <div className="hs-fence-rail">
            <div className="hs-fence-wire w1" />
            <div className="hs-fence-wire w2" />
            <div className="hs-fence-wire-fill" style={{ top: 17, width: pct + "%" }} />
            <div className="hs-fence-wire-fill" style={{ top: 31, width: pct + "%" }} />
            <div className="hs-posts">
              {Array.from({ length: posts }).map((_, i) => (
                <div key={i}
                  className={"hs-post" + (i < set ? " set" : "") + (i === set ? " now" : "")} />
              ))}
            </div>
          </div>
          <div className="hs-fence-labels">
            <span>$0</span>
            <span>{posts - set} posts left · {money(POST)} each</span>
            <span>{money(target)}</span>
          </div>
        </div>

        {editing && (
          <div className="hs-grid hs-g4" style={{ marginTop: 18 }}>
            <Field label="Saved so far" value={current}
              onChange={(v) => persist({ ...state, savings: { ...state.savings, current: Number(v) || 0 } })} />
            <Field label="Target" value={target}
              onChange={(v) => persist({ ...state, savings: { ...state.savings, target: Number(v) || 0 } })} />
            <Field label="Monthly" value={monthly}
              onChange={(v) => persist({ ...state, savings: { ...state.savings, monthly: Number(v) || 0 } })} />
          </div>
        )}
      </div>

      <div className="hs-sp" />
      <div className="hs-grid hs-g4">
        <Cell v={money(left)} l="Left to save" />
        <Cell v={months} l="Months to Dec 2026" />
        <Cell v={money(needed)} l="Needed per month"
          accent={needed <= monthly} warn={needed > monthly} />
        <Cell v={money(monthly)} l="Contributing now" />
      </div>

      <div className="hs-sp" />
      <div className="hs-panel">
        <div className="hs-note">
          {monthly >= needed ? (
            <>At {money(monthly)} a month you clear {money(target)} with room to spare — the pace isn't the
            risk. The reserve is.{" "}</>
          ) : (
            <>
              <strong style={{ color: "var(--mesquite)" }}>The current pace does not reach the target.</strong>{" "}
              {money(left)} left over {months} month{months === 1 ? "" : "s"} needs {money2(needed)} a month;
              you're contributing {money(monthly)}. That lands roughly{" "}
              {money((needed - monthly) * months)} short by Dec 2026. Move the rate, the date, or the target —
              and check it against Monarch, which is the system of record for this goal, not this page.{" "}
            </>
          )}
          Closing costs run 2–5% of the price and are <em>separate</em> from the 20%; on a
          $400,000 house that's {money(8000)}–{money(20000)} more. A down payment that lands exactly on target
          with nothing behind it is how people end up rolling costs into the loan they were trying to avoid.
        </div>
      </div>

      <h2 className="hs-h">Where things stand</h2>
      <div className="hs-grid hs-g4">
        <Cell v={doneCount + " / " + tasks.length} l="Tasks done" />
        <Cell v={state.properties.length} l="Properties tracked" />
        <Cell v={open.filter((t) => t.phase === "prepare").length} l="Open in Prepare" />
        <Cell v={learnedCount + " / " + learningTotal} l="Topics learned" />
      </div>

      <h2 className="hs-h">Next up</h2>
      <div className="hs-panel">
        {nextUp.length === 0 ? (
          <div className="hs-note">Prepare is clear. Move to Search when you're ready.</div>
        ) : (
          nextUp.map((t) => (
            <div key={t.id} className="hs-task">
              <span className="hs-check" aria-hidden="true" />
              <div className="hs-task-txt">
                {t.title}
                {t.detail && <div className="hs-note">{t.detail}</div>}
              </div>
            </div>
          ))
        )}
        <div style={{ marginTop: 14 }}>
          <button className="hs-btn ghost" onClick={() => setTab("tasks")}>Open tasks</button>
        </div>
      </div>

      <h2 className="hs-h">Decisions and deadlines</h2>
      <div className="hs-panel">
        <div className="hs-note" style={{ marginTop: 0, marginBottom: followThrough.length ? 14 : 0 }}>
          Open follow-through in {focusPhases.map((phase) => phase.name).join(" and ")}.
        </div>
        {followThrough.length === 0 ? (
          <div className="hs-empty" style={{ padding: "18px 0 8px" }}>
            <div className="hs-empty-t">Nothing needs attention here</div>
            Add a decision or deadline in Journey when one emerges.
          </div>
        ) : followThrough.map((item) => {
          const phase = PHASES.find((candidate) => candidate.id === item.phase);
          const overdue = item.type === "deadline" && item.dueDate && item.dueDate < today;
          return (
            <div key={item.id} className="hs-attention">
              <div className="hs-attention-copy">
                <div className="hs-attention-title">{item.title}</div>
                {item.detail && <div className="hs-note">{item.detail}</div>}
                <div className="hs-item-meta">
                  <span className="hs-kind">{item.type}</span>
                  <span className="hs-date">{phase?.name}</span>
                  {item.type === "deadline" && (
                    <span className={"hs-date" + (overdue ? " hs-overdue" : "")}>
                      {item.dueDate ? `${overdue ? "Overdue" : "Due"} ${item.dueDate}` : "Date needed"}
                    </span>
                  )}
                </div>
              </div>
              <button className="hs-btn ghost small" onClick={() => openJourney(item.phase)}>Open</button>
            </div>
          );
        })}
      </div>
    </>
  );
}

/* ---------------- journey ---------------- */

function Journey({ state, persist }) {
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState({ type: "task", title: "", detail: "", dueDate: "" });
  const draftRef = useRef(draft);
  const [editingId, setEditingId] = useState(null);
  const [editDraft, setEditDraft] = useState(null);
  const editDraftRef = useRef(null);
  const [pendingRemovalId, setPendingRemovalId] = useState(null);
  const currentPhase = PHASES.find((phase) => phase.id === state.journey.currentPhase) || PHASES[0];
  const items = state.items.filter((item) => item.phase === currentPhase.id);
  const open = items.filter((item) => !item.done).length;

  const selectPhase = (phase) => persist({ ...state, journey: { ...state.journey, currentPhase: phase } });
  const add = () => {
    const currentDraft = draftRef.current;
    if (!currentDraft.title.trim()) return;
    persist({
      ...state,
      items: [
        ...state.items,
        {
          id: "i" + Date.now(),
          type: currentDraft.type,
          phase: currentPhase.id,
          title: currentDraft.title.trim(),
          detail: currentDraft.detail.trim(),
          dueDate: currentDraft.type === "deadline" ? currentDraft.dueDate : "",
          done: false,
          createdAt: new Date().toISOString(),
        },
      ],
    });
    const emptyDraft = { type: "task", title: "", detail: "", dueDate: "" };
    draftRef.current = emptyDraft;
    setDraft(emptyDraft);
    setAdding(false);
  };
  const toggle = (id) => persist({
    ...state,
    items: state.items.map((item) => item.id === id ? { ...item, done: !item.done } : item),
  });
  const setDraftField = (key) => (value) => setDraft((current) => {
    const next = { ...current, [key]: value };
    draftRef.current = next;
    return next;
  });
  const startEdit = (item) => {
    const next = {
      type: item.type,
      phase: item.phase,
      title: item.title,
      detail: item.detail,
      dueDate: item.dueDate,
    };
    editDraftRef.current = next;
    setEditDraft(next);
    setEditingId(item.id);
    setPendingRemovalId(null);
  };
  const cancelEdit = () => {
    editDraftRef.current = null;
    setEditDraft(null);
    setEditingId(null);
  };
  const setEditField = (key) => (value) => setEditDraft((current) => {
    const next = { ...current, [key]: value };
    editDraftRef.current = next;
    return next;
  });
  const saveEdit = (id) => {
    const currentDraft = editDraftRef.current;
    if (!currentDraft?.title.trim()) return;
    persist({
      ...state,
      items: state.items.map((item) => item.id === id ? {
        ...item,
        type: currentDraft.type,
        phase: currentDraft.phase,
        title: currentDraft.title.trim(),
        detail: currentDraft.detail.trim(),
        dueDate: currentDraft.type === "deadline" ? currentDraft.dueDate : "",
        updatedAt: new Date().toISOString(),
      } : item),
    });
    cancelEdit();
  };
  const remove = (id) => {
    const item = state.items.find((candidate) => candidate.id === id);
    if (!item) return;
    persist({
      ...state,
      items: state.items.filter((candidate) => candidate.id !== id),
      trash: [...state.trash, { ...item, removedAt: new Date().toISOString() }],
    });
    setPendingRemovalId(null);
    if (editingId === id) cancelEdit();
  };
  const restore = (id) => {
    const item = state.trash.find((candidate) => candidate.id === id);
    if (!item) return;
    const { removedAt, ...restored } = item;
    persist({
      ...state,
      items: [...state.items, { ...restored, updatedAt: new Date().toISOString() }],
      trash: state.trash.filter((candidate) => candidate.id !== id),
    });
  };

  return (
    <>
      <h2 className="hs-h">The path home</h2>
      <div className="hs-panel">
        <div className="hs-note" style={{ marginTop: 0, marginBottom: 16 }}>
          One household record from preparation through the years after move-in. Choose the stage you are
          working in; tasks, decisions, deadlines, documents, and notes stay attached to that part of the journey.
        </div>
        <div className="hs-stagebar" role="navigation" aria-label="Home journey stages">
          {PHASES.map((phase, index) => (
            <button key={phase.id} className="hs-stage"
              aria-current={phase.id === currentPhase.id ? "step" : undefined}
              onClick={() => selectPhase(phase.id)}>
              <div className="hs-stage-n">{String(index + 1).padStart(2, "0")}</div>
              <div className="hs-stage-t">{phase.name}</div>
            </button>
          ))}
        </div>
      </div>

      <h2 className="hs-h">{currentPhase.name}</h2>
      <div className="hs-row" style={{ justifyContent: "space-between", marginBottom: 12 }}>
        <div>
          <div className="hs-phase-name">{currentPhase.when}</div>
          <div className="hs-note">{open} open · {items.length} total</div>
        </div>
        <button className="hs-btn" onClick={() => setAdding(!adding)}>{adding ? "Cancel" : "Add something"}</button>
      </div>

      {adding && (
        <div className="hs-panel" style={{ marginBottom: 12 }}>
          <div className="hs-grid hs-g2">
            <Select label="Kind" value={draft.type} onChange={setDraftField("type")} options={ITEM_TYPES} />
            <Field label="Title" type="text" value={draft.title} onChange={setDraftField("title")}
              placeholder="What should we remember or do?" />
            {draft.type === "deadline" && (
              <Field label="Due date" type="date" value={draft.dueDate} onChange={setDraftField("dueDate")} />
            )}
            <label className="hs-field">
              <span className="hs-field-lab">Details or source</span>
              <textarea className="hs-in" rows="3" value={draft.detail}
                placeholder="Context, source, where the document lives, or what we decided"
                onChange={(e) => setDraftField("detail")(e.target.value)} />
            </label>
          </div>
          <div style={{ marginTop: 14 }}>
            <button className="hs-btn" onClick={add}>Add to {currentPhase.name}</button>
          </div>
        </div>
      )}

      <div className="hs-panel">
        {items.length === 0 ? (
          <div className="hs-empty">
            <div className="hs-empty-t">Nothing recorded here yet</div>
            Add the first task, decision, deadline, document, or note for {currentPhase.name.toLowerCase()}.
          </div>
        ) : items.map((item) => (
          <div key={item.id} className={"hs-item" + (item.done ? " done" : "")}>
            {editingId === item.id && editDraft ? (
              <div className="hs-grid hs-g2">
                <Select label="Kind" value={editDraft.type} onChange={setEditField("type")} options={ITEM_TYPES} />
                <Select label="Stage" value={editDraft.phase} onChange={setEditField("phase")}
                  options={PHASES.map((phase) => [phase.id, phase.name])} />
                <Field label="Title" type="text" value={editDraft.title} onChange={setEditField("title")} />
                {editDraft.type === "deadline" && (
                  <Field label="Due date" type="date" value={editDraft.dueDate} onChange={setEditField("dueDate")} />
                )}
                <label className="hs-field">
                  <span className="hs-field-lab">Details or source</span>
                  <textarea className="hs-in" rows="3" value={editDraft.detail}
                    onChange={(e) => setEditField("detail")(e.target.value)} />
                </label>
                <div className="hs-item-actions" style={{ alignSelf: "end" }}>
                  <button className="hs-btn small" onClick={() => saveEdit(item.id)}>Save changes</button>
                  <button className="hs-btn ghost small" onClick={cancelEdit}>Cancel</button>
                </div>
              </div>
            ) : <div className="hs-item-main">
              <button className="hs-check" role="checkbox" aria-checked={item.done}
                aria-label={`${ITEM_DONE_LABELS[item.type]}: ${item.title}`} onClick={() => toggle(item.id)} />
              <div className="hs-item-copy">
                <div className="hs-item-title">{item.title}</div>
                {item.detail && !item.done && <div className="hs-note">{item.detail}</div>}
                <div className="hs-item-meta">
                  <span className="hs-kind">{ITEM_TYPES.find(([id]) => id === item.type)?.[1] || "Note"}</span>
                  {item.dueDate && <span className="hs-date">Due {item.dueDate}</span>}
                  {item.done && <span className="hs-date">{ITEM_DONE_LABELS[item.type]}</span>}
                </div>
                <div className="hs-item-actions">
                  <button className="hs-btn ghost small" onClick={() => startEdit(item)}>Edit</button>
                  {pendingRemovalId === item.id ? (
                    <>
                      <button className="hs-btn ghost small warn" onClick={() => remove(item.id)}>Move to recently removed</button>
                      <button className="hs-btn ghost small" onClick={() => setPendingRemovalId(null)}>Cancel</button>
                    </>
                  ) : (
                    <button className="hs-btn ghost small warn" onClick={() => setPendingRemovalId(item.id)}>Remove…</button>
                  )}
                </div>
              </div>
            </div>}
          </div>
        ))}
      </div>

      {state.trash.length > 0 && (
        <>
          <h2 className="hs-h">Recently removed</h2>
          <div className="hs-panel">
            <div className="hs-note" style={{ marginTop: 0, marginBottom: 14 }}>
              Removed Journey items stay here until restored. Nothing is permanently deleted in this workspace.
            </div>
            {state.trash.map((item) => {
              const phase = PHASES.find((candidate) => candidate.id === item.phase);
              return (
                <div key={item.id} className="hs-attention hs-removed">
                  <div className="hs-attention-copy">
                    <div className="hs-attention-title">{item.title}</div>
                    <div className="hs-item-meta">
                      <span className="hs-kind">{item.type}</span>
                      <span className="hs-date">{phase?.name}</span>
                    </div>
                  </div>
                  <button className="hs-btn ghost small" onClick={() => restore(item.id)}>Restore</button>
                </div>
              );
            })}
          </div>
        </>
      )}
    </>
  );
}

function Cell({ v, l, accent, warn }) {
  return (
    <div className="hs-cell">
      <div className={"hs-num sm" + (accent ? " hs-accent" : "") + (warn ? " hs-warn" : "")}>{v}</div>
      <div className="hs-lab">{l}</div>
    </div>
  );
}

function Field({ label, value, onChange, type = "number", placeholder }) {
  return (
    <label className="hs-field">
      <span className="hs-field-lab">{label}</span>
      <input className="hs-in" type={type} value={value ?? ""} placeholder={placeholder}
        onInput={type === "date" ? (e) => onChange(e.target.value) : undefined}
        onChange={(e) => onChange(e.target.value)} />
    </label>
  );
}

function Select({ label, value, onChange, options }) {
  return (
    <label className="hs-field">
      <span className="hs-field-lab">{label}</span>
      <select className="hs-sel" value={value} onChange={(e) => onChange(e.target.value)}>
        {options.map((o) => (
          <option key={o[0]} value={o[0]}>{o[1]}</option>
        ))}
      </select>
    </label>
  );
}

/* ---------------- properties ---------------- */

const BLANK = {
  address: "", city: "", price: "", sqft: "", beds: "", baths: "",
  lotAcres: "", yearBuilt: "", hoaMonthly: "", taxRatePct: "",
  buildType: "resale", district: "unknown", fencedYard: "unknown",
  status: "watching", notes: "",
};

const FACT_GROUPS = [
  ["Rooms & interior", /bed|bath|room|kitchen|appliance|interior|floor|fireplace|laundry|basement/i],
  ["Exterior & structure", /architect|construction|exterior|foundation|roof|story|stories|level|lot|garage|parking|patio|porch|pool|fenc|material|style|year built/i],
  ["Utilities & systems", /heating|cooling|sewer|water|utilit|security|window|energy|electric|gas/i],
  ["Community & HOA", /association|community|subdivision|region|school|district|hoa/i],
  ["Location & neighborhood", /location|neighborhood|county|quiet|pedestrian|transit|cycling|restaurant|grocer|shopping|park|greenery|daycare/i],
  ["Climate & sunlight", /climate|factor|flood|fire|heat|wind|air quality|sunlight|sun exposure/i],
  ["Zoning & land use", /zoning|setback|permitted use|site coverage|building height|ordinance/i],
  ["Financial & listing", /tax|parcel|price|listing|term|date|market|mls|loan|mortgage|possession|transaction|status|source|document|apn/i],
];

function humanize(key) {
  return String(key || "").replace(/([a-z0-9])([A-Z])/g, "$1 $2").replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function scalar(value) {
  if (value === null || value === undefined || value === "") return "";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (Array.isArray(value)) return value.slice(0, 24).map(scalar).filter(Boolean).join(" · ");
  if (typeof value === "object") return Object.entries(value).slice(0, 24)
    .map(([key, item]) => `${humanize(key)}: ${scalar(item)}`).filter((item) => !item.endsWith(": ")).join(" · ");
  return String(value);
}

const REDFIN_MACHINE_FACT = /RATIO|GUID|(?:^|_)KEY(?:_|$)|MUI|PROPERTY_MATCH|MULTI_PARCEL|VIRTUAL_TOUR|(?:^|_)URL(?:_|$)|TIMESTAMP|LATITUDE|LONGITUDE|LISTING_ID|MLS_ID|FSID|DOC_?BOX/i;

function cleanFactLabel(name = "") {
  return String(name)
    .replace(/\bYN\b$/i, "")
    .replace(/Bathrooms Total (?:Decimal|Integer)/i, "Bathrooms total")
    .replace(/Smart Home Features Appor Pass Y/i, "Smart home features approved")
    .replace(/\s+/g, " ").trim();
}

function amenityValue(item) {
  const values = Array.isArray(item?.values) ? item.values : [item?.values];
  return values.map((value) => scalar(value)).filter((value) => value && value !== "—").join(" · ");
}

function redfinFactPresentation(facts = {}) {
  const entries = [];
  const rooms = [];
  const seen = new Set();
  const add = (key, label, value) => {
    const rendered = scalar(value);
    const cleanLabel = cleanFactLabel(label);
    if (!cleanLabel || !rendered || rendered === "—") return;
    const signature = `${cleanLabel.toLowerCase()}\u0000${rendered.toLowerCase()}`;
    if (seen.has(signature)) return;
    seen.add(signature);
    entries.push([key, value, cleanLabel]);
  };

  const amenities = facts.amenities;
  if (amenities && typeof amenities === "object" && !Array.isArray(amenities)) {
    Object.entries(amenities).forEach(([category, sections]) => {
      if (!sections || typeof sections !== "object") return;
      Object.entries(sections).forEach(([section, items]) => {
        if (!Array.isArray(items)) return;
        if (/^Room \d+ Information$/i.test(section)) {
          const room = {};
          items.forEach((item) => {
            const name = String(item?.name || "");
            const value = amenityValue(item);
            if (/room type/i.test(name)) room.roomType = value;
            else if (/room level/i.test(name)) room.level = value;
            else if (/room dimensions/i.test(name)) room.roomDimensions = value;
            else if (/features/i.test(name)) room.features = value;
            else if (/room length/i.test(name)) room.length = value;
            else if (/room width/i.test(name)) room.width = value;
          });
          if (!room.roomDimensions && room.length && room.width) room.roomDimensions = `${room.length} x ${room.width}`;
          delete room.length; delete room.width;
          if (Object.values(room).some(Boolean)) rooms.push(room);
          return;
        }
        items.forEach((item, index) => {
          const reference = String(item?.reference_name || item?.name || index);
          if (REDFIN_MACHINE_FACT.test(reference) || REDFIN_MACHINE_FACT.test(String(item?.name || ""))) return;
          const value = amenityValue(item);
          add(`${category} ${section} ${reference}`, item?.name || reference, value);
        });
      });
    });

    const neighborhood = facts.neighborhood || {};
    add("Location neighborhood name", "Neighborhood", neighborhood.neighborhoodName);
    add("Location neighborhood overview", "Neighborhood overview", neighborhood.aiSummary);

    const scores = facts.location_score || {};
    const scoreLabels = {
      quietScore: "Quiet", pedestrianFriendlyScore: "Pedestrian friendly", transitFriendlyScore: "Transit friendly",
      cyclingFriendlyScore: "Cycling friendly", carFriendlyScore: "Car friendly", parksScore: "Parks",
      groceriesScore: "Groceries", restaurantsScore: "Restaurants", shoppingScore: "Shopping",
      greeneryScore: "Greenery", daycaresScore: "Daycares", primarySchoolsScore: "Primary schools",
      highSchoolsScore: "High schools",
    };
    Object.entries(scoreLabels).forEach(([key, label]) => {
      const value = Number(scores[key]);
      if (Number.isFinite(value)) add(`Location score ${key}`, label, `${value.toFixed(1)} / 10`);
    });

    const risks = facts.risk_factors || {};
    Object.values(risks).forEach((risk) => {
      if (!risk || typeof risk !== "object" || !risk.climateId) return;
      const title = risk.entryPointTitle?.value || `${humanize(risk.climateId)} factor`;
      const description = risk.entryPointDescription?.value || risk.scoreDescription?.value;
      add(`Climate factor ${risk.climateId}`, title, description);
    });

    const sun = facts.sun_exposure || {};
    const directSun = Number(sun.directSunlightAnnual);
    if (Number.isFinite(directSun)) add("Climate sunlight hours", "Average direct sunlight", `${directSun.toFixed(1)} hours/day`);
    const percentile = Number(sun.relativePercentile);
    if (Number.isFinite(percentile)) add("Climate sun exposure percentile", "Sun exposure percentile", `${Math.round(percentile)}th percentile`);

    const zoning = Array.isArray(facts.zoning) ? facts.zoning[0] : facts.zoning;
    if (zoning && typeof zoning === "object") {
      [["zoningCode", "Zoning code"], ["zoningCategory", "Zoning category"], ["zoningDescription", "Zoning description"],
        ["permittedUses", "Permitted uses"], ["frontSetbackFullDescription", "Front setback"], ["rearSetbackFullDescription", "Rear setback"],
        ["sideSetbackFullDescription", "Side setback"], ["maximumBuildingHeightFullDescription", "Maximum building height"],
        ["maximumSiteCoverageFullDescription", "Maximum site coverage"]].forEach(([key, label]) =>
        add(`Zoning ${key}`, label, zoning[key]));
    }
  } else {
    Object.entries(facts).filter(([key]) => key !== "rooms").forEach(([key, value]) => add(key, humanize(key), value));
  }
  return { entries, rooms };
}

function mediaKind(url, label = "") {
  const value = `${url} ${label}`.toLowerCase();
  if (/floor[_ -]?(map|plan|shape)|floorplan/.test(value)) return "floor_plan";
  if (/view-imx|view-3d-home|vrmodel|3d home|matterport/.test(value)) return "three_d";
  if (/\.mp4(?:\?|$)|video/.test(value)) return "video";
  if (/streetview|staticmap|maps\.google|map image/.test(value)) return "map";
  return "photo";
}

function normalizedMedia(fields) {
  const items = fields.media?.length ? fields.media : (fields.photo_urls || []).map((url, index) => ({
    url, kind: mediaKind(url), label: `Listing image ${index + 1}`,
  }));
  const seen = new Set();
  return items.filter((item) => {
    if (!item?.url || seen.has(item.url) || /logo|avatar|profile|favicon/i.test(`${item.url} ${item.label || ""}`)) return false;
    seen.add(item.url); return true;
  }).map((item) => ({ ...item, source_url: item.source_url || item.url, url: item.archived_url || item.url }));
}

function DataTable({ rows, preferred = [] }) {
  if (!rows?.length) return null;
  const columns = [...new Set([...preferred, ...rows.flatMap((row) => Object.keys(row || {}))])]
    .filter((key) => rows.some((row) => scalar(row?.[key]))).slice(0, 6);
  return (
    <div style={{ overflowX: "auto" }}>
      <table className="hs-data-table"><thead><tr>{columns.map((key) => <th key={key}>{humanize(key)}</th>)}</tr></thead>
        <tbody>{rows.slice(0, 40).map((row, index) => <tr key={index}>{columns.map((key) => <td key={key}>{formatTableValue(key, row?.[key])}</td>)}</tr>)}</tbody>
      </table>
    </div>
  );
}

function formatTableValue(key, value) {
  const number = Number(value);
  if (/^(date|time)$/i.test(key) && Number.isFinite(number) && number > 100000000000) {
    return new Date(number).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
  }
  if (/^(price|taxPaid|value)$/i.test(key) && Number.isFinite(number)) return money(number);
  if (/(increaseRate|priceChangeRate)$/i.test(key) && Number.isFinite(number)) return `${(number * 100).toFixed(1)}%`;
  return scalar(value);
}

function normalizedPriceHistory(rows = []) {
  return rows.map((item) => ({
    date: item.date ?? item.time ?? item.eventDate,
    event: item.event ?? item.eventDescription,
    price: item.price,
    priceChangeRate: item.priceChangeRate,
    source: item.source ?? item.dataSourceName,
  }));
}

function normalizedTaxHistory(rows = []) {
  return rows.map((item) => {
    const improvement = Number(item.taxableImprovementValue);
    const land = Number(item.taxableLandValue);
    const componentValue = (Number.isFinite(improvement) ? improvement : 0) + (Number.isFinite(land) ? land : 0);
    return {
      date: item.date ?? item.time ?? item.rollYear,
      taxPaid: item.taxPaid ?? item.taxesDue,
      value: item.value ?? item.taxAssessedValue ?? item.assessedValue ?? item.taxableValue
        ?? item.totalTaxableValue ?? (componentValue || undefined),
      taxIncreaseRate: item.taxIncreaseRate,
      valueIncreaseRate: item.valueIncreaseRate,
    };
  });
}

function normalizedSchools(rows = []) {
  return rows.map((item) => {
    const levels = [["elementary", "Elementary"], ["middle", "Middle"], ["high", "High"],
      ["isElementarySchool", "Elementary"], ["isMiddleSchool", "Middle"],
      ["isHighSchool", "High"]].filter(([key]) => item[key] === true).map(([, label]) => label)
      .filter((label, index, all) => all.indexOf(label) === index);
    return {
      name: item.name,
      rating: item.rating ?? item.greatSchoolsRating,
      distance: item.distance ?? item.distanceInMiles,
      level: item.level ?? item.schoolLevel ?? item.educationLevel ?? levels.join(", "),
      grades: item.grades ?? (Array.isArray(item.gradeRanges) ? item.gradeRanges.join(", ") : item.gradeRanges),
      type: item.type ?? item.institutionType,
    };
  });
}

function FactBlock({ title, entries }) {
  if (!entries.length) return null;
  return <section><div className="hs-dossier-subhead">{title}</div><div className="hs-fact-grid">
    {entries.map(([key, value, label]) => <div className="hs-fact" key={key}><div className="hs-fact-key">{label || humanize(key)}</div><div className="hs-fact-value">{scalar(value)}</div></div>)}
  </div></section>;
}

function ListingDossier({ fields, raw, compact = false, view = "all", onPhoto }) {
  if (!fields) return null;
  const media = normalizedMedia(fields);
  const photos = media.filter((item) => item.kind === "photo");
  const floorPlans = media.filter((item) => item.kind === "floor_plan");
  const richMedia = media.filter((item) => !["photo", "map", "floor_plan"].includes(item.kind));
  const archivedCount = photos.filter((item) => item.archive_status === "archived").length;
  const archiveFailures = photos.filter((item) => item.archive_status === "failed").length;
  const presentedFacts = redfinFactPresentation(fields.facts || {});
  const facts = presentedFacts.entries;
  const used = new Set();
  const grouped = FACT_GROUPS.map(([title, pattern]) => [title, facts.filter(([key, , label]) => {
    if (used.has(key) || !pattern.test(`${key} ${label || ""}`)) return false; used.add(key); return true;
  })]);
  grouped.push(["Other captured facts", facts.filter(([key]) => !used.has(key))]);
  const rooms = fields.facts?.rooms?.length ? fields.facts.rooms : presentedFacts.rooms;
  const details = Object.entries(fields.listing_details || {}).filter(([, value]) => scalar(value));
  const sections = Object.entries(fields.fact_sections || raw?.sections || {}).filter(([name]) =>
    /facts|features|interior|kitchen|bedroom|living|property|construction|utilities|community|financial|price history|public tax|school|special/i.test(name));
  const show = (name) => view === "all" || view === name;
  return <div className="hs-dossier">
    {show("overview") && <div className="hs-dossier-summary">
      {[[fields.price ? money(fields.price) : "", "Asking"], [fields.bedrooms, "Beds"], [fields.bathrooms, "Baths"],
        [fields.living_area ? Number(fields.living_area).toLocaleString() : "", "Square feet"],
        [fields.lot_sqft ? Number(fields.lot_sqft).toLocaleString() : "", "Lot sq ft"], [fields.year_built, "Year built"]]
        .filter(([value]) => value !== "" && value != null).map(([value, label]) => <div key={label}><div className="hs-dossier-value">{value}</div><div className="hs-dossier-label">{label}</div></div>)}
    </div>}
    {show("gallery") && photos.length > 0 && <section><div className="hs-dossier-subhead">Photos <span className="hs-note">({photos.length} captured{archivedCount ? ` · ${archivedCount} archived in Homestead` : ""}{archiveFailures ? ` · ${archiveFailures} archive failures` : ""})</span></div>
      <div className="hs-media-grid">{photos.slice(0, compact ? 6 : 18).map((item, index) => <figure className="hs-media-card" key={item.url}>
        {onPhoto ? <button type="button" onClick={() => onPhoto(index)} style={{ border: 0, padding: 0, width: "100%", cursor: "zoom-in" }}><img src={item.url} alt={item.label || `Listing photo ${index + 1}`} loading="lazy" /></button>
          : <a href={item.url} target="_blank" rel="noreferrer"><img src={item.url} alt={item.label || `Listing photo ${index + 1}`} loading="lazy" /></a>}
        <figcaption>{item.label || `Listing photo ${index + 1}`}</figcaption></figure>)}</div>
      {photos.length > (compact ? 6 : 18) && <div className="hs-note" style={{ marginTop: 7 }}>{photos.length - (compact ? 6 : 18)} additional photo URLs are preserved in this capture.</div>}
    </section>}
    {show("gallery") && floorPlans.map((item, index) => <section key={item.url}><div className="hs-dossier-subhead">Floor plan</div>
      <figure className="hs-floorplan-card">
        {onPhoto ? <button type="button" onClick={() => onPhoto(photos.length + index)} aria-label="Enlarge floor plan"><img src={item.url} alt={item.label || "Floor plan"} /></button>
          : <img src={item.url} alt={item.label || "Floor plan"} />}
        <figcaption>Floor plan{item.archive_status === "archived" ? " · saved in Homestead" : ""}</figcaption>
      </figure>
    </section>)}
    {show("gallery") && richMedia.length > 0 && <section><div className="hs-dossier-subhead">3D & video</div><div className="hs-dossier-links">
      {richMedia.map((item, index) => <a className="hs-btn ghost small" href={item.url} target="_blank" rel="noreferrer" key={item.url}>{item.kind === "three_d" ? "Open 3D tour" : "Open video"}{richMedia.length > 1 ? ` ${index + 1}` : ""}</a>)}
    </div></section>}
    {show("overview") && fields.description && <section><div className="hs-dossier-subhead">Listing description</div><div className="hs-dossier-description">{fields.description}</div></section>}
    {show("overview") && <FactBlock title="At a glance" entries={details} />}
    {!compact && show("facts") && grouped.map(([title, entries]) => <FactBlock title={title} entries={entries} key={title} />)}
    {!compact && show("facts") && rooms.length > 0 && <section><div className="hs-dossier-subhead">Rooms & dimensions</div><DataTable rows={rooms} preferred={["roomType", "roomDimensions", "level", "features"]} /></section>}
    {show("history") && fields.price_history?.length > 0 && <section><div className="hs-dossier-subhead">Price history</div><DataTable rows={normalizedPriceHistory(fields.price_history)} preferred={["date", "event", "price", "priceChangeRate", "source"]} /></section>}
    {show("history") && fields.tax_history?.length > 0 && <section><div className="hs-dossier-subhead">Public tax history</div><DataTable rows={normalizedTaxHistory(fields.tax_history)} preferred={["date", "taxPaid", "value", "taxIncreaseRate", "valueIncreaseRate"]} /></section>}
    {show("facts") && fields.schools?.length > 0 && <section><div className="hs-dossier-subhead">Schools</div><DataTable rows={normalizedSchools(fields.schools)} preferred={["name", "rating", "distance", "level", "grades", "type"]} /></section>}
    {!compact && show("facts") && Object.keys(fields.attribution_details || {}).length > 0 && <FactBlock title="Listing attribution" entries={Object.entries(fields.attribution_details).filter(([, value]) => scalar(value))} />}
    {!compact && show("source") && sections.slice(0, 12).map(([name, text]) => <details key={name}><summary>Source section: {name}</summary><div className="hs-note" style={{ marginTop: 7 }}>{text}</div></details>)}
  </div>;
}

function FilingActivity({ mediaCount }) {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const started = Date.now();
    const timer = window.setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => window.clearInterval(timer);
  }, []);
  const elapsedLabel = elapsed < 60
    ? `${elapsed}s`
    : `${Math.floor(elapsed / 60)}m ${String(elapsed % 60).padStart(2, "0")}s`;
  const mediaLabel = `${mediaCount} captured media reference${mediaCount === 1 ? "" : "s"}`;
  return <div className="hs-filing-activity">
    <div className="hs-filing-head">
      <div className="hs-filing-title" role="status" aria-live="polite">Filing capture</div>
      <div className="hs-filing-time" aria-hidden="true">{elapsedLabel}</div>
    </div>
    <div className="hs-filing-rail" role="progressbar" aria-label="Filing capture" aria-valuetext="Homestead is still working" />
    <div className="hs-filing-copy">Preserving the source and checking {mediaLabel}.</div>
    <div className="hs-filing-note">Keep this page open; Homestead is still working.</div>
  </div>;
}

function ListingImport({ capture, saving, error, onSave, onCancel }) {
  const [fields, setFields] = useState({ ...capture.fields });
  const d = (key) => (value) => setFields((current) => ({ ...current, [key]: value }));
  const mediaCount = normalizedMedia(fields).length;
  const counts = [
    `${Object.keys(fields.facts || {}).length || fields.features?.length || 0} fact groups`,
    `${normalizedMedia(fields).filter((item) => item.kind === "photo").length} photos`,
    `${fields.price_history?.length || 0} price events`,
    `${fields.tax_history?.length || 0} tax events`,
    `${fields.schools?.length || 0} schools`,
  ];
  return (
    <div className="hs-panel" style={{ marginBottom: 18, borderColor: "var(--county-teal)" }}>
      <div className="hs-learn-kicker">Extension capture · review before filing</div>
      <div className="hs-record-title" style={{ marginTop: 7 }}>{fields.source} listing</div>
      <div className="hs-note" style={{ margin: "5px 0 14px" }}>{counts.join(" · ")}</div>
      <ListingDossier fields={fields} raw={capture.raw} />
      <details open><summary>Edit core property fields before saving</summary><div className="hs-grid hs-g2" style={{ marginTop: 12 }}>
        <Field label="Address" type="text" value={fields.address} onChange={d("address")} />
        <Field label="City" type="text" value={fields.city} onChange={d("city")} />
        <Field label="State" type="text" value={fields.state} onChange={d("state")} />
        <Field label="ZIP" type="text" value={fields.postal_code} onChange={d("postal_code")} />
        <Field label="Asking price" value={fields.price} onChange={d("price")} />
        <Field label="Square feet" value={fields.living_area} onChange={d("living_area")} />
        <Field label="Beds" value={fields.bedrooms} onChange={d("bedrooms")} />
        <Field label="Baths" value={fields.bathrooms} onChange={d("bathrooms")} />
        <Field label="Lot (sq ft)" value={fields.lot_sqft} onChange={d("lot_sqft")} />
        <Field label="Year built" value={fields.year_built} onChange={d("year_built")} />
        <Field label="HOA per month" value={fields.hoa_monthly} onChange={d("hoa_monthly")} />
        <Field label="MLS ID" type="text" value={fields.mls_id} onChange={d("mls_id")} />
      </div>
      <label className="hs-field" style={{ marginTop: 10 }}>
        <span className="hs-field-lab">Listing description</span>
        <textarea className="hs-in" rows={4} value={fields.description || ""} onChange={(event) => d("description")(event.target.value)} />
      </label></details>
      {error && <div className="hs-flag" style={{ marginTop: 10 }}>{error}</div>}
      <div className="hs-row" style={{ marginTop: 14 }}>
        <button className="hs-btn" disabled={saving || !String(fields.address || "").trim()} onClick={() => onSave({ ...capture, fields })}>
          {saving ? "Filing capture…" : "Save listing to Homestead"}
        </button>
        <button className="hs-btn ghost" disabled={saving} onClick={onCancel}>Cancel</button>
        {saving && <FilingActivity mediaCount={mediaCount} />}
      </div>
    </div>
  );
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
}

function PropertiesMap({ records, onSelect }) {
  const node = useRef(null);
  useEffect(() => {
    const points = records.map((record) => ({ record, lat: Number(record.fields?.latitude), lng: Number(record.fields?.longitude) }))
      .filter((point) => Number.isFinite(point.lat) && Number.isFinite(point.lng));
    if (!node.current) return;
    const map = L.map(node.current, { scrollWheelZoom: false, zoomControl: true }).setView([32.90, -96.90], 9);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(map);
    const icon = L.divIcon({ className: "", html: '<div class="hs-map-pin"></div>', iconSize: [25, 25], iconAnchor: [12, 24] });
    points.forEach(({ record, lat, lng }) => {
      const fields = record.fields || {};
      const photo = normalizedMedia(fields).find((item) => item.kind === "photo");
      const image = photo ? `<img src="${escapeHtml(photo.url)}" alt="">` : "";
      const popup = `<div class="hs-map-popup">${image}<strong>${escapeHtml(fields.address)}</strong><br>${escapeHtml([fields.city, fields.state].filter(Boolean).join(", "))}<br>${fields.price ? escapeHtml(money(fields.price)) : ""}</div>`;
      const marker = L.marker([lat, lng], { icon }).addTo(map).bindPopup(popup);
      marker.on("click", () => onSelect(record.listing_id));
    });
    if (points.length === 1) map.setView([points[0].lat, points[0].lng], 13);
    if (points.length > 1) map.fitBounds(points.map((point) => [point.lat, point.lng]), { padding: [35, 35], maxZoom: 13 });
    setTimeout(() => map.invalidateSize(), 0);
    return () => map.remove();
  }, [records, onSelect]);
  return <div ref={node} className="hs-map" aria-label="Map of captured properties" />;
}

function PhotoLightbox({ photos, index, onClose, onChange }) {
  useEffect(() => {
    const key = (event) => {
      if (event.key === "Escape") onClose();
      if (event.key === "ArrowLeft") onChange((index - 1 + photos.length) % photos.length);
      if (event.key === "ArrowRight") onChange((index + 1) % photos.length);
    };
    window.addEventListener("keydown", key); return () => window.removeEventListener("keydown", key);
  }, [index, photos.length, onClose, onChange]);
  const photo = photos[index];
  if (!photo) return null;
  const description = photo.kind === "floor_plan" ? "Floor plan" : photo.label || `Listing photo ${index + 1}`;
  return <div className="hs-lightbox" role="dialog" aria-modal="true" aria-label="Property media viewer">
    <button className="hs-lightbox-close" onClick={onClose} aria-label="Close photo viewer">×</button>
    <button onClick={() => onChange((index - 1 + photos.length) % photos.length)} aria-label="Previous photo">‹</button>
    <div className="hs-lightbox-stage"><img src={photo.url} alt={description} />
      <div className="hs-lightbox-caption">{index + 1} of {photos.length} · {description}</div></div>
    <button onClick={() => onChange((index + 1) % photos.length)} aria-label="Next photo">›</button>
  </div>;
}

function PropertyModal({ property, listing, onClose }) {
  const [view, setView] = useState("overview");
  const [photoIndex, setPhotoIndex] = useState(null);
  const fields = listing.fields || {};
  const photos = normalizedMedia(fields).filter((item) => item.kind === "photo");
  const galleryItems = normalizedMedia(fields).filter((item) => item.kind === "photo" || item.kind === "floor_plan");
  useEffect(() => {
    const key = (event) => event.key === "Escape" && photoIndex === null && onClose();
    window.addEventListener("keydown", key); return () => window.removeEventListener("keydown", key);
  }, [onClose, photoIndex]);
  return <div className="hs-modal-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
    <article className="hs-property-modal" role="dialog" aria-modal="true" aria-label={`${fields.address} property details`}>
      <header className="hs-modal-head"><div className="hs-modal-title-row"><div>
        <div className="hs-property-title">{fields.address}</div>
        <div className="hs-prop-meta">{[fields.city, fields.state, fields.postal_code].filter(Boolean).join(", ")}</div>
      </div><button className="hs-btn ghost" onClick={onClose}>Close</button></div>
      <nav className="hs-modal-tabs" aria-label="Property sections">{[
        ["overview", "Overview"], ["gallery", `Photos & floor plan (${galleryItems.length})`], ["facts", "Facts & rooms"],
        ["history", "Price & tax history"], ["source", "Source evidence"],
      ].map(([id, label]) => <button className="hs-modal-tab" aria-selected={view === id} onClick={() => setView(id)} key={id}>{label}</button>)}</nav></header>
      <div className="hs-modal-body"><ListingDossier fields={fields} view={view} onPhoto={setPhotoIndex} />
        {property?.sourceUrl && <a className="hs-link" href={property.sourceUrl} target="_blank" rel="noreferrer">Open original {property.source || "source"} listing</a>}
      </div>
    </article>
    {photoIndex !== null && <PhotoLightbox photos={galleryItems} index={photoIndex} onClose={() => setPhotoIndex(null)} onChange={setPhotoIndex} />}
  </div>;
}

function Properties({ state, persist, listingRecords, listingErr }) {
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState(BLANK);
  const [selectedListingId, setSelectedListingId] = useState(null);
  const selectListing = useCallback((listingId) => setSelectedListingId(listingId), []);
  const selectedListing = listingRecords.find((item) => item.listing_id === selectedListingId);
  const selectedProperty = state.properties.find((item) => item.listingId === selectedListingId);

  const save = () => {
    if (!draft.address.trim()) return;
    persist({
      ...state,
      properties: [{ ...draft, id: "p" + Date.now() }, ...state.properties],
    });
    setDraft(BLANK);
    setAdding(false);
  };

  const remove = (id) =>
    persist({ ...state, properties: state.properties.filter((p) => p.id !== id) });

  const setStatus = (id, status) =>
    persist({
      ...state,
      properties: state.properties.map((p) => (p.id === id ? { ...p, status } : p)),
    });

  const d = (k) => (v) => setDraft({ ...draft, [k]: v });

  return (
    <>
      <h2 className="hs-h">Properties</h2>

      <div className="hs-note" style={{ marginBottom: 13 }}>
        Add manually, or use the Homestead Chrome extension while viewing a Zillow or Redfin listing.
        Each extension capture is preserved as a source generation before its core facts enter this record.
      </div>

      {listingErr && <div className="hs-flag" style={{ marginBottom: 13 }}>Captured listing details are temporarily unavailable.</div>}

      {!adding && (
        <button className="hs-btn" onClick={() => setAdding(true)}>Add a property</button>
      )}

      {adding && (
        <div className="hs-panel">
          <div className="hs-grid hs-g2">
            <Field label="Address" type="text" value={draft.address} onChange={d("address")} placeholder="123 Example St" />
            <Field label="City" type="text" value={draft.city} onChange={d("city")} placeholder="Rockwall" />
            <Field label="Asking price" value={draft.price} onChange={d("price")} />
            <Field label="Square feet" value={draft.sqft} onChange={d("sqft")} />
            <Field label="Beds" value={draft.beds} onChange={d("beds")} />
            <Field label="Baths" value={draft.baths} onChange={d("baths")} />
            <Field label="Lot (acres)" value={draft.lotAcres} onChange={d("lotAcres")} />
            <Field label="Year built" value={draft.yearBuilt} onChange={d("yearBuilt")} />
            <Field label="HOA per month" value={draft.hoaMonthly} onChange={d("hoaMonthly")} />
            <Field label="Tax rate %" value={draft.taxRatePct} onChange={d("taxRatePct")} />
            <Select label="Build" value={draft.buildType} onChange={d("buildType")}
              options={[["resale", "Resale"], ["newbuild", "New build"]]} />
            <Select label="MUD / PID" value={draft.district} onChange={d("district")}
              options={[["unknown", "Not confirmed"], ["none", "Neither"], ["mud", "MUD"], ["pid", "PID"], ["both", "Both"]]} />
            <Select label="Fenced yard" value={draft.fencedYard} onChange={d("fencedYard")}
              options={[["unknown", "Not confirmed"], ["yes", "Yes"], ["no", "No"]]} />
            <Select label="Status" value={draft.status} onChange={d("status")}
              options={STATUSES.map((s) => [s, s[0].toUpperCase() + s.slice(1)])} />
          </div>
          <div style={{ marginTop: 12 }}>
            <label className="hs-field">
              <span className="hs-field-lab">Notes</span>
              <textarea className="hs-in" rows={2} value={draft.notes}
                onChange={(e) => setDraft({ ...draft, notes: e.target.value })} />
            </label>
          </div>
          <div className="hs-row" style={{ marginTop: 14 }}>
            <button className="hs-btn" onClick={save}>Save property</button>
            <button className="hs-btn ghost" onClick={() => { setAdding(false); setDraft(BLANK); }}>Cancel</button>
          </div>
        </div>
      )}

      <div className="hs-sp" />

      {state.properties.length === 0 && !adding && (
        <div className="hs-panel">
          <div className="hs-empty">
            <div className="hs-empty-t">No properties yet</div>
            Add the first house you tour. Log it the same day — the details blur fast.
          </div>
        </div>
      )}

      {listingRecords.some((record) => Number.isFinite(Number(record.fields?.latitude)) && Number.isFinite(Number(record.fields?.longitude))) && <>
        <h2 className="hs-h">Captured properties map</h2>
        <PropertiesMap records={listingRecords} onSelect={selectListing} />
      </>}

      <h2 className="hs-h">Property files</h2>
      <div className="hs-property-list">
        {state.properties.map((p) => {
          const flags = flagsFor(p);
          const listing = p.listingId ? listingRecords.find((item) => item.listing_id === p.listingId) : null;
          const cover = listing?.fields ? normalizedMedia(listing.fields).find((item) => item.kind === "photo") : null;
          const photos = listing?.fields ? normalizedMedia(listing.fields).filter((item) => item.kind === "photo") : [];
          const archived = photos.filter((item) => item.archive_status === "archived").length;
          const ppsf = Number(p.price) && Number(p.sqft) ? Number(p.price) / Number(p.sqft) : 0;
          const monthlyTax = Number(p.price) && Number(p.taxRatePct)
            ? (Number(p.price) * Number(p.taxRatePct)) / 100 / 12 : 0;
          return (
            <article key={p.id} className="hs-panel hs-property-card">
              <button className="hs-property-cover" type="button" onClick={() => listing && selectListing(listing.listing_id)} aria-label={`Open ${p.address}`}>
                {cover ? <img src={cover.url} alt={`Front of ${p.address}`} /> : <span className="hs-property-cover-empty">No captured photo</span>}
                {photos.length > 0 && <span className="hs-photo-count">{photos.length} photos</span>}
              </button>
              <div className="hs-property-body">
                <div className="hs-prop-hd">
                <div>
                  <div className="hs-property-title">{p.address}</div>
                  <div className="hs-prop-meta">
                    {[p.city, p.beds && p.beds + " bd", p.baths && p.baths + " ba",
                      p.sqft && Number(p.sqft).toLocaleString() + " sf",
                      p.lotAcres && p.lotAcres + " ac", p.yearBuilt].filter(Boolean).join(" · ")}
                  </div>
                </div>
                <span className={"hs-status" + (p.status === "under contract" ? " live" : "")}>{p.status}</span>
              </div>

              {p.price && <div className="hs-property-price">{money(p.price)}</div>}
              <div className="hs-property-quick">
                {ppsf ? <span>${ppsf.toFixed(0)} / sq ft</span> : null}
                {monthlyTax ? <span>{money(monthlyTax)} tax / mo</span> : null}
                {p.hoaMonthly ? <span>{money(p.hoaMonthly)} HOA / mo</span> : null}
              </div>

              {p.notes && <div className="hs-note" style={{ marginTop: 12 }}>{p.notes}</div>}

              {listing && <div className="hs-capture-meta">{listing.snapshot_count} capture{listing.snapshot_count === 1 ? "" : "s"} · {photos.length} normalized photos{archived ? ` · ${archived} saved in Homestead` : ""} · updated {listing.updated_at.slice(0, 10)}</div>}

              {flags.length > 0 && (
                <div className="hs-flags">
                  {flags.map((f, i) => <div key={i} className="hs-flag">{f}</div>)}
                </div>
              )}

              <div className="hs-row" style={{ marginTop: 14 }}>
                {listing && <button className="hs-btn" onClick={() => selectListing(listing.listing_id)}>Open property</button>}
                {p.sourceUrl && <a className="hs-btn ghost" href={p.sourceUrl} target="_blank" rel="noreferrer">Original listing</a>}
                <select className="hs-sel" style={{ width: "auto", flex: 1 }}
                  value={p.status} onChange={(e) => setStatus(p.id, e.target.value)}>
                  {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
                <button className="hs-btn ghost" onClick={() => remove(p.id)}>Remove</button>
              </div>
              </div>
            </article>
          );
        })}
      </div>
      {selectedListing && <PropertyModal property={selectedProperty} listing={selectedListing} onClose={() => setSelectedListingId(null)} />}
    </>
  );
}

/* ---------------- tasks ---------------- */

function Tasks({ state, persist }) {
  const [newText, setNewText] = useState("");
  const [newPhase, setNewPhase] = useState("prepare");

  const toggle = (id) =>
    persist({
      ...state,
      items: state.items.map((t) => (t.id === id ? { ...t, done: !t.done } : t)),
    });

  const add = () => {
    if (!newText.trim()) return;
    persist({
      ...state,
      items: [...state.items, {
        id: "t" + Date.now(), type: "task", phase: newPhase, title: newText.trim(),
        detail: "", dueDate: "", done: false, createdAt: new Date().toISOString(),
      }],
    });
    setNewText("");
  };

  return (
    <>
      <h2 className="hs-h">Add a task</h2>
      <div className="hs-panel">
        <div className="hs-row">
          <input className="hs-in" style={{ flex: 3, minWidth: 200 }} value={newText}
            placeholder="What needs doing?" onChange={(e) => setNewText(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && add()} />
          <select className="hs-sel" style={{ flex: 1, minWidth: 150 }} value={newPhase}
            onChange={(e) => setNewPhase(e.target.value)}>
            {PHASES.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
          <button className="hs-btn" onClick={add}>Add</button>
        </div>
      </div>

      <div className="hs-sp" />

      {PHASES.map((ph) => {
        const items = state.items.filter((t) => t.type === "task" && t.phase === ph.id);
        const briefs = BRIEFS.filter((b) => b.phase === ph.id);
        if (items.length === 0 && briefs.length === 0) return null;
        const done = items.filter((t) => t.done).length;
        return (
          <div key={ph.id} className="hs-phase">
            <div className="hs-phase-hd">
              <div className="hs-phase-name">{ph.name}</div>
              <div className="hs-phase-when">{done}/{items.length} · {ph.when}</div>
            </div>

            {briefs.length > 0 && (
              <>
                <div className="hs-panel" style={{ marginBottom: 12 }}>
                  <div className="hs-lab" style={{ marginTop: 0, marginBottom: 14 }}>
                    Before you sign anything in this phase
                  </div>
                  {briefs.map((b) => (
                    <div key={b.code + b.t} className="hs-brief">
                      <div className="hs-brief-hd">
                        <span className="hs-brief-code">{b.code}</span>
                        <span className="hs-brief-t">{b.t}</span>
                      </div>
                      <div className="hs-brief-b">{b.b}</div>
                      <div className="hs-brief-do">{b.do}</div>
                      <div className="hs-tagrow">
                        {b.gap && <span className="hs-tag gap">No book covers this</span>}
                        {b.thin && <span className="hs-tag gap">Barely covered</span>}
                        <span className="hs-tag">{b.code.startsWith("40-11") ? "Financing addendum" : "Contract"}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </>
            )}

            {items.length > 0 && (
              <div className="hs-panel">
                {items.map((t) => (
                  <div key={t.id} className={"hs-task" + (t.done ? " done" : "")}>
                    <button className="hs-check" role="checkbox" aria-checked={t.done}
                      aria-label={t.title} onClick={() => toggle(t.id)} />
                    <div className="hs-task-txt">
                      {t.title}
                      {t.detail && !t.done && <div className="hs-note">{t.detail}</div>}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </>
  );
}

/* ---------------- money ---------------- */

function Money({ state, persist, finance: FINANCE }) {
  const m = state.money || { price: 375000, rate: 6.5, taxRate: 2.2, insurance: 2500 };
  const set = (k, v) => persist({ ...state, money: { ...m, [k]: Number(v) || 0 } });

  const down = FINANCE.goalTarget;
  const loan = Math.max(0, m.price - down);
  const r = m.rate / 100 / 12;
  const n = 360;
  const pi = r > 0 ? (loan * r * Math.pow(1 + r, n)) / (Math.pow(1 + r, n) - 1) : loan / n;
  const tax = (m.price * (m.taxRate / 100)) / 12;
  const ins = m.insurance / 12;
  const piti = pi + tax + ins;
  const nowCost = 750;
  const shock = piti - nowCost;
  const ccLow = m.price * 0.02, ccHigh = m.price * 0.05;
  // Cash that will still be there AFTER the down payment is spent. Today's total
  // cash minus today's goal balance is the part not earmarked for the down
  // payment; that is what carries through to closing. Subtracting a future
  // $75,000 from today's cash would be comparing two different points in time.
  const nonGoalCash = FINANCE.cash - FINANCE.goalCurrent;
  const cashAfter = nonGoalCash;
  const reserveGap = ccLow - cashAfter;
  const downPct = (down / m.price) * 100;

  const max = Math.max(...FINANCE.savings.map((s) => s[1]), FINANCE.goalTarget);

  return (
    <>
      <h2 className="hs-h">Getting to the down payment</h2>
      <div className="hs-panel">
        <div className="hs-note" style={{ marginTop: 0 }}>
          Actual balances, not projections — {FINANCE.savings.length} months of the REDACTED account
          as Monarch recorded it. The dashed line is the {money(FINANCE.goalTarget)} target.
        </div>
        <div style={{ position: "relative", marginTop: 18, paddingBottom: 18 }}>
          <div style={{ display: "flex", alignItems: "flex-end", gap: 6, height: 124 }}>
            {FINANCE.savings.map(([label, v]) => (
              <div key={label} style={{ flex: 1, textAlign: "center" }}>
                <div style={{
                  height: Math.round((v / max) * 104), background: "var(--bluestem)",
                  borderRadius: "2px 2px 0 0", minHeight: 2,
                }} />
                <div className="hs-spec-l" style={{ marginTop: 5 }}>{label}</div>
              </div>
            ))}
          </div>
          {/* target line, positioned proportionally rather than at a fixed offset */}
          <div style={{
            position: "absolute", left: 0, right: 0,
            bottom: 18 + 20 + Math.round((FINANCE.goalTarget / max) * 104),
            borderTop: "1px dashed var(--mesquite)", pointerEvents: "none",
          }}>
            <span className="hs-spec-l" style={{ color: "var(--mesquite)", position: "absolute", right: 0, top: -14 }}>
              {money(FINANCE.goalTarget)} target
            </span>
          </div>
        </div>

        <div className="hs-grid hs-g4" style={{ marginTop: 8 }}>
          <Cell v={money2(FINANCE.steadyMonthly)} l="actual monthly rate" accent />
          <Cell v={FINANCE.projectedHit} l="hits target" accent />
          <Cell v={money(FINANCE.goalTarget - FINANCE.goalCurrent)} l="left to save" />
          <Cell v={money(FINANCE.cash)} l="total cash" />
        </div>
        <div className="hs-note" style={{ marginTop: 14 }}>
          The real rate is {money2(FINANCE.steadyMonthly)} a month — well above the {money(5500)} budgeted —
          which lands the target around <strong style={{ color: "var(--bluestem)" }}>{FINANCE.projectedHit}</strong>,
          roughly a month early. <strong>Saving is not this project's risk.</strong>
        </div>
      </div>

      <h2 className="hs-h">What a house actually costs you per month</h2>
      <div className="hs-panel">
        <div className="hs-grid hs-g4">
          <Field label="Price" value={m.price} onChange={(v) => set("price", v)} />
          <Field label="Rate %" value={m.rate} onChange={(v) => set("rate", v)} />
          <Field label="Tax rate %" value={m.taxRate} onChange={(v) => set("taxRate", v)} />
          <Field label="Insurance /yr" value={m.insurance} onChange={(v) => set("insurance", v)} />
        </div>

        <div className="hs-grid hs-g4" style={{ marginTop: 16 }}>
          <Cell v={money2(pi)} l="principal + interest" />
          <Cell v={money2(tax)} l="property tax" />
          <Cell v={money2(ins)} l="insurance" />
          <Cell v={money2(piti)} l="total monthly" accent />
        </div>

        <div className="hs-sp" />
        <div className="hs-brief">
          <div className="hs-brief-hd">
            <span className="hs-brief-code">PAYMENT SHOCK</span>
            <span className="hs-brief-t">
              {money2(nowCost)} today → {money2(piti)} a month
            </span>
          </div>
          <div className="hs-brief-b">
            That is <strong style={{ color: "var(--mesquite)" }}>{money2(shock)} more per month</strong> than
            you pay for housing now, which is {money(nowCost)} across the household. The
            separation that funds this purchase is also what makes your current housing cost unusually low —
            so the jump at closing is larger than it would be for most buyers. You currently put{" "}
            {money2(FINANCE.steadyMonthly)} a month into savings; this payment consumes{" "}
            {Math.round((shock / FINANCE.steadyMonthly) * 100)}% of that.
          </div>
          <div className="hs-brief-do">
            Live on the new number before you commit to it. Move {money2(shock)} a month into savings for
            two months and see whether it pinches.
          </div>
          <div className="hs-tagrow">
            <span className="hs-tag gap">Rate, tax rate and insurance are assumptions — not quotes</span>
          </div>
        </div>
      </div>

      <h2 className="hs-h">What actually comes in and goes out</h2>
      <div className="hs-panel">
        <div className="hs-grid hs-g4">
          <Cell v={money2(FINANCE.flow.monthlyIncome)} l="income / month" accent />
          <Cell v={money2(FINANCE.flow.monthlyExpenses)} l="spending / month" />
          <Cell v={money2(FINANCE.flow.monthlySurplus)} l="surplus / month" accent />
          <Cell v={FINANCE.flow.savingsRate + "%"} l="savings rate" accent />
        </div>
        <div className="hs-note" style={{ marginTop: 14 }}>
          {FINANCE.flow.periodLabel} — {FINANCE.flow.transactionCount.toLocaleString()} transactions over {FINANCE.flow.months} months. A{" "}
          {FINANCE.flow.savingsRate}% savings rate is extraordinary, and it is what makes the payment above
          absorbable: {money2(piti)} against {money2(FINANCE.flow.monthlySurplus)} of surplus leaves{" "}
          {money2(FINANCE.flow.monthlySurplus - shock)} still free every month, since {money2(nowCost)} of
          rent goes away.
        </div>

        <div className="hs-brief" style={{ marginTop: 18 }}>
          <div className="hs-brief-hd">
            <span className="hs-brief-code">QUALIFYING</span>
            <span className="hs-brief-t">
              {FINANCE.flow.nonW2Pct}% of income may not count toward the loan
            </span>
          </div>
          <div className="hs-brief-b">
            {money2(FINANCE.flow.w2Monthly)}/mo arrives as W-2 paychecks — lenders count that immediately.
            The other {money2(FINANCE.flow.nonW2Monthly)}/mo is self-employment and other non-W-2 income,
            and underwriting generally requires <strong>two years of documented tax returns</strong> before
            it counts at all. It is real money that already funds this purchase; it may still be invisible
            to the loan.
          </div>
          <div className="hs-brief-do">
            Gather two years of returns and Schedule Cs before the first lender conversation. If the history
            is not there yet, plan the price around the W-2 figure alone.
          </div>
          <div className="hs-tagrow">
            <span className="hs-tag gap">Deposited amounts, not gross pay — a lender's DTI uses gross</span>
          </div>
        </div>

        <div className="hs-sp" />
        <div className="hs-lab" style={{ marginTop: 0 }}>Where it goes — 2026 to date</div>
        {FINANCE.flow.topExpenses.map(([cat, amt]) => (
          <div key={cat} className="hs-task" style={{ paddingTop: 7, paddingBottom: 7 }}>
            <div className="hs-task-txt" style={{ fontSize: 13.5 }}>{cat}</div>
            <div className="hs-phase-when">{money2(amt / FINANCE.flow.months)}/mo</div>
          </div>
        ))}
        <div className="hs-note" style={{ marginTop: 10 }}>
          Rent is the line that disappears at closing. Everything else stays — and a house adds
          maintenance, higher utilities, and lawn care that a shared rental never charged you for.
        </div>
      </div>

      <h2 className="hs-h">Why a lender will offer you too much</h2>
      <div className="hs-panel">
        <div className="hs-grid hs-g4">
          <Cell v={money2(FINANCE.installmentDebt)} l="installment debt / month"
            warn={FINANCE.installmentDebt > 0} />
          <Cell v={FINANCE.utilization.toFixed(2) + "%"} l="credit utilization" accent />
          <Cell v={money(FINANCE.liabilities)} l="total debt" accent />
          <Cell v={money(FINANCE.netWorth)} l="net worth" />
        </div>
        <div className="hs-brief" style={{ marginTop: 18 }}>
          <div className="hs-brief-hd">
            <span className="hs-brief-code">ADVERSARIAL</span>
            <span className="hs-brief-t">A clean file is leverage, not permission</span>
          </div>
          <div className="hs-brief-b">
            Both cars are owned outright and utilization is under 1% across {money(FINANCE.creditLimit)} of
            limits. Debt-to-income is almost entirely unused, so underwriting will approve a number far
            above {money(m.price)}. <strong>That number is what the lender is willing to risk, not what you
            can live on.</strong> The approval letter is a ceiling to negotiate under, never a target.
          </div>
          <div className="hs-brief-do">
            Decide your price ceiling from the monthly figure above, before you talk to a lender. Then treat
            any approval above it as irrelevant.
          </div>
        </div>

        {FINANCE.installmentDebt > 0 && (
        <div className="hs-brief">
          <div className="hs-brief-hd">
            <span className="hs-brief-code">HIDDEN DEBT</span>
            <span className="hs-brief-t">
              {money2(FINANCE.installmentDebt)}/mo of installment debt Monarch does not show as a loan
            </span>
          </div>
          <div className="hs-brief-b">
            {FINANCE.installmentDebtItems.map((d) => (
              <div key={d.label}>
                <strong>{d.label}</strong> — {money2(d.amount)}/month, filed by Monarch under
                “{d.filedAs}”. It is an installment loan with a balance and a term, but it is not linked
                as a loan account, so it appears in <em>neither</em> your account list nor your net worth.
                <strong> It is on your credit report and it counts toward debt-to-income.</strong>
              </div>
            ))}
          </div>
          <div className="hs-brief-do">
            Pay it off before applying, or expect it in the DTI calculation. Either way, know it exists
            before a lender tells you it does.
          </div>
          <div className="hs-tagrow">
            <span className="hs-tag gap">Found by recurrence detection, not by the account list</span>
          </div>
        </div>
        )}
      </div>

      <h2 className="hs-h">The part that is not funded</h2>
      <div className="hs-panel">
        <div className="hs-grid hs-g4">
          <Cell v={money(down)} l="down payment" />
          <Cell v={downPct.toFixed(1) + "%"} l={downPct >= 20 ? "of price — no PMI" : "of price — PMI"}
            warn={downPct < 20} />
          <Cell v={money(ccLow) + "–" + money(ccHigh)} l="closing costs" warn />
          <Cell v={money(cashAfter)} l="cash not earmarked for the down payment" warn={cashAfter < ccHigh} />
        </div>
        <div className="hs-note" style={{ marginTop: 14 }}>
          {cashAfter < ccLow ? (
            <>
              <strong style={{ color: "var(--mesquite)" }}>Closing costs are not covered.</strong> The{" "}
              {money(down)} goal is spoken for. Everything else — checking plus the unallocated part of
              savings — comes to {money(cashAfter)}, against {money(ccLow)}–{money(ccHigh)} of closing
              costs. That is short by {money(reserveGap)} at best, and{" "}
              {money(ccHigh - cashAfter)} at worst, before a single repair, appliance or moving truck.
            </>
          ) : (
            <>
              Beyond the {money(down)} down payment, {money(cashAfter)} is unearmarked against{" "}
              {money(ccLow)}–{money(ccHigh)} of closing costs. That is the whole cushion.
            </>
          )}{" "}
          The emergency fund is separate and sits at {money2(2000)} of a {money(9000)} target.
          Retirement holds {money(FINANCE.investments)}, but drawing it for a house is a tax event, not a
          reserve.
        </div>
      </div>

      <div className="hs-sp" />
      <div className="hs-panel">
        <div className="hs-note" style={{ fontSize: 12 }}>
          Balances from Monarch, {FINANCE.asOf} — {FINANCE.balanceCount.toLocaleString()} daily readings across{" "}
          {FINANCE.accountCount} accounts. Stored privately on Alpha outside the repository and synced vault.
          Monarch remains the system of record; this page is for the arithmetic Monarch does not do.
        </div>
      </div>
    </>
  );
}

/* ---------------- household operations ---------------- */

function Household({ state, persist, bills, billsErr }) {
  const [docDraft, setDocDraft] = useState({ title: "", category: "Closing", location: "", date: "", notes: "" });
  const [maintenanceDraft, setMaintenanceDraft] = useState({ title: "", area: "", cadence: "quarterly", nextDue: "", notes: "" });
  const { household } = state;
  const householdRef = useRef(household);
  useEffect(() => { householdRef.current = household; }, [household]);
  const billFacts = household.billFacts || {};
  const sortedBills = [...(bills || [])].sort((a, b) => (a.status === "active" ? -1 : 1) - (b.status === "active" ? -1 : 1) || a.label.localeCompare(b.label));
  const activeBills = sortedBills.filter((bill) => bill.status === "active" && bill.tier === "obligation" && !billFacts[bill.id]?.mergedInto);
  const activeMonthly = activeBills.reduce((sum, bill) => sum + Number(bill.annualised || 0) / 12, 0);

  const updateHousehold = (changes) => {
    const nextHousehold = { ...householdRef.current, ...changes };
    householdRef.current = nextHousehold;
    return persist({ ...state, household: nextHousehold });
  };
  const setBillFact = (id, field, value) => {
    const currentFacts = householdRef.current.billFacts || {};
    return updateHousehold({
      billFacts: {
        ...currentFacts,
        [id]: { ...(currentFacts[id] || {}), [field]: value },
      },
    });
  };
  const addDocument = () => {
    if (!docDraft.title.trim()) return;
    updateHousehold({
      documents: [...householdRef.current.documents, { ...docDraft, id: `d${Date.now()}`, title: docDraft.title.trim(), archived: false }],
    });
    setDocDraft({ title: "", category: "Closing", location: "", date: "", notes: "" });
  };
  const updateDocument = (id, changes) => updateHousehold({
    documents: householdRef.current.documents.map((item) => item.id === id ? { ...item, ...changes } : item),
  });
  const addMaintenance = () => {
    if (!maintenanceDraft.title.trim()) return;
    updateHousehold({
      maintenance: [...householdRef.current.maintenance, {
        ...maintenanceDraft,
        id: `m${Date.now()}`,
        title: maintenanceDraft.title.trim(),
        area: maintenanceDraft.area.trim() || "House",
        history: [],
        archived: false,
      }],
    });
    setMaintenanceDraft({ title: "", area: "", cadence: "quarterly", nextDue: "", notes: "" });
  };
  const completeMaintenance = (id) => {
    const today = new Date().toISOString().slice(0, 10);
    updateHousehold({
      maintenance: householdRef.current.maintenance.map((item) => item.id === id ? {
        ...item,
        history: [today, ...(item.history || [])],
        nextDue: addCadence(today, item.cadence),
      } : item),
    });
  };
  const updateMaintenance = (id, changes) => updateHousehold({
    maintenance: householdRef.current.maintenance.map((item) => item.id === id ? { ...item, ...changes } : item),
  });
  const setTax = (changes) => updateHousehold({ tax: { ...householdRef.current.tax, ...changes } });
  const currentYear = String(new Date().getFullYear());
  const calculatedProtestDeadline = protestDeadline(household.tax.appraisalNoticeDate);

  return (
    <>
      <div className="hs-panel hs-section-note">
        <div className="hs-learn-kicker">Household operating record</div>
        <div className="hs-learn-title" style={{ fontSize: "clamp(25px, 3.4vw, 36px)" }}>Keep the house after you buy it.</div>
        <div className="hs-note" style={{ fontSize: 13.5 }}>
          Homestead owns obligations, document references, recurring care, and household deadlines. Monarch
          remains the source for payments and balances; files stay in their protected storage location.
        </div>
      </div>

      <h2 className="hs-h">Bills and recurring commitments</h2>
      {!bills && (
        <div className="hs-panel"><div className={billsErr ? "hs-flag" : "hs-note"}>
          {billsErr ? "The obligation register is unavailable; saved manual facts are untouched." : "Opening the obligation register…"}
        </div></div>
      )}
      {bills && (
        <>
          <div className="hs-grid hs-g4" style={{ marginBottom: 12 }}>
            <Cell v={activeBills.length} l="active obligation families" />
            <Cell v={money2(activeMonthly)} l="estimated monthly obligations" />
            <Cell v={Object.values(billFacts).filter((item) => item.dueDay).length} l="contractual due dates entered" />
            <Cell v={Object.values(billFacts).filter((item) => item.autopay && item.autopay !== "unknown").length} l="autopay states confirmed" />
          </div>
          <div className="hs-panel">
            <div className="hs-note" style={{ marginBottom: 12 }}>
              Estimated dates come from transaction cadence. Enter the contractual day and autopay state by
              hand. If a price or card change created another row, link it to the same obligation family.
            </div>
            {sortedBills.map((bill) => {
              const fact = billFacts[bill.id] || {};
              const merged = sortedBills.find((candidate) => String(candidate.id) === String(fact.mergedInto));
              return (
                <div className={`hs-record${fact.mergedInto ? " hs-archived" : ""}`} key={bill.id}>
                  <div className="hs-record-hd">
                    <div>
                      <div className="hs-record-title">{bill.label}</div>
                      <div className="hs-record-meta">
                        {money2(bill.amount)} · {bill.cadence} · {bill.status} · next detected {bill.next_due_est || "unknown"}
                      </div>
                      {merged && <div className="hs-note">Same obligation family as {merged.label}.</div>}
                    </div>
                    <span className={`hs-status${bill.status === "active" ? " live" : ""}`}>{bill.obligation_type.replaceAll("_", " ")}</span>
                  </div>
                  <div className="hs-record-controls">
                    <label className="hs-field"><span className="hs-field-lab">Contract due day</span>
                      <input className="hs-in" inputMode="numeric" type="number" min="1" max="31" placeholder="Unknown"
                        value={fact.dueDay || ""} onChange={(event) => setBillFact(bill.id, "dueDay", event.target.value)} />
                    </label>
                    <label className="hs-field"><span className="hs-field-lab">Autopay</span>
                      <select className="hs-sel" value={fact.autopay || "unknown"}
                        onChange={(event) => setBillFact(bill.id, "autopay", event.target.value)}>
                        <option value="unknown">Unknown</option><option value="on">On</option>
                        <option value="off">Off</option><option value="manual">Manual payment</option>
                      </select>
                    </label>
                    {bill.status === "lapsed" ? (
                      <label className="hs-field"><span className="hs-field-lab">Same obligation as</span>
                        <select className="hs-sel" value={fact.mergedInto || ""}
                          onChange={(event) => setBillFact(bill.id, "mergedInto", event.target.value)}>
                          <option value="">Separate obligation</option>
                          {sortedBills.filter((candidate) => candidate.status === "active").map((candidate) => (
                            <option key={candidate.id} value={candidate.id}>{candidate.label} · {money2(candidate.amount)}</option>
                          ))}
                        </select>
                      </label>
                    ) : (
                      <div className="hs-field"><span className="hs-field-lab">Family role</span>
                        <div className="hs-note" style={{ paddingTop: 8 }}>Current row</div>
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </>
      )}

      <h2 className="hs-h">Home documents</h2>
      <div className="hs-panel">
        <div className="hs-note" style={{ marginBottom: 13 }}>
          Record where the protected original lives; do not paste account numbers, access codes, or full private documents here.
        </div>
        <div className="hs-record-controls">
          <label className="hs-field"><span className="hs-field-lab">Document</span>
            <input className="hs-in" value={docDraft.title} onChange={(event) => setDocDraft({ ...docDraft, title: event.target.value })} placeholder="Title policy" />
          </label>
          <label className="hs-field"><span className="hs-field-lab">Kind</span>
            <select className="hs-sel" value={docDraft.category} onChange={(event) => setDocDraft({ ...docDraft, category: event.target.value })}>
              {DOCUMENT_CATEGORIES.map((category) => <option key={category}>{category}</option>)}
            </select>
          </label>
          <label className="hs-field"><span className="hs-field-lab">Document date</span>
            <input className="hs-in" type="date" value={docDraft.date} onChange={(event) => setDocDraft({ ...docDraft, date: event.target.value })} />
          </label>
          <label className="hs-field"><span className="hs-field-lab">Protected location</span>
            <input className="hs-in" value={docDraft.location} onChange={(event) => setDocDraft({ ...docDraft, location: event.target.value })} placeholder="Safe / folder / provider portal" />
          </label>
        </div>
        <label className="hs-field" style={{ marginTop: 9 }}><span className="hs-field-lab">Notes</span>
          <input className="hs-in" value={docDraft.notes} onChange={(event) => setDocDraft({ ...docDraft, notes: event.target.value })} placeholder="Renewal, warranty, or retrieval note" />
        </label>
        <button className="hs-btn" style={{ marginTop: 11 }} onClick={addDocument}>Add document reference</button>
      </div>
      <div className="hs-sp" />
      <div className="hs-panel">
        {household.documents.length === 0 && <div className="hs-empty"><div className="hs-empty-t">The closing packet has a landing place.</div><div className="hs-note">Add references as documents arrive; the files themselves stay protected.</div></div>}
        {household.documents.map((item) => (
          <div className={`hs-record${item.archived ? " hs-archived" : ""}`} key={item.id}>
            <div className="hs-record-hd"><div><div className="hs-record-title">{item.title}</div>
              <div className="hs-record-meta">{item.category}{item.date ? ` · ${item.date}` : ""}</div></div>
              <button className="hs-btn ghost small" onClick={() => updateDocument(item.id, { archived: !item.archived })}>{item.archived ? "Restore" : "Archive"}</button>
            </div>
            {item.location && <div className="hs-note" style={{ marginTop: 8 }}>Stored at: {item.location}</div>}
            {item.notes && <div className="hs-note">{item.notes}</div>}
          </div>
        ))}
      </div>

      <h2 className="hs-h">Maintenance record</h2>
      <div className="hs-panel">
        <div className="hs-record-controls">
          <label className="hs-field"><span className="hs-field-lab">Work or inspection</span>
            <input className="hs-in" value={maintenanceDraft.title} onChange={(event) => setMaintenanceDraft({ ...maintenanceDraft, title: event.target.value })} placeholder="Flush water heater" />
          </label>
          <label className="hs-field"><span className="hs-field-lab">Area</span>
            <input className="hs-in" value={maintenanceDraft.area} onChange={(event) => setMaintenanceDraft({ ...maintenanceDraft, area: event.target.value })} placeholder="Plumbing" />
          </label>
          <label className="hs-field"><span className="hs-field-lab">Cadence</span>
            <select className="hs-sel" value={maintenanceDraft.cadence} onChange={(event) => setMaintenanceDraft({ ...maintenanceDraft, cadence: event.target.value })}>
              {MAINTENANCE_CADENCES.map((cadence) => <option key={cadence}>{cadence}</option>)}
            </select>
          </label>
          <label className="hs-field"><span className="hs-field-lab">First due</span>
            <input className="hs-in" type="date" value={maintenanceDraft.nextDue} onChange={(event) => setMaintenanceDraft({ ...maintenanceDraft, nextDue: event.target.value })} />
          </label>
        </div>
        <label className="hs-field" style={{ marginTop: 9 }}><span className="hs-field-lab">Notes</span>
          <input className="hs-in" value={maintenanceDraft.notes} onChange={(event) => setMaintenanceDraft({ ...maintenanceDraft, notes: event.target.value })} placeholder="Model, contractor, materials, or observation points" />
        </label>
        <button className="hs-btn" style={{ marginTop: 11 }} onClick={addMaintenance}>Add maintenance item</button>
      </div>
      <div className="hs-sp" />
      <div className="hs-panel">
        {household.maintenance.map((item) => (
          <div className={`hs-record${item.archived ? " hs-archived" : ""}`} key={item.id}>
            <div className="hs-record-hd"><div><div className="hs-record-title">{item.title}</div>
              <div className="hs-record-meta">{item.area} · {item.cadence}{item.nextDue ? ` · due ${item.nextDue}` : " · schedule after move-in"}</div></div>
              <div className="hs-row"><button className="hs-btn small" disabled={item.archived} onClick={() => completeMaintenance(item.id)}>Complete today</button>
                <button className="hs-btn ghost small" onClick={() => updateMaintenance(item.id, { archived: !item.archived })}>{item.archived ? "Restore" : "Archive"}</button></div>
            </div>
            {item.notes && <div className="hs-note" style={{ marginTop: 7 }}>{item.notes}</div>}
            {(item.history || []).length > 0 && <ul className="hs-history">{item.history.slice(0, 5).map((date, index) => <li key={`${date}-${index}`}>Completed {date}</li>)}</ul>}
          </div>
        ))}
      </div>

      <h2 className="hs-h">Texas property-tax calendar</h2>
      <div className="hs-grid hs-g2">
        <div className="hs-panel"><div className="hs-learn-kicker">After ownership + occupancy</div><div className="hs-record-title" style={{ marginTop: 7 }}>File Form 50-114</div>
          <div className="hs-note" style={{ marginTop: 7 }}>General exemption applications are normally due before May 1. A qualifying owner who acquires after Jan. 1 may receive the exemption for the applicable part of that tax year; verify the local appraisal district's instructions.</div>
          <label className="hs-row" style={{ marginTop: 12 }}><input type="checkbox" checked={household.tax.exemptionFiled} onChange={(event) => setTax({ exemptionFiled: event.target.checked })} /> <span>Application filed</span></label>
          <a className="hs-link" href="https://comptroller.texas.gov/forms/50-114.pdf" target="_blank" rel="noreferrer">Official Form 50-114</a>
        </div>
        <div className="hs-panel"><div className="hs-learn-kicker">Every appraisal cycle</div><div className="hs-record-title" style={{ marginTop: 7 }}>Review and, if needed, protest</div>
          <div className="hs-note" style={{ marginTop: 7 }}>The usual deadline is May 15 or 30 days after the appraisal district mails the notice of appraised value, whichever is later.</div>
          <label className="hs-field" style={{ marginTop: 10 }}><span className="hs-field-lab">Notice date</span><input className="hs-in" type="date" value={household.tax.appraisalNoticeDate} onChange={(event) => setTax({ appraisalNoticeDate: event.target.value })} /></label>
          <div className="hs-cal-date">Working deadline: {calculatedProtestDeadline}</div>
          <label className="hs-field" style={{ marginTop: 10 }}><span className="hs-field-lab">Last protest filed year</span><input className="hs-in" inputMode="numeric" placeholder={currentYear} value={household.tax.protestFiledYear} onChange={(event) => setTax({ protestFiledYear: event.target.value })} /></label>
          <a className="hs-link" href="https://comptroller.texas.gov/taxes/property-tax/protests/" target="_blank" rel="noreferrer">Official protest guidance</a>
        </div>
        <div className="hs-panel"><div className="hs-learn-kicker">Every payment cycle</div><div className="hs-record-title" style={{ marginTop: 7 }}>Verify the bill and pay on time</div>
          <div className="hs-note" style={{ marginTop: 7 }}>In the usual cycle, prior-year taxes become delinquent Feb. 1 when the bill was mailed by Jan. 10. Treat Jan. 31 as the pay-by date and verify the actual bill.</div>
          <label className="hs-field" style={{ marginTop: 10 }}><span className="hs-field-lab">Last tax year paid</span><input className="hs-in" inputMode="numeric" placeholder={currentYear} value={household.tax.taxPaidYear} onChange={(event) => setTax({ taxPaidYear: event.target.value })} /></label>
          <a className="hs-link" href="https://comptroller.texas.gov/taxes/property-tax/calendars/deadlines.php" target="_blank" rel="noreferrer">Official property-tax deadlines</a>
        </div>
        <div className="hs-panel"><div className="hs-learn-kicker">Calendar rule</div><div className="hs-record-title" style={{ marginTop: 7 }}>Local notice controls</div>
          <div className="hs-note" style={{ marginTop: 7 }}>These are statewide guardrails, not legal advice or a substitute for the county appraisal district. Keep the notice itself in Home documents and enter its mailed date here.</div>
        </div>
      </div>
    </>
  );
}

/* ---------------- reading ---------------- */

function MarkdownReader({ content }) {
  const blocks = String(content || "").split(/\n\s*\n/).filter(Boolean);
  return <div className="hs-reader-markdown">{blocks.map((block, index) => {
    const heading = block.match(/^(#{1,6})\s+(.+)$/s);
    if (heading) {
      const Tag = `h${Math.min(heading[1].length, 4)}`;
      return <Tag key={index}>{heading[2]}</Tag>;
    }
    const lines = block.split("\n");
    if (lines.every((line) => /^\s*[-*]\s+/.test(line))) {
      return <ul key={index}>{lines.map((line, item) => <li key={item}>{line.replace(/^\s*[-*]\s+/, "")}</li>)}</ul>;
    }
    return <p key={index}>{block.replace(/\n/g, " ")}</p>;
  })}</div>;
}

function SectionReader({ sectionId, opener, onDone }) {
  const [payload, setPayload] = useState(null);
  const [error, setError] = useState("");
  const [page, setPage] = useState(() => loadReaderPage(sessionStorage, sectionId));
  const [pages, setPages] = useState(1);
  const [pageWidth, setPageWidth] = useState(0);
  const viewportRef = useRef(null);
  const pagesRef = useRef(null);
  const doneRef = useRef(null);
  const touchRef = useRef(null);

  useEffect(() => {
    const controller = new AbortController();
    fetch(`/api/learning/sections/${encodeURIComponent(sectionId)}/reader`, { cache: "no-store", signal: controller.signal })
      .then((response) => { if (!response.ok) throw new Error("Full section unavailable"); return response.json(); })
      .then(setPayload).catch((reason) => { if (reason.name !== "AbortError") setError(reason.message); });
    return () => controller.abort();
  }, [sectionId]);

  useEffect(() => {
    const root = document.getElementById("root");
    const body = document.body;
    const prior = captureReturnState(window, document, opener);
    const priorBody = { position: body.style.position, top: body.style.top, left: body.style.left, width: body.style.width, overflow: body.style.overflow };
    body.style.position = "fixed"; body.style.top = `${-prior.scrollY}px`; body.style.left = `${-prior.scrollX}px`; body.style.width = "100%"; body.style.overflow = "hidden";
    root?.setAttribute("inert", ""); root?.setAttribute("aria-hidden", "true");
    requestAnimationFrame(() => doneRef.current?.focus());
    return () => {
      root?.removeAttribute("inert"); root?.removeAttribute("aria-hidden");
      Object.assign(body.style, priorBody);
      restoreReturnState(window, prior);
    };
  }, [opener]);

  const measure = useCallback(() => {
    const viewport = viewportRef.current, content = pagesRef.current;
    if (!viewport || !content) return;
    const width = Math.max(1, Math.floor(viewport.clientWidth));
    setPageWidth(width);
    content.style.setProperty("--reader-page-width", `${width}px`);
    requestAnimationFrame(() => {
      const count = Math.max(1, Math.ceil((content.scrollWidth + 1) / (width + 40)));
      setPages(count); setPage((current) => Math.min(current, count - 1));
    });
  }, []);

  useEffect(() => {
    if (!payload) return undefined;
    const observer = new ResizeObserver(measure); if (viewportRef.current) observer.observe(viewportRef.current);
    const images = [...(pagesRef.current?.querySelectorAll("img") || [])];
    images.forEach((image) => image.addEventListener("load", measure)); measure();
    return () => { observer.disconnect(); images.forEach((image) => image.removeEventListener("load", measure)); };
  }, [payload, measure]);

  useEffect(() => { saveReaderPage(sessionStorage, sectionId, page); }, [sectionId, page]);
  const move = useCallback((delta) => setPage((current) => Math.max(0, Math.min(pages - 1, current + delta))), [pages]);
  useEffect(() => {
    const keydown = (event) => {
      if (event.key === "Escape") { event.preventDefault(); onDone(); }
      else if (event.key === "ArrowRight" || event.key === "PageDown") { event.preventDefault(); move(1); }
      else if (event.key === "ArrowLeft" || event.key === "PageUp") { event.preventDefault(); move(-1); }
      else if (event.key === "Tab") {
        const focusable = [...document.querySelectorAll(".hs-reader-shell button:not(:disabled)")];
        if (!focusable.length) return;
        const index = focusable.indexOf(document.activeElement);
        const next = event.shiftKey ? (index <= 0 ? focusable.length - 1 : index - 1) : (index < 0 || index === focusable.length - 1 ? 0 : index + 1);
        event.preventDefault(); focusable[next].focus();
      }
    };
    document.addEventListener("keydown", keydown); return () => document.removeEventListener("keydown", keydown);
  }, [move, onDone]);

  const progress = pages ? Math.round(((page + 1) / pages) * 100) : 0;
  return createPortal(
    <div className="hs hs-reader-shell" role="dialog" aria-modal="true" aria-labelledby="hs-reader-title"
      onTouchStart={(event) => { const touch = event.touches[0]; touchRef.current = { x: touch.clientX, y: touch.clientY }; }}
      onTouchEnd={(event) => { const start = touchRef.current, touch = event.changedTouches[0]; if (!start || !touch) return; move(pageDeltaForGesture(touch.clientX - start.x, touch.clientY - start.y)); touchRef.current = null; }}>
      <header className="hs-reader-bar">
        <div style={{ minWidth: 0 }}><div className="hs-reader-kicker">Full section · {payload?.reader_format === "epub" ? "original EPUB" : "Markdown / OCR"}</div><div className="hs-reader-title" id="hs-reader-title">{payload?.title || "Opening section…"}</div><div className="hs-reader-bookline">{payload?.book_title || "Homestead field school"}</div></div>
        <button ref={doneRef} className="hs-btn ghost hs-reader-done" onClick={onDone}>Done</button>
      </header>
      <div className="hs-reader-stage">
        {payload?.reader_format === "markdown" && <div className="hs-reader-fallback">Original EPUB presentation is unavailable. Showing Homestead’s existing {payload.fallback_reason?.includes("OCR") ? "Markdown/OCR" : "Markdown"} source safely.</div>}
        <div className="hs-reader-viewport" ref={viewportRef}>
          {error ? <div className="hs-reader-loading" role="alert">{error}</div> : !payload ? <div className="hs-reader-loading">Opening the original section…</div> :
            <div ref={pagesRef} className="hs-reader-pages" style={{ transform: `translate3d(${pageOffset(page, pageWidth)}px,0,0)` }}>
              {payload.reader_format === "epub" ? <div dangerouslySetInnerHTML={{ __html: payload.html }} /> : <MarkdownReader content={payload.content} />}
            </div>}
        </div>
      </div>
      <footer className="hs-reader-status">
        <button className="hs-btn ghost" disabled={page <= 0} onClick={() => move(-1)}>← Previous</button>
        <div className="hs-reader-progress" aria-live="polite">Page {page + 1} of {pages} · {progress}%<span className="hs-reader-meter" aria-hidden="true"><i style={{ width: `${progress}%` }} /></span></div>
        <button className="hs-btn ghost next" disabled={page >= pages - 1} onClick={() => move(1)}>Next →</button>
      </footer>
    </div>, document.body
  );
}

function Reading({ state, persist, learning, learningErr }) {
  const [spine, setSpine] = useState("journey");
  const [selectedCode, setSelectedCode] = useState(null);
  const [query, setQuery] = useState("");
  const [openGroups, setOpenGroups] = useState({});
  const [reader, setReader] = useState(null);
  const selectedLessonRef = useRef(null);

  const track = learning?.tracks?.find((item) => item.spine === spine);
  const trackCodes = track?.groups?.flatMap((group) => group.objective_codes) || [];
  const selected = selectedCode ? learning?.objectives?.[selectedCode] : null;
  const learned = (code) => !!state.reading[`learn:${code}`];
  const learnedCount = trackCodes.filter(learned).length;
  const total = trackCodes.length;
  const progress = total ? Math.round((learnedCount / total) * 100) : 0;
  const isJourney = spine === "journey";

  useEffect(() => {
    if (!selectedCode && trackCodes.length) {
      setSelectedCode(trackCodes[0]);
      setOpenGroups({ [track.groups[0].code]: true });
    }
  }, [learning, selectedCode, trackCodes.length]);

  const chooseTrack = (nextSpine) => {
    const next = learning.tracks.find((item) => item.spine === nextSpine);
    const first = next?.groups?.[0];
    setSpine(nextSpine);
    setSelectedCode(first?.objective_codes?.[0] || null);
    setOpenGroups(first ? { [first.code]: true } : {});
    setQuery("");
  };
  const chooseTopic = (code, groupCode) => {
    setSelectedCode(code);
    setOpenGroups((current) => ({ ...current, [groupCode]: true }));
  };
  const toggleLearned = (code) => persist({
    ...state,
    reading: { ...state.reading, [`learn:${code}`]: !learned(code) },
  });
  const continueLearning = () => {
    const code = trackCodes.find((item) => !learned(item)) || trackCodes[0];
    if (!code) return;
    const group = track.groups.find((item) => item.objective_codes.includes(code));
    setSelectedCode(code);
    setOpenGroups({ [group.code]: true });
    revealLearningTarget(selectedLessonRef.current);
  };
  const selectedIndex = trackCodes.indexOf(selectedCode);
  const moveLesson = (amount) => {
    const code = trackCodes[selectedIndex + amount];
    if (!code) return;
    const group = track.groups.find((item) => item.objective_codes.includes(code));
    chooseTopic(code, group.code);
  };

  if (!learning) {
    return (
      <div className="hs-panel">
        <div className={learningErr ? "hs-flag" : "hs-note"}>
          {learningErr ? "The learning library is unavailable. Your progress is safe; try this section again shortly." : "Opening the learning library…"}
        </div>
      </div>
    );
  }

  return (
    <>
      {reader && <SectionReader sectionId={reader.sectionId} opener={reader.opener} onDone={() => setReader(null)} />}
      <div className="hs-panel hs-learn-hero">
        <div>
          <div className="hs-learn-kicker">Homestead field school</div>
          <div className="hs-learn-title">Learn the whole purchase, from first decision to first year.</div>
          <div className="hs-note" style={{ fontSize: 13.5, maxWidth: 650 }}>
            Start with the homebuying journey in the order it happens. The TREC contract and financing courses
            stay beside it as Texas-specific deep dives when the paperwork becomes relevant.
          </div>
        </div>
        <div>
          <div className="hs-row" style={{ justifyContent: "space-between" }}>
            <div className="hs-num sm">{learnedCount} / {total}</div>
            <div className="hs-phase-when">{progress}% learned</div>
          </div>
          <div className="hs-learn-progress" role="progressbar" aria-label="Course progress"
            aria-valuemin="0" aria-valuemax="100" aria-valuenow={progress}>
            <i style={{ width: `${progress}%` }} />
          </div>
          <button className="hs-btn" style={{ width: "100%", marginTop: 10 }} onClick={continueLearning}>
            {learnedCount ? "Continue this course" : isJourney ? "Start at the beginning" : "Start this deep dive"}
          </button>
        </div>
      </div>

      <div className="hs-sp" />
      <div className="hs-grid hs-g4">
        {isJourney ? (
          <>
            <Cell v={learning.metadata.journey_lesson_count} l="Journey lessons" />
            <Cell v={track.groups.length} l="Buying stages" />
            <Cell v={learning.metadata.book_count} l="Ingested books" />
            <Cell v={learning.metadata.contract_objective_count} l="Contract deep dives" />
          </>
        ) : (
          <>
            <Cell v={track.counts.total} l={spine === "20-19" ? "Contract topics" : "Financing topics"} />
            <Cell v={learning.metadata.book_count} l="Ingested books" />
            <Cell v={track.counts.gap} l="Book gaps flagged" warn={track.counts.gap > 0} />
            <Cell v={learning.metadata.journey_lesson_count} l="Journey lessons" />
          </>
        )}
      </div>

      <h2 className="hs-h">Learning workspace</h2>
      <div className="hs-learn-layout">
        <aside className="hs-panel hs-learn-sidebar" aria-label="Learning topics">
          <div className="hs-trackbar">
            {learning.tracks.map((item) => (
              <button key={item.spine} className="hs-track" aria-pressed={spine === item.spine}
                onClick={() => chooseTrack(item.spine)}>
                <div className="hs-track-code">{item.spine === "journey" ? "Start here" : `TREC ${item.spine}`}</div>
                <div className="hs-track-name">{item.name}</div>
              </button>
            ))}
          </div>
          <label className="hs-field" style={{ marginBottom: 10 }}>
            <span className="hs-field-lab">Find a topic</span>
            <input className="hs-in" value={query} onChange={(event) => setQuery(event.target.value)}
              placeholder={isJourney ? "budget, inspection, closing…" : "appraisal, option fee, notices…"} />
          </label>
          {track.groups.map((group) => {
            const matchingCodes = group.objective_codes.filter((code) => {
              const item = learning.objectives[code];
              const haystack = `${code} ${item.heading} ${item.description}`.toLowerCase();
              return !query || haystack.includes(query.toLowerCase());
            });
            if (!matchingCodes.length) return null;
            const isOpen = !!query || !!openGroups[group.code];
            const groupDone = group.objective_codes.filter(learned).length;
            return (
              <div className="hs-learn-group" key={group.code}>
                <button className="hs-learn-group-btn" aria-expanded={isOpen}
                  onClick={() => setOpenGroups((current) => ({ ...current, [group.code]: !isOpen }))}>
                  <span className="hs-learn-group-code">
                    {isJourney ? `Stage ${track.groups.indexOf(group) + 1}` : group.code.replace("TREC-", "").replace("-P", " ¶")}
                  </span>
                  <span className="hs-learn-group-title">{group.title}</span>
                  <span className="hs-learn-count">{groupDone}/{group.objective_codes.length}</span>
                </button>
                {isJourney && <div className="hs-group-when">{group.when}</div>}
                {isOpen && matchingCodes.map((code) => {
                  const item = learning.objectives[code];
                  return (
                    <button key={code} className="hs-learn-topic" aria-current={selectedCode === code ? "true" : undefined}
                      onClick={() => chooseTopic(code, group.code)}>
                      <span className={`hs-learn-topic-check${learned(code) ? " done" : ""}`} />
                      <span className="hs-learn-topic-name">{item.heading}</span>
                      <span className={`hs-coverage ${item.coverage}`}>
                        {item.coverage === "coverage-gap" ? "book gap" : item.coverage === "curated" ? "lesson" : item.coverage}
                      </span>
                    </button>
                  );
                })}
              </div>
            );
          })}
        </aside>

        <main ref={selectedLessonRef} className="hs-panel hs-selected-lesson" tabIndex="-1"
          aria-label="Selected learning lesson" aria-live="polite">
          {selected && (
            <>
              <div className="hs-lesson-head">
                <div className="hs-row">
                  <span className="hs-brief-code">{selected.short_code}</span>
                  <span className={`hs-coverage ${selected.coverage}`}>
                    {selected.coverage === "coverage-gap" ? "no published-book coverage" : selected.coverage === "curated" ? "journey lesson" : selected.coverage}
                  </span>
                </div>
                <div className="hs-lesson-title">{selected.heading}</div>
                <div className="hs-note" style={{ fontSize: 13.5 }}>{selected.description}</div>
                <div className="hs-note" style={{ marginTop: 11 }}>{selected.guidance}</div>
                <button className={learned(selected.code) ? "hs-btn ghost" : "hs-btn"} style={{ marginTop: 16 }}
                  onClick={() => toggleLearned(selected.code)}>
                  {learned(selected.code) ? "Marked complete — undo" : isJourney ? "Mark lesson complete" : "Mark topic learned"}
                </button>
              </div>

              <h2 className="hs-h">{isJourney ? "Reading for this step" : "Read for this topic"}</h2>
              {selected.readings.length ? selected.readings.map((reading, index) => {
                const derived = reading.role === "derived";
                const ocr = `${reading.fidelity} ${reading.text_fidelity || ""}`.toLowerCase().includes("ocr");
                return (
                  <article className="hs-reading-card" key={`${reading.section_id}-${index}`}>
                    <div className="hs-reading-hd">
                      <div>
                        <div className="hs-reading-book">{derived ? "Homestead gap brief" : reading.book_title}</div>
                        <div className="hs-reading-section">{reading.reading_title || reading.section_title}{reading.source_page ? ` · source p. ${reading.source_page}` : ""}</div>
                      </div>
                      <span className={`hs-coverage ${derived ? "coverage-gap" : reading.role === "primary_instruction" ? "complete" : "thin"}`}>
                        {derived ? "derived" : reading.role === "primary_instruction" ? "primary" : "deeper reading"}
                      </span>
                    </div>
                    <div className="hs-reading-body">{reading.excerpt}</div>
                    {!derived && <button className="hs-btn ghost hs-read-full" onClick={(event) => setReader({ sectionId: reading.section_id, opener: event.currentTarget })}>Read full section</button>}
                    {derived ? (
                      <div className="hs-source-note gap">Homestead-authored explanation, not published-book coverage. Verify against the official form or an attorney.</div>
                    ) : ocr ? (
                      <div className="hs-source-note warn">OCR-derived scan text. Use it to learn the concept; verify numbers and exact wording against the source image.</div>
                    ) : (
                      <div className="hs-source-note">Focused excerpt from the ingested book · section fingerprint {reading.sha256.slice(0, 12)}</div>
                    )}
                  </article>
                );
              }) : (
                <div className="hs-panel" style={{ background: "var(--blackland)" }}>
                  <div className="hs-flag">No ingested book covers this topic, and no derived brief is available yet. Use the official TREC form and ask the attorney.</div>
                </div>
              )}

              <h2 className="hs-h">Check yourself</h2>
              <div className="hs-note" style={{ fontSize: 13.5 }}>
                {selected.check_prompt || "Before marking this learned, explain in your own words: what does this paragraph control, when could it cost you money or a right to terminate, and what must each buyer verify?"}
              </div>
              <div className="hs-lesson-nav">
                <button className="hs-btn ghost" disabled={selectedIndex <= 0} onClick={() => moveLesson(-1)}>← Previous</button>
                <button className="hs-btn ghost" disabled={selectedIndex < 0 || selectedIndex >= trackCodes.length - 1} onClick={() => moveLesson(1)}>Next →</button>
              </div>
            </>
          )}
        </main>
      </div>
    </>
  );
}

createRoot(document.getElementById("root")).render(<Homestead />);
