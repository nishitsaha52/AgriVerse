from flask import Flask, request, jsonify
from flask_cors import CORS
import numpy as np
from PIL import Image
import tensorflow as tf
import json
import sys
import os

# Fix encoding issues for Windows console
sys.stdout.reconfigure(encoding='utf-8')

app = Flask(__name__)
CORS(app)

# Load the model and class indices
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

model = tf.keras.models.load_model(os.path.join(BASE_DIR, 'plant_disease_prediction_model.h5'))

with open(os.path.join(BASE_DIR, 'class_indices.json')) as f:
    class_indices = json.load(f)


# Reverse the class_indices mapping (int to class name)
index_to_class = {int(k): v for k, v in class_indices.items()}

def preprocess_image(image):
    img = image.resize((224, 224))
    img_array = np.array(img) / 255.0
    img_array = np.expand_dims(img_array, axis=0)
    return img_array

@app.route('/predict', methods=['POST'])
def predict():
    if 'file' not in request.files:
        app.logger.error("No file uploaded in the request")
        return jsonify({'error': 'No file uploaded'}), 400

    file = request.files['file']

    try:
        print("📸 File received:", file.filename)

        # Step 1: Open and preprocess image
        img = Image.open(file.stream).convert('RGB')
        print("🖼️ Image opened successfully")

        img_array = preprocess_image(img)
        print("🧪 Preprocessing complete:", img_array.shape)

        # Step 2: Predict
        predictions = model.predict(img_array)
        print("🔮 Raw predictions:", predictions)

        predicted_index = int(np.argmax(predictions, axis=1)[0])
        predicted_class = index_to_class.get(predicted_index, "Unknown class")

        confidence = float(np.max(predictions))

        print(f"✅ Prediction: {predicted_class} ({confidence*100:.2f}%)")

        return jsonify({
            'predicted_class': predicted_class,
            'confidence': round(confidence * 100, 2)
        })

    except Exception as e:
        print("❌ Error during prediction:", str(e))
        import traceback
        traceback.print_exc()
        return jsonify({'error': 'Failed to process image and predict.'}), 500

if __name__ == '__main__':
    app.run(port=5000, debug=True)