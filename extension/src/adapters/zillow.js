(function (global) {
  "use strict";
  var S = global.HomesteadListingShared;

  function match(url) {
    return /^https:\/\/(?:www\.)?zillow\.com\/homedetails\//i.test(url);
  }

  function parse(document, url) {
    var capture = S.baseCapture(document, url, "Zillow");
    var fields = capture.fields;
    var text = capture.visibleText;
    var nextData = null;
    var nextNode = document.getElementById("__NEXT_DATA__");
    if (nextNode) {
      try { nextData = JSON.parse(nextNode.textContent || ""); } catch (_) {}
    }
    var propertyRoot = nextData && nextData.props && nextData.props.pageProps && nextData.props.pageProps.componentProps && nextData.props.pageProps.componentProps.gdpClientCache;
    propertyRoot = propertyRoot || S.findFirst(nextData || capture.structured, ["gdpClientCache"]);
    if (typeof propertyRoot === "string") {
      try { propertyRoot = JSON.parse(propertyRoot); } catch (_) { propertyRoot = null; }
    }
    var property = S.findBestObject(propertyRoot || capture.structured, [
      "zpid", "resoFacts", "originalPhotos", "priceHistory", "taxHistory", "schools", "attributionInfo", "description"
    ]);
    var facts = property.resoFacts || {};
    var attribution = property.attributionInfo || {};
    var address = property.address || {};
    fields.external_id = fields.external_id || S.matchText(url, /\/(\d+)_zpid\/?/i);
    fields.external_id = String(property.zpid || fields.external_id || "");
    fields.address = S.cleanText(property.streetAddress || address.streetAddress || fields.address);
    fields.city = S.cleanText(property.city || address.city || fields.city);
    fields.state = S.cleanText(property.state || address.state || fields.state);
    fields.postal_code = S.cleanText(property.zipcode || address.zipcode || address.postalCode || fields.postal_code);
    fields.price = S.money(property.price) || fields.price;
    fields.bedrooms = S.number(property.bedrooms) || fields.bedrooms;
    fields.bathrooms = S.number(property.bathrooms) || fields.bathrooms;
    fields.living_area = S.number(property.livingArea || facts.livingArea) || fields.living_area;
    fields.year_built = S.number(property.yearBuilt || facts.yearBuilt) || fields.year_built;
    fields.property_type = S.cleanText(property.homeType || facts.homeType || facts.propertySubType || fields.property_type);
    fields.listing_status = S.cleanText(property.homeStatus || fields.listing_status);
    fields.description = S.cleanText(property.description || fields.description);
    fields.latitude = S.number(property.latitude || address.latitude) || fields.latitude;
    fields.longitude = S.number(property.longitude || address.longitude) || fields.longitude;
    fields.estimate = S.money(property.zestimate) || fields.estimate;
    fields.rent_estimate = S.money(property.rentZestimate) || fields.rent_estimate;
    fields.days_on_site = S.number(property.daysOnZillow) || fields.days_on_site;
    fields.mls_id = S.cleanText(attribution.mlsId || attribution.mlsNumber || fields.mls_id);
    fields.agent_name = S.cleanText(attribution.agentName || fields.agent_name);
    fields.agent_phone = S.cleanText(attribution.agentPhoneNumber || fields.agent_phone);
    fields.broker_name = S.cleanText(attribution.brokerName || attribution.brokerageName || fields.broker_name);
    fields.listed_date = S.cleanText(property.datePosted || property.listingDate || fields.listed_date);
    fields.price_history = Array.isArray(property.priceHistory) ? property.priceHistory.slice(0, 120) : fields.price_history;
    fields.tax_history = Array.isArray(property.taxHistory) ? property.taxHistory.slice(0, 120) : fields.tax_history;
    var schools = Array.isArray(property.schools) ? property.schools : (Array.isArray(property.assignedSchools) ? property.assignedSchools : fields.schools);
    fields.schools = (schools || []).slice(0, 40);
    fields.facts = S.compact(facts) || {};
    fields.attribution_details = S.compact(attribution) || {};
    fields.listing_details = S.compact({
      page_view_count: property.pageViewCount,
      favorite_count: property.favoriteCount,
      tour_view_count: property.tourViewCount,
      photo_count: property.photoCount,
      price_per_square_foot: property.pricePerSquareFoot || facts.pricePerSquareFoot,
      parcel_id: property.parcelId || facts.parcelId,
      county: property.county || facts.county,
      subdivision: facts.subdivisionName,
      tax_annual_amount: property.propertyTaxRate ? undefined : facts.taxAnnualAmount,
      tax_assessed_value: facts.taxAssessedValue,
      property_tax_rate: property.propertyTaxRate,
      has_3d_model: property.hasVRModel,
      listed_by: attribution.agentName,
      broker: attribution.brokerName,
      mls_name: attribution.mlsName,
      mls_id: attribution.mlsId,
      listing_provided_by: attribution.listingAgreement,
    }) || {};
    fields.media = S.mediaItems(document, property);
    fields.photo_urls = fields.media.filter(function (item) { return item.kind === "photo"; }).map(function (item) { return item.url; });
    fields.features = Array.isArray(facts.atAGlanceFacts) ? facts.atAGlanceFacts.map(function (item) {
      return typeof item === "string" ? item : [item.factLabel, item.factValue].filter(Boolean).join(": ");
    }).filter(Boolean) : fields.features;
    fields.lot_sqft = S.number(facts.lotSize || property.lotSize) || fields.lot_sqft;
    fields.hoa_monthly = S.money(facts.monthlyHoaFee || facts.hoaFee) || fields.hoa_monthly;
    var headingAddress = S.firstText(document, ["h1", '[data-testid="property-card-addr"]']);
    if (!fields.address && headingAddress) fields.address = S.parseAddress(headingAddress).address;
    fields.price = S.money(S.firstText(document, ['[data-testid="price"]', '[data-testid="price-and-tax"]'])) || fields.price;
    fields.bedrooms = fields.bedrooms || S.number(S.matchText(text, /(\d+(?:\.\d+)?)\s*(?:beds?|bd)\b/i));
    fields.bathrooms = fields.bathrooms || S.number(S.matchText(text, /(\d+(?:\.\d+)?)\s*(?:baths?|ba)\b/i));
    fields.living_area = fields.living_area || S.number(S.matchText(text, /([\d,]+)\s*(?:sq\.?\s*ft\.?|sqft)\b/i));
    var lotAcres = S.number(S.matchText(text, /(\d+(?:\.\d+)?)\s+Acres? Lot/i));
    if (!lotAcres && fields.lot_sqft > 0 && fields.lot_sqft < 10 && /Acres? Lot/i.test(text)) lotAcres = fields.lot_sqft;
    if (lotAcres) fields.lot_sqft = Math.round(lotAcres * 43560);
    fields.year_built = fields.year_built || S.number(S.matchText(text, /(?:Built in|Year built)\s*(\d{4})/i));
    fields.hoa_monthly = fields.hoa_monthly || S.money(S.matchText(text, /HOA(?: dues| fee)?\s*\$?([\d,]+)(?:\s*\/\s*mo(?:nth)?)?/i));
    fields.listing_status = fields.listing_status || S.matchText(text, /\b(For sale|Pending|Contingent|Off market|Coming soon)\b/i);
    fields.estimate = fields.estimate || S.money(S.matchText(text, /Zestimate[^$]{0,40}\$([\d,]+)/i));
    fields.rent_estimate = fields.rent_estimate || S.money(S.matchText(text, /Rent Zestimate[^$]{0,40}\$([\d,]+)/i));
    fields.days_on_site = fields.days_on_site || S.number(S.matchText(text, /(\d+)\s+days? on Zillow/i));
    if (!fields.description) fields.description = S.firstText(document, ['[data-testid="description"]', '[data-testid="home-description-text-description"]']);
    return S.finish(capture);
  }

  global.HomesteadListingAdapters = global.HomesteadListingAdapters || {};
  global.HomesteadListingAdapters.zillow = { id: "zillow", source: "Zillow", match: match, parse: parse };
})(typeof self !== "undefined" ? self : globalThis);
