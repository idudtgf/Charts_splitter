import pdfplumber
from PyPDF2 import PdfReader, PdfWriter
import os
import re
import unicodedata
import tkinter as tk
from tkinter import filedialog

# File explorer to select PDF
def select_pdf_file():
    root = tk.Tk()
    root.withdraw()
    file_path = filedialog.askopenfilename(
        title="Select Aviation Chart PDF",
        filetypes=[("PDF files", "*.pdf")]
    )
    root.destroy()
    return file_path

# Get PDF path from file explorer
pdf_path = select_pdf_file()
if not pdf_path:
    print("❌ No file selected. Exiting.")
    exit()

# Extract ICAO code from filename (e.g., GMAD from GMAD.pdf)
icao_code = os.path.splitext(os.path.basename(pdf_path))[0].upper()
# Create output folder named after ICAO code
output_folder = os.path.join(os.path.dirname(pdf_path), icao_code)
os.makedirs(output_folder, exist_ok=True)

reader = PdfReader(pdf_path)

# Clean and format text for filenames
def sanitize_title(text, max_length=100):
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode()
    text = re.sub(r'[\\/:"*?<>|]+', '-', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:max_length] if text else "Untitled"

# Check if page is rotated
def is_page_rotated(page):
    rotate = page.get('/Rotate', 0)
    if rotate in [90, 270]:
        return True
    # Fallback: check dimensions (portrait vs landscape)
    mediabox = page.get('/MediaBox', [0, 0, 612, 792])  # Default US Letter
    width, height = mediabox[2] - mediabox[0], mediabox[3] - mediabox[1]
    return width > height  # Landscape suggests rotation

# Extract text, handling rotation
def extract_text_with_rotation(pdfplumber_page, pypdf_page):
    if is_page_rotated(pypdf_page):
        # Use pdfplumber's crop and rotate for rotated pages
        bbox = pdfplumber_page.bbox
        # Crop to main content area, rotate to normalize
        cropped_page = pdfplumber_page.crop(bbox, relative=False)
        text = cropped_page.extract_text(layout=True)
        # Clean up fragmented text
        text = re.sub(r'\n\s*\n+', '\n', text).strip()
    else:
        text = pdfplumber_page.extract_text() or ""
    return text

# Define patterns to match common chart titles
def extract_chart_title(text):
    chart_patterns = [
        # STARs with identifiers and runway (e.g., AGALI 2A RWY 27, BUVAG 3B RWY 09L)
        r"(?:\.STAR\.|\bSTAR\b).*?([A-Z]{3,6}\s*\d[A-Z])(?:.*?RWY\s*(\d{2}[LR]?))?",
        # SIDs with identifiers and runway (e.g., KEGAG 1B RWY 27, DRAKE 2F RWY 09R)
        r"(?:\.SID\.|\bSID\b).*?([A-Z]{3,6}\s*\d[A-Z])(?:.*?RWY\s*(\d{2}[LR]?))?",
        # Approaches (e.g., ILS RWY 27, RNAV Z RWY 09L, VOR DME RWY 36)
        r"(ILS|LOC|VOR|NDB|RNAV|RNP|CAT II|CAT III)(?: [XYZ])?(?: or [A-Z]+)* Rwy (\d{2}[LR]?(?:/\d{2}[LR]?)?)(?: \([A-Z]+\))?",
        # Departure procedures
        r"(?:Climb STRAIGHT AHEAD|Departure Procedure).*?RWY (\d{2}[LR]?)",
        # Radar minimums
        r"\.RADAR\.MINIMUM\.ALTITUDES|Radar Minimum Altitudes",
        # Ground charts / diagrams
        r"(?:Parking Stands?|Apron|Stand|Gate|Taxiway).*?Coords",
        r"Low Visibility (?:Take-off|Procedures)",
        r"Control Tower.*?\b[A-Z]{4}\b",
        r"Airport (?:Diagram|Chart|Layout)",
        # Communication charts
        r"(?:D-ATIS|ATIS|Communications).*?\b[A-Z]{4}\b",
        # Noise abatement
        r"Noise Abatement(?: Procedures)?",
        # Admin/info pages
        r"Airport Information For \b[A-Z]{4}\b",
        r"Trip Kit Index",
        r"Terminal Chart Change Notices",
        r"Revision Letter.*Cycle.*",
        # Chart codes (e.g., 10-2A, 11-2, 20-3B)
        r"\b((?:10|11|20|30)-\d[A-Z]?)\b",
    ]

    for pattern in chart_patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            # Handle STARs
            if "STAR" in pattern:
                identifier = match.group(1).replace(' ', '')  # e.g., AGALI2A
                runway = match.group(2) or "Unknown"
                return sanitize_title(f"STAR {identifier} RWY {runway}")
            # Handle SIDs
            if "SID" in pattern:
                identifier = match.group(1).replace(' ', '')  # e.g., KEGAG1B
                runway = match.group(2) or "Unknown"
                return sanitize_title(f"SID {identifier} RWY {runway}")
            # Handle approaches
            if any(x in pattern for x in ["ILS", "LOC", "VOR", "NDB", "RNAV", "RNP"]):
                approach_type = match.group(1)
                runway = match.group(2)
                return sanitize_title(f"{approach_type} RWY {runway}")
            # Handle departures
            if "Climb STRAIGHT AHEAD" in pattern or "Departure Procedure" in pattern:
                runway = match.group(1)
                return sanitize_title(f"Departure RWY {runway}")
            # Handle chart codes
            if "-" in pattern:
                if "STAR" in text.upper() or "SID" in text.upper():
                    continue
                return sanitize_title(f"Chart {match.group(0)}")
            return sanitize_title(match.group())

    # Fallback: prioritize STAR or SID
    for chart_type in [("STAR", "STAR"), ("SID", "SID")]:
        if chart_type[0] in text.upper():
            match = re.search(r"([A-Z]{3,6}\s*\d[A-Z])", text, re.IGNORECASE)
            identifier = match.group(1).replace(' ', '') if match else "Unknown"
            runway = re.search(r"RWY\s*(\d{2}[LR]?)", text, re.IGNORECASE)
            runway = runway.group(1) if runway else "Unknown"
            return sanitize_title(f"{chart_type[1]} {identifier} RWY {runway}")

    # Fallback: chart codes
    chart_code = re.search(r"\b((?:10|11|20|30)-\d[A-Z]?)\b", text, re.IGNORECASE)
    if chart_code:
        return sanitize_title(f"Chart {chart_code.group(0)}")

    # Fallback: meaningful line
    lines = text.strip().splitlines()
    for line in lines:
        clean_line = line.strip()
        if len(clean_line) > 10 and not clean_line.isdigit() and "Printed from JeppView" not in clean_line:
            return sanitize_title(clean_line)

    return None

# Export PDF files
def export_pdf_page(reader, page_number, title, output_folder):
    try:
        writer = PdfWriter()
        writer.add_page(reader.pages[page_number])
        filename = f"{output_folder}/{page_number + 1:02d}_{title} - {icao_code}.pdf"
        
        with open(filename, "wb") as f_out:
            writer.write(f_out)
        print(f"✅ Saved: {filename}")
    except Exception as e:
        print(f"⚠️ Error saving page {page_number + 1}: {e}")

# Process each page
try:
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            try:
                pypdf_page = reader.pages[i]
                text = extract_text_with_rotation(page, pypdf_page)
                title = extract_chart_title(text)
                if not title:
                    title = f"Untitled_Page_{i+1}"
                export_pdf_page(reader, i, title, output_folder)
            except Exception as e:
                print(f"⚠️ Error on page {i+1}: {e}")
                title = f"Error_Page_{i+1}"
                export_pdf_page(reader, i, title, output_folder)
except Exception as e:
    print(f"❌ Script failed: {e}")

print(f"\n🎯 All charts split and named cleanly in folder: {output_folder}")