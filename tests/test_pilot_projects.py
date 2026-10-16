import uuid

from app.intake.pilot_access import Principal
from app.intake.pilot_objects import PilotObjectStore
from tests.test_pilot_access import pilot as pilot_fixture, client_for, draft, WRITE
from tests.test_pilot_admin import accept
from tests.test_pilot_capture import ANSWERS

pilot = pilot_fixture


def test_distinct_objects_own_projects_and_old_tab_guard(pilot):
    access, users, _ = pilot
    alice, bob = client_for(users["alice"][1]), client_for(users["bob"][1])
    accept(alice)
    first = draft(alice)
    first_id = first["project_id"]
    calculated = alice.post("/studio/api/calculate",headers=WRITE,json={"revision":first["revision"],"answers":ANSWERS}).json()
    create = {"request_id":uuid.uuid4().hex,"title":"Второй дом"}
    second = alice.post("/studio/api/projects",headers=WRITE,json=create)
    assert second.status_code == 200, second.text
    assert second.json()["project_id"] != first_id
    assert alice.post("/studio/api/projects",headers=WRITE,json=create).json() == second.json()
    stale = alice.patch("/studio/api/answer",headers={**WRITE,"X-Zarya-Draft":first_id},json={"revision":second.json()["revision"],"field":"residents","value":99})
    assert stale.status_code == 409
    second_calc = alice.post("/studio/api/calculate",headers=WRITE,json={"revision":second.json()["revision"],"answers":ANSWERS}).json()
    assert calculated["pilot_archive"]["object_id"] != second_calc["pilot_archive"]["object_id"]
    chosen = {"request_id":uuid.uuid4().hex,"project_id":first_id}
    assert bob.post("/studio/api/projects",headers=WRITE,json=chosen).status_code == 404
    restored = alice.post("/studio/api/projects",headers=WRITE,json=chosen)
    assert restored.json()["calculation"] == calculated["calculation"]
    assert "Второй дом" in alice.get("/studio/projects").text
    assert "Второй дом" not in bob.get("/studio/projects").text
    principal = Principal(users["alice"][0],"Алиса","tester",None)
    assert len(PilotObjectStore().objects(principal)[0]) == 2
