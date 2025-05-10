# soil_app.py

from flask import Flask, request, jsonify
from flask_cors import CORS
import numpy as np
import tensorflow as tf
import json
import sys
import os

# Fix encoding issues for Windows console
sys.stdout.reconfigure(encoding='utf-8')

app = Flask(__name__)
CORS(app)

# Load model and class indices
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

model = tf.keras.models.load_model(os.path.join(BASE_DIR, 'soil_fertility_model.h5'))

with open(os.path.join(BASE_DIR, 'fertility_class_indices.json')) as f:
    class_indices = json.load(f)


# Reverse the mapping (int to label)
index_to_class = {int(k): v for k, v in class_indices.items()}

@app.route('/soil-predict', methods=['POST'])
def predict_soil():
    data = request.get_json()
    print("🔵 Incoming data:", data)

    if not data:
        return jsonify({'error': 'No input data'}), 400

    try:
        input_features = np.array(data['features']).reshape(1, -1)
        print("🟡 Input shape:", input_features.shape)

        predictions = model.predict(input_features)
        predicted_index = int(np.argmax(predictions, axis=1)[0])
        confidence = float(np.max(predictions))

        predicted_class = index_to_class.get(predicted_index, "Unknown class")
        print(f"✅ Prediction: {predicted_class}, Confidence: {confidence}")

        return jsonify({
            'predicted_fertility': predicted_class,
            'confidence': round(confidence * 100, 2)
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(port=5001, debug=True)