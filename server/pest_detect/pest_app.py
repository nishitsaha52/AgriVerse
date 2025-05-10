# pest_app.py

from flask import Flask, request, jsonify
from flask_cors import CORS
import tensorflow as tf
import numpy as np
from PIL import Image
import io
import json
import traceback
import sys
import os

# Fix encoding issues for Windows console
sys.stdout.reconfigure(encoding='utf-8')

# -----------------------------------
# Flask App Initialization
# -----------------------------------
app = Flask(__name__)
CORS(app)

# -----------------------------------
# Load Trained Model
# -----------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

model = tf.keras.models.load_model(os.path.join(BASE_DIR, 'plant_pest_detection_model.h5'))

with open(os.path.join(BASE_DIR, 'pest_class_indices.json'), 'r') as f:
    class_indices = json.load(f)

# Convert keys from string to int
index_to_label = {int(k): v for k, v in class_indices.items()}

print("Index to Label Mapping:", index_to_label)

# -----------------------------------
# API Endpoint for Pest Detection
# -----------------------------------
@app.route('/detect-pest', methods=['POST'])
def detect_pest():
    file = request.files.get('file')

    if not file:
        return jsonify({'error': 'No file uploaded'}), 400

    try:
        # Preprocess the image
        img = Image.open(io.BytesIO(file.read())).convert('RGB')
        img = img.resize((224, 224))  # Match model input size
        img = np.array(img) / 255.0
        img = np.expand_dims(img, axis=0)

        # Make prediction
        prediction = model.predict(img)
        predicted_index = int(np.argmax(prediction))
        confidence = float(np.max(prediction)) * 100

        print(f"Prediction array: {prediction}")
        print(f"Predicted index: {predicted_index}")
        print(f"Available labels: {index_to_label}")

        # Map index to label
        predicted_class = index_to_label.get(predicted_index)

        if predicted_class is None:
            predicted_class = f"Unknown Pest (index {predicted_index})"

        # Determine risk based on confidence
        if confidence >= 80:
            risk = "HIGH"
        elif confidence >= 50:
            risk = "MEDIUM"
        else:
            risk = "LOW"

        return jsonify({
            'detected_class': predicted_class,
            'confidence': confidence,
            'risk': risk
        })

    except Exception as e:
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

# -----------------------------------
# Run the Flask App
# -----------------------------------
if __name__ == '__main__':
    app.run(port=5004, debug=True)