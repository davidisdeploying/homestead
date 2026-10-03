/* Scout lead helpers that are worth testing away from React.
 *
 * Everything here is UI-only. None of it is persisted, and in particular none of it may
 * ever reach scout_discovery.source_url -- reconcile.py matches a saved capture against
 * that column by canonical URL, so a synthesized search URL stored there would link a
 * property to the wrong lead.
 */

/* Redfin lookup, and why it is only a ZIP page.
 *
 * Redfin's alert emails wrap every link in an opaque redmail3.redfin.com/u/click tracker
 * with no query string, so the parser recovers no listing URL (runbooks/scout.md §13).
 * Three candidate ways to rebuild one were tried against the live site on 2026-08-09:
 *
 *   https://www.redfin.com/zipcode/75044                  -> works
 *   https://www.redfin.com/?searchInputBox=<address>      -> stays on the homepage
 *   https://www.redfin.com/TX/Garland/2922-Canis-Cir-75044 -> Page Not Found
 *
 * The address slug 404s because the canonical path also carries a property ID
 * (/TX/Garland/2922-Canis-Cir-75044/home/31494412) that the email never provides. Redfin's
 * own search box does resolve a full address straight to the listing, but it is a
 * JavaScript POST with no GET equivalent.
 *
 * So the ZIP browse page is the most precise URL that can honestly be built from what
 * Scout holds. The card pairs it with a copy-address action, because the remaining step is
 * pasting the address into Redfin's search box.
 */
export function redfinLookupUrl(lead) {
  const postal = String((lead && lead.postal_code) || "").trim();
  return /^\d{5}$/.test(postal)
    ? `https://www.redfin.com/zipcode/${postal}`
    : "https://www.redfin.com/";
}

/* The single line to paste into a listing site's search box. */
export function leadAddressLine(lead) {
  if (!lead) return "";
  const street = String(lead.address || "").trim();
  const city = String(lead.city || "").trim();
  const state = String(lead.state || "").trim();
  const postal = String(lead.postal_code || "").trim();
  if (!street) return "";
  const tail = [city, [state, postal].filter(Boolean).join(" ")].filter(Boolean).join(", ");
  return tail ? `${street}, ${tail}` : street;
}

/* A lead links straight out only when the parser recovered a real listing URL. Zillow
 * yields one; Redfin does not. */
export function hasDirectListingLink(lead) {
  return Boolean(lead && lead.source_url);
}
