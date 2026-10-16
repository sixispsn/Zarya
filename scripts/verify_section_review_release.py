"""HTTP proof: a saved view cannot certify or alter the engineering package."""
import hashlib


def verify(call, other, state, out):
    before = state['project_calculation']
    review = state['section_review']
    assert review['state'] == 'unreviewed' and review['can_record']
    current = review['current']
    url = f"/studio/api/preview/{current['preview_id']}/files/{current['filename']}"
    data = call('GET', url).content
    assert hashlib.sha256(data).hexdigest() == current['pdf_sha256']
    (out / current['filename']).write_bytes(data)
    payload = dict(revision=state['revision'], reviewer='Временная автопроверка — не проектировщик объекта',
                   architecture_ref='Синтетическая проверка интерфейса, не подтверждение АР',
                   fingerprint=current['fingerprint'], confirm=True)
    denied = other.post('/studio/api/section/review', json=payload)
    assert denied.status_code in {404, 422}, (denied.status_code, denied.text[:120])
    state = call('POST', '/studio/api/section/review', json=payload).json()
    assert state['section_review']['state'] == 'reviewed'
    assert not state['section_review']['release_ready'] and not state['section_review']['takeoff_eligible']
    assert state['project_calculation'] == before and not before['can_release']
    assert call('GET', url).content == data
    assert other.get(url).status_code == 404
    assert call('GET', '/studio/api/draft').json()['section_review'] == state['section_review']
    return state, dict(saved=True, pdf_unchanged=True, calculations_unchanged=True,
                       no_release=True, private=True, pdf_sha256=current['pdf_sha256'])
