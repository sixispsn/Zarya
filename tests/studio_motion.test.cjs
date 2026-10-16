/* Unit tests of transition orchestration. No browser or project data involved. */
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('app/web/static/studio_motion.js', 'utf8');
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return {promise, resolve, reject};
};
const classes = () => {
  const values = new Set();
  return {add:value=>values.add(value), remove:value=>values.delete(value), contains:value=>values.has(value)};
};
function harness({reduced = false, native = true, hidden = false, failStart = false} = {}) {
  const listeners = {};
  const preference = {matches:reduced, addEventListener:(_, fn)=>{listeners.preference=fn;}};
  const document = {hidden, documentElement:{classList:classes()}, addEventListener:(name, fn)=>{listeners[name]=fn;}};
  const transitions = [];
  if (native) document.startViewTransition = update => {
    if (failStart) throw new Error('unavailable');
    const done=deferred(), finish=deferred(), ready=deferred();
    const transition = {updateCallbackDone:done.promise, finished:finish.promise, ready:ready.promise,
      skipped:false, skipTransition(){this.skipped=true;ready.reject(new Error('skipped'));},
      commit(){try {update();done.resolve();ready.resolve();} catch(error) {done.reject(error);ready.reject(error);finish.reject(error);}},
      finish(){finish.resolve();}};
    transitions.push(transition);
    return transition;
  };
  const window = {matchMedia:()=>preference, addEventListener:(name, fn)=>{listeners[name]=fn;}};
  vm.runInNewContext(source, {window, document, Promise, Set});
  const surface = {classList:classes()};
  return {motion:window.ZaryaMotion, document, preference, listeners, transitions, surface};
}
const tick = async () => { for(let i=0;i<8;i++) await Promise.resolve(); };

for (const [name, options, animate] of [
  ['reduced motion', {reduced:true}, true], ['older browser', {native:false}, true],
  ['background tab', {hidden:true}, true], ['initial/error render', {}, false],
  ['native API failure', {failStart:true}, true],
]) test(`${name}: commits once without waiting for animation`, async () => {
  const h=harness(options); let commits=0;
  await h.motion.change(()=>commits++, ()=>h.surface, animate);
  assert.equal(commits,1);
  assert.equal(h.transitions.length,0);
  assert.equal(h.document.documentElement.classList.contains('studio-dissolving'),false);
});

test('returns after DOM commit, not the animation; tracks replacement surface', async () => {
  const h=harness(); let current=h.surface;
  const after={classList:classes()};
  const job=h.motion.change(()=>{current=after;},()=>current);
  await tick();
  assert.equal(h.surface.classList.contains('studio-motion-surface'),true);
  h.transitions[0].commit(); await job;
  assert.equal(h.surface.classList.contains('studio-motion-surface'),false);
  assert.equal(after.classList.contains('studio-motion-surface'),true);
  h.transitions[0].finish(); await tick();
  assert.equal(after.classList.contains('studio-motion-surface'),false);
});

test('rapid changes keep commit order but do not queue animation durations', async () => {
  const h=harness(); const seen=[];
  const first=h.motion.change(()=>seen.push(1),()=>h.surface); await tick();
  const second=h.motion.change(()=>seen.push(2),()=>h.surface); await tick();
  assert.equal(h.transitions[0].skipped,true);
  assert.equal(h.transitions.length,1);
  h.transitions[0].commit(); await first; await tick();
  assert.equal(h.transitions.length,2);
  h.transitions[1].commit(); await second;
  assert.deepEqual(seen,[1,2]);
  h.transitions[0].finish(); await tick();
  assert.equal(h.surface.classList.contains('studio-motion-surface'),true);
  h.transitions[1].finish(); await tick();
  assert.equal(h.surface.classList.contains('studio-motion-surface'),false);
});

for (const event of ['pointerdown','keydown','input','pagehide']) test(`${event} dismisses snapshots without replaying updates`, async () => {
  const h=harness(); let count=0;
  const job=h.motion.change(()=>count++,()=>h.surface); await tick();
  h.transitions[0].commit(); await job;
  h.listeners[event]();
  assert.equal(h.transitions[0].skipped,true);
  assert.equal(h.surface.classList.contains('studio-motion-surface'),false);
  assert.equal(count,1);
});

test('reduced-motion preference can change while animation is active', async () => {
  const h=harness();
  const job=h.motion.change(()=>{},()=>h.surface); await tick();
  h.transitions[0].commit(); await job;
  h.preference.matches=true; h.listeners.preference();
  assert.equal(h.transitions[0].skipped,true);
});

test('failed update is not retried, and the next update can proceed', async () => {
  const h=harness(); let count=0;
  const job=h.motion.change(()=>{count++;throw new Error('render failed');},()=>h.surface);
  const rejected=assert.rejects(job,/render failed/);
  await tick(); h.transitions[0].commit(); await rejected;
  await h.motion.change(()=>count++,()=>h.surface,false);
  assert.equal(count,2);
  assert.equal(h.surface.classList.contains('studio-motion-surface'),false);
});

test('a missing surface never prevents rendering', async () => {
  const h=harness(); let count=0;
  await h.motion.change(()=>count++,()=>null);
  assert.equal(count,1); assert.equal(h.transitions.length,0);
});

test('direct choices commit synchronously; another choice cancels only the paint', async () => {
  const h=harness(); const seen=[]; const animations=[];
  h.surface.animate = () => {
    const finish=deferred();
    const animation={finished:finish.promise,cancelled:false,cancel(){this.cancelled=true;finish.reject(new Error('cancelled'));}};
    animations.push(animation); return animation;
  };
  h.motion.reveal(()=>seen.push(1),()=>h.surface);
  assert.deepEqual(seen,[1]);
  h.motion.reveal(()=>seen.push(2),()=>h.surface);
  assert.deepEqual(seen,[1,2]);
  assert.equal(animations[0].cancelled,true);
  await tick();
  h.listeners.input();
  assert.equal(animations[1].cancelled,true);
});

test('direct choices respect reduced motion without deferring the update', () => {
  const h=harness({reduced:true}); let count=0;
  h.surface.animate=()=>{throw new Error('must not animate');};
  h.motion.reveal(()=>count++,()=>h.surface);
  assert.equal(count,1);
});
