"""Two curated public leads, deliberately separate from the fictional CSV identity graph."""

PRODUCT_URL = "https://swabtek.com/products/general-narcotics-test-kit"
PARTNER_URL = "https://swabtek.com/pages/partners"
PA_INCIDENT = "https://www.pa.gov/agencies/cor/about-us/newsroom/newsroom/doc-investigation-uncovers-scheme-to-smuggle-synthetic-drugs-thr"
PA_PROCUREMENT = "https://www.pa.gov/agencies/cor/about-us/offices-and-bureaus/bureau-of-administration"
PA_MAIL = "https://www.pa.gov/agencies/cor/find-or-contact-inmate/mail-rules"

PROSPECTS = [
    {
        "key": "real:pa.gov:department-of-corrections",
        "name": "Pennsylvania Department of Corrections",
        "state": "PA",
        "official_url": "https://www.pa.gov/agencies/cor",
        "allowed_domains": ["pa.gov", "state.pa.us", "swabtek.com"],
        "priority": 1,
        "selection_reason": "A dated official report identifies synthetic-cannabinoid paper in legal mail. Agency procurement guidance gives a concrete discovery route. This supports investigating fit, not assuming demand, funding, or net-new status.",
        "seed_urls": [PA_INCIDENT, PA_PROCUREMENT, PA_MAIL, PRODUCT_URL, PARTNER_URL],
        "seed_notes": [
            "Official incident report dated 2026-02-17; six intercepted parcels reportedly contained synthetic cannabinoids. Do not name accused individuals in sales outreach.",
            "Current undated mail guidance distinguishes outsourced general correspondence, the Security Processing Center, and institution-level legal mail. Do not pitch screening all incoming mail at every prison.",
            "Current undated procurement guidance points to DGS vendor registration and eMarketplace. Confirm applicable contracts and rules; no active solicitation was established during shortlist research.",
            "SwabTek's current manufacturer page describes presumptive General Narcotics screening, including synthetic cannabinoids and nicotine. It cannot identify the reacting substance; laboratory confirmation and product-specific validation matter.",
            "Public partner information demonstrates a distribution program, not an authorized distributor serving this account. Smart Communications is a mail-service vendor, not an established SwabTek distributor.",
        ],
    },
    {
        "key": "real:mass.gov:department-of-correction",
        "name": "Massachusetts Department of Correction",
        "state": "MA",
        "official_url": "https://www.mass.gov/orgs/massachusetts-department-of-correction",
        "allowed_domains": ["mass.gov", "swabtek.com"],
        "priority": 2,
        "selection_reason": "Official search results describe mail-related synthetic-cannabinoid incidents and existing TruNarc equipment. A complementary screening need is only a hypothesis; existing tools and inaccessible source detail reduce confidence relative to Pennsylvania.",
        "seed_urls": [
            "https://www.mass.gov/news/massachusetts-department-of-correction-announces-latest-results-from-efforts-to-prevent-drugs-and-contraband-in-state-prisons",
            "https://www.mass.gov/orgs/massachusetts-department-of-correction",
            PRODUCT_URL, PARTNER_URL,
        ],
        "seed_notes": [
            "Initial source access returned HTTP 403; search-result excerpts alone are not full-page verification. Verify publication date and procurement route before qualification.",
            "Existing TruNarc use is a potential competitive or complementary factor, not evidence of an unmet need or dissatisfaction.",
        ],
    },
]


def seed_prospects(store, as_of):
    return [store.add_prospect(profile, as_of) for profile in PROSPECTS]
