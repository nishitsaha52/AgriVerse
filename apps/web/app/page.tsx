import {
  ArrowRight,
  BookOpenCheck,
  CloudSun,
  Leaf,
  ScanLine,
  ShieldCheck,
  Sprout,
} from "lucide-react";
import Link from "next/link";

export default function Home() {
  return (
    <main className="shell">
      <header className="topbar">
        <Link className="brand" href="/">
          <span className="brand-mark">
            <Sprout size={20} />
          </span>
          AgriVerse
        </Link>
        <nav className="nav-actions" aria-label="Account">
          <Link className="button ghost" href="/login">
            Sign in
          </Link>
          <Link className="button" href="/register">
            Join with invite <ArrowRight size={16} />
          </Link>
        </nav>
      </header>

      <section className="hero">
        <div>
          <div className="eyebrow">
            <ShieldCheck size={14} /> Cited, field-aware guidance
          </div>
          <h1>
            Know your field.
            <br />
            <span>Grow with confidence.</span>
          </h1>
          <p className="hero-copy">
            AgriVerse brings soil health, local weather, crop suitability, and cautious
            plant diagnosis into one living field record—so every recommendation starts
            with your actual farm.
          </p>
          <div className="hero-actions">
            <Link className="button" href="/register">
              Start your field record <ArrowRight size={17} />
            </Link>
            <Link className="button secondary" href="/login">
              I already have an account
            </Link>
          </div>
        </div>

        <div className="field-card" aria-label="Example field health summary">
          <div className="eyebrow">Tomato field · Nadia</div>
          <h2 style={{ fontFamily: "Georgia, serif", fontSize: "2.1rem", marginTop: 18 }}>
            Today’s field brief
          </h2>
          <p style={{ color: "rgb(255 255 255 / 65%)", lineHeight: 1.6 }}>
            Conditions are stable. One leaf scan is waiting for agronomist review.
          </p>
          <div className="metric-grid">
            <div className="metric">
              <Leaf size={19} />
              <strong>82</strong>
              <span>Soil fertility index</span>
            </div>
            <div className="metric">
              <CloudSun size={19} />
              <strong>29°</strong>
              <span>Current temperature</span>
            </div>
            <div className="metric">
              <ScanLine size={19} />
              <strong>3</strong>
              <span>Recent plant scans</span>
            </div>
            <div className="metric">
              <BookOpenCheck size={19} />
              <strong>5</strong>
              <span>Retrieved sources</span>
            </div>
          </div>
        </div>
      </section>
    </main>
  );
}
