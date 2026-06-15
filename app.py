import streamlit as st
import pandas as pd
from jiwer import wer
import difflib
import fitz  # PyMuPDF
from docx import Document
import unicodedata
import re
from typing import Tuple, List
from io import BytesIO
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

# ==================================================
# Extraction helpers
# ==================================================

def extract_pdf_text(pdf_file) -> str:
    page_separator = "\n\f\n"
    pdf = fitz.open(stream=pdf_file.read(), filetype="pdf")
    pages = []
    for page in pdf:
        pages.append(page.get_text("text"))
    return page_separator.join(pages)


def extract_docx_text(docx_file) -> str:
    doc = Document(docx_file)
    page_separator = "\n\f\n"
    paragraphs = []
    for para in doc.paragraphs:
        paragraphs.append(para.text)
    return page_separator.join(paragraphs)


# ==================================================
# Normalization
# ==================================================

def normalize_text(text: str) -> str:
    if text is None:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\f", "\n\f\n")
    text = re.sub(r"\n[ \t]*\f[ \t]*\n", "\n<PAGE>\n", text)

    metadata_patterns = [
        r"^\s*(ocr output)\b.*$",
        r"^\s*(ocr:)\b.*$",
        r"^\s*(filename|file):\b.*$",
        r"^\s*(pages?):\b.*$",
        r"^\s*(method|methods):\b.*$",
        r"^\s*PAGE[_\-]?\d+\b.*$",
        r"^\s*page[_\-]?\d+\b.*$",
        r"^\s*[-=]{3,}\s*$",
        r"^\s*text extracted by\b.*$",
    ]

    lines = text.split("\n")
    filtered_lines = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            filtered_lines.append("")
            continue
        is_metadata = any(re.match(pat, stripped, flags=re.IGNORECASE) for pat in metadata_patterns)
        if not is_metadata:
            filtered_lines.append(line)

    text = "\n".join(filtered_lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    paragraphs = [p.strip() for p in text.split("\n\n")]
    text = "\n\n".join([re.sub(r"\s+", " ", p) for p in paragraphs])
    text = text.replace("<PAGE>", "[PAGE]")
    text = text.lower().strip()
    return text


# ==================================================
# Accuracy calculation
# ==================================================

def calculate_ocr_accuracy(ground_truth: str, ocr_text: str) -> Tuple[float, float]:
    ground_truth = "" if ground_truth is None else str(ground_truth)
    ocr_text = "" if ocr_text is None else str(ocr_text)
    gt_norm = normalize_text(ground_truth)
    ocr_norm = normalize_text(ocr_text)
    error_rate = wer(gt_norm, ocr_norm)
    accuracy = max(0.0, (1 - error_rate) * 100)
    return error_rate, accuracy


def generate_word_comparison(gt_words: List[str], ocr_words: List[str]) -> pd.DataFrame:
    diff = list(difflib.ndiff(gt_words, ocr_words))
    comparison_data = []
    i = 0
    tokens = list(diff)
    while i < len(tokens):
        token = tokens[i]
        if token.startswith("  "):
            word = token[2:]
            comparison_data.append({
                "Ground Truth": word,
                "OCR Output": word,
                "Status": "Match"
            })
            i += 1
        elif token.startswith("- "):
            gt_word = token[2:]
            # Check if next token is an insertion → substitution
            if i + 1 < len(tokens) and tokens[i + 1].startswith("+ "):
                ocr_word = tokens[i + 1][2:]
                comparison_data.append({
                    "Ground Truth": gt_word,
                    "OCR Output": ocr_word,
                    "Status": "Substitution"
                })
                i += 2
            else:
                comparison_data.append({
                    "Ground Truth": gt_word,
                    "OCR Output": "[MISSING]",
                    "Status": "Deletion"
                })
                i += 1
        elif token.startswith("+ "):
            comparison_data.append({
                "Ground Truth": "[EXTRA]",
                "OCR Output": token[2:],
                "Status": "Insertion"
            })
            i += 1
        else:
            i += 1
    return pd.DataFrame(comparison_data)


def calculate_error_statistics(comparison_df: pd.DataFrame) -> dict:
    counts = comparison_df["Status"].value_counts().to_dict()
    return {
        "Matches":       counts.get("Match", 0),
        "Substitutions": counts.get("Substitution", 0),
        "Insertions":    counts.get("Insertion", 0),
        "Deletions":     counts.get("Deletion", 0),
    }


# ==================================================
# Excel report builder — 2 sheets matching screenshot
# ==================================================

def _thin_border():
    thin = Side(style="thin", color="CCCCCC")
    return Border(left=thin, right=thin, top=thin, bottom=thin)


def _apply_header_row(ws, row_num: int, header_fill_hex: str = "4472C4"):
    fill = PatternFill("solid", start_color=header_fill_hex, end_color=header_fill_hex)
    font = Font(bold=True, color="FFFFFF", name="Arial", size=10)
    for cell in ws[row_num]:
        cell.fill = fill
        cell.font = font
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = _thin_border()


def create_excel_report(
    ground_truth: str,
    ocr_text: str,
    accuracy: float,
    error_rate: float,
    source_filename: str = "uploaded file",
) -> bytes:
    """
    Produces a 2-sheet Excel workbook:

    Sheet 1 — OCR Accuracy Report
        Exactly matches the screenshot:
        | Metric               | Value  |
        | OCR Accuracy (%)     | 93.95  |
        | Word Error Rate (%)  | 6.05   |
        | Ground Truth Words   | 7023   |
        | OCR Words            | 7221   |
        Plus: Matches, Substitutions, Insertions, Deletions

    Sheet 2 — Word Comparison
        Exactly matches the screenshot second table:
        | Ground Truth | OCR Output   |   Status     |
        | word1        | word1        | Match        |
        | word2        | word2        | Match        |
        | word3        | wrong_word   | Substitution |
        Color-coded rows (green = match, red = substitution, orange = deletion/insertion)
    """
    gt_norm  = normalize_text(ground_truth)
    ocr_norm = normalize_text(ocr_text)
    gt_words  = gt_norm.split()
    ocr_words = ocr_norm.split()

    comparison_df = generate_word_comparison(gt_words, ocr_words)
    error_stats   = calculate_error_statistics(comparison_df)

    output = BytesIO()
    wb = openpyxl.Workbook()

    # ── SHEET 1: OCR Accuracy Report ──────────────────────────────────────────
    ws1 = wb.active
    ws1.title = "OCR Accuracy Report"

    # Title row
    ws1.merge_cells("A1:B1")
    title_cell = ws1["A1"]
    title_cell.value = "OCR ACCURACY REPORT"
    title_cell.font = Font(bold=True, color="FFFFFF", name="Arial", size=13)
    title_cell.fill = PatternFill("solid", start_color="1F3864", end_color="1F3864")
    title_cell.alignment = Alignment(horizontal="center", vertical="center")
    ws1.row_dimensions[1].height = 30

    # Sub-title / source
    ws1.merge_cells("A2:B2")
    ws1["A2"].value = f"Source: {source_filename}"
    ws1["A2"].font = Font(italic=True, color="555555", name="Arial", size=9)
    ws1["A2"].alignment = Alignment(horizontal="center")
    ws1.row_dimensions[2].height = 16

    # Blank row
    ws1.row_dimensions[3].height = 8

    # Header row (row 4)
    ws1["A4"] = "Metric"
    ws1["B4"] = "Value"
    _apply_header_row(ws1, 4)
    ws1.row_dimensions[4].height = 22

    # Data rows
    total_errors = (
        error_stats["Substitutions"]
        + error_stats["Insertions"]
        + error_stats["Deletions"]
    )

    metrics = [
        ("OCR Accuracy (%)",    round(accuracy, 2)),
        ("Word Error Rate (%)", round(error_rate * 100, 2)),
        ("Ground Truth Words",  len(gt_words)),
        ("OCR Words",           len(ocr_words)),
        ("Total Matches",       error_stats["Matches"]),
        ("Total Mismatches",    total_errors),
        ("Substitutions",       error_stats["Substitutions"]),
        ("Insertions",          error_stats["Insertions"]),
        ("Deletions",           error_stats["Deletions"]),
    ]

    # Color map for each metric row
    row_colors = {
        "OCR Accuracy (%)":    ("E2EFDA", "375623"),   # green bg, dark green text
        "Word Error Rate (%)": ("FCE4D6", "843C0C"),   # orange bg, dark orange text
        "Ground Truth Words":  ("DDEEFF", "1F3864"),
        "OCR Words":           ("DDEEFF", "1F3864"),
        "Total Matches":       ("E2EFDA", "375623"),
        "Total Mismatches":    ("FCE4D6", "843C0C"),
        "Substitutions":       ("FFF2CC", "7F6000"),
        "Insertions":          ("FCE4D6", "843C0C"),
        "Deletions":           ("FCE4D6", "843C0C"),
    }

    for r_offset, (metric_name, metric_val) in enumerate(metrics):
        excel_row = 5 + r_offset
        bg, fg = row_colors.get(metric_name, ("FFFFFF", "000000"))

        cell_a = ws1.cell(row=excel_row, column=1, value=metric_name)
        cell_b = ws1.cell(row=excel_row, column=2, value=metric_val)

        for cell in (cell_a, cell_b):
            cell.fill = PatternFill("solid", start_color=bg, end_color=bg)
            cell.font = Font(name="Arial", size=10, color=fg,
                             bold=(metric_name in ("OCR Accuracy (%)", "Word Error Rate (%)")))
            cell.border = _thin_border()
            cell.alignment = Alignment(horizontal="center" if cell.column == 2 else "left",
                                       vertical="center")
        ws1.row_dimensions[excel_row].height = 20

    # Column widths
    ws1.column_dimensions["A"].width = 28
    ws1.column_dimensions["B"].width = 18

    # ── SHEET 2: Word Comparison ───────────────────────────────────────────────
    ws2 = wb.create_sheet("Word Comparison")

    # Title
    ws2.merge_cells("A1:C1")
    ws2["A1"].value = "WORD COMPARISON — Ground Truth vs OCR Output"
    ws2["A1"].font = Font(bold=True, color="FFFFFF", name="Arial", size=12)
    ws2["A1"].fill = PatternFill("solid", start_color="1F3864", end_color="1F3864")
    ws2["A1"].alignment = Alignment(horizontal="center", vertical="center")
    ws2.row_dimensions[1].height = 28

    # Note row
    ws2.merge_cells("A2:C2")
    ws2["A2"].value = (
        f"Showing all {len(comparison_df):,} word comparisons  |  "
        f"Match = ✅ green  |  Substitution = 🔴 red  |  "
        f"Deletion = 🟡 orange  |  Insertion = 🟠 salmon"
    )
    ws2["A2"].font = Font(italic=True, color="444444", name="Arial", size=9)
    ws2["A2"].alignment = Alignment(horizontal="center")
    ws2.row_dimensions[2].height = 16

    # Blank
    ws2.row_dimensions[3].height = 6

    # Header
    ws2["A4"] = "Ground Truth"
    ws2["B4"] = "OCR Output"
    ws2["C4"] = "Status"
    _apply_header_row(ws2, 4)
    ws2.row_dimensions[4].height = 22

    # Status → fill colours
    status_fill = {
        "Match":        PatternFill("solid", start_color="C6EFCE", end_color="C6EFCE"),
        "Substitution": PatternFill("solid", start_color="FFC7CE", end_color="FFC7CE"),
        "Deletion":     PatternFill("solid", start_color="FFEB9C", end_color="FFEB9C"),
        "Insertion":    PatternFill("solid", start_color="FCE4D6", end_color="FCE4D6"),
    }
    status_font_color = {
        "Match":        "375623",
        "Substitution": "9C0006",
        "Deletion":     "7F6000",
        "Insertion":    "843C0C",
    }

    for r_offset, (_, data_row) in enumerate(comparison_df.iterrows()):
        excel_row = 5 + r_offset
        status = data_row["Status"]

        fill = status_fill.get(status, PatternFill("solid", start_color="FFFFFF", end_color="FFFFFF"))
        fcolor = status_font_color.get(status, "000000")

        for col_idx, col_key in enumerate(["Ground Truth", "OCR Output", "Status"], start=1):
            cell = ws2.cell(row=excel_row, column=col_idx, value=data_row[col_key])
            cell.fill = fill
            cell.font = Font(name="Arial", size=9, color=fcolor)
            cell.border = _thin_border()
            cell.alignment = Alignment(horizontal="center", vertical="center")
        ws2.row_dimensions[excel_row].height = 16

    # Freeze panes so header stays visible while scrolling
    ws2.freeze_panes = "A5"

    # Column widths
    ws2.column_dimensions["A"].width = 30
    ws2.column_dimensions["B"].width = 30
    ws2.column_dimensions["C"].width = 18

    output_bytes = output.getvalue()
    wb.save(output)
    return output.getvalue()


# ==================================================
# Streamlit UI
# ==================================================

st.set_page_config(page_title="MedYukthee QA Tool", layout="wide")
st.title("MedYukthee QA Validation Tool")

tab1, tab2, tab3 = st.tabs([
    "📄 OCR Accuracy (QA-01)",
    "🏷️ NER Validator (QA-02)",
    "🔗 Relationship Reviewer (QA-03 + DB-02)",
])

# ══════════════════════════════════════════════════════════════════
# TAB 1 — OCR Accuracy (QA-01)
# ══════════════════════════════════════════════════════════════════
with tab1:
    st.subheader("OCR Accuracy Validation")
    st.write("Upload the **Original PDF** and the **OCR output text file**. "
             "The tool will generate two Excel report sheets.")

    col_up1, col_up2 = st.columns(2)
    with col_up1:
        original_pdf = st.file_uploader("📂 Upload Original PDF (Ground Truth)", type=["pdf"], key="pdf")
    with col_up2:
        ocr_file = st.file_uploader("📂 Upload OCR Output (.txt or .docx)", type=["txt", "docx"], key="ocr")

    if st.button("▶ Calculate Accuracy & Generate Reports", type="primary"):
        if not original_pdf or not ocr_file:
            st.warning("Please upload both files before calculating.")
        else:
            with st.spinner("Analysing OCR accuracy..."):
                ground_truth = extract_pdf_text(original_pdf)

                if ocr_file.name.lower().endswith(".txt"):
                    raw = ocr_file.read()
                    try:
                        ocr_text = raw.decode("utf-8")
                    except Exception:
                        ocr_text = raw.decode("latin-1", errors="ignore")
                elif ocr_file.name.lower().endswith(".docx"):
                    ocr_text = extract_docx_text(ocr_file)
                else:
                    st.error("Unsupported OCR file format.")
                    st.stop()

                error_rate, accuracy = calculate_ocr_accuracy(ground_truth, ocr_text)

                gt_norm   = normalize_text(ground_truth)
                ocr_norm  = normalize_text(ocr_text)
                gt_words  = gt_norm.split()
                ocr_words = ocr_norm.split()

                comparison_df = generate_word_comparison(gt_words, ocr_words)
                error_stats   = calculate_error_statistics(comparison_df)

            # ── Metric cards ──────────────────────────────────────────────────
            st.markdown("---")
            st.markdown("### 📊 Report 1 — OCR Accuracy Summary")

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("OCR Accuracy",      f"{accuracy:.2f}%")
            m2.metric("Word Error Rate",   f"{error_rate * 100:.2f}%")
            m3.metric("Ground Truth Words", f"{len(gt_words):,}")
            m4.metric("OCR Words",          f"{len(ocr_words):,}")

            e1, e2, e3, e4 = st.columns(4)
            e1.metric("✅ Matches",       f"{error_stats['Matches']:,}")
            e2.metric("🔄 Substitutions", f"{error_stats['Substitutions']:,}")
            e3.metric("➕ Insertions",    f"{error_stats['Insertions']:,}")
            e4.metric("➖ Deletions",     f"{error_stats['Deletions']:,}")

            # Summary table (mirrors Sheet 1 of the Excel)
            summary_data = {
                "Metric": [
                    "OCR Accuracy (%)",
                    "Word Error Rate (%)",
                    "Ground Truth Words",
                    "OCR Words",
                    "Total Matches",
                    "Total Mismatches",
                    "Substitutions",
                    "Insertions",
                    "Deletions",
                ],
                "Value": [
                    round(accuracy, 2),
                    round(error_rate * 100, 2),
                    len(gt_words),
                    len(ocr_words),
                    error_stats["Matches"],
                    error_stats["Substitutions"] + error_stats["Insertions"] + error_stats["Deletions"],
                    error_stats["Substitutions"],
                    error_stats["Insertions"],
                    error_stats["Deletions"],
                ],
            }
            st.dataframe(pd.DataFrame(summary_data), use_container_width=True, hide_index=True)

            # ── Word comparison preview ───────────────────────────────────────
            st.markdown("---")
            st.markdown("### 📋 Report 2 — Word Comparison (Ground Truth vs OCR Output)")

            # Colour-map for display
            def highlight_status(row):
                color_map = {
                    "Match":        "background-color: #C6EFCE; color: #375623",
                    "Substitution": "background-color: #FFC7CE; color: #9C0006",
                    "Deletion":     "background-color: #FFEB9C; color: #7F6000",
                    "Insertion":    "background-color: #FCE4D6; color: #843C0C",
                }
                style = color_map.get(row["Status"], "")
                return [style, style, style]

            preview_df = comparison_df.head(200).reset_index(drop=True)
            st.dataframe(
                preview_df.style.apply(highlight_status, axis=1),
                use_container_width=True,
                height=400,
            )

            if len(comparison_df) > 200:
                st.info(
                    f"Showing first 200 of **{len(comparison_df):,}** word comparisons. "
                    "Full data is in the downloaded Excel file (all rows included)."
                )

            # ── Inline diff view ─────────────────────────────────────────────
            st.markdown("---")
            st.markdown("### 🔍 Inline Diff View")
            diff_tokens = difflib.ndiff(gt_words[:500], ocr_words[:500])
            diff_html = ""
            for token in diff_tokens:
                if token.startswith("  "):
                    diff_html += f"{token[2:]} "
                elif token.startswith("- "):
                    diff_html += (
                        f'<span style="background:#FFC7CE;border-radius:3px;'
                        f'padding:1px 3px;margin:1px">{token[2:]}</span> '
                    )
                elif token.startswith("+ "):
                    diff_html += (
                        f'<span style="background:#C6EFCE;border-radius:3px;'
                        f'padding:1px 3px;margin:1px">{token[2:]}</span> '
                    )
            st.markdown(
                f'<div style="line-height:2;font-size:13px;font-family:monospace">{diff_html}</div>',
                unsafe_allow_html=True,
            )

            # ── Download — Excel with 2 sheets ───────────────────────────────
            st.markdown("---")
            excel_bytes = create_excel_report(
                ground_truth, ocr_text, accuracy, error_rate,
                source_filename=original_pdf.name,
            )

            st.success(
                "✅ Excel report ready — **2 sheets inside**: "
                "*Sheet 1 = OCR Accuracy Report* · *Sheet 2 = Word Comparison*"
            )

            st.download_button(
                label="📥 Download Excel Report (.xlsx) — 2 Sheets",
                data=excel_bytes,
                file_name="ocr_accuracy_report.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

            # Also offer plain text report (matches Abna's existing .txt format)
            txt_report = (
                f"OCR ACCURACY REPORT\n"
                f"{'='*30}\n"
                f"OCR Accuracy : {accuracy:.2f} %\n"
                f"Word Error Rate : {error_rate * 100:.2f} %\n\n"
                f"Ground Truth Words : {len(gt_words)}\n"
                f"OCR Words : {len(ocr_words)}\n\n"
                f"Matches       : {error_stats['Matches']}\n"
                f"Substitutions : {error_stats['Substitutions']}\n"
                f"Insertions    : {error_stats['Insertions']}\n"
                f"Deletions     : {error_stats['Deletions']}\n"
            )
            st.download_button(
                label="📄 Download Text Report (.txt)",
                data=txt_report,
                file_name="ocr_accuracy_report.txt",
                mime="text/plain",
            )

# ══════════════════════════════════════════════════════════════════
# TAB 2 — NER Validator (QA-02)
# ══════════════════════════════════════════════════════════════════
with tab2:
    st.subheader("NER Entity Validator")
    st.write("Upload entities.csv with columns: **word, label**")

    ner_file = st.file_uploader("Upload entities.csv", type="csv", key="ner")
    sample_text = st.text_area("Paste Sample Text to Highlight Entities", height=150)

    colors = {
        "HERB":      "#c8f7c5",
        "DISEASE":   "#fad7d7",
        "DOSHA":     "#ddd5f7",
        "COMPOUND":  "#fef3c7",
        "SYMPTOM":   "#ffe4b5",
        "PROCEDURE": "#d0f0fd",
    }

    if ner_file is not None and sample_text:
        df = pd.read_csv(ner_file)
        df["word"]  = df["word"].astype(str)
        df["label"] = df["label"].str.upper()
        st.success(f"Loaded {df.shape[0]} entities")

        highlighted = sample_text
        for _, row in df.iterrows():
            word  = row["word"]
            label = row["label"]
            color = colors.get(label, "#e5e7eb")
            highlighted = highlighted.replace(
                word,
                f'<mark style="background:{color};padding:2px 5px;'
                f'border-radius:4px;font-weight:500" title="{label}">{word}</mark>',
            )

        st.subheader("Highlighted Entities")
        st.markdown(
            f'<div style="line-height:2.2;font-size:14px">{highlighted}</div>',
            unsafe_allow_html=True,
        )

        # Legend
        st.markdown("---")
        leg_cols = st.columns(len(colors))
        for i, (lbl, col) in enumerate(colors.items()):
            leg_cols[i].markdown(
                f'<span style="background:{col};padding:3px 10px;'
                f'border-radius:4px;font-size:12px">{lbl}</span>',
                unsafe_allow_html=True,
            )

        st.subheader("Entity Breakdown")
        entity_counts = df["label"].value_counts().reset_index()
        entity_counts.columns = ["Entity Type", "Count"]
        st.dataframe(entity_counts, use_container_width=True)

        # F1 section
        st.markdown("---")
        st.subheader("F1 Score Validation")
        st.write("Upload your manually labelled ground truth to calculate F1 score.")
        gt_file = st.file_uploader("Upload ground_truth.csv (word, label)", type="csv", key="gt")

        if gt_file:
            from sklearn.metrics import classification_report
            df_gt = pd.read_csv(gt_file)
            df_gt["word"]  = df_gt["word"].str.lower().str.strip()
            df_gt["label"] = df_gt["label"].str.upper().str.strip()
            df["word"]     = df["word"].str.lower().str.strip()

            merged = pd.merge(df_gt, df, on="word", suffixes=("_true", "_pred"))
            if merged.empty:
                st.warning("No matching words found between the two files.")
            else:
                report = classification_report(
                    merged["label_true"], merged["label_pred"],
                    output_dict=True, zero_division=0,
                )
                report_df = pd.DataFrame(report).T.round(2)
                st.dataframe(report_df, use_container_width=True)
                overall_f1 = report.get("weighted avg", {}).get("f1-score", 0)
                st.metric("Overall F1 Score", f"{overall_f1:.2f}")
                if overall_f1 >= 0.8:
                    st.success("Good NER performance!")
                elif overall_f1 >= 0.6:
                    st.warning("Moderate — some improvement possible.")
                else:
                    st.error("Low performance — model may need retraining.")

                csv_bytes = report_df.to_csv().encode()
                st.download_button(
                    "📥 Download F1 Report (CSV)", csv_bytes,
                    "ner_f1_report.csv", "text/csv",
                )

# ══════════════════════════════════════════════════════════════════
# TAB 3 — Relationship Reviewer + Neo4j (QA-03 + DB-02)
# ══════════════════════════════════════════════════════════════════
with tab3:
    st.subheader("Relationship Reviewer + Neo4j Export")
    st.write("Upload **relationships.csv** (columns: subject, relation, object)")

    rel_file = st.file_uploader("Upload relationships.csv", type="csv", key="rel")

    if rel_file:
        if "rel_df" not in st.session_state or st.session_state.get("loaded_file") != rel_file.name:
            df_rel = pd.read_csv(rel_file)
            df_rel["validated"] = ""
            st.session_state["rel_df"]      = df_rel
            st.session_state["loaded_file"] = rel_file.name

        df_rel  = st.session_state["rel_df"]
        total   = len(df_rel)
        reviewed = (df_rel["validated"] != "").sum()

        st.progress(int(reviewed) / total, text=f"Progress: {int(reviewed)} of {total} reviewed")

        c1, c2, c3 = st.columns(3)
        c1.metric("Total",    total)
        c2.metric("✅ Correct", int((df_rel["validated"] == "correct").sum()))
        c3.metric("❌ Wrong",   int((df_rel["validated"] == "wrong").sum()))

        st.markdown("---")
        pending = df_rel[df_rel["validated"] == ""]

        if not pending.empty:
            idx = pending.index[0]
            row = df_rel.loc[idx]

            st.markdown("### Is this relationship correct?")
            st.markdown(
                f'<div style="background:var(--secondary-background-color);'
                f'border-radius:12px;padding:20px;text-align:center;margin:10px 0">'
                f'<span style="font-size:20px;font-weight:600">{row["subject"]}</span>'
                f'<span style="font-size:14px;color:#888;margin:0 14px;font-style:italic">'
                f'── {row["relation"]} ──▶</span>'
                f'<span style="font-size:20px;font-weight:600">{row["object"]}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )

            b1, b2, b3 = st.columns([2, 2, 1])
            if b1.button("✅  Correct", use_container_width=True):
                st.session_state["rel_df"].at[idx, "validated"] = "correct"
                st.rerun()
            if b2.button("❌  Wrong", use_container_width=True):
                st.session_state["rel_df"].at[idx, "validated"] = "wrong"
                st.rerun()
            if b3.button("⏭ Skip", use_container_width=True):
                st.session_state["rel_df"].at[idx, "validated"] = "skip"
                st.rerun()
        else:
            st.success("All relationships reviewed!")

        st.markdown("---")
        validated_df = df_rel[df_rel["validated"] == "correct"]
        st.subheader(f"Validated Relationships ({len(validated_df)})")
        if not validated_df.empty:
            st.dataframe(
                validated_df[["subject", "relation", "object"]],
                use_container_width=True,
            )

            # Cypher export
            st.markdown("---")
            st.subheader("Neo4j Cypher Export (DB-02)")
            cypher_lines = [
                "// MedYukthee AI — Validated Ayurveda Knowledge Graph",
                "// Generated by QA Validation Tool", "",
            ]
            for _, r in validated_df.iterrows():
                s   = str(r["subject"]).replace('"', "'").strip()
                rel = str(r["relation"]).upper().replace(" ", "_").strip()
                o   = str(r["object"]).replace('"', "'").strip()
                cypher_lines.append(
                    f'MERGE (a:Entity {{name:"{s}"}}) '
                    f'MERGE (b:Entity {{name:"{o}"}}) '
                    f'MERGE (a)-[:{rel}]->(b);'
                )
            cypher_text = "\n".join(cypher_lines)
            st.code(cypher_text, language="cypher")

            st.download_button(
                "📥 Download Neo4j Cypher File",
                cypher_text,
                "medyukthee_validated.cypher",
                "text/plain",
            )
            st.download_button(
                "📥 Download Validated CSV",
                validated_df.to_csv(index=False).encode(),
                "validated_relationships.csv",
                "text/csv",
            )

            # Graph schema reference
            st.markdown("---")
            st.subheader("Neo4j Graph Schema (DB-02)")
            st.markdown("""
**Node Types:** `Herb` · `Disease` · `Dosha` · `Compound`

**Relationship Types:**
- `Herb` **TREATS** `Disease`
- `Herb` **BALANCES** `Dosha`
- `Herb` **CONTAINS** `Compound`
- `Herb` **IMPROVES** Condition
- `Herb` **PREVENTS** `Disease`
            """)
        else:
            st.info("Validate some relationships above to enable export.")
