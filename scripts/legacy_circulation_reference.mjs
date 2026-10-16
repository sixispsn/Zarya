// Execute the built working HTML, not a corrective overlay or a copied oracle.
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const input = JSON.parse(readFileSync(0, 'utf8'));
const html = readFileSync(new URL('../legacy/sp30_calculator.html', import.meta.url), 'utf8');
const source = html.slice(html.indexOf('const PUMP_CURVES = ['), html.indexOf('function renderTop3('));
const context = vm.createContext({});
vm.runInContext(source, context);
const cases = input.cases.map(c => {
  context.c = c;
  try {
    return vm.runInContext(`(() => {
      const r = circulationCandidates(c.q, c.head, c.basis, c.mode || '1', c.npsh ?? null);
      return {...r, candidates: r.candidates.map(x => ({model: x.pump.model,
        head: x.head_at_design, score: x.score, npsh_ok: x.npsh_ok}))};
    })()`, context);
  } catch (error) { return {error: error.message}; }
});
process.stdout.write(JSON.stringify(cases));
