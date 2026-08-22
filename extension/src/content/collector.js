(function (global) {
  "use strict";
  global.__homesteadCollectListing = function () {
    var registry = global.HomesteadListingAdapters && global.HomesteadListingAdapters.registry;
    var adapter = registry && registry.findAdapter(global.location.href);
    if (!adapter) return { error: "Open a Zillow or Redfin home-detail page first." };
    try {
      return { adapter_id: adapter.id, capture: adapter.parse(global.document, global.location.href) };
    } catch (error) {
      return { error: "The listing page changed and could not be extracted: " + String(error && error.message || error) };
    }
  };
})(typeof self !== "undefined" ? self : globalThis);
