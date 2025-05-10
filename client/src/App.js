// frontend-mern/src/App.js
import PlantDiseaseUpload from './components/PlantDiseaseUpload';
import SoilFertilityPredict from './components/SoilFertilityPredict';
import WeatherComponent from './components/Weather';
import CropRecommendation from './components/CropRecommendation';
import PestDetectionUpload from './components/PestDetectionUpload';

function App() {
  return (
    <div className="App" style={styles.container}>
      <h1 style={styles.header}>AgriVerse</h1>

      {/* Weather Component */}
      <section style={styles.section}>
        <WeatherComponent />
      </section>

      <hr style={styles.separator} />

      {/* Plant Disease Upload */}
      <section style={styles.section}>
        <PlantDiseaseUpload />
      </section>

      <hr style={styles.separator} />

      {/* Soil Fertility Prediction */}
      <section style={styles.section}>
        <SoilFertilityPredict />
      </section>

      <hr style={styles.separator} />

      {/* Soil Fertility Prediction */}
      <section style={styles.section}>
        <CropRecommendation />
      </section>

      <hr style={styles.separator} />

      {/* Soil Fertility Prediction */}
      <section style={styles.section}>
        <PestDetectionUpload />
      </section>
    </div>
  );
}

const styles = {
  container: {
    textAlign: 'center',
    marginTop: '30px',
    fontFamily: 'Segoe UI, sans-serif',
    backgroundColor: '#f9f9f9',
    minHeight: '100vh',
    padding: '40px',
  },
  header: {
    color: '#2E7D32',
    marginBottom: '30px',
    fontSize: '2.8rem',
    letterSpacing: '1px',
  },
  subHeader: {
    fontSize: '1.8rem',
    color: '#1b5e20',
    marginBottom: '20px',
  },
  section: {
    marginBottom: '60px',
  },
  separator: {
    margin: '40px 0',
    borderColor: '#ccc',
  },
};

export default App;