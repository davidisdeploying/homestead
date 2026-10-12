(function (global) {
  "use strict";

  var MAX_VISIBLE_TEXT = 350000;
  var MAX_EMBEDDED_JSON = 900000;
  var MAX_ARRAY_ITEMS = 250;

  function cleanText(value) {
    return String(value == null ? "" : value).replace(/\s+/g, " ").trim();
  }

  function firstText(document, selectors) {
    for (var i = 0; i < selectors.length; i++) {
      var node = document.querySelector(selectors[i]);
      var value = node && cleanText(node.textContent);
      if (value) return value;
    }
    return "";
  }

  function firstAttr(document, selectors, attr) {
    for (var i = 0; i < selectors.length; i++) {
      var node = document.querySelector(selectors[i]);
      var value = node && cleanText(node.getAttribute(attr));
      if (value) return value;
    }
    return "";
  }

  function number(value) {
    var match = String(value == null ? "" : value).replace(/,/g, "").match(/-?\d+(?:\.\d+)?/);
    return match ? Number(match[0]) : null;
  }

  function money(value) {
    var parsed = number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }

  function unique(values, max) {
    var seen = Object.create(null);
    var out = [];
    (values || []).forEach(function (value) {
      var text = cleanText(value);
      if (!text || seen[text]) return;
      seen[text] = true;
      if (out.length < (max || MAX_ARRAY_ITEMS)) out.push(text);
    });
    return out;
  }

  function parseJsonScripts(document) {
    var parsed = [];
    var raw = [];
    var remaining = MAX_EMBEDDED_JSON;
    Array.from(document.querySelectorAll('script[type="application/ld+json"]')).forEach(function (script) {
      var text = script.textContent || "";
      if (!text.trim()) return;
      if (remaining > 0) {
        raw.push(text.slice(0, remaining));
        remaining -= Math.min(text.length, remaining);
      }
      try { parsed.push(JSON.parse(text)); } catch (_) {}
    });
    return { parsed: parsed, raw: raw };
  }

  function parseEmbeddedJson(document) {
    var parsed = [];
    var raw = [];
    var remaining = MAX_EMBEDDED_JSON;
    Array.from(document.querySelectorAll('script[type="application/json"], script[id*="NEXT"], script[id*="preload" i], script[id*="initial" i]'))
      .forEach(function (script) {
        if (parsed.length >= 12) return;
        var text = script.textContent || "";
        if (!text.trim() || text.length > 5000000) return;
        try {
          parsed.push(JSON.parse(text));
          if (remaining > 0) {
            raw.push({ id: script.id || "", text: text.slice(0, remaining), truncated: text.length > remaining });
            remaining -= Math.min(text.length, remaining);
          }
        } catch (_) {}
      });
    return { parsed: parsed, raw: raw };
  }

  function walk(value, visit, depth, budget) {
    if (budget.count++ > 120000 || depth > 18 || value == null) return;
    if (typeof value === "string") {
      if (value.length < 2000000 && /^[\[{]/.test(value.trim())) {
        try { walk(JSON.parse(value), visit, depth + 1, budget); } catch (_) {}
      }
      return;
    }
    if (typeof value !== "object") return;
    if (Array.isArray(value)) {
      for (var i = 0; i < Math.min(value.length, 600); i++) walk(value[i], visit, depth + 1, budget);
      return;
    }
    Object.keys(value).forEach(function (key) {
      visit(key, value[key]);
      walk(value[key], visit, depth + 1, budget);
    });
  }

  function findFirst(root, keys) {
    var wanted = keys.map(function (key) { return key.toLowerCase(); });
    var found;
    walk(root, function (key, value) {
      if (found !== undefined || wanted.indexOf(key.toLowerCase()) === -1) return;
      if (value == null || typeof value === "object") return;
      if (cleanText(value) !== "") found = value;
    }, 0, { count: 0 });
    return found;
  }

  function findArrays(root, keys) {
    var wanted = keys.map(function (key) { return key.toLowerCase(); });
    var found = [];
    walk(root, function (key, value) {
      if (found.length || wanted.indexOf(key.toLowerCase()) === -1 || !Array.isArray(value)) return;
      found = value.slice(0, MAX_ARRAY_ITEMS);
    }, 0, { count: 0 });
    return found;
  }

  function findBestObject(root, scoreKeys) {
    var wanted = scoreKeys.map(function (key) { return key.toLowerCase(); });
    var best = null;
    var bestScore = 0;
    var budget = { count: 0 };
    function inspect(value, depth) {
      if (budget.count++ > 140000 || depth > 20 || value == null) return;
      if (typeof value === "string") {
        if (value.length < 5000000 && /^[\[{]/.test(value.trim())) {
          try { inspect(JSON.parse(value), depth + 1); } catch (_) {}
        }
        return;
      }
      if (typeof value !== "object") return;
      if (Array.isArray(value)) {
        for (var i = 0; i < Math.min(value.length, 600); i++) inspect(value[i], depth + 1);
        return;
      }
      var keys = Object.keys(value);
      var score = keys.reduce(function (total, key) {
        return total + (wanted.indexOf(key.toLowerCase()) >= 0 ? 1 : 0);
      }, 0);
      if (score > bestScore) { best = value; bestScore = score; }
      keys.forEach(function (key) { inspect(value[key], depth + 1); });
    }
    inspect(root, 0);
    return best || {};
  }

  function compact(value, depth) {
    depth = depth || 0;
    if (value == null || depth > 8) return undefined;
    if (typeof value === "string") {
      var text = cleanText(value);
      return text ? text.slice(0, 12000) : undefined;
    }
    if (typeof value === "number" || typeof value === "boolean") return value;
    if (Array.isArray(value)) {
      var items = value.slice(0, 120).map(function (item) { return compact(item, depth + 1); })
        .filter(function (item) { return item !== undefined; });
      return items.length ? items : undefined;
    }
    if (typeof value === "object") {
      var out = {};
      Object.keys(value).slice(0, 240).forEach(function (key) {
        var item = compact(value[key], depth + 1);
        if (item === undefined) return;
        if (Array.isArray(item) && !item.length) return;
        if (typeof item === "object" && !Array.isArray(item) && !Object.keys(item).length) return;
        out[key] = item;
      });
      return Object.keys(out).length ? out : undefined;
    }
    return undefined;
  }

  function bestPhotoUrl(item) {
    if (typeof item === "string") return item;
    if (!item || typeof item !== "object") return "";
    var candidates = [];
    [item.mixedSources && item.mixedSources.webp, item.mixedSources && item.mixedSources.jpeg,
      item.sources, item.srcSet].forEach(function (group) {
      if (!Array.isArray(group)) return;
      group.forEach(function (source) {
        if (typeof source === "string") candidates.push({ url: source, width: 0 });
        else if (source && source.url) candidates.push({ url: source.url, width: Number(source.width) || 0 });
      });
    });
    candidates.sort(function (a, b) { return b.width - a.width; });
    return (candidates[0] && candidates[0].url) ||
      item.photoUrls && (item.photoUrls.fullScreenPhotoUrl || item.photoUrls.nonFullScreenPhotoUrl || item.photoUrls.lightboxListUrl) ||
      item.thumbnailData && item.thumbnailData.thumbnailUrl || item.url || item.src || item.originalUrl || "";
  }

  function mediaKind(url, label) {
    var value = (String(url || "") + " " + String(label || "")).toLowerCase();
    if (/floor[_ -]?(?:map|plan|shape)|floorplan/.test(value)) return "floor_plan";
    if (/view-imx|view-3d-home|vrmodel|3d home|matterport|virtual tour|propertypanorama|instaview/.test(value)) return "three_d";
    if (/\.mp4(?:\?|$)|video/.test(value)) return "video";
    if (/streetview|staticmap|maps\.google|map image/.test(value)) return "map";
    return "photo";
  }

  function mediaItems(document, property) {
    var out = [];
    var seen = Object.create(null);
    function add(url, kind, label, extra) {
      url = cleanText(url);
      if (!/^https?:\/\//.test(url) || seen[url]) return;
      seen[url] = true;
      out.push(Object.assign({ url: url, kind: kind || mediaKind(url, label), label: cleanText(label || "") }, extra || {}));
    }
    var primaryPhotos = [property && property.originalPhotos, property && property.responsivePhotos, property && property.photos]
      .find(function (items) { return Array.isArray(items) && items.length; }) || [];
    var declaredPhotoCount = Number(property && property.photoCount) || primaryPhotos.length || 100;
    primaryPhotos.slice(0, Math.min(100, declaredPhotoCount)).forEach(function (item, index) {
      add(bestPhotoUrl(item), "photo", item && (item.caption || item.alt) || ("Listing photo " + (index + 1)));
    });
    if (!primaryPhotos.length && property && Array.isArray(property.images)) property.images.slice(0, 100).forEach(function (item, index) {
      add(bestPhotoUrl(item), "photo", "Listing photo " + (index + 1));
    });
    Array.from(document.images || []).forEach(function (img) {
      var url = img.currentSrc || img.src || "";
      var label = img.alt || img.getAttribute("aria-label") || "";
      var kind = mediaKind(url, label);
      if (kind !== "photo" || (!primaryPhotos.length && /(?:zillowstatic\.com\/fp\/|photo|images|listing|cdn-redfin)/i.test(url))) add(url, kind, label);
    });
    var facts = property && property.resoFacts || {};
    [facts.virtualTour, facts.virtualTourUrl, facts.virtualTourURL, property && property.interactiveFloorPlanUrl]
      .forEach(function (url) { if (typeof url === "string") add(url, mediaKind(url, "virtual tour"), "Virtual tour"); });
    function addViewerGroups(value) {
      if (!value || typeof value !== "object") return;
      Object.keys(value).forEach(function (key) {
        var items = Array.isArray(value[key]) ? value[key] : [value[key]];
        items.forEach(function (item) {
          if (item && typeof item === "object") add(item.viewerUrl || item.url, mediaKind(item.viewerUrl || item.url, key), key);
        });
      });
    }
    addViewerGroups(property && property.richMedia);
    return out.slice(0, 180);
  }

  function meta(document) {
    var out = {};
    Array.from(document.querySelectorAll("meta[name], meta[property]")).forEach(function (node) {
      var key = node.getAttribute("property") || node.getAttribute("name");
      var value = node.getAttribute("content");
      if (key && value && Object.keys(out).length < 120) out[key] = value;
    });
    return out;
  }

  function matchText(text, regex) {
    var match = String(text || "").match(regex);
    return match ? cleanText(match[1]) : "";
  }

  function parseAddress(value) {
    var text = cleanText(value).replace(/\s*\|.*$/, "");
    var match = text.match(/^(.+?),\s*([^,]+),\s*([A-Z]{2})\s+(\d{5}(?:-\d{4})?)/);
    return match ? { address: match[1], city: match[2], state: match[3], postal_code: match[4] } : { address: text };
  }

  function imageUrls(document, structured) {
    var urls = [];
    Array.from(document.images || []).forEach(function (img) {
      urls.push(img.currentSrc || img.src || "");
    });
    var structuredImages = findArrays(structured, ["photos", "images", "originalPhotos", "responsivePhotos"]);
    structuredImages.forEach(function (item) {
      if (typeof item === "string") urls.push(item);
      else if (item && typeof item === "object") urls.push(item.url || item.src || item.mixedSources?.jpeg?.[0]?.url || "");
    });
    return unique(urls.filter(function (url) { return /^https?:\/\//.test(url); }), 160);
  }

  function sectionTexts(document) {
    var out = {};
    var remaining = 250000;
    Array.from(document.querySelectorAll("h2, h3")).forEach(function (heading) {
      if (remaining <= 0 || Object.keys(out).length >= 40) return;
      var name = cleanText(heading.textContent);
      if (!name || out[name]) return;
      var container = heading.closest("section") || heading.parentElement;
      var text = cleanText(container && (container.innerText || container.textContent));
      if (!text) return;
      text = text.slice(0, Math.min(50000, remaining));
      out[name] = text;
      remaining -= text.length;
    });
    return out;
  }

  function baseCapture(document, url, source) {
    var jsonLd = parseJsonScripts(document);
    var embedded = parseEmbeddedJson(document);
    var structured = jsonLd.parsed.concat(embedded.parsed);
    var metadata = meta(document);
    var visibleText = cleanText(document.body ? document.body.innerText || document.body.textContent : "");
    var title = cleanText(document.title || metadata["og:title"] || "");
    var address = parseAddress(metadata["og:title"] || title);
    var fields = {
      source: source,
      source_url: url.split("?")[0],
      external_id: cleanText(findFirst(structured, ["zpid", "listingId", "listing_id", "propertyId", "mlsId"]) || ""),
      mls_id: cleanText(findFirst(structured, ["mlsId", "mlsNumber", "mls_id"]) || matchText(visibleText, /MLS(?:\s+ID|\s*#| Number)?\s*[:#]?\s*([A-Z0-9-]+)/i)),
      address: cleanText(findFirst(structured, ["streetAddress", "addressLine", "address1"]) || address.address || ""),
      city: cleanText(findFirst(structured, ["addressLocality", "city"]) || address.city || ""),
      state: cleanText(findFirst(structured, ["addressRegion", "state"]) || address.state || ""),
      postal_code: cleanText(findFirst(structured, ["postalCode", "zipcode", "zipCode"]) || address.postal_code || ""),
      price: money(findFirst(structured, ["price", "listPrice", "unformattedPrice"]) || metadata["product:price:amount"]),
      bedrooms: number(findFirst(structured, ["bedrooms", "beds", "numberOfBedrooms"])),
      bathrooms: number(findFirst(structured, ["bathrooms", "baths", "numberOfBathroomsTotal"])),
      living_area: number(findFirst(structured, ["livingArea", "sqFt", "squareFeet", "floorSize"])),
      lot_sqft: number(findFirst(structured, ["lotSize", "lotSizeSqFt", "lot_sqft"])),
      year_built: number(findFirst(structured, ["yearBuilt", "year_built"])),
      hoa_monthly: money(findFirst(structured, ["monthlyHoaFee", "hoaFee", "hoaDues"])),
      property_type: cleanText(findFirst(structured, ["homeType", "propertyType", "propertySubType"]) || ""),
      listing_status: cleanText(findFirst(structured, ["homeStatus", "listingStatus", "statusText"]) || ""),
      description: cleanText(findFirst(structured, ["description", "remarks", "publicRemarks"]) || metadata.description || metadata["og:description"] || ""),
      latitude: number(findFirst(structured, ["latitude", "lat"])),
      longitude: number(findFirst(structured, ["longitude", "lng", "lon"])),
      estimate: money(findFirst(structured, ["zestimate", "avm", "estimatedValue", "redfinEstimate"])),
      rent_estimate: money(findFirst(structured, ["rentZestimate", "rentEstimate"])),
      agent_name: cleanText(findFirst(structured, ["agentName", "listingAgentName"]) || ""),
      agent_phone: cleanText(findFirst(structured, ["agentPhoneNumber", "agentPhone"]) || ""),
      broker_name: cleanText(findFirst(structured, ["brokerName", "brokerageName", "listingOfficeName"]) || ""),
      listed_date: cleanText(findFirst(structured, ["datePosted", "listedDate", "listingDate"]) || ""),
      days_on_site: number(findFirst(structured, ["daysOnZillow", "daysOnMarket", "timeOnRedfin"])),
      attribution: cleanText(findFirst(structured, ["attributionInfo", "providerListingId", "mlsName"]) || ""),
      features: unique(findArrays(structured, ["features", "amenities", "propertyFeatures", "amenityFeature", "atAGlanceFacts"]).map(function (item) {
        return typeof item === "string" ? item : item && (item.name || item.featureName || item.text);
      })),
      photo_urls: imageUrls(document, structured),
      price_history: findArrays(structured, ["priceHistory", "price_history"]),
      tax_history: findArrays(structured, ["taxHistory", "tax_history"]),
      schools: findArrays(structured, ["schools", "nearbySchools"]),
    };
    if (!fields.lot_sqft) {
      var lotAcres = number(findFirst(structured, ["lotSizeAcres", "lotAcres"]));
      if (lotAcres) fields.lot_sqft = Math.round(lotAcres * 43560);
    }
    return {
      fields: fields,
      raw: {
        page_title: title,
        metadata: metadata,
        json_ld_text: jsonLd.raw,
        embedded_json: embedded.raw,
        sections: sectionTexts(document),
        visible_text: visibleText.slice(0, MAX_VISIBLE_TEXT),
        visible_text_truncated: visibleText.length > MAX_VISIBLE_TEXT,
        source_url: url,
        captured_at: new Date().toISOString(),
      },
      structured: structured,
      visibleText: visibleText,
    };
  }

  function finish(capture) {
    var required = ["address", "price", "bedrooms", "bathrooms", "living_area"];
    var missing = required.filter(function (key) {
      return capture.fields[key] === null || capture.fields[key] === undefined || capture.fields[key] === "";
    });
    delete capture.structured;
    delete capture.visibleText;
    capture.missing = missing;
    capture.schema_version = 1;
    return capture;
  }

  global.HomesteadListingShared = {
    baseCapture: baseCapture,
    cleanText: cleanText,
    firstText: firstText,
    firstAttr: firstAttr,
    number: number,
    money: money,
    matchText: matchText,
    parseAddress: parseAddress,
    unique: unique,
    findFirst: findFirst,
    findArrays: findArrays,
    findBestObject: findBestObject,
    compact: compact,
    bestPhotoUrl: bestPhotoUrl,
    mediaKind: mediaKind,
    mediaItems: mediaItems,
    finish: finish,
  };
})(typeof self !== "undefined" ? self : globalThis);
