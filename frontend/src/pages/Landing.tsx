import { Link } from "react-router-dom";
import { ArrowUpRight, BookOpen, ChartNoAxesCombined, Moon, Sun, ScanLine } from "lucide-react";
import { useThemeStore } from "../store/theme";
import "./landing.css";
import { LaunchWaitlist } from "../components/LaunchWaitlist";

const offers = [
  { icon: ScanLine, title: "Watch the setup form", text: "Follow a focused group of tickers. See which chart conditions the bot checks and what it is still waiting for.", tag: "Live charts + bot reasoning" },
  { icon: ChartNoAxesCombined, title: "Understand the context", text: "Start with a Daily Brief. Read clear explanations of market news and why a story could matter to a ticker.", tag: "Daily Brief + Market Context" },
  { icon: BookOpen, title: "Learn the pattern", text: "Build your understanding of chart patterns, entries, exits and risk. Start with the basics, work through examples and check what you have learned.", tag: "Learning Portal + guided practice" },
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
        <div className="landing-hero-copy"><p className="landing-eyebrow"><span/> JOIN THE CELO LAUNCH LIST</p>
          <h1>Fewer tickers.<br/>Deeper <em>understanding.</em></h1>
          <p className="landing-intro">Stop staring at charts without knowing what to look for. CELO connects the chart, the bot’s checks and plain-English explanations so you can understand the setup, follow the reasoning and build your skills.</p>
          <div className="landing-hero-actions"><button className="landing-button" onClick={() => jump("landing-waitlist")}>Join the waitlist <ArrowUpRight size={19}/></button><button className="landing-text-link" onClick={() => jump("landing-offers")}>Explore CELO <span aria-hidden="true">↓</span></button></div>
          <p className="landing-fine">Choose your path. Join free. Be ready for launch.</p>
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
      <section id="landing-about" className="landing-about"><div><p className="landing-eyebrow">ABOUT CELO</p><h2>Built for traders<br/>who want to understand.</h2></div><div><p className="landing-about-lead">CELO Trader is a minority-owned, women-owned business founded by Melanin.</p><p>CELO brings focus to a noisy market. Follow a focused set of tickers, understand the conditions behind each setup and learn the language of the chart. Less jumping between tools. More time understanding what you see.</p><p>Founded by Melanin, CELO is built around a simple belief: trading tools should explain themselves. From your first candle to your own trade plan, you deserve clear lessons, useful context and control over your decisions.</p></div></section>
      <section id="landing-offers" className="landing-offers"><div className="landing-section-heading"><div><p className="landing-eyebrow">WHAT CELO OFFERS</p><h2>Watch. Understand. Learn.</h2></div><p>Keep the chart and its explanation together.</p></div><div className="landing-feature-grid">{offers.map(({ icon: Icon, title, text, tag }, i) => <article className="landing-feature" key={title}><div className="landing-feature-top"><Icon size={24}/><span>0{i + 1}</span></div><h3>{title}</h3><p>{text}</p><span className="landing-feature-tag">{tag}</span></article>)}</div></section>
      <section id="landing-start" className="landing-start"><div><p className="landing-eyebrow">HOW IT FITS TOGETHER</p><h2>Follow the chart.<br/>Ask better questions.</h2><p>Learn at your own pace. You make your own decisions.</p></div><ol><li><span>01</span><div><h3>Get familiar</h3><p>See the chart and the conditions the bot is checking, explained without assuming you already know the terms.</p></div></li><li><span>02</span><div><h3>Understand the checks</h3><p>Learn why a condition passed, failed or needs more time. See the reason behind each check instead of decoding a wall of alerts.</p></div></li><li><span>03</span><div><h3>Build your understanding</h3><p>Use lessons and practice to connect what you see on the chart with how a strategy template works.</p></div></li></ol></section>
      <section id="landing-plans" className="landing-plans"><p className="landing-eyebrow">FOUR WAYS TO GO DEEPER</p><h2>Your next step starts here.</h2><p>Choose the experience that fits you. Join the waitlist today; subscriptions open at launch.</p><div className="landing-plan-grid">{[
        {name:"Watch-only",price:29,tag:"See the why",items:["Live charts and bot reasoning","Daily Brief for market context","Free community access"],note:"Launch plan"},
        {name:"Learning",price:69,tag:"Build your skills",items:["Everything in Watch-only","Learning Portal: lessons, examples and practice","AI chart pattern callouts at launch"],note:"Launch plan"},
        {name:"Learning + Discord",price:99,tag:"Learn with a community",items:["Everything in Learning","Members-only Discord channel","Bot decision logs with educational context"],note:"Launch plan"},
        {name:"Trading",price:149,tag:"Put your plan into action",items:["Everything in Learning + Discord","Buy and sell confirmations","Orders in your own supported brokerage account"],note:"Upcoming, subject to legal review"},
      ].map(plan=><article key={plan.name}><span>{plan.name}</span><h3>${plan.price} <small>/ month</small></h3><strong>{plan.tag}</strong><ul>{plan.items.map(item=><li key={item}>{item}</li>)}</ul><p className="landing-fine">{plan.note}</p><button className="landing-button" onClick={()=>jump("landing-waitlist")}>Join the waitlist</button></article>)}</div><p className="landing-fine">Launch pricing and planned inclusions. The current invite-only preview includes charts and guided learning; AI callouts, Discord delivery and customer trading are not yet available. No payment is collected here.</p></section>
      <section className="landing-about"><div><p className="landing-eyebrow">THE LEARNING PORTAL</p><h2>Start with zero jargon.<br/>Leave with a clearer plan.</h2></div><div><p className="landing-about-lead">A step-by-step path from “What is an option?” to reading a chart, comparing a contract and reviewing a paper trade.</p><p>Short lessons. Worked examples. Practice with explanations. Learn independently or work through the examples together as a family. No brokerage account is needed to learn.</p><p>Explore stocks and options, calls and puts, chart patterns, pricing, risk, entries and exits. Check your understanding before moving on.</p><button className="landing-button" onClick={()=>jump("landing-waitlist")}>Start your learning journey</button></div></section>
      <LaunchWaitlist />
    </main>
    <footer className="landing-footer"><div><Link className="landing-brand" to="/about">CELO <b>TRADER</b></Link><p>Fewer tickers. Deeper understanding.</p></div><div><p>CELO Trader is software for education and information. You make your own decisions. Options trading involves risk, including loss of your investment. Research and paper results do not guarantee live results. CELO does not promise profits.</p><Link to="/terms">Terms of Service &amp; Disclosures</Link><span>© {new Date().getFullYear()} CELO Trader</span></div></footer>
  </div>;
}
