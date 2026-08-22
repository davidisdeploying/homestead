(function (global) {
  "use strict";
  var ADAPTERS = [
    { id: "zillow", file: "src/adapters/zillow.js" },
    { id: "redfin", file: "src/adapters/redfin.js" }
  ];

  function findAdapter(url) {
    var adapters = global.HomesteadListingAdapters || {};
    for (var i = 0; i < ADAPTERS.length; i++) {
      var adapter = adapters[ADAPTERS[i].id];
      if (adapter && adapter.match(url)) return adapter;
    }
    return null;
  }

  function fileList() {
    return ["src/adapters/shared.js"]
      .concat(ADAPTERS.map(function (adapter) { return adapter.file; }))
      .concat(["src/adapters/registry.js", "src/content/collector.js"]);
  }

  global.HomesteadListingAdapters = global.HomesteadListingAdapters || {};
  global.HomesteadListingAdapters.registry = { findAdapter: findAdapter, fileList: fileList };
})(typeof self !== "undefined" ? self : globalThis);
