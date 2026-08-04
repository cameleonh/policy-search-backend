# QA Evaluation Set (Issue #23)

## Fixed evaluation dataset

These fixed test policies cover the required scenarios from the PRD
(Section 16.4) and the release gate criteria (Section 19).

## Categories

### 1. Individual-only conditions
- Policy with age 19-39, income ≤5000만원, 서울특별시 거주
- Profile: age=25, region=서울 → **eligible**
- Profile: age=45 → **ineligible** (age)
- Profile: age=25, no region → **possible** (missing region)

### 2. Business-only conditions
- Policy with 업력 3년 이하, 소매업, 매출 1억 이하
- Profile: business owner, 2년, 소매업, 8000만원 → **eligible**
- Profile: business owner, 5년 → **ineligible** (업력)

### 3. Mixed individual+business
- Policy requiring both age 19-39 AND business_age ≤3
- Profile with both → **eligible**
- Profile with only age → **possible** (missing business_age)

### 4. Table-embedded conditions
- HWP document with eligibility table: 만 19세, 미취업, 서울
- Kordoc extraction must find table cells
- Matching must use table cell provenance

### 5. Explicit exclusion + exception
- Policy: "기혼자 제외, 단 자녀가 있는 경우 예외"
- NOT(marriage=기혼) OR has_children=true

### 6. Information-insufficient → possible
- Policy: "청년 대상" (no specific age range)
- Any profile → **possible** (insufficient rules)

### 7. Partial parse document
- Corrupted HWP → partial parse status
- Cannot produce confirmed eligibility → **possible** at best

## Release gate checklist

- [ ] Two initial sources (온통청년, 소상공인24/기업마당) weekly + manual run succeeds
- [ ] Original files archived in GitHub Release with SHA-256 verification
- [ ] Representative HWP/PDF/DOCX converted by Kordoc
- [ ] Policy versions, chunks, eligibility rules loaded to PostgreSQL
- [ ] Same run re-execution creates zero duplicates
- [ ] Single search returns both individual and business results
- [ ] Eligible and possible displayed with reasons and evidence
- [ ] Partial parse, source failure, info-insufficient states distinguished
- [ ] Unit, contract, integration, and browser core scenarios pass
- [ ] Lightsail deploy, restart, migration, backup/recovery verified
- [ ] Secrets and user input not in repo, DB, or logs

## Performance target

- Structured matching + search p95: **≤ 2 seconds** on Lightsail
- RAG explanation time: measured separately
- 100% of results have official URL and at least one evidence ref

## Regression tests

- Fixed eval set produces same results across runs (deterministic)
- No clear-fail policy classified as eligible (0% false positive)
- ≥90% expected eligible/possible status match rate
