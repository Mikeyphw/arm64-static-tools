#!/usr/bin/env python3
"""Build an opt-in PitchBlack theme ZIP with a single Nerd Mono terminal font.

Host-only tool. Never installs themes, replaces recovery images, or downloads
font files. Both source theme and locally supplied font must be hash-approved.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import struct
import sys
import tempfile
import zipfile

NEW_NAME = 'AST-NerdFontMono.ttf'
NEW_MEMBER = 'fonts/' + NEW_NAME
MAX_FONT = 32 * 1024 * 1024
MAX_THEME = 192 * 1024 * 1024
MAX_ENTRIES = 8000
MAX_MEMBER = 64 * 1024 * 1024
REQUIRED_GLYPHS = (ord('A'), 0xE0B0, 0xF013)
HEX_SHA = re.compile(r'[0-9a-f]{64}\Z')
TAG = re.compile(rb'<font\b[^<>]*?/?>', re.I)
ATTR = re.compile(rb'\b([A-Za-z_][A-Za-z0-9_-]*)\s*=\s*(["\'])(.*?)\2', re.S)


class Refused(ValueError):
    pass


def digest(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def verified_file(path: Path, expected: str, limit: int) -> bytes:
    if not HEX_SHA.fullmatch(expected):
        raise Refused('Expected SHA-256 must be 64 lower-case hexadecimal characters')
    if path.is_symlink() or not path.is_file():
        raise Refused('Source must be an ordinary file, never a symlink')
    if path.stat().st_size > limit:
        raise Refused('Input exceeds size limit')
    raw = path.read_bytes()
    if digest(raw) != expected:
        raise Refused('Source SHA-256 mismatch')
    return raw


def u16(x: bytes, offset: int) -> int:
    if offset < 0 or offset + 2 > len(x):
        raise Refused('Truncated TrueType table')
    return struct.unpack_from('>H', x, offset)[0]


def u32(x: bytes, offset: int) -> int:
    if offset < 0 or offset + 4 > len(x):
        raise Refused('Truncated TrueType table')
    return struct.unpack_from('>I', x, offset)[0]


def cmap_coverage(font: bytes) -> set[int]:
    """Read only bounded cmap 4/12 indices; no font code or external parsers."""
    if len(font) < 12 or font[:4] != b'\x00\x01\x00\x00':
        raise Refused('Only TrueType .ttf fonts are supported by this PBRP theme builder')
    n = u16(font, 4)
    if n == 0 or n > 80 or 12 + n * 16 > len(font):
        raise Refused('Invalid TrueType directory')
    tables = {}
    for i in range(n):
        off = 12 + i*16
        name = font[off:off+4]
        pos, length = u32(font, off+8), u32(font, off+12)
        if pos + length > len(font) or length > MAX_FONT:
            raise Refused('Invalid TrueType table bounds')
        if name in tables:
            raise Refused('Duplicate TrueType table')
        tables[name] = font[pos:pos+length]
    if b'cmap' not in tables or b'head' not in tables or b'maxp' not in tables:
        raise Refused('Missing TrueType cmap/head/maxp')
    table = tables[b'cmap']
    if len(table) < 4 or u16(table,0) != 0:
        raise Refused('Unsupported cmap')
    count = u16(table,2)
    if count > 128 or 4 + 8*count > len(table):
        raise Refused('Invalid cmap subtables')
    covered = set()
    for i in range(count):
        platform, encoding = u16(table,4+i*8), u16(table,6+i*8)
        if platform not in (0,3) or (platform == 3 and encoding not in (1,10)):
            continue
        pos = u32(table,8+i*8)
        if pos+4 > len(table):
            raise Refused('cmap offset outside table')
        fmt = u16(table,pos)
        if fmt == 4:
            size = u16(table,pos+2)
            if size < 24 or pos+size > len(table):
                raise Refused('Invalid cmap format 4 length')
            data = table[pos:pos+size]
            seg = u16(data,6)//2
            if seg == 0 or seg > 32768:
                raise Refused('Invalid cmap segment count')
            ends, starts, deltas, offsets = 14, 16+2*seg, 16+4*seg, 16+6*seg
            if offsets+2*seg > len(data):
                raise Refused('Invalid cmap segment bounds')
            for cp in REQUIRED_GLYPHS:
                if cp > 0xffff:
                    continue
                for k in range(seg):
                    a,b = u16(data,starts+2*k),u16(data,ends+2*k)
                    if a <= cp <= b:
                        adjust = u16(data,deltas+2*k)
                        offset = u16(data,offsets+2*k)
                        if not offset:
                            glyph = (cp+adjust)&65535
                        else:
                            idx = offsets + 2*k + offset + 2*(cp-a)
                            glyph = u16(data,idx) if idx+2 <= len(data) else 0
                            if glyph:glyph = (glyph+adjust)&65535
                        if glyph:covered.add(cp)
                        break
        elif fmt == 12:
            if pos+16 > len(table):
                raise Refused('Truncated cmap format 12')
            length, groups = u32(table,pos+4), u32(table,pos+12)
            if groups > 150000 or length > len(table)-pos or 16+groups*12 > length:
                raise Refused('Invalid cmap format 12 bounds')
            for cp in REQUIRED_GLYPHS:
                for k in range(groups):
                    start,end,glyph = (u32(table,pos+16+k*12+j) for j in (0,4,8))
                    if start <= cp <= end:
                        if glyph+cp-start:covered.add(cp)
                        break
    return covered


def patch_ui(xml: bytes) -> bytes:
    if len(xml) > 3_000_000 or b'<!DOCTYPE' in xml.upper() or b'<!ENTITY' in xml.upper():
        raise Refused('Unsafe or oversized PBRP UI')
    if not (b'<recovery>' in xml and b'<resources>' in xml and
            (b'PitchBlack' in xml or b'PBRP' in xml)):
        raise Refused('Not a recognizable PitchBlack theme UI')
    hits = []
    for tag in TAG.finditer(xml):
        attrs = {a.group(1).lower():a.group(3) for a in ATTR.finditer(tag.group())}
        if attrs.get(b'name') == b'cons':
            hits.append((tag, attrs))
    if len(hits) != 1 or b'filename' not in hits[0][1] or not hits[0][1][b'filename'].lower().endswith(b'.ttf'):
        raise Refused('Expected exactly one valid cons font resource')
    match = hits[0][0]
    original = match.group()
    old = hits[0][1][b'filename']
    new = re.sub(rb'(\bfilename\s*=\s*["\'])' + re.escape(old) + rb'(["\'])',
                 lambda m: m.group(1)+NEW_NAME.encode()+m.group(2), original, count=1)
    if new == original or b'filename' not in new:
        raise Refused('Unable to replace PBRP terminal font')
    return xml[:match.start()] + new + xml[match.end():]


def build(theme_path: Path, theme_sha: str, font_path: Path, font_sha: str, output: Path) -> dict:
    theme = verified_file(theme_path,theme_sha,MAX_THEME)
    font = verified_file(font_path,font_sha,MAX_FONT)
    if set(REQUIRED_GLYPHS) - cmap_coverage(font):
        raise Refused('Font lacks ASCII / Powerline U+E0B0 / Nerd U+F013 glyph coverage')
    try:
        zin = zipfile.ZipFile(__import__('io').BytesIO(theme))
    except (zipfile.BadZipFile, OSError) as exc:
        raise Refused('Invalid source theme ZIP') from exc
    with zin:
        infos = zin.infolist()
        if len(infos) > MAX_ENTRIES or sum(i.file_size for i in infos) > MAX_THEME:
            raise Refused('Theme exceeds archive budget')
        names = set()
        for i in infos:
            p = PurePosixPath(i.filename)
            if (not i.filename or i.filename.startswith('/') or '\\' in i.filename or
                    '..' in p.parts or any(not part for part in p.parts) or i.filename in names):
                raise Refused('Invalid or duplicate theme member')
            names.add(i.filename)
            typ = (i.external_attr>>16)&0o170000
            if typ not in (0,stat.S_IFREG,stat.S_IFDIR):
                raise Refused('Theme symlink or special archive member refused')
            if i.file_size > MAX_MEMBER or i.flag_bits & 1:
                raise Refused('Oversized or encrypted theme member')
        if 'ui.xml' not in names or NEW_MEMBER in names:
            raise Refused('Theme needs ui.xml and must not already have the AST font member')
        ui = patch_ui(zin.read('ui.xml'))
        if 'portrait.xml' not in names:
            raise Refused('Complete PitchBlack theme must contain portrait.xml')
        portrait = zin.read('portrait.xml')
        if b'<style name="terminal">' not in portrait or b'<font resource="cons"' not in portrait:
            raise Refused('PitchBlack terminal style does not use cons resource')
        if output.exists() or output.is_symlink():
            raise Refused('Output already exists; never overwrite an existing theme')
        output.parent.mkdir(parents=True,exist_ok=True)
        temp = None
        created_out = False
        try:
            with tempfile.NamedTemporaryFile(dir=output.parent,prefix='.ast-pbrp-theme-',suffix='.tmp',delete=False) as f:
                temp=Path(f.name)
            with zipfile.ZipFile(temp,'w') as zout:
                for info in infos:
                    data = ui if info.filename=='ui.xml' else zin.read(info)
                    zout.writestr(info,data)
                zout.writestr(NEW_MEMBER,font,compress_type=zipfile.ZIP_DEFLATED,compresslevel=6)
            with open(output,'xb') as dst, open(temp,'rb') as src:
                created_out = True
                shutil.copyfileobj(src,dst,length=1024*1024)
        except BaseException:
            if created_out:output.unlink(missing_ok=True)
            raise
        finally:
            if temp is not None:temp.unlink(missing_ok=True)
    result = {'theme_sha256':theme_sha,'font_sha256':font_sha,
              'output_sha256':hashlib.sha256(output.read_bytes()).hexdigest(),
              'changed_resource':'cons','added_member':NEW_MEMBER,
              'install_performed':False,'recovery_image_modified':False,
              'device_qualified':False}
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--theme',type=Path,required=True)
    ap.add_argument('--theme-sha256',required=True)
    ap.add_argument('--font',type=Path,required=True)
    ap.add_argument('--font-sha256',required=True)
    ap.add_argument('--out',type=Path,required=True)
    args=ap.parse_args()
    try:
        info=build(args.theme,args.theme_sha256,args.font,args.font_sha256,args.out)
    except (Refused,OSError,zipfile.BadZipFile,struct.error) as exc:
        raise SystemExit('AST_PBRP_FONT_REFUSED '+str(exc))
    print(json.dumps(info,indent=2))


if __name__=='__main__':main()
