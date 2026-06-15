# QA Validation Tool — Technical Audit

**Document Purpose**: Comprehensive technical architecture and code quality assessment for academic, professional, and internship review contexts.

**Audit Date**: 2026-06-14  
**Auditor Role**: Senior Software Architect  
**Project Status**: Alpha/Beta (feature-complete but pre-production)

---

## 1. Executive Summary

### What the Project Does
The **QA Validation Tool** is a Streamlit-based web application that:
- Validates OCR (Optical Character Recognition) output quality by comparing OCR-generated text against ground-truth PDF originals
- Provides Named Entity Recognition (NER) entity highlighting and distribution analysis for medical domain entities
- Converts relational CSV data into Neo4j Cypher export format for knowledge graph construction

### Why It Exists
- **Problem**: OCR systems produce errors that corrupt downstream NLP/knowledge graph pipelines; identifying and measuring these errors is critical for data quality
- **Domain**: Medical/Ayurvedic text digitization (inferred from NER labels: HERB, DISEASE, DOSHA, COMPOUND, SYMPTOM)
- **Use Case**: QA teams need quick, visual, reproducible evaluation of OCR accuracy before feeding text to entity extraction or knowledge graph systems

### Primary Users
- Data QA engineers and annotation teams
- OCR system evaluators and researchers
- Knowledge graph curators preparing medical domain data

---

## 2. Architecture Overview

### High-Level Design Pattern
**Single-file Streamlit MVP** with layered functionality:
```
┌─────────────────────────────────────────┐
│      Streamlit UI Layer (Tab-based)     │  (app.py: lines 162–330)
│  ┌─────────────────────────────────────┐│
│  │ Tab 1: OCR Accuracy | Tab 2: NER    ││
│  │ Tab 3: Relationships | Cypher Export││
│  └─────────────────────────────────────┘│
└─────────────────────────────────────────┘
            ↓ (calls)
┌─────────────────────────────────────────┐
│     Business Logic Layer (Functions)    │
│  ┌─────────────────────────────────────┐│
│  │ extract_pdf_text()                  ││ (lines 13–33)
│  │ extract_docx_text()                 ││ (lines 36–53)
│  │ normalize_text()                    ││ (lines 58–156)
│  │ calculate_ocr_accuracy()            ││ (lines 161–179)
│  └─────────────────────────────────────┘│
└─────────────────────────────────────────┘
            ↓ (uses)
┌─────────────────────────────────────────┐
│     External Libraries & Services       │
│  ┌─────────────────────────────────────┐│
│  │ PyMuPDF (fitz) | python-docx        ││
│  │ jiwer | pandas | difflib            ││
│  │ unicodedata | re | typing           ││
│  └─────────────────────────────────────┘│
└─────────────────────────────────────────┘
```

### Architectural Style
- **Monolithic**: Single Python file, no separation into modules
- **Functional**: Business logic uses pure functions (extract, normalize, calculate)
- **Imperative UI**: Direct Streamlit widget state management
- **Stateless**: No persistent state or sessions (each page refresh resets)

---

## 3. Module Breakdown

### 3.1 Extraction Layer

#### `extract_pdf_text(pdf_file) → str` (lines 13–33)
**Purpose**: Read PDF file and extract all text preserving page boundaries.

**Implementation**:
- Opens PDF via `fitz.open()` in memory (uses `pdf_file.read()`)
- Iterates pages and calls `page.get_text("text")` (plain text mode)
- Joins pages with explicit form-feed separator `"\n\f\n"` for downstream normalization
- Returns single concatenated string with page markers

**Strengths**:
- Simple, direct API
- Preserves page structure via explicit separator (not arbitrary newlines)

**Weaknesses**:
- No error handling for malformed PDFs
- Reads entire PDF into memory (can OOM on very large files)
- No support for text extraction from images/scanned pages (fitz requires text layer)
- No customization (e.g., extraction mode, language parameters)

---

#### `extract_docx_text(docx_file) → str` (lines 36–53)
**Purpose**: Extract text from DOCX by reading paragraph content.

**Implementation**:
- Loads DOCX via `Document(docx_file)`
- Iterates `.paragraphs` collection and extracts `.text`
- Joins with same form-feed separator `"\n\f\n"`
- Returns concatenated string

**Strengths**:
- Handles standard DOCX structured format
- Preserves paragraph boundaries

**Weaknesses**:
- Ignores text in text boxes, shapes, headers/footers (only reads body paragraphs)
- Does NOT expose page boundaries (python-docx API limitation); pages are treated as groups of paragraphs
- **Mismatch with PDF**: PDF has explicit page breaks; DOCX does not → WER scores can differ between formats even for identical content

---

### 3.2 Normalization Pipeline

#### `normalize_text(text: str) → str` (lines 58–156)
**Purpose**: Apply production-quality preprocessing for OCR evaluation per industry best practices.

**Six-Step Normalization Process**:

1. **Unicode Normalization (NFKC)** (line 89)
   - **Why**: OCR systems may output characters in different unicode compositions (e.g., é as single codepoint vs e + combining accent). Without NFKC, identical-looking text scores differently in WER.
   - **Method**: `unicodedata.normalize("NFKC", text)`
   - **Rationale**: NFKC (compatibility decompose then compose) collapses ligatures (ﬁ→fi), normalizes diacritics, and handles width variants (full-width vs half-width Japanese/CJK).

2. **Line Break Normalization** (lines 92–93)
   - **Why**: PDFs, OCR outputs, and DOCXs may use different line ending conventions (CR, LF, CRLF). Inconsistent endings cause spurious word splits.
   - **Method**: Replace `\r\n` and `\r` with `\n`
   - **Rationale**: Standardize to Unix line endings for uniform tokenization.

3. **Page Separator Normalization** (lines 96–97)
   - **Why**: Preserve page boundaries from PDF extraction but normalize them across sources (PDF vs OCR TXT).
   - **Method**: Convert form-feed (`\f`) to explicit `<PAGE>` token; normalize with regex.
   - **Rationale**: Makes page breaks visible and consistent without treating them as content words.

4. **Metadata Removal** (lines 100–143)
   - **Why**: OCR export tools often prepend metadata headers (filename, pages, OCR method, page labels). This metadata is not document content and inflates WER if not removed.
   - **Method**: 
     - Define 9 regex patterns for common metadata lines (see `metadata_patterns` list)
     - Patterns match: `ocr output`, `ocr:`, `filename:`, `pages:`, `page_N`, separator lines (`---`), etc.
     - Conservative approach: only remove lines that match **complete line** patterns, not substring matches
   - **Rationale**: Avoids false positives (e.g., "Page 3 discusses..." is legitimate content; `PAGE_3` is metadata)

5. **Whitespace Collapsing** (lines 146–154)
   - **Why**: OCR may introduce spurious spaces, tabs, or irregular line breaks. PDFs and DOCXs handle whitespace inconsistently.
   - **Method**:
     - Collapse 3+ consecutive newlines to exactly 2 (preserve paragraph breaks)
     - Within paragraphs, collapse multiple spaces/tabs to single space
     - Replace `<PAGE>` token with `[PAGE]` for final output
   - **Rationale**: Normalizes whitespace variance without removing structural paragraph breaks.

6. **Lowercase & Strip** (lines 157–158)
   - **Why**: Case sensitivity can inflate WER (OCR capitalizing words, PDFs using title case, etc.). Lowercase for fair comparison.
   - **Method**: `.lower()` and `.strip()`
   - **Rationale**: Case-insensitive WER is standard for OCR evaluation; removes leading/trailing junk.

**Data Flow Through Normalization**:
```
Raw Text (mixed unicode, line endings, metadata, noise)
    ↓ NFKC normalize
Unicode-normalized (é, fi, diacritics uniform)
    ↓ Normalize line endings
LF-only line endings
    ↓ Normalize page separators
Explicit <PAGE> markers
    ↓ Remove metadata lines
No export headers/labels
    ↓ Collapse whitespace
Single spaces within paragraphs
    ↓ Lowercase + strip
Final normalized text (ready for WER)
```

**Production Quality Assessment**:
- ✅ Follows established OCR evaluation standards (Unicode NFKC, whitespace normalization, metadata removal)
- ✅ Conservative metadata removal (line-level patterns, not substring surgery)
- ✅ Well-documented rationale in docstring
- ⚠️ Metadata patterns may have false positives/negatives (edge cases exist)
- ⚠️ Hard-coded metadata patterns; not configurable

---

### 3.3 Accuracy Calculation

#### `calculate_ocr_accuracy(ground_truth: str, ocr_text: str) → Tuple[float, float]` (lines 161–179)
**Purpose**: Compute Word Error Rate (WER) and accuracy percentage from normalized text.

**Implementation**:
- Normalizes both inputs via `normalize_text()`
- Calls `jiwer.wer()` with normalized strings
- Returns `(error_rate, accuracy)` where accuracy = max(0, (1 - WER) * 100)

**Algorithm Details**:
- **WER (Word Error Rate)**: Computed by jiwer as (substitutions + insertions + deletions) / reference_word_count
  - Operates at **word level** (splits on whitespace)
  - Aligns sequences using dynamic programming (edit distance)
  - Range: 0 (perfect) to >1 (very poor)
- **Accuracy**: Percentage form; clamped to [0, 100]

**Example**:
```
Ground Truth: "the quick brown fox"
OCR Output:   "the quik brown fox"  (typo: "quick" → "quik")

After normalization: identical format
WER calculation: 1 substitution / 4 words = 0.25 (25% error)
Accuracy: (1 - 0.25) * 100 = 75%
```

---

### 3.4 UI Layer (Streamlit)

#### Tab 1: OCR Accuracy Validation (lines 167–226)
**Flow**:
1. User uploads PDF and OCR file (TXT or DOCX)
2. Click "Calculate Accuracy" button
3. Extract text from both files
4. Normalize and calculate WER
5. Display metrics (WER, Accuracy) in two-column layout
6. Show normalized previews (3000 char limit)
7. Render word-level diff with color coding (red=missing, green=extra)
8. Offer downloadable text report

**Code Quality**:
- ✅ Proper validation (check file uploads before processing)
- ✅ Graceful error handling (try/except for encoding fallback)
- ✅ User feedback (warning, error messages, success metrics)
- ⚠️ No timeout or file size limits
- ⚠️ No loading indicators for large files (appears frozen)

---

#### Tab 2: NER Validator (lines 228–267)
**Flow**:
1. User uploads `entities.csv` with `word,label` columns
2. Pastes sample text
3. Replace word occurrences with highlighted HTML
4. Display entity breakdown chart

**Implementation**:
- Simple string `.replace()` for each entity (substring matching)
- Color map for entity types (HERB, DISEASE, DOSHA, COMPOUND, SYMPTOM)
- pandas value_counts for breakdown

**Known Issues**:
- ⚠️ **Naive substring matching**: Will match "disease" inside "diseasement" or miss case variants
- ⚠️ **Order-dependent**: Entities processed in CSV order; if "herb" appears in "herbal", first match wins
- ⚠️ **No boundary detection**: Should use regex word boundaries `\b` for accurate NER

---

#### Tab 3: Relationship Validator (lines 269–330)
**Flow**:
1. User uploads `relationships.csv` with `subject,relation,object` columns
2. Iterate rows and generate Neo4j Cypher MERGE statements
3. Offer downloadable Cypher file

**Implementation**:
- Generate Cypher: `MERGE (a {name:"subject"}) MERGE (b {name:"object"}) MERGE (a)-[:RELATION]->(b);`
- Escape double quotes and convert relation to uppercase/underscores

**Security Risk**:
- ⚠️ **CSV Injection**: If CSV is untrusted, malicious values could break Cypher syntax or inject commands

---

## 4. Data Flow & Processing Pipeline

```
┌──────────────────────────────────────────────────────────┐
│ USER ACTION: Upload PDF + OCR File (Tab 1: OCR Accuracy) │
└──────────────────┬───────────────────────────────────────┘
                   ↓
┌──────────────────────────────────────────────────────────┐
│ Validation: Check files exist & are correct type          │
│ If fail → Show warning, return                            │
└──────────────────┬───────────────────────────────────────┘
                   ↓
        ┌──────────────────┬────────────────┐
        ↓                  ↓                ↓
   PDF File          TXT File          DOCX File
        ↓                  ↓                ↓
   extract_pdf_     Try UTF-8        extract_docx_
     text()         Fall back to        text()
        ↓              latin-1            ↓
        └──────────────────┬──────────────┘
                   ↓
        ┌──────────────────────────────────┐
        │ Raw texts (PDF + OCR)            │
        │ - Format: string with \n, \f    │
        │ - Content: pages + metadata     │
        └──────────┬───────────────────────┘
                   ↓
        ┌──────────────────────────────────┐
        │ calculate_ocr_accuracy()         │
        │ (calls normalize_text on both)   │
        └──────────┬───────────────────────┘
                   ↓
        ┌──────────────────────────────────┐
        │ normalize_text() — 6 steps       │
        │ 1. Unicode NFKC                 │
        │ 2. Line endings                 │
        │ 3. Page separators              │
        │ 4. Remove metadata              │
        │ 5. Collapse whitespace          │
        │ 6. Lowercase + strip            │
        │ → Normalized texts (identical   │
        │   format for comparison)        │
        └──────────┬───────────────────────┘
                   ↓
        ┌──────────────────────────────────┐
        │ jiwer.wer()                      │
        │ → WER score (float)              │
        └──────────┬───────────────────────┘
                   ↓
        ┌──────────────────────────────────┐
        │ Calculate accuracy (1 - WER)*100 │
        └──────────┬───────────────────────┘
                   ↓
   ┌────────────────────────────────────────────┐
   │ Render UI:                                  │
   │ - Metrics (WER %, Accuracy %)               │
   │ - Normalized previews (3000 char)           │
   │ - Word-level diff (red/green highlighting) │
   │ - Download button (text report)             │
   └────────────────────────────────────────────┘
```

---

## 5. Dependencies & Tech Stack

| Library | Version | Purpose | Risk |
|---------|---------|---------|------|
| **streamlit** | Latest (pinned) | Web UI framework, file upload, session state | Medium (web framework; potential XSS if markdown not sanitized) |
| **pandas** | Latest (pinned) | CSV parsing, entity counting | Low (data processing only) |
| **jiwer** | Latest (pinned) | WER calculation (edit distance algorithm) | Low (pure algorithm) |
| **pymupdf** (fitz) | Latest (pinned) | PDF text extraction | Medium (third-party binary; PDF parsing is complex) |
| **python-docx** | Latest (pinned) | DOCX text extraction | Low (open format, well-tested) |
| **Python stdlib** | 3.8+ | unicodedata, re, typing, difflib | None (standard library) |

**Dependency Lock Status**: ❌ **NOT pinned** (requirements.txt has no version specifiers)  
→ Risk: Compatibility issues on different machines or after package updates

---

## 6. Strengths

### ✅ Correct Normalization Pipeline
- Implements industry-standard OCR evaluation preprocessing (Unicode NFKC, line ending normalization, conservative metadata removal)
- Preserves real OCR errors while removing structural artifacts
- Well-documented rationale for each preprocessing step

### ✅ Multi-Format Support
- Accepts PDF, TXT, and DOCX inputs
- Graceful fallback for text encoding (UTF-8 → latin-1)

### ✅ Rich Visual Feedback
- Real-time metrics display (WER, Accuracy)
- Word-level diff with color coding (missing words in red, extra words in green)
- Normalized text previews to diagnose preprocessing issues
- Downloadable report for audit trail

### ✅ Clean Code Organization
- Functions are separated by concern (extraction, normalization, accuracy)
- Type hints on function signatures (e.g., `Tuple[float, float]`)
- Comprehensive docstrings explaining algorithm and rationale

### ✅ Production-Ready UI Patterns
- Tab-based navigation for feature separation
- File upload validation
- Metrics displayed in clean column layout
- Safe HTML rendering with Streamlit's `.markdown(unsafe_allow_html=True)`

---

## 7. Weaknesses

### ❌ Critical Issues

1. **No Error Handling for Extraction**
   - PDFs without text layer will silently return empty strings
   - No exception handling for corrupted PDF/DOCX files
   - User sees no error message; metrics appear as 0% or undefined

2. **Memory and Performance**
   - Entire files read into memory; will OOM on multi-GB PDFs
   - No streaming or chunking
   - No progress indicator (UI appears frozen on large files)

3. **Metadata Removal False Positives**
   - Patterns like `r"^\s*(pages?):\b.*$"` will remove legitimate text like "Pages: X and Y were analyzed"
   - Conservative approach but still risky

4. **DOCX ↔ PDF Mismatch**
   - `extract_pdf_text()` uses explicit form-feed separators for pages
   - `extract_docx_text()` has no page boundary concept (python-docx limitation)
   - WER scores will differ even for identical content if one is PDF and one is DOCX (page separator handling)

5. **No Reproducibility**
   - No version pinning in requirements.txt
   - No test suite to validate normalization behavior
   - Running on different machines/times may produce different results

### ⚠️ Code Quality Issues

6. **NER Validator Uses Naive Substring Matching**
   - `highlighted.replace(word, ...)` will:
     - Match "herb" inside "herbalist"
     - Miss case variants ("Herb" vs "herb")
     - Replace all occurrences (even if already highlighted)
   - Should use regex word boundaries: `\b{word}\b`

7. **Security: CSV Injection in Cypher Export**
   - If relationships CSV contains malicious values (e.g., `"` or `;`), could break Cypher syntax
   - Current escaping (`replace('"', "'")`) is insufficient for Cypher injection
   - Should use parameterized queries or rigorous validation

8. **Text Encoding Fallback Not Robust**
   - Falls back to `latin-1` for TXT decoding, but latin-1 silently accepts invalid bytes
   - Should use charset detection library (`chardet`, `charset-normalizer`) for accurate decoding

9. **No Input Validation**
   - No file size limits (risk of DoS via 100GB upload)
   - No validation of CSV schema (assumes `word,label` columns exist)
   - No timeout on extraction operations

10. **Hardcoded Configuration**
    - Metadata patterns, color map, and page separator token are hardcoded
    - Not configurable for different OCR tools or domains
    - No settings/options UI

### ⚠️ Missing Features

11. **No Persistence**
    - Results are lost on page refresh (Streamlit default behavior)
    - No history or comparison across multiple runs
    - No export of normalized texts (useful for debugging)

12. **No Logging or Monitoring**
    - No audit trail of what files were processed and when
    - No error telemetry
    - Cannot investigate failures post-hoc

13. **No Batch Processing**
    - Can only process one file pair at a time
    - No API or CLI for integration with pipelines

14. **Poor Mobile Experience**
    - Wide layout may not render well on mobile
    - File upload UI not optimized for mobile

---

## 8. Production Readiness Score

### **6/10** — Alpha/Beta, not production-ready

**Breakdown**:
- ✅ Core algorithm correct (normalization, WER): **8/10**
- ⚠️ Error handling: **3/10** (no error paths)
- ⚠️ Performance/scalability: **4/10** (no limits, no streaming)
- ⚠️ Security: **4/10** (CSV injection, encoding risks)
- ⚠️ Testing/reproducibility: **2/10** (no tests, no version pinning)
- ✅ UI/UX: **7/10** (clean, intuitive, but limited)
- ⚠️ Monitoring/ops: **1/10** (no logging, no dashboards)

**Verdict**: Suitable for **research, prototyping, or internal tooling**. Not suitable for **production SaaS** or **mission-critical QA pipelines** without further hardening.

---

## 9. Code Quality Assessment

### Pylint / Code Style
- ✅ PEP 8 compliant (indentation, naming)
- ✅ Type hints present (Tuple, str)
- ⚠️ Missing type hints in some places (UI layer variables)
- ✅ Docstrings comprehensive

### Complexity
- **Cyclomatic Complexity**: Low to medium
  - `normalize_text()` has nested loops and conditionals (moderate complexity)
  - `calculate_ocr_accuracy()` and extraction functions: trivial
  - UI layer: sequential (low complexity)

### Maintainability
- ✅ Code is readable and well-commented
- ❌ Single-file monolith (hard to test individual pieces)
- ❌ No modularization (impossible to reuse functions outside Streamlit context)

### Test Coverage
- ❌ **0% test coverage** (no test files present)
- No unit tests for `normalize_text()`, `extract_*()`, or `calculate_ocr_accuracy()`
- No fixtures or reference data

---

## 10. Security Concerns

### 🔴 High Priority

1. **CSV Injection (Tab 3: Relationship Validator)**
   - **Risk**: Malicious CSV can break Neo4j Cypher syntax or inject commands
   - **Example**: CSV with subject=`"abc"; DROP DATABASE neo4j; --`
   - **Impact**: If Cypher is executed, data loss
   - **Mitigation**: Parameterized queries; validate CSV structure

2. **Encoding Attack (Tab 1: TXT fallback)**
   - **Risk**: `decode("latin-1", errors="ignore")` silently corrupts multibyte encodings
   - **Example**: UTF-8 file misinterpreted as latin-1 → garbage text → bad WER
   - **Impact**: Silent data corruption
   - **Mitigation**: Use `chardet` or `charset-normalizer` for accurate detection

### 🟡 Medium Priority

3. **XSS via Streamlit Markdown** (Tab 1, 2: diff rendering)
   - **Risk**: If OCR output contains `<script>` tags, rendered as HTML
   - **Current Code**: `st.markdown(diff_html, unsafe_allow_html=True)`
   - **Impact**: Unlikely in practice (OCR outputs text, not code), but possible
   - **Mitigation**: Sanitize HTML or use `st.markdown(..., unsafe_allow_html=False)`

4. **DoS via Large File Upload** (All tabs)
   - **Risk**: User uploads 10GB PDF; app tries to load into memory → OOM crash
   - **Impact**: Service unavailability
   - **Mitigation**: Set `max_upload_size` in Streamlit config; implement streaming

### 🟢 Low Priority

5. **Information Disclosure** (Download buttons)
   - **Risk**: Downloaded files include normalized text with metadata removed
   - **Impact**: Minimal (user owns the data)
   - **Mitigation**: None needed

---

## 11. Scalability Concerns

### Current Limitations

1. **Single-Instance Only**
   - Streamlit is designed for single-user exploration; not designed for multi-user SaaS
   - Each user gets own process (horizontal scaling difficult)
   - Shared state not available

2. **No Caching**
   - Recomputes normalization on every interaction
   - No memoization of extraction results
   - Could be 10-100x slower than necessary

3. **File Size Limits**
   - PDFs >1GB will fail
   - No streaming or chunked processing

4. **Stateless Architecture**
   - No database for result history
   - No audit trail
   - Each run is ephemeral

### Recommendations for Scaling

- **For 10–100 users**: Deploy multiple Streamlit instances behind a load balancer; add Redis caching
- **For 100–10k users**: Migrate to FastAPI + React; add PostgreSQL for result history; implement Celery workers for async processing
- **For 10k+ users**: Microservices (extraction service, normalization service, diff rendering service); add message queue (RabbitMQ, Kafka)

---

## 12. Suggested Improvements (Priority Order)

### 🔴 P1: Critical (Do First)

1. **Add Error Handling**
   - Wrap extraction in try/except; catch PDF parse errors, DOCX errors
   - Show user-facing error messages

2. **Implement File Size Limits**
   - Add config parameter (max 500MB)
   - Reject files before processing
   - Display error to user

3. **Fix CSV Injection**
   - Validate CSV columns exist (`subject`, `relation`, `object`)
   - Use parameterized Cypher generation or OGM library

4. **Pin Dependencies**
   - Add version specifiers to requirements.txt (e.g., `streamlit==1.28.0`)

### 🟡 P2: High (Do Soon)

5. **Add Unit Tests**
   - Test `normalize_text()` with fixtures (clean text, metadata, unicode, line endings)
   - Test `extract_pdf_text()` and `extract_docx_text()` with sample files
   - Aim for 80% coverage

6. **Improve Text Encoding Handling**
   - Use `chardet` to detect encoding before decoding
   - Replace hardcoded latin-1 fallback

7. **Fix NER Highlighting**
   - Use regex with word boundaries: `re.sub(rf"\b{re.escape(word)}\b", ...)`
   - Handle case-insensitive matching

8. **Refactor into Modules**
   - Move extraction/normalization into `ocr_processor.py`
   - Move UI logic into `app.py`
   - Allow reuse outside Streamlit

### 🟢 P3: Nice-to-Have (Later)

9. **Add Logging**
   - Log processing time, file sizes, WER scores
   - Export to `app.log` or external service

10. **Add Progress Indicators**
    - Show progress bar for large files
    - Display processing time

11. **Implement Result History**
    - Store results in SQLite or PostgreSQL
    - Allow comparison across runs
    - Export results as CSV/JSON

12. **Add Configuration UI**
    - Allow users to customize metadata patterns
    - Toggle case sensitivity
    - Select normalization options (keep punctuation, preserve numbers, etc.)

13. **Support OCR-Specific Formats**
    - Add support for Tesseract HOCR output
    - Add support for ALTO XML (abbyy, calamari)
    - Parse confidence scores if available

---

## 13. Deployment Recommendations

### Local Development
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
# Open http://localhost:8501
```

### Docker Deployment (for consistent environments)
Create `Dockerfile`:
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .
EXPOSE 8501
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
```

Build and run:
```bash
docker build -t qa-validation-tool .
docker run -p 8501:8501 qa-validation-tool
```

### Cloud Deployment Options
- **Streamlit Cloud** (free tier): Deploy directly from GitHub repo; no infrastructure needed
- **Heroku**: Add `Procfile` and `runtime.txt`; deploy via git push
- **AWS**: EC2 instance + Streamlit; or use Elastic Beanstalk
- **GCP**: Cloud Run (serverless); auto-scales; pay per request

### Production Checklist
- ❌ Add HTTPS/TLS (use reverse proxy like Nginx)
- ❌ Add authentication (Streamlit Community Cloud or custom OAuth)
- ❌ Add rate limiting (protect against abuse)
- ❌ Add monitoring (APM, error tracking, logs)
- ❌ Set up CI/CD pipeline (GitHub Actions, GitLab CI)
- ❌ Document API/usage guidelines
- ❌ Add health check endpoint

---

## 14. Interview Questions & Answers

### Q1: "Walk me through the architecture. What does each function do?"

**Answer**:
The project is a single-file Streamlit app with three main layers:

1. **Extraction Layer** (`extract_pdf_text`, `extract_docx_text`):
   - Reads PDF or DOCX files and extracts text
   - Uses PyMuPDF for PDFs, python-docx for DOCX
   - Adds explicit page separators (`\f`) to preserve page structure

2. **Normalization Layer** (`normalize_text`):
   - Applies 6-step preprocessing: Unicode NFKC, line ending normalization, page separator handling, metadata removal, whitespace collapsing, and lowercasing
   - Follows industry-standard OCR evaluation practices to ensure fair comparison

3. **Accuracy Layer** (`calculate_ocr_accuracy`):
   - Normalizes both ground truth and OCR text
   - Computes Word Error Rate (WER) using the jiwer library
   - Returns WER and accuracy percentage

4. **UI Layer** (Streamlit tabs):
   - Tab 1: OCR Accuracy (upload PDF + OCR file, see metrics and diff)
   - Tab 2: NER Validator (highlight entities in sample text)
   - Tab 3: Relationship Validator (convert CSV to Neo4j Cypher)

The data flows: Upload → Extract → Normalize → Calculate → Render

---

### Q2: "Why is the metadata removal step necessary? Can't we just compare raw text?"

**Answer**:
If we compared raw OCR output directly against PDF text, the WER score would be artificially inflated by metadata that's not part of the document content. For example:

```
OCR Output (raw):
OCR OUTPUT - filename: scan_001.pdf
PAGES: 5
PAGE_1
This is the document content.
...
```

If we don't remove "OCR OUTPUT", "PAGES: 5", "PAGE_1", the WER calculation treats these as **missing words** in the PDF extract, even though they're not real OCR errors.

Our metadata removal is **conservative**: we only remove entire lines that match known patterns (like `OCR OUTPUT:`, `PAGE_\d+`, etc.). We don't substring-match, so legitimate content like "Page 3 of the report" isn't removed.

This way, the WER score measures **true OCR accuracy**, not artifact pollution.

---

### Q3: "Why use NFKC unicode normalization?"

**Answer**:
Unicode normalization ensures that visually identical characters are represented identically. For example:

- The letter `é` can be encoded as:
  - Single codepoint U+00E9 (composed)
  - `e` (U+0065) + combining acute accent (U+0301) (decomposed)

Without normalization, these appear identical on screen but are byte-different, causing WER to treat them as mismatches.

NFKC (Compatibility Decompose + Compose) goes further and:
- Normalizes ligatures: `ﬁ` → `fi`
- Normalizes width variants: full-width `Ａ` → half-width `A`
- Normalizes other compatibility issues

This is **standard practice** in NLP and OCR evaluation to ensure fair comparison.

---

### Q4: "What are the main security risks?"

**Answer**:
1. **CSV Injection** (Tab 3): If a relationship CSV contains malicious Cypher syntax (e.g., with embedded quotes or semicolons), it could break the export or inject commands.
2. **Text Encoding Attacks** (Tab 1): If we decode a multibyte encoding (e.g., UTF-8) as latin-1, we silently corrupt the text. Should use charset detection.
3. **Potential XSS** (Tab 1): We render HTML with `unsafe_allow_html=True`. If OCR output contained HTML/script tags, they'd be rendered. Unlikely in practice but risky.
4. **DoS via Large Files**: No file size limits; user could upload 100GB, crashing the app.

Mitigations:
- Parameterized Cypher queries or CSV validation
- Charset detection library
- Sanitize HTML before rendering (or disable `unsafe_allow_html`)
- Add max file size config

---

### Q5: "What makes this production-ready or not?"

**Answer**:
**Current Status: 6/10 (Beta)**

**Why it's good**:
- Core normalization algorithm is correct and industry-standard
- UI is clean and intuitive
- Error handling for most file formats
- Comprehensive docstrings

**Why it's not production-ready**:
- No error handling for extraction failures (e.g., corrupted PDFs)
- No file size limits (DoS risk)
- No logging or monitoring
- No test coverage
- Dependencies not version-pinned
- Single-user/single-instance (doesn't scale)
- No persistent result history

**To make it production-ready** (in priority order):
1. Add comprehensive error handling
2. Pin all dependencies
3. Add unit tests (~80% coverage)
4. Implement file size limits and timeouts
5. Add logging and monitoring
6. Refactor into modules for testability
7. Fix security issues (CSV injection, charset detection)
8. Add rate limiting and authentication
9. Migrate to FastAPI for multi-user support
10. Add PostgreSQL for result history

For a research project or internal tool, it's ready now. For a public SaaS, needs 2-3 weeks of hardening.

---

### Q6: "What's the difference between WER and accuracy?"

**Answer**:
- **WER (Word Error Rate)**: Percentage of words that are wrong (substituted, inserted, or deleted) relative to the reference text
  - Formula: `(sub + ins + del) / total_words * 100%`
  - Range: 0% (perfect) to >100% (very poor; extra words)
  
- **Accuracy**: `(1 - WER) * 100%`
  - Clamped to [0, 100]%
  - If WER > 100%, accuracy shown as 0%

Example:
```
Reference: "the quick brown fox" (4 words)
OCR:       "the quik brown fox"  (4 words)
           Substitution: "quick" → "quik" (1 error)
WER = 1/4 = 25%
Accuracy = (1 - 0.25) * 100 = 75%
```

WER is standard in OCR research; Accuracy is easier for non-technical users to understand.

---

### Q7: "Why is PDF extraction different from DOCX extraction?"

**Answer**:
- **PDF extraction** (`extract_pdf_text`):
  - PDFs are binary format with text layer (if OCR'd or digital-born)
  - We extract text page-by-page using PyMuPDF
  - Pages are physically delimited; we add explicit `\f` separators
  
- **DOCX extraction** (`extract_docx_text`):
  - DOCX is zipped XML format
  - python-docx API only exposes paragraphs, not page boundaries
  - We join paragraphs with `\f`, but page breaks may not be explicit
  
**The Problem**: If comparing a PDF-extracted file to a DOCX-extracted file, the page separator handling differs. This can inflate WER even for identical content.

**Solution**: Our `normalize_text()` converts `\f` to explicit `[PAGE]` markers, making handling uniform downstream. But the **extraction** mismatch remains a source of potential error.

Better solution: Detect page boundaries in DOCX via page break runs (harder to implement).

---

### Q8: "How does the NER highlighting work, and what are its limitations?"

**Answer**:
**Current Implementation** (Tab 2):
```python
for word in entities:
    highlighted = highlighted.replace(word, f"<mark>{word}</mark>")
```

**Limitations**:
1. **Naive substring matching**: Matches "herb" inside "herbalist"
2. **Case-sensitive**: Won't match "Herb" if entity is "herb"
3. **Order-dependent**: If entities list includes "herb" and "herbalist", process order matters
4. **Overlapping entities**: If one entity contains another, highlights both

**Better Approach** (not yet implemented):
```python
import re
pattern = r"\b" + re.escape(word) + r"\b"
highlighted = re.sub(pattern, f"<mark>{word}</mark>", highlighted, flags=re.IGNORECASE)
```

This uses regex word boundaries and case-insensitive matching.

For **nested entities** or **overlapping spans**, would need NLP tokenizer or custom entity resolution logic.

---

### Q9: "How would you scale this to handle 1000 users?"

**Answer**:
**Current**: Single-user Streamlit app; doesn't scale.

**For 1000 concurrent users**:

1. **Replace Streamlit with FastAPI**:
   - Streamlit boots a new Python interpreter per user
   - FastAPI handles concurrent requests in a thread/async pool
   - Reduces resource overhead 100x

2. **Add Caching Layer**:
   - Redis cache for normalized text (avoid recomputing)
   - Cache extraction results by file hash

3. **Async Processing**:
   - Long extractions (PDFs >100MB) handled by Celery workers
   - Return async job ID; user polls for results
   - Prevents blocking main server

4. **Horizontal Scaling**:
   - Multiple API instances behind load balancer (nginx)
   - Shared Redis/cache
   - PostgreSQL for persistent result history

5. **Database**:
   - Store extraction results, WER scores, user sessions
   - Enable result comparison and history

6. **Monitoring**:
   - APM (Application Performance Monitoring) tool
   - Log aggregation (ELK stack)
   - Error tracking (Sentry)

**Architecture**:
```
Load Balancer (nginx)
    ↓
API Instance 1 (FastAPI)  API Instance 2  API Instance 3
    ↓                           ↓              ↓
  Redis Cache ← ← ← → ← → PostgreSQL DB
    ↓
Celery Workers (extraction/normalization)
```

---

### Q10: "What would you improve if you had 2 weeks?"

**Answer** (in priority order):

**Week 1**:
- Add comprehensive error handling (try/except on extraction)
- Pin dependencies (requirements.txt with versions)
- Add unit tests (fixtures, normalize_text tests, 80% coverage)
- Fix CSV injection risk (validate CSV schema)
- Implement file size limits (config parameter)

**Week 2**:
- Refactor into modules (separate app.py, ocr_processor.py, etc.)
- Add charset detection for robust TXT decoding
- Fix NER regex (word boundaries, case-insensitive)
- Add logging (processing time, file sizes, errors)
- Add simple SQLite result history (persist across sessions)
- Deploy to Streamlit Cloud or Docker for testing

**Outcome**: Move from 6/10 (Beta) → 8/10 (Production-Ready for internal use).

For public SaaS, would need 4-6 more weeks (FastAPI migration, multi-tenancy, monitoring, etc.).

---

## 15. Summary Table: Project Snapshot

| Aspect | Status | Score |
|--------|--------|-------|
| **Core Algorithm** | ✅ Industry-standard | 8/10 |
| **Error Handling** | ❌ Minimal | 3/10 |
| **Performance** | ⚠️ Single-file, no caching | 4/10 |
| **Security** | ⚠️ CSV injection, encoding risks | 4/10 |
| **Testing** | ❌ No tests | 2/10 |
| **Code Quality** | ✅ Clean, documented | 7/10 |
| **UI/UX** | ✅ Intuitive, visual | 7/10 |
| **Deployment** | ✅ Works with Streamlit/Docker | 7/10 |
| **Scalability** | ❌ Single-instance only | 3/10 |
| **Documentation** | ⚠️ Good code docs, no user guide | 6/10 |
| **Overall** | **Beta** | **6/10** |

---

## 16. Conclusion

The **QA Validation Tool** is a **well-architected alpha-stage project** suitable for **research, prototyping, and internal QA workflows**. It implements a **correct, industry-standard OCR evaluation pipeline** with clean code and intuitive UI.

**For Academic/Interview Context**:
- Demonstrates understanding of OCR pipelines, normalization, and WER
- Shows good software engineering practices (modular functions, type hints, docstrings)
- Identifies scalability and security tradeoffs

**To Reach Production**:
- Harden error handling and add test coverage (Week 1)
- Address security risks and add monitoring (Week 1-2)
- Migrate to FastAPI for scalability (Month 2)
- Add persistent storage and multi-user support (Month 2)

**Recommended Talking Points for Professors/Recruiters**:
1. "This project implements an industry-standard OCR evaluation pipeline with 6-step normalization"
2. "I prioritized correctness over quick hacks (e.g., conservative metadata removal instead of aggressive regex)"
3. "I identified key production gaps: error handling, security, testing, scalability"
4. "I can scale this to 1000+ users by migrating from Streamlit to FastAPI + async workers"

---

**End of Technical Audit**
