import os
from flask import Flask, request, jsonify
import pickle
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# Base path for this script
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Load model and encoder with correct path
with open(os.path.join(BASE_DIR, 'crop_recommendation_model.pkl'), 'rb') as f:
    model = pickle.load(f)

# Correct path for soil_encoder.pkl
with open(os.path.join(BASE_DIR, '..', 'soil_fertility', 'soil_encoder.pkl'), 'rb') as f:
    encoder = pickle.load(f)

@app.route('/recommend-crop', methods=['POST'])
def recommend_crop():
    data = request.get_json()

    soil_type = data['soil_type']
    temperature = float(data['temperature'])
    rainfall = float(data['rainfall'])
    month = int(data['month'])

    # Encode soil type
    soil_encoded = encoder.transform([soil_type])[0]

    # Predict
    input_features = [[soil_encoded, temperature, rainfall, month]]
    prediction = model.predict(input_features)

    return jsonify({'recommended_crop': prediction[0]})

if __name__ == '__main__':
    app.run(port=5002, debug=True)
