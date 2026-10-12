import { useState } from "react";
import { createRoot } from "react-dom/client";
import { TradeChart } from "../src/components/charts/TradeChart";
import { stockPositionDrawings } from "../src/lib/stockPositionDrawings";
import type { Trade, ScannerOpportunity } from "../src/lib/api";
import "../src/index.css";
const start = Date.parse("2026-10-12T16:35:00Z");
const bars = Array.from({length:71}, (_,i)=>({time:new Date(start+i*60_000).toISOString(),open:777.8-i*.009,close:777.79-i*.009,high:777.83-i*.009,low:777.76-i*.009,volume:100}));
const trade: Trade = {id:288,ticker:"SPY",direction:"short",option_type:"put",entry_time:"2026-10-12T16:55:16Z",exit_time:"2026-10-12T17:25:19Z",entry_price:3.52,exit_price:3.45,contracts:2,status:"closed"};
const setup = {ticker:"SPY",trade:{id:288},setup_details:{v2_entry_reference:777.71,v2_stop:778.01,v2_target:777.11}} as ScannerOpportunity;
function Harness(){
 const [shown,setShown]=useState(false);
 return <main style={{maxWidth:1100,margin:"20px auto"}}><p>OFFLINE STOCK CHART TEST DATA</p><button onClick={()=>setShown(!shown)}>Toggle chart</button>
 <div hidden={!shown}><TradeChart bars={bars} trades={[trade]} annotations={stockPositionDrawings(trade,setup)} ticker="SPY" showRsi showMacd showPositionCard={false} showOR={false} showVwap={false} height={420}/></div></main>;
}
createRoot(document.getElementById("root")!).render(<Harness/>);
