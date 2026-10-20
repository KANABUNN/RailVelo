"""Verify public JR reference pages; save facts and hashes, not timetable data."""
import datetime as dt
import hashlib
import html
import json
from pathlib import Path
import re
import urllib.error
import urllib.request

ROOT=Path(__file__).resolve().parents[1]


def get(url):
    with urllib.request.urlopen(url,timeout=60) as response:
        data=response.read()
        info=dict(url=url,status=response.status,bytes=len(data),sha256=hashlib.sha256(data).hexdigest(),
                  retrieved_utc=dt.datetime.now(dt.timezone.utc).isoformat())
    return data,info


def main():
    config=json.loads((ROOT/"config/corridor.json").read_text(encoding="utf-8"))
    body,station_info=get(config["station_order_source"])
    text=body.decode("utf-8")
    section=re.search(r'<span class="btnaccent">鹿児島本線</span>(.*?)</dd>',text,re.S)
    if not section:
        raise ValueError("Official station-list markup changed; review manually")
    names=[html.unescape(n) for n in re.findall(r'<em>(.*?)</em>',section.group(1),re.S)]
    names=names[:names.index("博多")+1]
    if names!=config["stations"]:
        raise ValueError("Official station order differs from the frozen configuration")
    station_info.update(verified_station_order=names,verified_count=len(names))
    body,direction_info=get(config["direction_source"])
    text=html.unescape(re.sub("<[^>]+>"," ",body.decode("utf-8")))
    match=re.search(r"小倉・博多・久留米・大牟田方面[（(]下り[）)]",text)
    if not match:
        raise ValueError("Official direction reference changed; review manually")
    direction_info.update(verified_direction=match.group(0))
    try:
        body,km_info=get(config["operating_km_reference"]["source_url"])
        if not body.startswith(b"%PDF"):
            raise ValueError("Operating-km reference is not a PDF")
    except urllib.error.HTTPError as error:
        # Preserve the distinction between the web reader's successful access and
        # an independently executed Python download. Do not invent a PDF hash.
        km_info=dict(url=config["operating_km_reference"]["source_url"],status=error.code,
                     error="Direct Python retrieval rejected; official PDF was read using the web research tool",
                     retrieved_utc=dt.datetime.now(dt.timezone.utc).isoformat())
    km_info.update(facts=config["operating_km_reference"],
                   fact_verification="Manual reading of official PDF page 1 in this run; this script verifies retrieval/hash, not PDF numeric extraction")
    result=dict(official_station_list=station_info,official_direction=direction_info,official_operating_km=km_info)
    report=ROOT/"reports/reference_verification.json"
    report.parent.mkdir(exist_ok=True)
    report.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(f"Verified 32-station order and down direction; direct operating-km PDF HTTP status {km_info['status']} (numeric facts checked manually)")


if __name__=="__main__":
    main()
