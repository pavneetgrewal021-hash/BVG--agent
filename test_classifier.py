from services.document_classifier import classify_pdf_pages, save_split_documents

# replace this with the actual path to your real combined PDF
pdf_path = r"C:\Users\satwi\Desktop\Documents.pdf"

results = classify_pdf_pages(pdf_path)
print("Page classification:", results)

saved = save_split_documents(pdf_path, results, "test_output")
print("Saved files:", saved)