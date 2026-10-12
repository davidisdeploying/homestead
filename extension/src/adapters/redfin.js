(function (global) {
  "use strict";
  var S = global.HomesteadListingShared;

  function match(url) {
    return /^https:\/\/(?:www\.)?redfin\.com\/(?:[^/?#]+\/)+home\/\d+(?:[/?#]|$)/i.test(url);
  }

  function serverPayloads(document) {
    var payloads = {};
    var marker = "root.__reactServerState.InitialContext = ";
    var allowed = [
      /\/initialInfo$/, /\/aboveTheFold$/, /\/belowTheFold$/,
      /\/schoolsAndDistrictsInfo$/, /\/avm$/, /\/rental-estimate$/,
      /\/popularityInfo$/, /\/propertyParcelInfo(?:\?|$)/,
      /\/localInsights$/, /\/riskFactorData$/, /\/location-score$/,
      /\/sun-exposure$/, /\/monthly-weather-averages$/, /\/parcel-zoning$/,
      /\/property-neighborhood-info$/, /\/activityData$/, /\/marketInsightsInfo$/,
      /\/photoTagsAndCaptions\//
    ];
    Array.from(document.scripts || []).some(function (script) {
      var text = script.textContent || "";
      var start = text.indexOf(marker);
      if (start < 0 || text.length > 5000000) return false;
      start += marker.length;
      var end = text.indexOf(";\nroot.", start);
      if (end < 0) end = text.indexOf(";\r\nroot.", start);
      if (end < 0) return false;
      var context;
      try { context = JSON.parse(text.slice(start, end)); } catch (_) { return false; }
      var cache = context && context["ReactServerAgent.cache"] && context["ReactServerAgent.cache"].dataCache || {};
      Object.keys(cache).forEach(function (endpoint) {
        if (!allowed.some(function (pattern) { return pattern.test(endpoint); })) return;
        var body = cache[endpoint] && cache[endpoint].res && cache[endpoint].res.text || "";
        body = body.replace(/^\{\}\&\&/, "");
        try {
          var parsed = JSON.parse(body);
          if (parsed && parsed.payload) payloads[endpoint] = parsed.payload;
        } catch (_) {}
      });
      return true;
    });
    return payloads;
  }

  function payload(payloads, pattern) {
    var key = Object.keys(payloads).find(function (name) { return pattern.test(name); });
    return key ? payloads[key] : {};
  }

  function amenityFacts(amenitiesInfo) {
    var sections = {};
    var features = [];
    var tours = [];
    (amenitiesInfo && amenitiesInfo.superGroups || []).forEach(function (superGroup) {
      var sectionName = S.cleanText(superGroup.titleString || "Other");
      var groups = sections[sectionName] = sections[sectionName] || {};
      (superGroup.amenityGroups || []).forEach(function (group) {
        var groupName = S.cleanText(group.groupTitle || "Details");
        groups[groupName] = (group.amenityEntries || []).map(function (entry) {
          var values = (entry.amenityValues || []).map(S.cleanText).filter(Boolean);
          values.forEach(function (value) {
            var match = value.match(/href=['"](https?:\/\/[^'"]+)/i);
            if (match) tours.push({ url: match[1], label: groupName });
          });
          var name = S.cleanText(entry.amenityName || entry.referenceName || "Detail");
          if (values.length) features.push(name + ": " + values.join(", ").replace(/<[^>]+>/g, ""));
          return { name: name, values: values, reference_name: entry.referenceName || "" };
        });
      });
    });
    return { sections: sections, features: S.unique(features, 240), tours: tours };
  }

  function parse(document, url) {
    var capture = S.baseCapture(document, url, "Redfin");
    var fields = capture.fields;
    var text = capture.visibleText;
    var server = serverPayloads(document);
    var initial = payload(server, /\/initialInfo$/);
    var above = payload(server, /\/aboveTheFold$/);
    var below = payload(server, /\/belowTheFold$/);
    var schools = payload(server, /\/schoolsAndDistrictsInfo$/);
    var avm = payload(server, /\/avm$/);
    var popularity = payload(server, /\/popularityInfo$/);
    var addressInfo = above.addressSectionInfo || {};
    var mediaInfo = above.mediaBrowserInfo || {};
    var amenityInfo = below.amenitiesInfo || {};
    var amenities = amenityFacts(amenityInfo);
    capture.structured = capture.structured.concat(Object.keys(server).map(function (key) { return server[key]; }));
    capture.raw.redfin_server_payloads = S.compact(server) || {};
    var property = S.findBestObject(capture.structured, [
      "listingId", "propertyId", "photos", "priceHistory", "schools", "remarks", "propertyDetails"
    ]);
    fields.external_id = String(initial.propertyId || fields.external_id || S.matchText(url, /\/home\/(\d+)/i));
    fields.mls_id = String(initial.mlsId || fields.mls_id || "");
    fields.address = S.cleanText(addressInfo.streetAddress && addressInfo.streetAddress.assembledAddress || fields.address);
    fields.city = S.cleanText(addressInfo.city || fields.city);
    fields.state = S.cleanText(addressInfo.state || fields.state);
    fields.postal_code = S.cleanText(addressInfo.zip || fields.postal_code);
    fields.latitude = S.number(addressInfo.latLong && addressInfo.latLong.latitude) || fields.latitude;
    fields.longitude = S.number(addressInfo.latLong && addressInfo.latLong.longitude) || fields.longitude;
    fields.price = S.money(addressInfo.latestPriceInfo && addressInfo.latestPriceInfo.amount || addressInfo.priceInfo && addressInfo.priceInfo.amount) || fields.price;
    fields.bedrooms = S.number(addressInfo.beds) || fields.bedrooms;
    fields.bathrooms = S.number(addressInfo.baths) || fields.bathrooms;
    fields.living_area = S.number(addressInfo.sqFt && addressInfo.sqFt.value) || fields.living_area;
    fields.lot_sqft = S.number(addressInfo.lotSize) || fields.lot_sqft;
    fields.year_built = S.number(addressInfo.yearBuilt) || fields.year_built;
    fields.listing_status = S.cleanText(addressInfo.status && (addressInfo.status.longerDefinitionToken || addressInfo.status.displayValue) || fields.listing_status);
    fields.estimate = S.money(addressInfo.avmInfo && addressInfo.avmInfo.predictedValue || avm.predictedValue) || fields.estimate;
    var headingAddress = S.firstText(document, [".street-address", ".homeAddressV2", "h1"]);
    if (headingAddress) fields.address = S.parseAddress(headingAddress).address;
    fields.price = S.money(S.firstText(document, [".statsValue", ".price", '[data-rf-test-id="abp-price"]'])) || fields.price;
    fields.bedrooms = fields.bedrooms || S.number(S.matchText(text, /(\d+(?:\.\d+)?)\s*(?:beds?|bd)\b/i));
    fields.bathrooms = fields.bathrooms || S.number(S.matchText(text, /(\d+(?:\.\d+)?)\s*(?:baths?|ba)\b/i));
    fields.living_area = fields.living_area || S.number(S.matchText(text, /([\d,]+)\s*(?:sq\.?\s*ft\.?|sqft)\b/i));
    fields.lot_sqft = fields.lot_sqft || S.number(S.matchText(text, /([\d,]+)\s+sq\.?\s*ft\.?\s+Lot Size/i));
    fields.year_built = fields.year_built || S.number(S.matchText(text, /(?:Built in|Year built)\s*(\d{4})/i));
    fields.hoa_monthly = fields.hoa_monthly || S.money(S.matchText(text, /HOA(?: dues| fee)?\s*\$?([\d,]+)(?:\s*\/\s*mo(?:nth)?)?/i));
    fields.listing_status = fields.listing_status || S.matchText(text, /\b(For sale|Pending|Contingent|Off market|Coming soon)\b/i);
    fields.estimate = fields.estimate || S.money(S.matchText(text, /Redfin Estimate[^$]{0,60}\$([\d,]+)/i));
    fields.days_on_site = fields.days_on_site || S.number(S.matchText(text, /(\d+)\s+days? on Redfin/i));
    var visibleMls = S.matchText(text, /\bMLS\s*#\s*([A-Z0-9-]+)/i) || S.matchText(text, /Source:\s*[^#]{0,80}#([A-Z0-9-]+)/i) || S.matchText(capture.raw.page_title, /\bMLS\s*#\s*([A-Z0-9-]+)/i);
    if (visibleMls) fields.mls_id = visibleMls;
    fields.agent_name = fields.agent_name || S.matchText(text, /Listed by\s+(.+?)\s+•/i);
    fields.broker_name = fields.broker_name || S.matchText(text, /Listed by.+?•\s*(.+?)\s+Contact:/i);
    fields.agent_phone = fields.agent_phone || S.matchText(text, /Contact:\s*([\d()\s-]{10,})/i);
    fields.description = S.firstText(document, [".remarks", ".sectionContent .description", '[data-rf-test-id="abp-home-description"]']) || fields.description;
    fields.features = S.unique((fields.features || []).concat(amenities.features), 240);
    fields.facts = S.compact({
      amenities: amenities.sections,
      public_records: below.publicRecordsInfo || {},
      local_insights: payload(server, /\/localInsights$/),
      risk_factors: payload(server, /\/riskFactorData$/),
      location_score: payload(server, /\/location-score$/),
      sun_exposure: payload(server, /\/sun-exposure$/),
      zoning: payload(server, /\/parcel-zoning$/),
      neighborhood: payload(server, /\/property-neighborhood-info$/),
    }) || S.compact(property.propertyDetails || property.facts || property.propertyFacts || {}) || {};
    fields.listing_details = S.compact({
      property_id: initial.propertyId,
      listing_id: initial.listingId,
      data_source_id: initial.dataSourceId,
      market_name: initial.marketName,
      page_view_count: popularity.numHomeViews || property.pageViewCount,
      favorite_count: S.number(S.matchText(text, /(\d+)\s+favorites?/i)) || property.favoriteCount,
      price_per_square_foot: addressInfo.pricePerSqFt || property.pricePerSqFt || property.pricePerSquareFoot,
      parcel_id: addressInfo.apn || property.parcelId || property.apn,
      county: property.county,
      subdivision: property.subdivision,
      cumulative_days_on_market: addressInfo.cumulativeDaysOnMarket,
    }) || {};
    fields.price_history = below.propertyHistoryInfo && below.propertyHistoryInfo.events || fields.price_history;
    fields.tax_history = below.publicRecordsInfo && (below.publicRecordsInfo.allTaxInfo || below.publicRecordsInfo.taxInfo) || fields.tax_history;
    fields.schools = schools.servingThisHomeSchools || schools.schoolsToShowOnDP || fields.schools;
    fields.media = S.mediaItems(document, {
      photos: mediaInfo.photos || property.photos || [],
      photoCount: mediaInfo.photos && mediaInfo.photos.length,
      richMedia: { scans: mediaInfo.scans || [], videos: mediaInfo.videos || [], tours: amenities.tours },
    });
    fields.photo_urls = fields.media.filter(function (item) { return item.kind === "photo"; }).map(function (item) { return item.url; });
    fields.fact_sections = Object.keys(capture.raw.sections).filter(function (name) {
      return /facts|features|interior|exterior|property details|parking|utilities|community|financial|schools/i.test(name);
    }).reduce(function (out, name) { out[name] = capture.raw.sections[name]; return out; }, {});
    return S.finish(capture);
  }

  global.HomesteadListingAdapters = global.HomesteadListingAdapters || {};
  global.HomesteadListingAdapters.redfin = { id: "redfin", source: "Redfin", match: match, parse: parse };
})(typeof self !== "undefined" ? self : globalThis);
