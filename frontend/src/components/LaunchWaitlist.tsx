import { useCallback, useEffect, useState, type FormEvent } from "react";

async function send(path: string, body: object) {
  const response = await fetch(`/api/launch/${path}`, {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body)});
  const result = await response.json();
  if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "We could not save this request. Please try again.");
  return result;
}

export function LaunchWaitlist() {
  const [email, setEmail] = useState("");
  const [interest, setInterest] = useState("undecided");
  const [consent, setConsent] = useState(false);
  const [website, setWebsite] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [removal, setRemoval] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      const result = await send("waitlist", {email,interest,consent,website});
      setMessage(result.message); setRemoval(result.removal_token ?? ""); setEmail("");
    } catch(e) { setError(e instanceof Error ? e.message : "Please try again."); }
    finally { setBusy(false); }
  }
  return <section id="landing-waitlist" className="landing-waitlist">
    <div><p className="landing-eyebrow">GET LAUNCH UPDATES</p><h2>Be part of what comes next.</h2><p>Pick your path and join the CELO launch list. We’ll use your choice to share relevant launch updates.</p><p className="landing-fine">Free to join. No payment or brokerage connection required.</p></div>
    {message ? <div role="status"><h3>You’re on the list.</h3><p>{message}</p>{removal && <p><a href={`/#/waitlist-remove?token=${encodeURIComponent(removal)}`}>Save this link to remove your signup</a></p>}</div> : <form onSubmit={submit}>
      <label htmlFor="launch-email">Email address</label><input id="launch-email" type="email" required maxLength={254} autoComplete="email" value={email} onChange={e=>setEmail(e.target.value)} placeholder="you@example.com" />
      <label htmlFor="launch-interest">What interests you?</label><select id="launch-interest" value={interest} onChange={e=>setInterest(e.target.value)}><option value="undecided">Not sure yet</option><option value="watch">Watch-only</option><option value="learning">Learning</option><option value="learning_discord">Learning + Discord</option><option value="trading">Trading (upcoming)</option></select>
      <div className="landing-honeypot" aria-hidden="true"><label>Website<input tabIndex={-1} autoComplete="off" value={website} onChange={e=>setWebsite(e.target.value)}/></label></div>
      <label className="landing-consent"><input type="checkbox" required checked={consent} onChange={e=>setConsent(e.target.checked)}/><span>Email me CELO Trader launch updates. No purchase or trading account is created. For family learning, a parent or guardian should join using their own email.</span></label>
      <p className="landing-fine">We save your email, interest and consent on CELO’s server for launch updates. We do not sell this list. A removal link appears after a new signup. </p>
      {error && <p role="alert" className="landing-error">{error}</p>}<button className="landing-button" disabled={busy}>{busy ? "Saving..." : "Join the waitlist"}</button>
    </form>}
  </section>;
}

export function WaitlistRemove() {
  const token = new URLSearchParams(window.location.hash.split("?")[1] ?? "").get("token");
  const [message,setMessage] = useState("");
  const [busy,setBusy] = useState(false);
  return <main className="celo-landing" style={{padding:"48px 24px",minHeight:"100vh"}}><h1>Leave the waitlist</h1><p>This removes your saved launch signup. It does not affect a trading account.</p>{message ? <p role="status">{message}</p> : <button className="landing-button" disabled={!token || busy} onClick={async()=>{setBusy(true);try {const result=await send("waitlist/remove",{token});setMessage(result.message);}catch{setMessage("We could not remove this signup. Try again later.");}finally{setBusy(false);}}}>Remove my signup</button>}<p><a href="/#/about">Back to CELO Trader</a></p></main>;
}

type WaitlistData = {total:number;items:{email:string;interest:string;created_at:string}[];email_delivery:string};
export function LaunchWaitlistAdmin() {
  const [data,setData] = useState<WaitlistData|null>(null);
  const [error,setError] = useState("");
  const [page,setPage] = useState(1);
  const load = useCallback(async () => {
    setError("");
    try { const response=await fetch(`/api/launch/waitlist?page=${page}`,{credentials:"include"}); if(!response.ok) throw new Error("Waitlist could not load."); setData(await response.json()); }
    catch(e){setError(e instanceof Error?e.message:"Waitlist could not load.");}
  }, [page]);
  useEffect(()=>{void load();},[load]);
  return <section className="card p-4"><div className="flex justify-between"><h2 className="font-semibold">Launch waitlist</h2><button className="btn btn-ghost" onClick={load}>Refresh</button></div><p>{data?.total ?? "..."} signups. These are launch interests, not subscribers or trading accounts.</p><p>{data?.email_delivery}</p>{error && <p role="alert">{error}</p>}<div className="overflow-auto"><table className="w-full text-sm"><thead><tr><th className="text-left p-2">Email</th><th className="text-left">Interest</th><th className="text-left">Joined</th></tr></thead><tbody>{data?.items.map(row=><tr key={row.email}><td className="p-2">{row.email}</td><td>{row.interest === "watch" ? "Watch-only" : row.interest === "learning" ? "Learning" : row.interest === "learning_discord" ? "Learning + Discord" : row.interest === "trading" ? "Trading (upcoming)" : "Not sure yet"}</td><td>{new Date(row.created_at).toLocaleString()}</td></tr>)}</tbody></table></div>{data?.total === 0 && <p>No signups yet.</p>}<div className="flex gap-2 mt-3"><button className="btn btn-ghost" disabled={page===1} onClick={()=>setPage(page-1)}>Previous</button><span>Page {page}</span><button className="btn btn-ghost" disabled={!data || page*50>=data.total} onClick={()=>setPage(page+1)}>Next</button></div></section>;
}
