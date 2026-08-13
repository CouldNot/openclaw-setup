#!/usr/bin/env python3
import json, sqlite3, subprocess, tempfile, time, uuid
from pathlib import Path

SCRIPT=Path(__file__).parents[1]/"workspace/skills/second-brain/scripts/second_brain.py"
N=100000
with tempfile.TemporaryDirectory() as td:
    dbpath=Path(td)/"scale.sqlite"
    subprocess.check_call(["python3",str(SCRIPT),"--db",str(dbpath),"init"],stdout=subprocess.DEVNULL)
    db=sqlite3.connect(dbpath); t=time.perf_counter(); stamp="2030-01-01T00:00:00+00:00"
    entities=[]; assertions=[]
    for i in range(N):
        eid=f"ent_scale_{i}"
        entities.append((eid,"PERSON",f"Person {i}",f"person {i}","[]",None,"confirmed",.9,stamp,stamp,"simulation",f"sim:{i}",stamp,stamp))
        value="important historical anchor" if i==42424 else f"ordinary memory {i}"
        assertions.append((f"ast_scale_{i}",eid,"context",json.dumps(value),"FACT","confirmed",.9,.95 if i==42424 else .2,stamp,None,stamp,stamp,"simulation",f"sim:{i}",None,stamp,stamp))
    db.executemany("insert into entities values(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",entities)
    db.executemany("insert into assertions values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",assertions)
    db.commit(); insert_s=time.perf_counter()-t
    t=time.perf_counter()
    row=db.execute("select e.canonical_name,a.value_json from assertions a join entities e on e.id=a.subject_id where e.normalized_name=? and a.status in ('tentative','likely','confirmed') order by a.importance desc limit 1",("person 42424",)).fetchone()
    exact_ms=(time.perf_counter()-t)*1000
    t=time.perf_counter()
    row2=db.execute("select id,value_json from assertions where value_json like ? and status!='deleted' order by importance desc limit 1",("%historical anchor%",)).fetchone()
    scan_ms=(time.perf_counter()-t)*1000
    integrity=db.execute("pragma integrity_check").fetchone()[0]; size=dbpath.stat().st_size; db.close()
    print(json.dumps({"memories":N,"insert_seconds":round(insert_s,3),"exact_lookup_ms":round(exact_ms,3),"historical_scan_ms":round(scan_ms,3),"exact_result":row,"historical_result":row2,"integrity":integrity,"db_bytes":size},indent=2))
