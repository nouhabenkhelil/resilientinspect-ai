"""Small synthetic security fixtures; real restore is exercised separately."""
import io
import json
import os
from pathlib import Path
import secrets
import tarfile
import tempfile
import unittest
from cryptography.exceptions import InvalidTag
from backup import encrypt,decrypt,safe_extract,backup_lock,rotate,sha


class BackupTests(unittest.TestCase):
    def test_authenticated_roundtrip_and_tampering(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); source=root/'source'; archive=root/'encrypted'; out=root/'out'
            source.write_bytes(secrets.token_bytes(1024*1024+17)); key=secrets.token_bytes(32)
            encrypt(source,archive,key); decrypt(archive,out,key)
            self.assertEqual(source.read_bytes(),out.read_bytes())
            data=bytearray(archive.read_bytes()); data[30]^=1; archive.write_bytes(data)
            with self.assertRaises(InvalidTag): decrypt(archive,out,key)

    def test_path_and_link_rejection(self):
        for name,link in [('../escape',False),('/absolute',False),('C:/drive',False),('data/link',True)]:
            with self.subTest(name=name),tempfile.TemporaryDirectory() as folder:
                root=Path(folder); path=root/'fixture.tar'
                with tarfile.open(path,'w') as archive:
                    item=tarfile.TarInfo(name)
                    if link: item.type=tarfile.SYMTYPE; item.linkname='../../escape'
                    archive.addfile(item)
                with self.assertRaises(ValueError): safe_extract(path,root/'out')

    def test_exclusive_maintenance_lock(self):
        with tempfile.TemporaryDirectory() as folder:
            config={'backup_root':folder}
            with backup_lock(config):
                with self.assertRaises(RuntimeError):
                    with backup_lock(config): pass

    def test_rotation_keeps_newest_valid_pair_and_unrelated_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); (root/'unrelated').write_text('retain')
            for index in (1,2):
                stem=f'core-20261124T12000{index}Z-abcdef'; archive=root/(stem+'.ri3'); archive.write_bytes(b'fixture')
                record=archive.with_suffix('.json'); record.write_text(json.dumps({'archive':archive.name,'sha256':sha(archive),'kind':'core','id':stem}))
                os.utime(record,(index,index))
            rotate({'backup_root':folder,'keep_core':1},'core')
            self.assertEqual(len(list(root.glob('*.ri3'))),1)
            self.assertTrue((root/'unrelated').exists())

    def test_rotation_rejects_escape(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); (root/'core-20261124T120001Z-abcdef.json').write_text(json.dumps({'archive':'../elsewhere.ri3','kind':'core'}))
            with self.assertRaises(ValueError): rotate({'backup_root':folder,'keep_core':0},'core')


if __name__=='__main__': unittest.main()
