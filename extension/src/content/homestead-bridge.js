(function () {
  "use strict";
  var PENDING_KEY = "homesteadPendingListingCapture";

  function deliver() {
    chrome.storage.local.get([PENDING_KEY], function (items) {
      var pending = items && items[PENDING_KEY];
      if (!pending || !pending.capture) return;
      document.documentElement.setAttribute("data-homestead-listing-import", JSON.stringify(pending));
      document.dispatchEvent(new Event("homestead-listing-import-ready"));
    });
  }

  document.addEventListener("homestead-listing-import-consumed", function () {
    chrome.storage.local.remove(PENDING_KEY);
    document.documentElement.removeAttribute("data-homestead-listing-import");
  });

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", deliver, { once: true });
  else deliver();
})();
