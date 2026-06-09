import multiprocessing
import uvicorn

# Ensure PyInstaller imports all needed modules
import app as main_app

def main():
    # freeze_support is required when using multiprocessing on Windows with PyInstaller
    multiprocessing.freeze_support()
    
    print("\n" + "=" * 70)
    print("  Google Drive Cleaner GUI server is starting...")
    print("  Open your browser and navigate to: http://127.0.0.1:8000")
    print("=" * 70 + "\n")
    
    # We pass the application instance directly to avoid string import issues in PyInstaller
    uvicorn.run(main_app.app, host="127.0.0.1", port=8000, log_level="info")

if __name__ == "__main__":
    main()
