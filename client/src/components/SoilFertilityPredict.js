// frontend/src/components/SoilFertilityPredict.js
import React, { useState } from 'react';
import axios from 'axios';
import styles from '../AppStyles.module.css';

function SoilFertilityPredict() {
  const [features, setFeatures] = useState(Array(12).fill(''));
  const [prediction, setPrediction] = useState('');
  const [confidence, setConfidence] = useState(null);
  const [loading, setLoading] = useState(false);

  const handleChange = (index, value) => {
    const newFeatures = [...features];
    newFeatures[index] = value;
    setFeatures(newFeatures);
  };

  const handlePredict = async () => {
    setLoading(true);
    setPrediction('');
    setConfidence(null);

    try {
      const res = await axios.post('http://localhost:5001/soil-predict', {
        features: features.map(f => parseFloat(f)),
      });

      console.log(res.data);
      setPrediction(res.data.predicted_fertility);
      setConfidence(res.data.confidence);
    } catch (error) {
      console.error(error);
      setPrediction('Error predicting fertility.');
    }

    setLoading(false);
  };

  const labels = ['N', 'P', 'K', 'pH', 'EC', 'OC', 'S', 'Zn', 'Fe', 'Cu', 'Mn', 'B'];

  return (
    <div className={styles.card}>
      <h2 className={styles.titleGreen}>Soil Fertility Prediction</h2>

      {labels.map((label, idx) => (
        <div key={idx} className="inputGroup">
          <label>{label}:</label>
          <input
            type="number"
            value={features[idx]}
            onChange={(e) => handleChange(idx, e.target.value)}
            className={styles.input}
          />
        </div>
      ))}

      <button onClick={handlePredict} className={styles.buttonGreen}>
        Predict Fertility
      </button>

      {loading && <p className={styles.loading}>🔄 Predicting...</p>}

      {!loading && prediction && (
        <div className={styles.result}>
          <h3 className={styles.resultHeader}>🧪 Result</h3>
          <p><strong>Fertility:</strong> {prediction}</p>
          {confidence !== null && (
            <p><strong>Confidence:</strong> {confidence.toFixed(2)}%</p>
          )}
        </div>
      )}
    </div>
  );
}

export default SoilFertilityPredict;