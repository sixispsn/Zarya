const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const scope = {window: {}};
vm.runInNewContext(fs.readFileSync('app/web/static/studio_transport.js','utf8'), scope);
const transport = scope.window.ZaryaTransport;

test('successful JSON response is retained', async () => {
  assert.equal((await transport.decode(new Response('{"revision":4}'))).revision, 4);
});
for (const status of [500, 502, 401, 413, 409]) {
  test(`non-JSON HTTP ${status} is not a connection error`, async () => {
    await assert.rejects(transport.decode(new Response('<html>error</html>', {status})), error => {
      assert.equal(error.status, status);
      assert.doesNotMatch(transport.presentation(error).message, /Связь.*прервалась/);
      return true;
    });
  });
}
test('domain validation details survive', async () => {
  await assert.rejects(transport.decode(new Response('{"detail":"Уточните исходные"}', {status:422})), error => {
    assert.equal(error.message, 'Уточните исходные');
    assert.equal(error.reload, false);
    return true;
  });
});
test('structured 422 addresses preserve original detail; other statuses cannot navigate',async()=>{
  const body={detail:'Original detail',input_message:'Readable message',input_issues:[{code:'duplicate_riser_id'}]};
  for(const status of [422,409,500])await assert.rejects(transport.decode(new Response(JSON.stringify(body),{status})),error=>{
    assert.equal(error.message,body.detail);
    assert.equal(error.inputMessage,status===422?body.input_message:undefined);
    assert.equal(error.inputIssues?.length,status===422?1:undefined);
    return true;
  });
});
test('malformed success response and local rendering errors are distinct', async () => {
  await assert.rejects(transport.decode(new Response('not-json')), error => {
    assert.equal(error.kind, 'response');
    assert.equal(error.reload, true);
    return true;
  });
  assert.match(transport.presentation(new TypeError('render failed')).message, /отобразить/);
});
test('real network interruption / timeout recommend reload, not blind retry', () => {
  assert.match(transport.interrupted(new TypeError('fetch')).message, /Связь/);
  assert.match(transport.interrupted({name:'AbortError'}).message, /не успел/);
  assert.equal(transport.presentation(transport.interrupted({})).reload, true);
});
test('unstructured conflict explains version mismatch without promising a retry',async()=>{
  await assert.rejects(transport.decode(new Response('Conflict',{status:409})),error=>{
    assert.match(error.message,/Версия или открытый проект/);
    assert.match(error.message,/автоматического повтора нет/);
    assert.equal(error.reload,true);assert.equal(error.inputIssues,undefined);return true;
  });
});
