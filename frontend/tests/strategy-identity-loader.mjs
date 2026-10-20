import { readFileSync } from "node:fs";
import ts from "typescript";

export function resolveStrategyIdentity(code) {
  let audit = ts.transpileModule(readFileSync(new URL("../src/components/settings/WeeklyExitAudit.tsx", import.meta.url), "utf8"), {
    compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.ESNext },
  }).outputText;
  for (const name of ["react", "react/jsx-runtime", "@tanstack/react-query"]) {
    audit = audit.replaceAll(JSON.stringify(name), JSON.stringify(import.meta.resolve(name)));
  }
  audit = audit.replaceAll(JSON.stringify("../../contexts/AuthContext"),
    JSON.stringify("data:text/javascript,export const useAuth=()=>({user:null})"));
  const utility = new URL("../src/lib/strategyIdentity.js", import.meta.url).href;
  let identity = ts.transpileModule(readFileSync(new URL("../src/components/settings/StrategyIdentity.tsx", import.meta.url), "utf8"), {
    compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.ESNext },
  }).outputText;
  identity = identity.replaceAll(JSON.stringify("react/jsx-runtime"), JSON.stringify(import.meta.resolve("react/jsx-runtime")))
    .replaceAll(JSON.stringify("./WeeklyExitAudit"), JSON.stringify(`data:text/javascript;base64,${Buffer.from(audit).toString("base64")}`))
    .replaceAll(JSON.stringify("../../lib/strategyIdentity.js"), JSON.stringify(utility));
  return code.replaceAll(JSON.stringify("../../lib/strategyIdentity.js"), JSON.stringify(utility))
    .replaceAll(JSON.stringify("./StrategyIdentity"), JSON.stringify(`data:text/javascript;base64,${Buffer.from(identity).toString("base64")}`));
}
