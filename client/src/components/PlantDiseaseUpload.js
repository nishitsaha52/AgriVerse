import React, { useState } from 'react';
import axios from 'axios';
import styles from '../AppStyles.module.css'; // ✅ Import shared CSS module

function PlantDiseaseUpload() {
  const [file, setFile] = useState(null);
  const [prediction, setPrediction] = useState("");
  const [confidence, setConfidence] = useState(null);
  const [loading, setLoading] = useState(false);

  const handleUpload = async () => {
    if (!file) return;

    const formData = new FormData();
    formData.append('file', file);

    setLoading(true);
    setPrediction("");
    setConfidence(null);

    try {
      const res = await axios.post('http://localhost:5000/predict', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      console.log("Backend response:", res.data);

      setPrediction(res.data.predicted_class);
      setConfidence(res.data.confidence);
    } catch (err) {
      console.error("Prediction error:", err);
      setPrediction("Error predicting disease");
    }
    setLoading(false);
  };

  return (
    <div className={styles.card}>
      <h2 className={styles.titleGreen}>Plant Diesease Detection</h2>

      <input
        type="file"
        onChange={(e) => setFile(e.target.files[0])}
        className={styles.fileInput}
      />

      <button onClick={handleUpload} className={styles.buttonGreen}>
        Upload & Predict
      </button>

      {loading && <p className={styles.loading}>🔄 Analyzing image...</p>}

      {!loading && prediction && (
        <div className={styles.result}>
          <h3 className={styles.resultHeader}>🧪 Prediction Result</h3>
          <p><strong>Disease:</strong> {prediction}</p>
          {confidence !== null && (
            <p><strong>Confidence:</strong> {confidence.toFixed(2)}%</p>
          )}
        </div>
      )}
    </div>
  );
}

export default PlantDiseaseUpload;
