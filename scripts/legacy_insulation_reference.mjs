// Execute calcGvs and its tables verbatim from the working HTML.
// An explicit OD is a geometry input for the existing Python extension,
// not a formula/table correction. The HTML on disk is never modified.
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import vm from 'node:vm';

const html = readFileSync(new URL('../legacy/sp30_calculator.html', import.meta.url), 'utf8');
const input = JSON.parse(readFileSync(0, 'utf8'));
const start = html.indexOf('const T4_SP61 =');
const end = html.indexOf('function calcHvs(', start);
if (start < 0 || end < start) throw Error('legacy insulation block not found');
const source = html.slice(start, end);
const cases = (input.cases ?? []).map(c => {
  const context = vm.createContext({input: c});
  vm.runInContext(source, context);
  if (c.outer_diameter_mm != null) {
    if (!Number.isFinite(c.outer_diameter_mm) || c.outer_diameter_mm <= 0) throw Error('invalid OD');
    vm.runInContext('PIPE_OD[input.dn] = input.outer_diameter_mm', context);
  }
  return vm.runInContext('calcGvs(input.dn, input.t_water, input.t_room, 0.05)', context);
});
process.stdout.write(JSON.stringify({cases,
  source_sha256: createHash('sha256').update(source).digest('hex')}));
