# QA Validation Tool

A production-quality Streamlit application for **OCR accuracy validation**, **NER entity highlighting**, and **knowledge graph relationship extraction**.

## 🎯 Project Purpose

Validate OCR (Optical Character Recognition) output quality in medical document digitization pipelines. Compares OCR-generated text against ground-truth PDFs using industry-standard normalization and word error rate (WER) metrics.

## ✨ Key Features

### 1. **OCR Accuracy Validation** (QA-01)
- Upload original PDF and OCR-generated text (TXT or DOCX)
- Automatic text normalization (Unicode NFKC, whitespace, metadata removal)
- Word Error Rate (WER) and accuracy percentage metrics
- Visual word-level diff with color-coded errors (red=missing, green=extra)
- Downloadable audit report

### 2. **NER Entity Validator** (QA-02)
- Upload entity CSV with `word` and `label` columns
- Highlight entity occurrences in sample text
- Entity type distribution chart
- Support for medical domain labels: HERB, DISEASE, DOSHA, COMPOUND, SYMPTOM

### 3. **Relationship Validator + Neo4j Export** (QA-03)
- Upload relationship CSV with `subject`, `relation`, `object` columns
- Auto-generate Neo4j Cypher MERGE statements
- Download `.cypher` file for direct database import

## 🛠 Tech Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **UI Framework** | Streamlit | Interactive web interface |
| **PDF Extraction** | PyMuPDF (fitz) | Extract text from PDF files |
| **DOCX Extraction** | python-docx | Extract text from Word documents |
| **OCR Metrics** | Jiwer | Word Error Rate calculation |
| **Data Processing** | Pandas | CSV parsing and entity analysis |
| **Text Processing** | unicodedata, re | Unicode normalization, regex |
| **Language** | Python 3.8+ | Core implementation |

## 📊 Normalization Pipeline

The tool implements a **6-step industry-standard OCR normalization pipeline**:

1. **Unicode Normalization (NFKC)**: Collapse visually-equivalent characters
2. **Line Break Normalization**: Convert CR/CRLF to LF
3. **Page Separator Handling**: Explicit page boundary markers
4. **Metadata Removal**: Conservative removal of OCR export headers
5. **Whitespace Collapsing**: Normalize spaces and paragraph breaks
6. **Lowercasing**: Case-insensitive comparison

See [TECHNICAL_AUDIT.md](TECHNICAL_AUDIT.md#32-normalization-pipeline) for detailed rationale.

## 🚀 Quick Start

### Prerequisites
- Python 3.8+
- pip or conda

### Installation

1. **Clone or download this repository**

2. **Create virtual environment**:
```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. **Install dependencies**:
```bash
pip install -r requirements.txt
```

4. **Run the app**:
```bash
streamlit run app.py
```

5. **Open in browser**:
```
http://localhost:8501
```

## 📝 Usage Examples

### Example 1: Validate OCR Accuracy
1. Go to **OCR Accuracy (QA-01)** tab
2. Upload:
   - Original PDF (ground truth)
   - OCR output (TXT or DOCX)
3. Click **Calculate Accuracy**
4. View metrics and color-coded diff
5. Download report for audit trail

### Example 2: Highlight Medical Entities
1. Go to **NER Validator (QA-02)** tab
2. Prepare `entities.csv`:
   ```csv
   word,label
   turmeric,HERB
   fever,SYMPTOM
   dosage,COMPOUND
   ```
3. Upload CSV and paste sample text
4. See highlighted entities and distribution chart

### Example 3: Generate Neo4j Cypher
1. Go to **Relationship Reviewer (QA-03)** tab
2. Prepare `relationships.csv`:
   ```csv
   subject,relation,object
   turmeric,treats,inflammation
   ginger,complements,turmeric
   ```
3. Upload CSV → auto-generated Cypher
4. Download and import into Neo4j

## 🏗 Architecture

- **Single-file monolithic design** (`app.py`)
- **Functional programming model**: Pure functions for extraction, normalization, accuracy calculation
- **Stateless Streamlit UI**: Each interaction is independent
- **No persistent storage** (current version)

See [TECHNICAL_AUDIT.md](TECHNICAL_AUDIT.md#2-architecture-overview) for full architecture details.

## 📋 Files & Responsibilities

| File | Purpose | Key Functions |
|------|---------|---------------|
| `app.py` | Main application | `extract_pdf_text()`, `extract_docx_text()`, `normalize_text()`, `calculate_ocr_accuracy()` |
| `requirements.txt` | Dependencies | Pinned package versions |
| `README.md` | This file | User and developer guide |
| `TECHNICAL_AUDIT.md` | Architecture deep-dive | Full technical assessment |

## ⚠️ Known Limitations

1. **No persistent history**: Results lost on page refresh
2. **Single-instance only**: Not designed for multi-user production
3. **Memory constraints**: Large PDFs (>500MB) may cause OOM
4. **DOCX page boundaries**: Python-docx doesn't expose page breaks; workaround uses paragraph grouping
5. **NER matching**: Current implementation uses substring matching (can match partial words)

See [TECHNICAL_AUDIT.md](TECHNICAL_AUDIT.md#7-weaknesses) for complete list and mitigation strategies.

## 🔒 Security Considerations

- **CSV Injection**: User CSV values are minimally validated before Cypher generation
- **File Upload**: No file size limits; DoS risk on very large uploads
- **Text Encoding**: Fallback to `latin-1` may corrupt multibyte encodings

See [TECHNICAL_AUDIT.md](TECHNICAL_AUDIT.md#10-security-concerns) for details and fixes.

## 📈 Production Readiness

**Current Score: 6/10 (Beta)**

**Suitable for**: Research, prototyping, internal QA  
**Not suitable for**: Public SaaS, mission-critical pipelines

**To reach production (6/10 → 8/10)**:
- Add error handling and file size limits
- Add unit tests (80%+ coverage)
- Pin all dependency versions
- Fix security issues (CSV validation, charset detection)
- Add logging and monitoring

See [TECHNICAL_AUDIT.md](TECHNICAL_AUDIT.md#12-suggested-improvements-priority-order) for prioritized improvement roadmap.

## 🚢 Deployment

### Local Development
```bash
streamlit run app.py
```

### Docker
```bash
docker build -t qa-validation-tool .
docker run -p 8501:8501 qa-validation-tool
```

### Streamlit Cloud (Free)
1. Push repo to GitHub
2. Go to https://share.streamlit.io/
3. Link GitHub repo
4. App runs on Streamlit's servers

### Production (AWS/GCP/Azure)
See [TECHNICAL_AUDIT.md](TECHNICAL_AUDIT.md#13-deployment-recommendations) for cloud deployment options.

## 📚 Documentation

- **[TECHNICAL_AUDIT.md](TECHNICAL_AUDIT.md)**: Complete architecture, code quality, security, and scalability assessment (20+ pages)
- **[INTERVIEW_GUIDE.md](INTERVIEW_GUIDE.md)**: Structured Q&A for explaining project to professors, recruiters, and internship reviewers

## 🤝 Contributing

This is a research/internship project. For suggestions or improvements:
1. Open an issue describing the problem
2. Submit a pull request with a fix

## 📞 Contact & Support

For questions about this project, refer to the technical documentation or contact the project author.

## 📄 License

[Specify license if open-source, or "Internal Use" if proprietary]

---

**Last Updated**: 2026-06-14  
**Status**: Alpha/Beta  
**Maintainer**: [Your Name/Team]
