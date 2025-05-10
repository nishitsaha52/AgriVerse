import React, { useState } from 'react';
import axios from 'axios';
import styles from '../AppStyles.module.css';

function PestDetectionUpload() {
  const [file, setFile] = useState(null);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);

  const handleUpload = async () => {
    if (!file) return;

    const formData = new FormData();
    formData.append('file', file);

    setLoading(true);
    setResult(null);

    try {
      const res = await axios.post('http://localhost:5004/detect-pest', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });

      setResult(res.data);
    } catch (err) {
      console.error("Error detecting pest:", err);
      setResult({ error: "Error detecting pest" });
    }

    setLoading(false);
  };

  return (
    <div className={styles.card}>
      <h2 className={styles.title}> Pest Detection</h2>

      <input
        type="file"
        onChange={(e) => setFile(e.target.files[0])}
        className={styles.input}
      />
      <button onClick={handleUpload} className={styles.button}>
        Detect Pest
      </button>

      {loading && <p className={styles.loading}>🔍 Analyzing image...</p>}

      {result && !result.error && (
        <div className={styles.result}>
          <h3 className={styles.resultHeader}>🧪 Detection Result</h3>
          <p><strong>Pest:</strong> {result.detected_class || "Unknown Pest"}</p>
          <p><strong>Risk:</strong> {result.risk}</p>
          <p><strong>Confidence:</strong> {result.confidence ? result.confidence.toFixed(2) : "N/A"}%</p>
        </div>
      )}

      {result && result.error && (
        <div className={styles.alert}>Error: {result.error}</div>
      )}
    </div>
  );
}

export default PestDetectionUpload;