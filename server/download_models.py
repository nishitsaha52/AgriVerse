# server/download_models.py
import os
import boto3

# Map of model filenames to destination relative paths
MODEL_PATHS = {
    "crop_recommendation_model.pkl": "server/crop_recomm",
    "plant_pest_detection_model.h5": "server/pest_detect",
    "plant_disease_prediction_model.h5": "server/plant_disease",
    "soil_encoder.pkl": "server/soil_fertility",
    "soil_fertility_model.h5": "server/soil_fertility",
}

BUCKET_NAME = "nishit-linux-bucket"
REGION_NAME = "ap-south-1"

def download_models():
    print(f"Connecting to S3 bucket: {BUCKET_NAME} in {REGION_NAME}...")
    s3 = boto3.client("s3", region_name=REGION_NAME)

    for filename, target_dir in MODEL_PATHS.items():
        dest_path = os.path.join(target_dir, filename)
        os.makedirs(target_dir, exist_ok=True)
        print(f"Downloading {filename} to {dest_path}...")
        try:
            s3.download_file(BUCKET_NAME, filename, dest_path)
            print(f"Downloaded {filename}")
        except Exception as e:
            print(f"Failed to download {filename}: {e}")

def main():
    download_models()

if __name__ == "__main__":
    main()