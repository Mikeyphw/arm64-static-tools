"""R04: version-locked Toybox and safe PitchBlack terminal font theme tests."""
from __future__ import annotations
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import struct
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('pbrpfont',ROOT/'scripts/build_pbrp_nerd_theme.py')
pbrp=importlib.util.module_from_spec(spec);spec.loader.exec_module(pbrp)


def toy_font(chars=(65,0xe0b0,0xf013)):
    # Minimal TrueType container for cmap parsing only, not a visual font.
    groups=b''.join(struct.pack('>III',cp,cp,i+1) for i,cp in enumerate(chars))
    sub=struct.pack('>HHIII',12,0,16+len(groups),0,len(chars))+groups
    cmap=struct.pack('>HHHHI',0,1,3,10,12)+sub
    tables={b'cmap':cmap,b'head':b'\0'*54,b'maxp':b'\0'*6}
    pos=12+16*len(tables);directory=bytearray();data=bytearray()
    for name,value in tables.items():
        directory.extend(struct.pack('>4sIII',name,0,pos,len(value)))
        data.extend(value);pos+=len(value)
    return struct.pack('>IHHHH',0x10000,len(tables),0,0,0)+directory+data


def source_ui():
    return (b'<description>PitchBlack Recovery Project</description>\n<?xml version="1.0"?>\n'
            b'<recovery><resources><font name="cons" filename="DroidSansMono.ttf" size="30"/>'
            b'<font name="other" filename="Roboto.ttf" size="20"/></resources></recovery>')


def theme_bytes(ui=None, extra=None):
    content=io.BytesIO()
    with zipfile.ZipFile(content,'w') as z:
        z.writestr('ui.xml',ui if ui is not None else source_ui())
        z.writestr('portrait.xml',b'<recovery><styles><style name="terminal"><font resource="cons"/></style></styles></recovery>')
        z.writestr('fonts/DroidSansMono.ttf',b'ORIGINAL-FONT')
        z.writestr('images/icon.png',b'\x89PNGplaceholder')
        if extra:
            for name,data in extra:z.writestr(name,data)
    return content.getvalue()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.work=Path(self.tmp.name)
        self.theme=self.work/'input.zip';self.font=self.work/'font.ttf';self.out=self.work/'output.zip'
        self.theme.write_bytes(theme_bytes());self.font.write_bytes(toy_font())
    def build(self):
        return pbrp.build(self.theme,pbrp.digest(self.theme.read_bytes()),self.font,pbrp.digest(self.font.read_bytes()),self.out)


class ToyboxLockTests(unittest.TestCase):
    def test_versioned_source_matches_lock(self):
        sources=json.loads((ROOT/'manifest/sources.json').read_text());lock=json.loads((ROOT/'manifest/lock.json').read_text())
        a=next(x for x in sources['tools'] if x['name']=='toybox');b=next(x for x in lock['tools'] if x['name']=='toybox')
        self.assertEqual(a['url'],b['source_url'])
        self.assertIn('/binaries/0.8.14/toybox-aarch64',a['url'])
        self.assertNotIn('/latest/',a['url'])
        self.assertEqual(b['source_sha256'],b['sha256'])
        self.assertEqual(b['size'],838240)
    def test_version_lock_is_not_silently_repinned(self):
        src=(ROOT/'scripts/verify_manifest.py').read_text()
        self.assertIn("assert toybox['version'] == '0.8.14'",src)
        self.assertIn("assert '/latest/' not in src['url']",src)


class FontTests(Base):
    def test_valid_true_type_glyphs(self):
        self.assertEqual(set(pbrp.REQUIRED_GLYPHS),pbrp.cmap_coverage(toy_font()))
    def test_false_claim_to_nerd_font_fails(self):
        self.font.write_bytes(toy_font((65,0xe0b0)))
        with self.assertRaisesRegex(pbrp.Refused,'Font lacks'):self.build()
    def test_bad_font_magic_fails(self):
        self.font.write_bytes(b'OTTO'+b'0'*64)
        with self.assertRaisesRegex(pbrp.Refused,'TrueType'):self.build()
    def test_missing_cmap_fails(self):
        self.font.write_bytes(b'\x00\x01\x00\x00'+b'\0'*20)
        with self.assertRaises(pbrp.Refused):self.build()
    def test_mismatched_font_digest_fails(self):
        with self.assertRaisesRegex(pbrp.Refused,'SHA-256 mismatch'):
            pbrp.build(self.theme,pbrp.digest(self.theme.read_bytes()),self.font,'0'*64,self.out)
    def test_mismatched_theme_digest_fails(self):
        with self.assertRaisesRegex(pbrp.Refused,'SHA-256 mismatch'):
            pbrp.build(self.theme,'f'*64,self.font,pbrp.digest(self.font.read_bytes()),self.out)
    def test_theme_zip_single_target_and_other_bytes_unchanged(self):
        result=self.build()
        self.assertTrue(result['output_sha256'])
        self.assertFalse(result['install_performed'])
        with zipfile.ZipFile(self.theme) as old,zipfile.ZipFile(self.out) as new:
            for name in old.namelist():
                if name=='ui.xml':
                    self.assertIn(b'filename="AST-NerdFontMono.ttf"',new.read(name))
                    self.assertIn(b'name="other" filename="Roboto.ttf"',new.read(name))
                else:self.assertEqual(old.read(name),new.read(name))
            self.assertEqual(new.read('fonts/AST-NerdFontMono.ttf'),self.font.read_bytes())
            self.assertEqual(len(new.namelist()),len(old.namelist())+1)
    def test_output_existing_refused_and_not_overwritten(self):
        self.out.write_text('USER FILE')
        with self.assertRaisesRegex(pbrp.Refused,'already exists'):self.build()
        self.assertEqual(self.out.read_text(),'USER FILE')
    def test_duplicate_zip_member_refused(self):
        self.theme.write_bytes(theme_bytes(extra=[('images/icon.png',b'overwrite')]))
        with self.assertRaisesRegex(pbrp.Refused,'duplicate'):self.build()
    def test_symlink_theme_member_refused(self):
        b=io.BytesIO()
        with zipfile.ZipFile(b,'w') as z:
            z.writestr('ui.xml',source_ui())
            z.writestr('portrait.xml','<style name="terminal"><font resource="cons"/></style>')
            x=zipfile.ZipInfo('fonts/link.ttf');x.create_system=3;x.external_attr=stat.S_IFLNK<<16
            z.writestr(x,'../../etc/shadow')
        self.theme.write_bytes(b.getvalue())
        with self.assertRaisesRegex(pbrp.Refused,'symlink'):self.build()
    def test_traversal_zip_member_refused(self):
        self.theme.write_bytes(theme_bytes(extra=[('../outside.txt',b'evil')]))
        with self.assertRaisesRegex(pbrp.Refused,'Invalid'):self.build()
    def test_wrong_pbrp_identity_refused(self):
        self.theme.write_bytes(theme_bytes(ui=source_ui().replace(b'PitchBlack',b'NotBrand ')))
        with self.assertRaisesRegex(pbrp.Refused,'PitchBlack'):self.build()
    def test_multiple_cons_entries_refused(self):
        xml=source_ui().replace(b'</resources>',b'<font name="cons" filename="second.ttf" size="30"/></resources>')
        self.theme.write_bytes(theme_bytes(ui=xml))
        with self.assertRaisesRegex(pbrp.Refused,'exactly one'):self.build()
    def test_doctype_refused_without_parser(self):
        self.theme.write_bytes(theme_bytes(ui=source_ui()+b'<!DOCTYPE pwn>'))
        with self.assertRaisesRegex(pbrp.Refused,'Unsafe'):self.build()
    def test_missing_terminal_style_refused(self):
        b=io.BytesIO()
        with zipfile.ZipFile(b,'w') as z:
            z.writestr('ui.xml',source_ui());z.writestr('portrait.xml',b'<recovery/>')
        self.theme.write_bytes(b.getvalue())
        with self.assertRaisesRegex(pbrp.Refused,'terminal style'):self.build()
    def test_embedded_ast_does_not_autoflash(self):
        src=(ROOT/'scripts/build_pbrp_nerd_theme.py').read_text()
        self.assertNotIn('subprocess',src)
        self.assertNotIn('mount -o rw',src)
        self.assertNotIn('fastboot flash',src)
        self.assertNotIn('dd if=',src)


class RecoveryFontControls(unittest.TestCase):
    def test_shell_font_controls_are_manual(self):
        sh=(ROOT/'module/ast/entrypoint.sh').read_text()
        self.assertIn('NERD_FONT_RENDERED_OK',sh)
        self.assertIn('[ -t 0 ] && [ -t 1 ]',sh)
        self.assertIn('Only after installing a compatible PitchBlack theme',sh)
        self.assertIn('Mode:',sh)
        subprocess.run(['sh','-n',str(ROOT/'module/ast/entrypoint.sh')],check=True)
    def test_modern_prompt_requires_confirmation_in_recovery(self):
        z=(ROOT/'module/ast/zshrc').read_text()
        self.assertIn('ast_choice == modern && $AST_MODE == recovery',z)
        self.assertIn('ast_choice=compact',z)
        self.assertIn('nerd-font-verified',z)
    def test_packaging_never_bundles_font(self):
        self.assertFalse(list((ROOT/'module').rglob('*.ttf')))
        self.assertIn('scripts/build_pbrp_nerd_theme.py',(ROOT/'Makefile').read_text())


if __name__=='__main__':unittest.main()
