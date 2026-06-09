import gdrive_dedup
service = gdrive_dedup.authenticate()
try:
    res = service.files().update(fileId='1Il6KyrYSadcVboCI6O0TJ9vAMt_7ywF-', body={"trashed": True}).execute()
    print("Trashed successfully", res)
except Exception as e:
    print("Error:", e)
