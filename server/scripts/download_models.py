# scripts/download_models.py

import os
import shutil
import tarfile
import urllib.request

# Map of model filenames to destination relative paths
MODEL_PATHS = {
    "crop_recommendation_model.pkl": "server/crop_recomm",
    "plant_pest_detection_model.h5": "server/pest_detect",
    "plant_disease_prediction_model.h5": "server/plant_disease",
    "soil_encoder.pkl": "server/soil_fertility",
    "soil_fertility_model.h5": "server/soil_fertility",
}

# Path to your exported models archive
MODEL_ARCHIVE_URL = "https://your-server.com/path-to/linux-models.tar.gz"  # Replace this with actual hosting (S3, GitHub Release, etc.)
ARCHIVE_NAME = "linux-models.tar.gz"
EXTRACT_DIR = "temp_model_extract"

def download_archive():
    if os.path.exists(ARCHIVE_NAME):
        print(f"Archive {ARCHIVE_NAME} already exists.")
        return
    print(f"Downloading model archive from {MODEL_ARCHIVE_URL}...")
    urllib.request.urlretrieve(MODEL_ARCHIVE_URL, ARCHIVE_NAME)
    print("Download completed.")

def extract_models():
    print(f"Extracting {ARCHIVE_NAME}...")
    os.makedirs(EXTRACT_DIR, exist_ok=True)
    with tarfile.open(ARCHIVE_NAME, "r:gz") as tar:
        tar.extractall(EXTRACT_DIR)
    print("Extraction completed.")

def place_models():
    for filename, target_dir in MODEL_PATHS.items():
        src_path = os.path.join(EXTRACT_DIR, filename)
        dest_path = os.path.join(target_dir, filename)
        os.makedirs(target_dir, exist_ok=True)
        if os.path.exists(src_path):
            shutil.move(src_path, dest_path)
            print(f"Placed {filename} → {dest_path}")
        else:
            print(f"Missing {filename} in archive.")

def clean_up():
    print("Cleaning up temporary files...")
    if os.path.exists(EXTRACT_DIR):
        shutil.rmtree(EXTRACT_DIR)
    if os.path.exists(ARCHIVE_NAME):
        os.remove(ARCHIVE_NAME)
    print("Cleanup done.")

def main():
    download_archive()
    extract_models()
    place_models()
    clean_up()

if __name__ == "__main__":
    main()
