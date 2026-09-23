import { readFileSync } from "node:fs";
import ts from "typescript";

export function resolveStrategyIdentity(code) {
  const utility = new URL("../src/lib/strategyIdentity.js", import.meta.url).href;
  let identity = ts.transpileModule(readFileSync(new URL("../src/components/settings/StrategyIdentity.tsx", import.meta.url), "utf8"), {
    compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.ESNext },
  }).outputText;
  identity = identity.replaceAll(JSON.stringify("react/jsx-runtime"), JSON.stringify(import.meta.resolve("react/jsx-runtime")))
    .replaceAll(JSON.stringify("../../lib/strategyIdentity.js"), JSON.stringify(utility));
  return code.replaceAll(JSON.stringify("../../lib/strategyIdentity.js"), JSON.stringify(utility))
    .replaceAll(JSON.stringify("./StrategyIdentity"), JSON.stringify(`data:text/javascript;base64,${Buffer.from(identity).toString("base64")}`));
}
