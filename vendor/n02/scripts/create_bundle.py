"""Package only deliverables and public raw inputs, with checksums; exclude .venv/runs."""
import argparse
import hashlib
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parents[1]
DIRECTORIES={"scripts","schemas","config","data","output","reports","docs"}
ROOT_FILES={"README.md","NOTICE.md","requirements.lock.txt",".gitignore",".gitattributes"}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dest",type=Path,default=ROOT.parent/"railmonitor_mojiko_hakata_20261020.zip")
    args=p.parse_args()
    target=args.dest.resolve()
    if target.exists():
        raise FileExistsError("Archive already exists; choose a new --dest")
    files=[]
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file():
            continue
        relative=path.relative_to(ROOT)
        if "__pycache__" in relative.parts or path.suffix in (".pyc",".tmp"):
            continue
        if (len(relative.parts)==1 and relative.name in ROOT_FILES) or (relative.parts[0] in DIRECTORIES):
            files.append(path)
    checksums=ROOT/"MANIFEST.sha256"
    checksums.write_text("".join(f"{digest(f)}  {f.relative_to(ROOT).as_posix()}\n" for f in files),encoding="utf-8")
    files.append(checksums)
    with zipfile.ZipFile(target,"x",compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for path in sorted(files):
            name="railmonitor_n02/"+path.relative_to(ROOT).as_posix()
            entry=zipfile.ZipInfo(name,date_time=(2026,10,20,0,0,0))
            entry.compress_type=zipfile.ZIP_DEFLATED
            entry.external_attr=0o100644<<16
            z.writestr(entry,path.read_bytes(),compress_type=zipfile.ZIP_DEFLATED,compresslevel=9)
    with zipfile.ZipFile(target) as z:
        if z.testzip() is not None:
            raise RuntimeError("Packaged ZIP failed CRC validation")
        for path in files:
            name="railmonitor_n02/"+path.relative_to(ROOT).as_posix()
            if hashlib.sha256(z.read(name)).hexdigest()!=digest(path):
                raise RuntimeError(f"Packaged content mismatch: {name}")
    target.with_suffix(target.suffix+".sha256").write_text(f"{digest(target)}  {target.name}\n",encoding="utf-8")
    print(f"Packaged and verified {len(files)} files, {target.stat().st_size:,} bytes, sha256 {digest(target)}")


if __name__=="__main__":
    main()
