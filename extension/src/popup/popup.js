(function () {
  "use strict";
  var PENDING_KEY = "homesteadPendingListingCapture";
  var HOMESTEAD_URL = "https://homestead.example.com/?listing-import=extension";
  var capture = null;

  function show(id) {
    ["idle", "loading", "review", "result"].forEach(function (name) {
      document.getElementById(name).hidden = name !== id;
    });
  }

  function value(value, suffix) {
    if (value === null || value === undefined || value === "") return "—";
    return String(value) + (suffix || "");
  }

  function render(result) {
    capture = result.capture;
    var fields = capture.fields;
    document.getElementById("source").textContent = fields.source + " · captured now";
    document.getElementById("address").textContent = fields.address || "Address not found";
    var rows = [
      ["Price", fields.price == null ? "—" : "$" + Number(fields.price).toLocaleString()],
      ["Beds / baths", value(fields.bedrooms) + " / " + value(fields.bathrooms)],
      ["Living area", value(fields.living_area, fields.living_area ? " sq ft" : "")],
      ["Lot", value(fields.lot_sqft, fields.lot_sqft ? " sq ft" : "")],
      ["Year built", value(fields.year_built)],
      ["MLS", value(fields.mls_id)],
      ["Status", value(fields.listing_status)]
    ];
    var dl = document.getElementById("fields"); dl.innerHTML = "";
    rows.forEach(function (row) {
      var dt = document.createElement("dt"); dt.textContent = row[0];
      var dd = document.createElement("dd"); dd.textContent = row[1];
      dl.append(dt, dd);
    });
    document.getElementById("counts").textContent = [
      (fields.features || []).length + " features",
      (fields.photo_urls || []).length + " photos",
      (fields.price_history || []).length + " price events",
      (fields.schools || []).length + " schools"
    ].join(" · ");
    document.getElementById("missing").textContent = capture.missing.length ? "Review missing: " + capture.missing.join(", ") : "";
    show("review");
  }

  function extract() {
    show("loading");
    chrome.tabs.query({ active: true, currentWindow: true }, function (tabs) {
      var tab = tabs[0];
      if (!tab || !tab.id) return fail("No active tab found.");
      chrome.scripting.executeScript({ target: { tabId: tab.id }, files: HomesteadListingAdapters.registry.fileList() }, function () {
        if (chrome.runtime.lastError) return fail(chrome.runtime.lastError.message);
        chrome.scripting.executeScript({ target: { tabId: tab.id }, func: function () { return window.__homesteadCollectListing(); } }, function (results) {
          var result = results && results[0] && results[0].result;
          if (chrome.runtime.lastError || !result || result.error) return fail(result && result.error || chrome.runtime.lastError && chrome.runtime.lastError.message || "No capture returned.");
          render(result);
        });
      });
    });
  }

  function fail(message) {
    document.getElementById("message").textContent = message;
    show("result");
  }

  document.getElementById("extract").addEventListener("click", extract);
  document.getElementById("again").addEventListener("click", extract);
  document.getElementById("send").addEventListener("click", function () {
    if (!capture) return;
    var payload = {}; payload[PENDING_KEY] = { capture: capture, saved_at: new Date().toISOString() };
    chrome.storage.local.set(payload, function () {
      chrome.tabs.create({ url: HOMESTEAD_URL });
      window.close();
    });
  });
  document.getElementById("close").addEventListener("click", function () { window.close(); });
})();
