import { Link } from "react-router-dom";
import { ArrowUpRight, BookOpen, ChartNoAxesCombined, Moon, Sun, ScanLine } from "lucide-react";
import { useThemeStore } from "../store/theme";
import "./landing.css";
import { LaunchWaitlist } from "../components/LaunchWaitlist";

const offers = [
  { icon: ScanLine, title: "Watch the setup form", text: "Follow a focused group of tickers. See which chart conditions the bot checks and what it is still waiting for.", tag: "Live charts + bot reasoning" },
  { icon: ChartNoAxesCombined, title: "Understand the context", text: "Start with a Daily Brief. Read clear explanations of market news and why a story could matter to a ticker.", tag: "Daily Brief + Market Context" },
  { icon: BookOpen, title: "Learn the pattern", text: "Build your understanding of chart patterns, entries, exits and risk. Live AI pattern callouts are planned for the Learning tier.", tag: "Learning Hub + planned chart callouts" },
];
function jump(id: string) { document.getElementById(id)?.scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" }); }

export function Landing() {
  const { theme, toggle } = useThemeStore();
  return <div className="celo-landing">
    <a className="landing-skip" href="#landing-content" onClick={e => { e.preventDefault(); document.getElementById("landing-content")?.focus(); }}>Skip to content</a>
    <header className="landing-nav">
      <Link to="/about" className="landing-brand" aria-label="CELO Trader home"><span className="brand-symbol">C</span><span>CELO <b>TRADER</b></span></Link>
      <nav aria-label="Main navigation"><button onClick={() => jump("landing-about")}>About us</button><button onClick={() => jump("landing-offers")}>What we offer</button><button onClick={() => jump("landing-start")}>How it works</button><button onClick={() => jump("landing-plans")}>Plans</button></nav>
      <div className="landing-nav-actions"><button className="landing-theme" onClick={toggle} aria-label={`Switch to ${theme === "light" ? "dark" : "light"} mode`}>{theme === "light" ? <Moon size={18}/> : <Sun size={18}/>}</button><Link to="/login" className="landing-button small">Sign in <ArrowUpRight size={16}/></Link></div>
    </header>
    <main id="landing-content" tabIndex={-1}>
      <section className="landing-hero">
        <div className="landing-hero-copy"><p className="landing-eyebrow"><span/> PREPARING FOR LAUNCH</p>
          <h1>Fewer tickers.<br/>Deeper <em>understanding.</em></h1>
          <p className="landing-intro">Watch the bot read the chart. Understand what it is looking for, what is missing, and why a setup matters. CELO Trader brings options education and plain-English explanations into one focused workspace.</p>
          <div className="landing-hero-actions"><button className="landing-button" onClick={() => jump("landing-waitlist")}>Join the waitlist <ArrowUpRight size={19}/></button><button className="landing-text-link" onClick={() => jump("landing-offers")}>Explore CELO <span aria-hidden="true">↓</span></button></div>
          <p className="landing-fine">Launching with Watch-only and Learning. Joining the waitlist does not enable trading.</p>
        </div>
        <div className="landing-preview" aria-label="Illustration of the CELO workflow, not market data">
          <div className="landing-preview-head"><span>YOUR TRADING WORKSPACE</span><span className="landing-demo">Illustrative preview</span></div>
          <div className="landing-preview-title"><div><p>From chart to decision</p><h2>Stay close to the plan.</h2></div><span className="landing-orbit">↗</span></div>
          <div className="landing-chart" aria-hidden="true"><svg viewBox="0 0 480 180" role="presentation"><defs><linearGradient id="landing-area" x1="0" y1="0" x2="0" y2="1"><stop stopColor="#36aeb0" stopOpacity=".22"/><stop offset="1" stopColor="#36aeb0" stopOpacity="0"/></linearGradient></defs><path d="M0 144 L35 132 L60 142 L90 110 L120 119 L150 80 L180 99 L210 65 L240 78 L270 45 L300 60 L330 30 L360 50 L390 23 L420 42 L450 18 L480 30 V180 H0Z" fill="url(#landing-area)"/><path d="M0 144 L35 132 L60 142 L90 110 L120 119 L150 80 L180 99 L210 65 L240 78 L270 45 L300 60 L330 30 L360 50 L390 23 L420 42 L450 18 L480 30" fill="none" stroke="#168a83" strokeWidth="3"/></svg><span>Observe the market</span></div>
          <div className="landing-preview-card"><span className="landing-step-dot">01</span><div><strong>Understand the setup</strong><p>What needs to happen before an entry?</p></div><span className="landing-chip">Evaluate</span></div>
          <div className="landing-preview-card"><span className="landing-step-dot blue">02</span><div><strong>Follow the explanation</strong><p>What changed on the chart?</p></div><span className="landing-chip blue">Learn</span></div>
          <div className="landing-preview-footer"><BookOpen size={17}/><span>Every step is a chance to understand more.</span></div>
        </div>
      </section>
      <section id="landing-about" className="landing-about"><div><p className="landing-eyebrow">ABOUT CELO</p><h2>Built for traders<br/>who want to understand.</h2></div><div><p className="landing-about-lead">CELO Trader is a minority-owned, women-owned business founded by Melanin.</p><p>We are building CELO around a simple idea: spending more time understanding a few markets can be more useful than chasing hundreds of alerts. Our focus is options education, chart context and clear explanations. The launch ticker lineup will be confirmed later.</p><p>Our goal is to explain what the bot sees in everyday language, so you can build your own understanding. Internal research helps us review the software. It is not a promise that a template or trade will make money.</p></div></section>
      <section id="landing-offers" className="landing-offers"><div className="landing-section-heading"><div><p className="landing-eyebrow">WHAT CELO OFFERS</p><h2>Watch. Understand. Learn.</h2></div><p>Keep the chart and its explanation together.</p></div><div className="landing-feature-grid">{offers.map(({ icon: Icon, title, text, tag }, i) => <article className="landing-feature" key={title}><div className="landing-feature-top"><Icon size={24}/><span>0{i + 1}</span></div><h3>{title}</h3><p>{text}</p><span className="landing-feature-tag">{tag}</span></article>)}</div></section>
      <section id="landing-start" className="landing-start"><div><p className="landing-eyebrow">HOW IT FITS TOGETHER</p><h2>Follow the chart.<br/>Ask better questions.</h2><p>Learn at your own pace. You make your own decisions.</p></div><ol><li><span>01</span><div><h3>Get familiar</h3><p>See the chart and the conditions the bot is checking, explained without assuming you already know the terms.</p></div></li><li><span>02</span><div><h3>Understand the checks</h3><p>Learn why a condition passed, failed or needs more time. A chart condition is an observation, not a promise or an instruction to buy.</p></div></li><li><span>03</span><div><h3>Build your understanding</h3><p>Use lessons and practice to connect what you see on the chart with how a strategy template works.</p></div></li></ol></section>
      <section id="landing-plans" className="landing-plans"><p className="landing-eyebrow">PLANNED LAUNCH PLANS</p><h2>Start with watching. Go deeper with learning.</h2><p>Planned pricing. Subscriptions are not open and no payments are being collected.</p><div className="landing-plan-grid"><article><span>WATCH-ONLY</span><h3>$29 <small>/ month</small></h3><p>Live charts, the bot’s plain-English reasoning and the Daily Brief.</p><p>Watch the chart with context.</p><button className="landing-button" onClick={() => jump("landing-waitlist")}>Get launch updates</button></article><article><span>LEARNING</span><h3>$69 <small>/ month</small></h3><p>Everything in Watch-only, plus planned AI pattern explanations drawn on the chart.</p><p>Learn what the pattern means as you watch.</p><button className="landing-button" onClick={() => jump("landing-waitlist")}>Get launch updates</button></article></div><p className="landing-fine">Learning features are in development. Final availability and terms will be confirmed before subscriptions open. Customer trading is not included in this launch offer.</p></section>
      <LaunchWaitlist />
    </main>
    <footer className="landing-footer"><div><Link className="landing-brand" to="/about">CELO <b>TRADER</b></Link><p>Fewer tickers. Deeper understanding.</p></div><div><p>CELO Trader is software for education and information. You make your own decisions. Options trading involves risk, including loss of your investment. Research and paper results do not guarantee live results. CELO does not promise profits.</p><Link to="/terms">Terms of Service &amp; Disclosures</Link><span>© {new Date().getFullYear()} CELO Trader</span></div></footer>
  </div>;
}
