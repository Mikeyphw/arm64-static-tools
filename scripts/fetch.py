#!/usr/bin/env python3
from __future__ import annotations
import argparse, fnmatch, hashlib, json, os, re, shutil, stat, subprocess, sys, tarfile, tempfile, urllib.request, zipfile
from pathlib import Path

UA = "arm64-static-tools-module/0.1"

def req_json(url):
    r = urllib.request.Request(url, headers={"User-Agent": UA, "Accept":"application/vnd.github+json"})
    tok = os.getenv("GITHUB_TOKEN")
    if tok: r.add_header("Authorization", f"Bearer {tok}")
    with urllib.request.urlopen(r) as f: return json.load(f)

def download(url, dst: Path):
    dst.parent.mkdir(parents=True, exist_ok=True)
    r = urllib.request.Request(url, headers={"User-Agent": UA})
    tok = os.getenv("GITHUB_TOKEN")
    if tok and "api.github.com" in url: r.add_header("Authorization", f"Bearer {tok}")
    with urllib.request.urlopen(r) as src, open(dst,"wb") as out: shutil.copyfileobj(src,out)

def latest_asset(repo, regex):
    rel = req_json(f"https://api.github.com/repos/{repo}/releases/latest")
    pat = re.compile(regex)
    matches = [a for a in rel.get("assets",[]) if pat.search(a["name"])]
    if not matches: raise RuntimeError(f"{repo}: no latest-release asset matches {regex!r}")
    return rel.get("tag_name") or rel.get("name"), matches[0]["browser_download_url"], matches[0]["name"]

def repo_file(repo, paths):
    for p in paths:
        try:
            meta=req_json(f"https://api.github.com/repos/{repo}/contents/{p}")
            if meta.get("download_url"): return meta.get("sha") or "repo", meta["download_url"], Path(p).name
        except Exception: pass
    raise RuntimeError(f"{repo}: none of candidate paths exist: {paths}")

def repo_glob(repo, globs):
    meta=req_json(f"https://api.github.com/repos/{repo}")
    branch=meta.get("default_branch","main")
    ref=req_json(f"https://api.github.com/repos/{repo}/git/refs/heads/{branch}")
    sha=ref["object"]["sha"]
    tree=req_json(f"https://api.github.com/repos/{repo}/git/trees/{sha}?recursive=1")
    if tree.get("truncated"):
        raise RuntimeError(f"{repo}: recursive tree truncated")
    files=[x for x in tree.get("tree",[]) if x.get("type")=="blob"]
    for g in globs:
        for item in files:
            path=item["path"]
            if fnmatch.fnmatch(path,g) or fnmatch.fnmatch(Path(path).name,g):
                url=f"https://raw.githubusercontent.com/{repo}/{sha}/{path}"
                return sha, url, Path(path).name
    raise RuntimeError(f"{repo}: no file matches {globs}")

def extract_one(src: Path, pick_regex: str|None, work: Path):
    if not pick_regex: return src
    pat=re.compile(pick_regex)
    outdir=work/"extract"; outdir.mkdir(parents=True, exist_ok=True)
    name=src.name.lower()
    if zipfile.is_zipfile(src):
        with zipfile.ZipFile(src) as z:
            names=[n for n in z.namelist() if pat.search(n) and not n.endswith('/')]
            if not names: raise RuntimeError(f"no member matches {pick_regex}")
            member=names[0]; z.extract(member,outdir); return outdir/member
    try:
        if tarfile.is_tarfile(src):
            with tarfile.open(src,"r:*") as t:
                members=[m for m in t.getmembers() if m.isfile() and pat.search(m.name)]
                if not members: raise RuntimeError(f"no member matches {pick_regex}")
                t.extract(members[0],outdir,filter="data"); return outdir/members[0].name
    except TypeError:
        with tarfile.open(src,"r:*") as t:
            members=[m for m in t.getmembers() if m.isfile() and pat.search(m.name)]
            if not members: raise RuntimeError(f"no member matches {pick_regex}")
            t.extract(members[0],outdir); return outdir/members[0].name
    raise RuntimeError(f"archive not recognized: {src}")

def run(*cmd): return subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False).stdout

def elf_info(path: Path):
    info={"file":run("file","-b",str(path)).strip(),"needed":[],"interpreter":None}
    if "aarch64" not in info["file"].lower() and "arm64" not in info["file"].lower():
        raise RuntimeError(f"not AArch64: {info['file']}")
    rd=shutil.which("readelf")
    if rd:
        dyn=run(rd,"-d",str(path)); info["needed"]=re.findall(r"Shared library: \[(.*?)\]",dyn)
        prog=run(rd,"-l",str(path)); m=re.search(r"Requesting program interpreter:\s*(.*?)\]",prog); info["interpreter"]=m.group(1) if m else None
    return info

def sha256(path):
    h=hashlib.sha256()
    with open(path,"rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--manifest",default="manifest/sources.json"); ap.add_argument("--out",default="build/bin"); ap.add_argument("--only",action="append",default=[]); args=ap.parse_args()
    cfg=json.load(open(args.manifest)); out=Path(args.out); out.mkdir(parents=True,exist_ok=True); prov=[]
    for t in cfg["tools"]:
        if args.only and t["name"] not in args.only: continue
        print(f"==> {t['name']} ({t['provider']})")
        try:
            with tempfile.TemporaryDirectory() as td:
                td=Path(td)
                kind=t["kind"]
                if kind=="direct": ver="direct"; url=t["url"]; fn=Path(url).name
                elif kind=="github_release_asset": ver,url,fn=latest_asset(t["provider"],t["asset_regex"])
                elif kind=="github_repo_file": ver,url,fn=repo_file(t["provider"],t["path_candidates"])
                elif kind=="github_repo_file_glob": ver,url,fn=repo_glob(t["provider"],t["glob_candidates"])
                else: raise RuntimeError(f"unknown kind {kind}")
                dl=td/fn; download(url,dl); chosen=extract_one(dl,t.get("pick_regex"),td)
                dest=out/t["name"]; shutil.copy2(chosen,dest); dest.chmod(dest.stat().st_mode|stat.S_IXUSR|stat.S_IXGRP|stat.S_IXOTH)
                ei=elf_info(dest)
                is_static=(not ei["needed"] and not ei["interpreter"])
                policy=t.get("static","preferred")
                if policy=="required" and not is_static:
                    raise RuntimeError(f"{t['name']} is not fully static; needed={ei['needed']} interp={ei['interpreter']}")
                if not is_static and not t.get("allow_android_system_libs",False) and policy!="preferred":
                    raise RuntimeError(f"dynamic binary without explicit exception: {t['name']}")
                prov.append({"name":t["name"],"provider":t["provider"],"version":ver,"url":url,"sha256":sha256(dest),"static":is_static,**ei})
        except Exception as e:
            if t.get("optional"):
                print(f"WARN optional {t['name']}: {e}",file=sys.stderr); continue
            raise
    Path("build").mkdir(exist_ok=True); json.dump(prov,open("build/provenance.json","w"),indent=2,sort_keys=True); print(f"Fetched {len(prov)} tools")
if __name__=="__main__": main()
