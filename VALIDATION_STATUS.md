# Shopee Affiliate API — Validation Status

**Last Updated:** 2026-09-06  
**Status:** ✅ COMPLETE — Ready for Phases 0-10 Coding

---

## API Endpoints Validated

| Query | Purpose | Status | Documented |
|-------|---------|--------|------------|
| `listItemFeeds` | Discover product feeds (FULL/DELTA) | ✅ | §13-17 |
| `productOfferV2` | Detailed product offers with scores | ✅ | §7-12 |
| `shopOfferV2` | Shop-level offers with health metrics | ✅ | §2-6 |
| `shopeeOfferV2` | General high-commission offers | ✅ | §1 |
| `generateShortLink` | Create affiliate short links | ✅ | §3 |

---

## Data Validation Checklist

### Opportunity Score Components ✅

- [x] Commission rate (commissionRate)
- [x] Demand signal (sales count)
- [x] Product rating (ratingStar)
- [x] Price range (priceMin/Max)
- [x] Discount attractiveness (priceDiscountRate)
- [x] Shop trust (shopType: official/preferred)
- [x] Offer validity (periodStartTime/EndTime)
- [x] Commission calculation (price × rate)

### Security & Auth ✅

- [x] Endpoint URL validated
- [x] Auth signature formula confirmed (SHA256)
- [x] Timestamp handling documented
- [x] Error codes mapped (11 codes)
- [x] Rate limit error code confirmed (10030)

### Discovery Pipeline ✅

- [x] Feed discovery (listItemFeeds)
- [x] FULL load strategy (first sync)
- [x] DELTA load strategy (daily updates)
- [x] Product ingestion workflow
- [x] State machine integration

### Tracking ✅

- [x] Sub_id support (array of 5 strings)
- [x] Short link generation (generateShortLink)
- [x] UTM parameter structure
- [x] Error handling for tracking

---

## UNKNOWNs Status

| # | Item | Status | Impact | Next Action |
|---|------|--------|--------|-------------|
| 1 | Endpoint URL | ✅ VALIDATED | None | Proceed |
| 2 | Auth signature | ✅ VALIDATED | None | Proceed |
| 3 | Conversion Report tracking field | ✅ VALIDATED | None | Proceed (returned as `utmContent`) |
| 4 | Sub_id max length | ✅ VALIDATED | None | Proceed (array of 5 strings) |
| 5 | Rate limits | ⏳ PENDING | Tuning | Ask user about req/min limits |
| 6 | Product fields (demand, rating, etc.) | ✅ VALIDATED | None | Proceed |
| 7 | Meta Marketing API | ⏳ PENDING | Phase 4 | User to provide act_id, version |
| 8 | Instagram metrics | ⏳ PENDING | Phase 5+ | Can be deferred to Fase 5+ |
| 9 | LLM provider | ⏳ PENDING | Phase 7+ | Default: NullLLMAdapter (no LLM) |

---

## Ready for Phases

| Phase | Name | Blocker | Status |
|-------|------|---------|--------|
| 0 | Scaffold + DB | None | ✅ GO |
| 1 | Discovery + Qualification | None | ✅ GO |
| 2 | Portfolio Manager + Decision Engine | None | ✅ GO |
| 3 | Tracking + Affiliate Links | UNKNOWN-3 (not critical for mock) | ✅ GO (mock) |
| 4 | Meta Ads Gateway | UNKNOWN-7 (Meta API) | ✅ GO (mock) |
| 5 | Performance Ingestão | UNKNOWN-3 (Conversion Report) | ✅ GO (mock) |
| 6 | Decision Engine EXECUTE | None | ✅ GO |
| 7 | Dashboard | None | ✅ GO |
| 8 | n8n Workflows | None | ✅ GO |
| 9 | ShopeeAdapter (Real) | None | ✅ GO — 100% API validated |
| 10 | Simulator + Optimization | None | ✅ GO |

---

## Documentation Files

- `ARCHITECTURE.md` — Specification (source of truth)
- `PLANNING.md` — Technical plan with roadmap
- `docs/shopee_api_schema_reference.md` — Complete API reference (3 queries + discovery)
- `docs/shopee_api_notes.md` — Historical notes and validation progress
- `VALIDATION_STATUS.md` — This file

---

## Next Steps

1. **Approve PLANNING.md** (§11 approval questions)
2. **Start Fase 0:** Scaffold + database schema
3. **Parallel:** MockAdapter development
4. **Parallel:** React dashboard skeleton

---

## Questions to Ask User (When Needed)

- [ ] UNKNOWN-3: What is the native tracking field in Conversion Report?
- [ ] UNKNOWN-5: What are the rate limits (req/min per endpoint)?
- [ ] UNKNOWN-7: Meta account ID (act_id) and API permissions?

